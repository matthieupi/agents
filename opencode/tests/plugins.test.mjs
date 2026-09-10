import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile, readdir, rm, symlink, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { publishPlugins } from '../scripts/publish-plugins.mjs';

const source = fileURLToPath(new URL('../.opencode/config/', import.meta.url));
const names = ['background-agents', 'notify', 'worktree'];
async function temporary(t) {
  const root = await mkdtemp(join(tmpdir(), 'kdco-publication-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  return root;
}

test('only three static entrypoints; helpers stay outside recursive discovery', async () => {
  const entries = (await readdir(join(source, 'plugins'))).filter(n => n.startsWith('kdco-'));
  assert.deepEqual(entries.sort(), names.map(n => `kdco-${n}.ts`).sort());
  for (const name of names) {
    assert.equal(await readFile(join(source, `plugins/kdco-${name}.ts`), 'utf8'),
      `export { default } from "../kdco/${name}"\n`);
  }
});

test('upstream provenance: only the approved security-patched file differs', async () => {
  const upstream = JSON.parse(await readFile(join(source, 'kdco/upstream.json')));
  const changed = [];
  for (const [name, sha] of Object.entries(upstream.files)) {
    const actual = createHash('sha256').update(await readFile(join(source, 'kdco', name))).digest('hex');
    if (actual !== sha) changed.push(name);
  }
  assert.deepEqual(changed, ['background-agents.ts']);
});

test('fresh/repeated publication preserves all private fields and unrelated plugins', async t => {
  const root = await temporary(t);
  await mkdir(join(root, 'plugins'));
  for (const name of ['opencode.jsonc', 'package.json', 'package-lock.json', 'plugins/private.ts']) {
    await writeFile(join(root, name), 'private bytes, never parse or replace');
  }
  await publishPlugins(source, root);
  await publishPlugins(source, root);
  for (const name of ['opencode.jsonc', 'package.json', 'package-lock.json', 'plugins/private.ts']) {
    assert.equal(await readFile(join(root, name), 'utf8'), 'private bytes, never parse or replace');
  }
  assert.equal(await realpath(join(root, 'kdco')), join(source, 'kdco'));
});

test('conflicts and redirected private discovery directories fail without replacement', async t => {
  const root = await temporary(t);
  await mkdir(join(root, 'kdco'));
  await assert.rejects(publishPlugins(source, root), /Preserved conflicting/);
  assert.deepEqual(await readdir(join(root, 'plugins')), []);
  await rm(join(root, 'plugins'), { recursive: true });
  await symlink(join(root, 'kdco'), join(root, 'plugins'));
  await assert.rejects(publishPlugins(source, root), /Redirected/);
});

test('dependency resolution follows managed source through a private HOME mount', async t => {
  const root = await temporary(t);
  await publishPlugins(source, root);
  const pkg = JSON.parse(await readFile(join(source, 'kdco/package.json')));
  for (const name of Object.keys(pkg.dependencies)) {
    const resolved = execFileSync(process.execPath, ['--input-type=module', '-e',
      'console.log(import.meta.resolve(process.argv[1]))', name], { cwd: join(root, 'kdco'), encoding: 'utf8' });
    assert.ok(resolved.startsWith('file://' + join(source, 'kdco/node_modules/')), resolved);
  }
});

test('redirected config ancestor is rejected before creating children outside HOME', async t => {
  const root = await temporary(t);
  await mkdir(join(root, 'outside'));
  await symlink(join(root, 'outside'), join(root, '.config'));
  await assert.rejects(publishPlugins(source, join(root, '.config/opencode')), /Redirected/);
  assert.deepEqual(await readdir(join(root, 'outside')), []);
});
