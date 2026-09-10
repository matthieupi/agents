// Managed plugin publication and dependency installation. Never import plugins,
// parse/write private OpenCode config, or control a running OpenCode process.
import { mkdir, realpath, lstat, readlink, symlink, readdir, readFile, writeFile, unlink, rename } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';

async function manifestFingerprint(directory) {
  const hash = createHash('sha256');
  for (const name of ['package.json', 'package-lock.json']) {
    const file = join(directory, name);
    if (!(await lstat(file)).isFile()) throw new Error(`Physical package manifest required: ${name}`);
    const data = await readFile(file);
    hash.update(JSON.stringify([name, data.length])).update(data);
  }
  return hash.digest('hex');
}

// Hash actual installed bytes, paths and link targets, including empty directories.
// Missing/damaged trees cannot be accepted on the strength of the saved stamp.
export async function dependencyFingerprint(directory) {
  const root = join(directory, 'node_modules');
  const hash = createHash('sha256');
  async function visit(relative) {
    const path = join(root, relative);
    const info = await lstat(path);
    if (info.isDirectory()) {
      hash.update(JSON.stringify(['directory', relative]));
      for (const name of (await readdir(path)).sort()) await visit(join(relative, name));
    } else if (info.isFile()) {
      const data = await readFile(path);
      hash.update(JSON.stringify(['file', relative, data.length])).update(data);
    } else if (info.isSymbolicLink() && relative) {
      hash.update(JSON.stringify(['link', relative, await readlink(path)]));
    } else {
      throw new Error('Physical node_modules directory and ordinary dependency entries required');
    }
  }
  try { await visit(''); }
  catch (e) { if (e.code === 'ENOENT') return null; throw e; }
  return hash.digest('hex');
}

// Caller holds flock on PACKAGE/.kdco-install.lock through this entire operation.
// This coordinates installers, NOT active sessions: real updates require idle
// sessions. An in-place npm failure may leave dependencies partially replaced.
export async function installDependencies(directory) {
  directory = resolve(directory);
  if (await realpath(directory) !== directory) throw new Error('Physical package directory required');
  const state = join(directory, '.kdco-install.json');
  const info = await lstat(state).catch(e => { if (e.code !== 'ENOENT') throw e; });
  if (info && !info.isFile()) throw new Error('Preserved redirected installation stamp');
  let previous = null;
  if (info) {
    const text = await readFile(state, 'utf8');
    try { previous = JSON.parse(text); }
    catch (e) { if (!(e instanceof SyntaxError)) throw e; }
  }
  const inputs = await manifestFingerprint(directory);
  const tree = await dependencyFingerprint(directory);
  if (tree && previous?.inputs === inputs && previous?.tree === tree) return { changed: false };
  if (info) await unlink(state);
  // npm diagnostics go to stderr; stdout remains a small result for Ansible.
  execFileSync('npm', ['ci', '--prefix', directory, '--ignore-scripts', '--no-audit', '--no-fund'],
    { stdio: ['ignore', 2, 2] });
  if (await manifestFingerprint(directory) !== inputs) throw new Error('Package inputs changed during install; retry while idle');
  // npm legitimately omits node_modules for an empty dependency graph.
  await mkdir(join(directory, 'node_modules'), { recursive: true });
  const installed = await dependencyFingerprint(directory);
  if (!installed) throw new Error('npm completed without an installed dependency tree');
  const temporary = state + '.' + randomUUID() + '.tmp';
  try {
    await writeFile(temporary, JSON.stringify({ inputs, tree: installed }) + '\n', { flag: 'wx', mode: 0o600 });
    await rename(temporary, state);
  } finally {
    await unlink(temporary).catch(e => { if (e.code !== 'ENOENT') throw e; });
  }
  return { changed: true };
}

async function physicalDirectory(path) {
  let current = '/';
  for (const part of path.split('/').filter(Boolean)) {
    current = join(current, part);
    try { await mkdir(current, { mode: 0o700 }); }
    catch (e) { if (e.code !== 'EEXIST') throw e; }
    const info = await lstat(current);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('Redirected private directory refused');
  }
}

export async function publishPlugins(source, destination) {
  source = resolve(source);
  destination = resolve(destination);
  if (await realpath(source) !== source) throw new Error('Physical plugin source required');
  await physicalDirectory(destination);
  const plugins = join(destination, 'plugins');
  await physicalDirectory(plugins);
  const names = ['kdco', ...['background-agents', 'worktree', 'notify'].map(n => `plugins/kdco-${n}.ts`)];
  // Validate the complete narrow set before publishing any links.
  for (const name of names) {
    const from = join(source, name), to = join(destination, name);
    const info = await lstat(from);
    if (info.isSymbolicLink() || !(name === 'kdco' ? info.isDirectory() : info.isFile())) {
      throw new Error(`Invalid managed plugin source: ${name}`);
    }
    if (from === to) continue;
    const existing = await lstat(to).catch(e => { if (e.code !== 'ENOENT') throw e; });
    if (existing && (!existing.isSymbolicLink() || await readlink(to) !== from)) {
      throw new Error(`Preserved conflicting managed plugin path: ${to}`);
    }
  }
  for (const name of names) {
    const from = join(source, name), to = join(destination, name);
    if (from === to) continue;
    try { await symlink(from, to); }
    catch (e) {
      if (e.code !== 'EEXIST' || await readlink(to).catch(() => '') !== from) throw e;
    }
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (process.argv.length !== 4) throw new Error('usage: publish-plugins.mjs SOURCE_CONFIG DESTINATION_CONFIG | install PACKAGE');
  if (process.argv[2] === 'install') console.log(JSON.stringify(await installDependencies(process.argv[3])));
  else await publishPlugins(process.argv[2], process.argv[3]);
}
