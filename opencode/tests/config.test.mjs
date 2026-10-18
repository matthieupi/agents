// Filesystem-only publication checks. No OpenCode, providers, npm or network.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, symlink, readlink, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as publication from '../scripts/publish-plugins.mjs';

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'opencode-config-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const source = join(root, 'defaults'), resources = join(root, 'agent'), home = join(root, 'home');
  for (const path of [source, resources, home, join(source, 'plugins')]) await mkdir(path);
  for (const name of ['system', 'commands', 'skills']) await mkdir(join(resources, name));
  await writeFile(join(resources, 'system/build.md'), 'maintained prompt');
  await writeFile(join(source, 'opencode.json'), JSON.stringify({ model: 'provider/model', permission: 'allow', agent: { build: { prompt: '{file:./system/build.md}' } } }));
  await writeFile(join(source, 'tui.json'), '{"theme":"system"}');
  await writeFile(join(source, 'plugins/title.js'), 'export default () => ({})');
  return { source, resources, destination: join(home, '.config/opencode'), home };
}

test('publishes whole configuration and resolvable resources without copying private state', async t => {
  const f = await fixture(t);
  await publication.publishConfig(f.source, f.resources, f.destination);
  assert.equal(await readFile(join(f.destination, 'opencode.json'), 'utf8'), await readFile(join(f.source, 'opencode.json'), 'utf8'));
  assert.equal(await readFile(join(f.destination, 'system/build.md'), 'utf8'), 'maintained prompt');
  assert.equal(await readlink(join(f.destination, 'tui.json')), join(f.source, 'tui.json'));
  assert.equal(await readlink(join(f.destination, 'plugins/title.js')), join(f.source, 'plugins/title.js'));
});

test('managed links follow updates and remove only retired managed links', async t => {
  const f = await fixture(t);
  await publication.publishConfig(f.source, f.resources, f.destination);
  await writeFile(join(f.destination, 'plugins/private.js'), 'private plugin');
  await writeFile(join(f.source, 'opencode.json'), '{"model":"provider/new"}');
  await rm(join(f.source, 'plugins/title.js'));
  await publication.publishConfig(f.source, f.resources, f.destination);
  assert.equal(await readFile(join(f.destination, 'opencode.json'), 'utf8'), '{"model":"provider/new"}');
  await assert.rejects(readlink(join(f.destination, 'plugins/title.js')), { code: 'ENOENT' });
  assert.equal(await readFile(join(f.destination, 'plugins/private.js'), 'utf8'), 'private plugin');
});

test('preserves local config and redirected HOME conflicts rather than overwriting', async t => {
  const f = await fixture(t);
  await mkdir(f.destination, { recursive: true });
  await writeFile(join(f.destination, 'opencode.jsonc'), 'private settings');
  await assert.rejects(publication.publishConfig(f.source, f.resources, f.destination), /conflict/i);
  assert.equal(await readFile(join(f.destination, 'opencode.jsonc'), 'utf8'), 'private settings');
  await rm(join(f.destination, 'opencode.jsonc'));
  await rm(join(f.destination, 'plugins'), { recursive: true });
  await symlink(f.source, join(f.destination, 'plugins'));
  await assert.rejects(publication.publishConfig(f.source, f.resources, f.destination), /redirected/i);
});

test('canonical workstation models, permissions and every prompt survive publication unchanged', async t => {
  const f = await fixture(t);
  const config = await readFile(new URL('../.opencode/config/opencode.json', import.meta.url), 'utf8');
  await writeFile(join(f.source, 'opencode.json'), config);
  const resources = fileURLToPath(new URL('../../agent', import.meta.url));
  await publication.publishConfig(f.source, resources, f.destination);
  const delivered = await readFile(join(f.destination, 'opencode.json'), 'utf8');
  assert.equal(delivered, config);
  for (const [, path] of delivered.matchAll(/\{file:([^}]+)\}/g)) {
    assert.ok((await readFile(join(f.destination, path), 'utf8')).length > 0, path);
  }
  assert.ok(Object.keys(JSON.parse(delivered).agent).length > 2);
  const agents = JSON.parse(delivered).agent;
  assert.equal(agents.DevOps.mode, 'all');
  assert.equal(agents['DevOps Junior'].mode, 'subagent');
  assert.equal(agents['DevOps Junior'].hidden, true);
  assert.equal(agents['DevOps Junior'].model, 'openai/gpt-6-sol');
  assert.equal(agents['DevOps Medium'], undefined);
  assert.equal(agents['devops-low'], undefined);
  assert.ok(Object.keys(agents).every(name => !name.startsWith('gsd-')));
});

test('retires only exact legacy GSD links, preserving custom links and real content', async t => {
  const f = await fixture(t);
  await publication.publishConfig(f.source, f.resources, f.destination);
  const legacy = join(f.destination, 'gsd');
  for (const target of [join(f.resources, 'gsd'), join(f.source, 'gsd')]) {
    await symlink(target, legacy);
    await publication.publishConfig(f.source, f.resources, f.destination);
    await assert.rejects(readlink(legacy), { code: 'ENOENT' });
  }
  await symlink('/custom/gsd', legacy);
  await publication.publishConfig(f.source, f.resources, f.destination);
  assert.equal(await readlink(legacy), '/custom/gsd');
  await rm(legacy);
  await mkdir(legacy);
  await writeFile(join(legacy, 'private.md'), 'preserved');
  await publication.publishConfig(f.source, f.resources, f.destination);
  assert.equal(await readFile(join(legacy, 'private.md'), 'utf8'), 'preserved');
});

test('publication leaves credentials, sessions and unrelated discovery entries alone', async t => {
  const f = await fixture(t);
  const data = join(f.home, '.local/share/opencode');
  await mkdir(data, { recursive: true });
  await writeFile(join(data, 'auth.json'), 'private credentials');
  await writeFile(join(data, 'opencode.db'), 'private sessions');
  await mkdir(f.destination, { recursive: true });
  await writeFile(join(f.destination, 'private.txt'), 'private config');
  await publication.publishConfig(f.source, f.resources, f.destination);
  await publication.publishConfig(f.source, f.resources, f.destination);
  assert.equal(await readFile(join(data, 'auth.json'), 'utf8'), 'private credentials');
  assert.equal(await readFile(join(data, 'opencode.db'), 'utf8'), 'private sessions');
  assert.equal(await readFile(join(f.destination, 'private.txt'), 'utf8'), 'private config');
});
