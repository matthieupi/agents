// Shared V2 public configuration publisher. Callers hold resource then HOME locks.
// No dependency installation, plugin imports, private-state copying or service control.
import { mkdir, realpath, lstat, readlink, symlink, readdir, readFile, unlink, rename } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { resolve, join, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';

const knownSnapshots = new Set([
  '0a1dec62e5d116dbd684482dfb00ce0746200d536b0ec8cda49aaba4d88d3316', // public V1
  '35be11e8a689f547ee95f6890abf56f81f700756c6f0766e46c7431e22d79932', // remote public V1
  'f90e64c84363535db05bbaa423e2cb51a16308ca37c3ac96dbe3902e2b212029', // migration public V2
]);
const knownAssets = {
  'plugins/first-prompt-title.js': 'cba82bd8132a28b2dba9cde7a2afa055b15d7a469c0f1734669968ac56ba6c22',
  'tui-plugins/session-title.mjs': '0d0499e92e4e68c1a5760316be216d2bf3186cada8c101bc6e7a43e799ec00b6',
};
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const stat = path => lstat(path).catch(error => { if (error.code !== 'ENOENT') throw error; });
// Tracked public documentation/test inputs are not runtime plugin entrypoints.
const nonRuntimeAssets = new Set([
  'tui-plugins/README.md',
  'tui-plugins/run-tests.mjs',
  'tui-plugins/session-title.test.mjs',
]);

async function physicalDirectory(path) {
  let current = '/';
  for (const part of path.split('/').filter(Boolean)) {
    current = join(current, part);
    try { await mkdir(current, { mode: 0o700 }); }
    catch (error) { if (error.code !== 'EEXIST') throw error; }
    if (!(await lstat(current)).isDirectory()) throw new Error(`Redirected private directory refused: ${current}`);
  }
}

export async function publishConfig(source, resources, destination) {
  source = resolve(source);
  resources = resolve(resources);
  destination = resolve(destination);
  for (const path of [source, resources]) {
    if (await realpath(path) !== path) throw new Error('Physical configuration source required');
  }
  if (destination === source) throw new Error('Private destination must differ from public source');
  const links = new Map();
  for (const name of ['commands', 'skills', 'system']) {
    const path = join(resources, name);
    if (!(await lstat(path)).isDirectory()) throw new Error(`Missing physical resource: ${name}`);
    links.set(name, path);
  }
  // Narrow public inputs only. Never publish auth, state, manifests, KDCO or GSD.
  for (const name of ['opencode.json', 'cli.json', 'tui.json']) {
    if (await stat(join(source, name))) links.set(name, join(source, name));
  }
  async function assets(directory) {
    const path = join(source, directory), info = await stat(path);
    if (!info) return;
    if (!info.isDirectory()) throw new Error(`Redirected configuration source: ${path}`);
    for (const name of await readdir(path)) {
      const relative = join(directory, name), from = join(source, relative);
      if (name.startsWith('kdco-')) continue;
      const entry = await lstat(from);
      if (nonRuntimeAssets.has(relative) && entry.isFile()) continue;
      if (entry.isDirectory()) await assets(relative);
      else if (entry.isFile() && /\.(js|mjs|ts|json)$/.test(name)) links.set(relative, from);
      else throw new Error(`Invalid public asset: ${from}`);
    }
  }
  await assets('plugins');
  await assets('tui-plugins');
  if (!links.has('opencode.json')) throw new Error('Missing maintained opencode.json');
  for (const [name, path] of links) {
    const info = await lstat(path);
    if (info.isSymbolicLink() || (!['commands', 'skills', 'system'].includes(name) && !info.isFile())) {
      throw new Error(`Redirected or invalid configuration source: ${name}`);
    }
  }
  await physicalDirectory(destination);
  // Validate all parents before inspecting/replacing any files beneath them.
  for (const name of [...links.keys(), 'plugins/placeholder', 'plugin/placeholder']) {
    await physicalDirectory(dirname(join(destination, name)));
  }
  const retire = [];
  // Retire only wrappers whose complete bytes or exact former managed link prove ownership.
  for (const directory of ['plugins', 'plugin']) {
    for (const name of await readdir(join(destination, directory))) {
      if (!name.startsWith('kdco-')) continue;
      const path = join(destination, directory, name), info = await lstat(path);
      const module = name.slice(5, -3);
      const recognized = ['background-agents', 'notify', 'worktree'].includes(module) && name.endsWith('.ts');
      const target = info.isSymbolicLink() ? await readlink(path) : '';
      const owned = recognized && (info.isSymbolicLink()
        ? [join(source, 'plugins', name), join('/opt/opencode-defaults/plugins', name),
          join('/opt/opencode/component/.opencode/config/plugins', name)].includes(target)
        : info.isFile() && await readFile(path, 'utf8') === `export { default } from "../kdco/${module}"\n`);
      if (!owned) throw new Error(`Preserved conflicting V1 wrapper: ${path}`);
      retire.push(path);
    }
  }
  // A second format must never silently override the maintained file.
  const jsonc = join(destination, 'opencode.jsonc'), jsoncInfo = await stat(jsonc);
  if (jsoncInfo) {
    if (jsoncInfo.isFile() && knownSnapshots.has(digest(await readFile(jsonc)))) retire.push(jsonc);
    else throw new Error('Preserved conflicting configuration: opencode.jsonc');
  }
  const replace = new Set();
  for (const [name, from] of links) {
    const to = join(destination, name), info = await stat(to);
    if (!info) continue;
    if (info.isSymbolicLink()) {
      const target = await readlink(to);
      if (target === from) continue;
      if (target === join('/opt/opencode-defaults', name) ||
          target === join('/opt/opencode/component/.opencode/config', name) ||
          (['commands', 'skills', 'system'].includes(name) && target === join('/opt/agent', name))) {
        replace.add(name);
        continue;
      }
    }
    if (info.isFile()) {
      const bytes = await readFile(to), hash = digest(bytes);
      if (bytes.equals(await readFile(from)) || (name === 'opencode.json' && knownSnapshots.has(hash)) || knownAssets[name] === hash) {
        replace.add(name);
        continue;
      }
    }
    throw new Error(`Preserved conflicting configuration: ${to}`);
  }
  // All conflicts are checked before any managed content changes. Atomic per file;
  // resource/HOME locks serialize cooperating publishers, not active sessions.
  for (const [name, from] of links) {
    const to = join(destination, name);
    if (replace.has(name)) {
      const temporary = `${to}.${randomUUID()}.tmp`;
      try { await symlink(from, temporary); await rename(temporary, to); }
      finally { await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error; }); }
    } else if (!(await stat(to))) await symlink(from, to);
  }
  for (const path of retire) await unlink(path);
  // Retire only exact managed links; leave private files and custom links alone.
  async function cleanup(directory = '') {
    for (const name of await readdir(join(destination, directory))) {
      const relative = join(directory, name), path = join(destination, relative), info = await lstat(path);
      if (info.isSymbolicLink() && !links.has(relative)) {
        const target = await readlink(path);
        if (target === join(source, relative) || (relative === 'gsd' && target === join(resources, 'gsd')) ||
            (relative === 'kdco' && target === '/opt/opencode/component/.opencode/config/kdco')) await unlink(path);
      } else if (info.isDirectory() && ['plugins', 'tui-plugins'].includes(name)) await cleanup(relative);
    }
  }
  await cleanup();
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (process.argv[2] !== 'config' || process.argv.length !== 6) {
    throw new Error('usage: publish-plugins.mjs config SOURCE_CONFIG RESOURCES DESTINATION_CONFIG');
  }
  await publishConfig(...process.argv.slice(3));
}
