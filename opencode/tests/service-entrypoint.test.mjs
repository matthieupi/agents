// Exercise actual VM startup shell/publication with only absolute paths relocated.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, rm, symlink, readlink, lstat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync, execFileSync } from 'node:child_process';
import { publishConfig } from '../.opencode/config/publish-plugins.mjs';

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'opencode-startup-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const home = join(root, 'home'), defaults = join(root, 'defaults'), resources = join(root, 'agent');
  const destination = join(home, '.config/opencode');
  for (const directory of [home, defaults, resources, join(defaults, 'plugins'),
    join(defaults, 'tui-plugins'), join(defaults, 'tui-plugins/session-title')]) await mkdir(directory);
  for (const name of ['commands', 'skills', 'system']) await mkdir(join(resources, name));
  const canonical = JSON.stringify({ plugins: ['./plugins/background-subagents.js'] });
  await writeFile(join(defaults, 'opencode.json'), canonical);
  await writeFile(join(defaults, 'plugins/background-subagents.js'), "export default 'background-subagents'");
  await writeFile(join(defaults, 'cli.json'), '{"plugins":["./tui-plugins/session-title"]}');
  await writeFile(join(defaults, 'tui-plugins/session-title.mjs'), 'export {}');
  await writeFile(join(defaults, 'tui-plugins/session-title/tui.js'), 'export {}');
  const helper = fileURLToPath(new URL('../.opencode/config/publish-plugins.mjs', import.meta.url));
  const shell = (await readFile(new URL('../service-entrypoint.sh', import.meta.url), 'utf8'))
    .replaceAll('/opt/opencode/component/scripts/publish-plugins.mjs', helper)
    .replaceAll('/opt/opencode-defaults', defaults).replaceAll('/opt/agent', resources);
  const env = { PATH: '/usr/local/bin:/usr/bin:/bin', HOME: home, OPENCODE_CONFIG_DIR: destination };
  const launch = (command = ['/usr/bin/printf', 'launched:%s', 'exact argument'], overrides = {}) =>
    spawnSync('/bin/bash', ['-c', shell, '--', ...command],
      { env: { ...env, ...overrides }, encoding: 'utf8', timeout: 10000 });
  return { home, defaults, resources, destination, canonical, launch };
}

test('VM startup publishes V2 config, background plugin and footer assets before exact exec', async t => {
  const f = await fixture(t);
  const first = f.launch();
  assert.equal(first.status, 0, first.stderr);
  assert.equal(first.stdout, 'launched:exact argument');
  for (const relative of ['opencode.json', 'plugins/background-subagents.js',
    'tui-plugins/session-title.mjs', 'tui-plugins/session-title/tui.js']) {
    assert.equal(await readlink(join(f.destination, relative)), join(f.defaults, relative));
  }
  assert.equal((await lstat(join(f.destination, 'cli.json'))).isFile(), true);
  assert.equal(await readFile(join(f.destination, 'cli.json'), 'utf8'), await readFile(join(f.defaults, 'cli.json'), 'utf8'));
  assert.equal(f.launch().status, 0);
  await writeFile(join(f.defaults, 'plugins/background-subagents.js'), 'updated');
  assert.equal(await readFile(join(f.destination, 'plugins/background-subagents.js'), 'utf8'), 'updated');
});

test('retires exact managed title-generator links in either discovery directory', async t => {
  for (const directory of ['plugins', 'plugin']) {
    for (const prefix of ['source', '/opt/opencode-defaults', '/opt/opencode/component/.opencode/config']) {
      const f = await fixture(t);
      await mkdir(join(f.destination, directory), { recursive: true });
      const path = join(f.destination, directory, 'first-prompt-title.js');
      await symlink(join(prefix === 'source' ? f.defaults : prefix, directory, 'first-prompt-title.js'), path);
      const result = f.launch();
      assert.equal(result.status, 0, result.stderr);
      await assert.rejects(lstat(path), { code: 'ENOENT' });
      assert.equal(await readlink(join(f.destination, 'plugins/background-subagents.js')),
        join(f.defaults, 'plugins/background-subagents.js'));
      assert.equal((await lstat(join(f.destination, 'tui-plugins/session-title/tui.js'))).isSymbolicLink(), true);
    }
  }
});

test('retires byte-identical title-generator copies but preserves private files and custom links', async t => {
  for (const directory of ['plugins', 'plugin']) {
    const f = await fixture(t);
    await mkdir(join(f.destination, directory), { recursive: true });
    const path = join(f.destination, directory, 'first-prompt-title.js');
    const bytes = execFileSync('git', ['show', '8a6ba61:opencode/.opencode/config/plugins/first-prompt-title.js'],
      { cwd: fileURLToPath(new URL('../..', import.meta.url)) });
    await writeFile(path, bytes);
    assert.equal(f.launch().status, 0);
    await assert.rejects(lstat(path), { code: 'ENOENT' });
    await writeFile(path, 'private custom title behavior');
    assert.equal(f.launch().status, 0);
    assert.equal(await readFile(path, 'utf8'), 'private custom title behavior');
    await rm(path);
    await symlink('/private/custom-title.js', path);
    assert.equal(f.launch().status, 0);
    assert.equal(await readlink(path), '/private/custom-title.js');
  }
});

test('title-generator retirement waits until all configuration conflicts are checked', async t => {
  const f = await fixture(t);
  await mkdir(join(f.destination, 'plugins'), { recursive: true });
  const path = join(f.destination, 'plugins/first-prompt-title.js');
  await symlink('/opt/opencode-defaults/plugins/first-prompt-title.js', path);
  await writeFile(join(f.destination, 'cli.json'), '{invalid');
  const result = f.launch();
  assert.notEqual(result.status, 0);
  assert.equal(await readlink(path), '/opt/opencode-defaults/plugins/first-prompt-title.js');
});

test('existing CLI preferences allow startup and gain only required plugin registration idempotently', async t => {
  const f = await fixture(t);
  await mkdir(f.destination, { recursive: true });
  const path = join(f.destination, 'cli.json');
  const settings = { theme: { name: 'custom' }, keybinds: { leader: 'ctrl+x' }, plugins: ['private-plugin'] };
  await writeFile(path, JSON.stringify(settings));
  const sourceBefore = await readFile(join(f.defaults, 'cli.json'), 'utf8');
  const first = f.launch();
  assert.equal(first.status, 0, first.stderr);
  assert.equal(first.stdout, 'launched:exact argument');
  assert.deepEqual(JSON.parse(await readFile(path, 'utf8')), {
    ...settings, plugins: ['private-plugin', './tui-plugins/session-title'],
  });
  assert.equal((await lstat(path)).isFile(), true);
  const after = await readFile(path, 'utf8');
  assert.equal(f.launch().status, 0);
  assert.equal(await readFile(path, 'utf8'), after);
  assert.equal(await readFile(join(f.defaults, 'cli.json'), 'utf8'), sourceBefore);
});

test('existing CLI settings without plugins preserve preferences without applying public defaults', async t => {
  const f = await fixture(t);
  await mkdir(f.destination, { recursive: true });
  const settings = { theme: { name: 'custom' }, custom: { enabled: false } };
  await writeFile(join(f.destination, 'cli.json'), JSON.stringify(settings));
  assert.equal(f.launch().status, 0);
  assert.deepEqual(JSON.parse(await readFile(join(f.destination, 'cli.json'), 'utf8')), {
    ...settings, plugins: ['./tui-plugins/session-title'],
  });
});

test('already registered CLI plugin preserves bytes and configured plugin options', async t => {
  for (const registration of ['./tui-plugins/session-title', ['./tui-plugins/session-title', { enabled: true }]]) {
    const f = await fixture(t);
    await mkdir(f.destination, { recursive: true });
    const path = join(f.destination, 'cli.json');
    const content = JSON.stringify({ plugins: [registration, 'private-plugin'], theme: { name: 'custom' } }, null, 4);
    await writeFile(path, content);
    const result = f.launch();
    assert.equal(result.status, 0, result.stderr);
    assert.equal(await readFile(path, 'utf8'), content);
  }
});

test('retired title-module registration is replaced without removing unrelated plugins', async t => {
  const f = await fixture(t);
  await mkdir(f.destination, { recursive: true });
  await writeFile(join(f.destination, 'cli.json'), JSON.stringify({
    plugins: ['private-plugin', './tui-plugins/session-title.mjs'], theme: { name: 'custom' },
  }));
  const result = f.launch();
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(await readFile(join(f.destination, 'cli.json'), 'utf8')), {
    plugins: ['private-plugin', './tui-plugins/session-title'], theme: { name: 'custom' },
  });
});

test('invalid CLI JSON or plugin-list shape is preserved and blocks before managed publication', async t => {
  for (const content of ['{broken', 'null', '[]', '{"plugins":"private-plugin"}']) {
    const f = await fixture(t);
    await mkdir(f.destination, { recursive: true });
    const path = join(f.destination, 'cli.json');
    await writeFile(path, content);
    const result = f.launch();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /invalid CLI configuration.*cli\.json/i);
    assert.equal(result.stdout, '');
    assert.equal(await readFile(path, 'utf8'), content);
    await assert.rejects(readlink(join(f.destination, 'opencode.json')), { code: 'ENOENT' });
  }
});

test('unknown CLI symlink is preserved without modifying its target', async t => {
  const f = await fixture(t);
  await mkdir(f.destination, { recursive: true });
  const target = join(f.home, 'private-cli.json');
  const content = '{"theme":{"name":"custom"}}';
  await writeFile(target, content);
  await symlink(target, join(f.destination, 'cli.json'));
  const result = f.launch();
  assert.notEqual(result.status, 0);
  assert.equal(await readlink(join(f.destination, 'cli.json')), target);
  assert.equal(await readFile(target, 'utf8'), content);
});

test('private config conflicts block launch and leave managed files/wrappers untouched', async t => {
  const f = await fixture(t);
  await mkdir(join(f.destination, 'plugins'), { recursive: true });
  await writeFile(join(f.destination, 'opencode.jsonc'), 'private settings');
  const wrapper = join(f.destination, 'plugins/kdco-notify.ts');
  await writeFile(wrapper, 'export { default } from "../kdco/notify"\n');
  const conflict = f.launch();
  assert.notEqual(conflict.status, 0);
  assert.equal(conflict.stdout, '');
  assert.match(conflict.stderr, /conflict/i);
  assert.equal(await readFile(join(f.destination, 'opencode.jsonc'), 'utf8'), 'private settings');
  assert.equal(await readFile(wrapper, 'utf8'), 'export { default } from "../kdco/notify"\n');
  await assert.rejects(readlink(join(f.destination, 'opencode.json')), { code: 'ENOENT' });
});

test('promotes exact public V1 snapshot and retires only recognized wrappers; private state survives', async t => {
  const f = await fixture(t);
  await mkdir(join(f.destination, 'plugins'), { recursive: true });
  const old = execFileSync('git', ['show', 'c19d250:opencode/.opencode/config/opencode.json'],
    { cwd: fileURLToPath(new URL('../..', import.meta.url)) });
  await writeFile(join(f.destination, 'opencode.json'), old);
  await symlink('/opt/opencode/component/.opencode/config/plugins/kdco-notify.ts', join(f.destination, 'plugins/kdco-notify.ts'));
  await writeFile(join(f.destination, 'plugins/kdco-worktree.ts'), 'export { default } from "../kdco/worktree"\n');
  await writeFile(join(f.destination, 'auth.json'), 'private auth');
  const result = f.launch();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(await readlink(join(f.destination, 'opencode.json')), join(f.defaults, 'opencode.json'));
  for (const name of ['notify', 'worktree']) await assert.rejects(readlink(join(f.destination, `plugins/kdco-${name}.ts`)), { code: 'ENOENT' });
  assert.equal(await readFile(join(f.destination, 'auth.json'), 'utf8'), 'private auth');
});

test('modified V1 snapshot, unknown wrapper, and whole-config symlink are preserved', async t => {
  for (const kind of ['config', 'wrapper', 'directory']) {
    const f = await fixture(t);
    if (kind === 'directory') {
      await mkdir(join(f.home, '.config'));
      await symlink(f.defaults, f.destination);
    } else {
      await mkdir(join(f.destination, 'plugins'), { recursive: true });
      await writeFile(join(f.destination, kind === 'config' ? 'opencode.json' : 'plugins/kdco-notify.ts'), 'private');
    }
    const result = f.launch();
    assert.notEqual(result.status, 0, kind);
    assert.equal(result.stdout, '');
    if (kind === 'directory') assert.equal(await readlink(f.destination), f.defaults);
    else assert.equal(await readFile(join(f.destination, kind === 'config' ? 'opencode.json' : 'plugins/kdco-notify.ts'), 'utf8'), 'private');
  }
});

test('known managed links refresh; unknown links and redirected public plugin roots fail closed', async t => {
  const f = await fixture(t);
  await mkdir(join(f.destination, 'plugins'), { recursive: true });
  await symlink('/opt/opencode-defaults/opencode.json', join(f.destination, 'opencode.json'));
  let result = f.launch();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(await readlink(join(f.destination, 'opencode.json')), join(f.defaults, 'opencode.json'));
  await rm(join(f.destination, 'opencode.json'));
  await symlink('/private/custom.json', join(f.destination, 'opencode.json'));
  result = f.launch();
  assert.notEqual(result.status, 0);
  assert.equal(await readlink(join(f.destination, 'opencode.json')), '/private/custom.json');
  await rm(join(f.destination, 'opencode.json'));
  await rm(join(f.defaults, 'plugins'), { recursive: true });
  await symlink(f.resources, join(f.defaults, 'plugins'));
  result = f.launch();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /redirected/i);
});

test('tracked TUI documentation and tests are ignored, not published or executed', async t => {
  const f = await fixture(t);
  for (const name of ['README.md', 'run-tests.mjs', 'session-title.test.mjs']) {
    await writeFile(join(f.defaults, 'tui-plugins', name), 'not a runtime asset');
  }
  assert.equal(f.launch().status, 0);
  for (const name of ['README.md', 'run-tests.mjs', 'session-title.test.mjs']) {
    await assert.rejects(readFile(join(f.destination, 'tui-plugins', name)), { code: 'ENOENT' });
  }
  // Known filenames do not grant permission to follow redirected sources.
  await rm(join(f.defaults, 'tui-plugins/README.md'));
  await symlink(join(f.defaults, 'cli.json'), join(f.defaults, 'tui-plugins/README.md'));
  const redirected = f.launch();
  assert.notEqual(redirected.status, 0);
  assert.match(redirected.stderr, /invalid public asset/i);
});

test('unsupported public executable blocks publication before any config is installed', async t => {
  const f = await fixture(t);
  await writeFile(join(f.defaults, 'plugins/unknown.py'), 'print("not supported")');
  const result = f.launch();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /invalid public asset/i);
  await assert.rejects(readFile(join(f.destination, 'opencode.json')), { code: 'ENOENT' });
});

test('direct native serve without protected V2 password fails before locks, config writes or exec', async t => {
  for (const executable of ['opencode', '/usr/local/bin/opencode']) {
    const f = await fixture(t);
    // Missing resource mount proves credential validation happens before locks.
    await rm(f.resources, { recursive: true });
    for (const password of [undefined, '']) {
      const result = f.launch([executable, 'serve'], {
        OPENCODE_PASSWORD: password, OPENCODE_SERVER_PASSWORD: 'legacy-not-sufficient',
      });
      assert.equal(result.status, 1);
      assert.equal(result.stdout, '');
      assert.match(result.stderr, /OPENCODE_PASSWORD is required for native serve/);
      assert.doesNotMatch(result.stderr, /legacy-not-sufficient/);
      await assert.rejects(readFile(join(f.destination, 'opencode.json')), { code: 'ENOENT' });
    }
  }
});

test('explicit native password permits exec; embedded commands do not require it', async t => {
  const f = await fixture(t), bin = join(f.home, 'bin');
  await mkdir(bin);
  for (const name of ['opencode', 'python', 'sshd']) {
    await writeFile(join(bin, name), '#!/bin/bash\nprintf "started:%s" "$*"\n', { mode: 0o700 });
  }
  const native = f.launch([join(bin, 'opencode'), 'serve', '--port', '4196'], { OPENCODE_PASSWORD: 'disposable-only' });
  assert.equal(native.status, 0, native.stderr);
  assert.equal(native.stdout, 'started:serve --port 4196');
  assert.doesNotMatch(native.stdout + native.stderr, /disposable-only/);
  for (const name of ['python', 'sshd']) {
    const embedded = f.launch([join(bin, name), 'embedded']);
    assert.equal(embedded.status, 0, embedded.stderr);
    assert.equal(embedded.stdout, 'started:embedded');
  }
});

test('complete canonical public source closure publishes without docs/test entrypoints', async t => {
  const f = await fixture(t);
  const source = fileURLToPath(new URL('../.opencode/config', import.meta.url));
  const resources = fileURLToPath(new URL('../../agent', import.meta.url));
  await publishConfig(source, resources, f.destination);
  assert.equal(await readFile(join(f.destination, 'opencode.json'), 'utf8'), await readFile(join(source, 'opencode.json'), 'utf8'));
  for (const relative of ['plugins/background-subagents.js',
    'tui-plugins/session-title.mjs', 'tui-plugins/session-title/tui.js']) {
    assert.equal(await readlink(join(f.destination, relative)), join(source, relative));
  }
  assert.equal((await lstat(join(f.destination, 'cli.json'))).isFile(), true);
  assert.equal(await readFile(join(f.destination, 'cli.json'), 'utf8'), await readFile(join(source, 'cli.json'), 'utf8'));
  for (const name of ['README.md', 'run-tests.mjs', 'session-title.test.mjs']) {
    await assert.rejects(readFile(join(f.destination, 'tui-plugins', name)), { code: 'ENOENT' });
  }
});
