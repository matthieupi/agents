// Exercise the actual startup shell with only container absolute paths relocated.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, rm, symlink, readlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

test('workstation initialization retires exact GSD links without changing private content', async t => {
  const root = await mkdtemp(join(tmpdir(), 'opencode-workstation-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const home = join(root, 'home'), resources = join(root, 'agent'), defaults = join(root, 'defaults');
  const config = join(home, '.config/opencode'), shared = join(home, '.agents');
  for (const path of [config, shared, join(defaults, 'kdco'), join(defaults, 'plugins')]) {
    await mkdir(path, { recursive: true });
  }
  for (const name of ['commands', 'skills', 'system']) await mkdir(join(resources, name), { recursive: true });
  for (const name of ['background-agents', 'notify', 'worktree']) {
    await writeFile(join(defaults, `plugins/kdco-${name}.ts`), '');
  }
  await writeFile(join(config, 'opencode.json'), 'private config');
  for (const directory of [config, shared]) await symlink(join(resources, 'gsd'), join(directory, 'gsd'));
  const helper = fileURLToPath(new URL('../scripts/publish-plugins.mjs', import.meta.url));
  const shell = (await readFile(new URL('../init.sh', import.meta.url), 'utf8'))
    .replaceAll('/home/opencode', home).replaceAll('/opt/agent', resources)
    .replaceAll('/opt/opencode-defaults', defaults).replaceAll('/opt/opencode-publish-plugins.mjs', helper);
  function initialize() {
    const result = spawnSync('/bin/bash', ['-c', shell], {
      env: { PATH: '/usr/local/bin:/usr/bin:/bin', HOME: home }, encoding: 'utf8', timeout: 10000,
    });
    assert.equal(result.status, 0, result.stderr);
  }
  initialize();
  for (const directory of [config, shared]) await assert.rejects(readlink(join(directory, 'gsd')), { code: 'ENOENT' });
  await symlink('/custom/gsd', join(config, 'gsd'));
  await mkdir(join(shared, 'gsd'));
  await writeFile(join(shared, 'gsd/private.md'), 'preserved');
  initialize();
  assert.equal(await readlink(join(config, 'gsd')), '/custom/gsd');
  assert.equal(await readFile(join(shared, 'gsd/private.md'), 'utf8'), 'preserved');
  assert.equal(await readFile(join(config, 'opencode.json'), 'utf8'), 'private config');
});

test('VM startup publishes config and plugins before exec; conflicts block launch', async t => {
  const root = await mkdtemp(join(tmpdir(), 'opencode-startup-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const home = join(root, 'home'), defaults = join(root, 'defaults');
  const resources = join(root, 'agent'), plugins = join(root, 'baked');
  const destination = join(home, '.config/opencode');
  for (const directory of [home, defaults, resources, plugins, join(defaults, 'plugins'),
                           join(plugins, 'plugins'), join(plugins, 'kdco')]) await mkdir(directory);
  for (const name of ['commands', 'skills', 'system']) await mkdir(join(resources, name));
  for (const name of ['background-agents', 'notify', 'worktree']) {
    await writeFile(join(plugins, `plugins/kdco-${name}.ts`), '');
  }
  await writeFile(join(defaults, 'opencode.json'), '{"permission":"allow"}');
  const helper = fileURLToPath(new URL('../scripts/publish-plugins.mjs', import.meta.url));
  const shell = (await readFile(new URL('../service-entrypoint.sh', import.meta.url), 'utf8'))
    .replaceAll('/opt/opencode/component/scripts/publish-plugins.mjs', helper)
    .replaceAll('/opt/opencode/component/.opencode/config', plugins)
    .replaceAll('/opt/opencode-defaults', defaults)
    .replaceAll('/opt/agent', resources);
  const env = { PATH: '/usr/local/bin:/usr/bin:/bin', HOME: home, OPENCODE_CONFIG_DIR: destination };
  function launch() {
    return spawnSync('/bin/bash', ['-c', shell, '--', '/usr/bin/printf', 'launched:%s', 'exact argument'],
                     { env, encoding: 'utf8', timeout: 10000 });
  }
  const first = launch();
  assert.equal(first.status, 0, first.stderr);
  assert.equal(first.stdout, 'launched:exact argument');
  assert.equal(await readFile(join(destination, 'opencode.json'), 'utf8'), '{"permission":"allow"}');
  assert.equal(await readFile(join(destination, 'plugins/kdco-notify.ts'), 'utf8'), '');
  await writeFile(join(destination, 'opencode.jsonc'), 'local config');
  const conflict = launch();
  assert.notEqual(conflict.status, 0);
  assert.equal(conflict.stdout, '');
  assert.match(conflict.stderr, /conflict/i);
  assert.equal(await readFile(join(destination, 'opencode.jsonc'), 'utf8'), 'local config');
});
