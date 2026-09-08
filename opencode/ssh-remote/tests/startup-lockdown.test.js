import test from 'node:test';
import assert from 'node:assert/strict';
import plugin from '../index.js';
import { fixture } from './fixture.js';
import { load, commit, excerpts, excerpt } from './pinned-loader.js';
import { readdir, writeFile, mkdir, chmod, access } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';

test('pinned host really swallows factory failures and returns without registered hooks', async () => {
  assert.deepEqual(await load(async () => { throw Error('synthetic factory failure'); }, {}, {}), []);
});

test('native binary version probe uses only an isolated fixture home', {
  skip: !process.env.OPENCODE_TEST_BINARY && 'Opt-in isolated binary probe; not a full engine test',
}, async t => {
  const f = await fixture(t);
  const result = spawnSync(process.env.OPENCODE_TEST_BINARY, ['--version'], {
    cwd: f.directory, encoding: 'utf8', timeout: 10000,
    env: { PATH: '/usr/local/bin:/usr/bin:/bin', HOME: f.directory,
      XDG_CONFIG_HOME: path.join(f.directory, 'config'), XDG_DATA_HOME: path.join(f.directory, 'data'),
      XDG_STATE_HOME: path.join(f.directory, 'state'), XDG_CACHE_HOME: path.join(f.directory, 'cache'),
      OPENCODE_DISABLE_AUTOUPDATE: '1', OPENCODE_DISABLE_MODELS_FETCH: '1' },
  });
  assert.equal(result.status, 0, result.stderr || String(result.error || ''));
  t.diagnostic('Isolated native binary version: ' + result.stdout.trim());
  assert.equal(f.connections(), 0);
});

test('isolated native 1.18.29 engine rejects invalid remote startup before native Bash', {
  skip: !process.env.OPENCODE_TEST_BINARY && 'Opt-in full native engine fixture; npm run test:engine',
}, async t => {
  const f = await fixture(t);
  const neutral = path.join(f.directory, 'neutral');
  const configHome = path.join(f.directory, 'config');
  const configDir = path.join(configHome, 'opencode');
  await mkdir(neutral);
  await mkdir(configDir, { recursive: true });
  // Pinned core/src/npm.ts: install returns immediately for an unwritable dir.
  // No installs outside the package, no dependency symlinks or global settings.
  await chmod(configDir, 0o500);
  const env = { PATH: '/usr/local/bin:/usr/bin:/bin', HOME: f.directory,
    XDG_CONFIG_HOME: configHome, XDG_DATA_HOME: path.join(f.directory, 'data'),
    XDG_STATE_HOME: path.join(f.directory, 'state'), XDG_CACHE_HOME: path.join(f.directory, 'cache'),
    OPENCODE_DISABLE_AUTOUPDATE: '1', OPENCODE_DISABLE_MODELS_FETCH: '1',
    OPENCODE_DISABLE_DEFAULT_PLUGINS: '1', OPENCODE_DISABLE_PROJECT_CONFIG: '1',
    OPENCODE_DISABLE_EXTERNAL_SKILLS: '1', OPENCODE_DISABLE_CLAUDE_CODE: '1',
    OPENCODE_EXPERIMENTAL_DISABLE_FILEWATCHER: '1' };
  try {
    const version = spawnSync(process.env.OPENCODE_TEST_BINARY, ['--version'], { cwd: neutral, env, encoding: 'utf8', timeout: 10000 });
    assert.equal(version.status, 0, version.stderr);
    assert.equal(version.stdout.trim(), '1.18.29', 'fixture requires the reviewed native version');
    for (const options of [{ ...f.options, project: 'fake.missing' }, { enabled: 'true' }]) {
      const config = { $schema: 'https://opencode.ai/config.json',
        plugin: [[new URL('../index.js', import.meta.url).href, options]],
        enabled_providers: [], agent: { fixture: { mode: 'primary', model: 'fixture/fixture' } },
        snapshot: false, lsp: false, formatter: false, autoupdate: false, share: 'disabled' };
      const result = spawnSync(process.env.OPENCODE_TEST_BINARY,
        ['debug', 'agent', 'fixture', '--tool', 'bash', '--params', JSON.stringify({ command: 'touch NATIVE_SENTINEL', description: 'must never execute' })],
        { cwd: neutral, env: { ...env, OPENCODE_CONFIG_CONTENT: JSON.stringify(config) }, encoding: 'utf8', timeout: 20000, maxBuffer: 1024 * 1024 });
      assert.equal(result.error, undefined, String(result.error || ''));
      assert.notEqual(result.status, 0, 'native CLI must reject tool dispatch');
      assert.match(result.stderr + result.stdout, /SSH remote lockdown/, 'must fail via registered plugin, not an unrelated startup error');
      await assert.rejects(access(path.join(neutral, 'NATIVE_SENTINEL')), { code: 'ENOENT' });
    }
    assert.deepEqual(await readdir(configDir), [], 'native bootstrap did not install dependencies or mutate configuration');
    assert.equal(f.connections(), 0);
  } finally { await chmod(configDir, 0o700); }
});

test('invalid enabled startup survives host catch as blocking hooks, not missing plugin', async t => {
  const f = await fixture(t);
  const [hooks] = await load(plugin, f.input, { ...f.options, project: 'fake.missing' });
  assert.ok(hooks, 'the host must retain lockdown hooks rather than continue without the plugin');
  await assert.rejects(hooks['experimental.chat.system.transform']({}, { system: [] }), /lockdown/i);
});

test('schema-valid enabled profiles with invalid targets retain every lockdown guard', async t => {
  const f = await fixture(t);
  const before = await readdir(f.directory);
  for (const override of [{ project: 'fake.missing' }, { catalog: f.catalog + '.missing' }, { timeoutMs: 600001 }, { stateDirectory: 'relative' }]) {
    const [hooks] = await load(plugin, f.input, { ...f.options, ...override });
    assert.ok(hooks, 'loader did not retain hooks');
    const cfg = { permission: { edit: 'deny' }, plugin: ['unrelated-auth'], mcp: { fake: { enabled: true } } };
    await hooks.config(cfg);
    assert.equal(cfg.snapshot, false); assert.equal(cfg.lsp, false); assert.equal(cfg.formatter, false);
    assert.deepEqual(cfg.watcher.ignore, ['**']);
    assert.deepEqual(cfg.mcp.fake, { enabled: false });
    assert.deepEqual(cfg.permission, { edit: 'deny' });
    assert.deepEqual(cfg.plugin, ['unrelated-auth']);
    for (const name of ['experimental.chat.system.transform', 'tool.definition', 'tool.execute.before', 'shell.env'])
      await assert.rejects(hooks[name]({ tool: 'bash', toolID: 'bash' }, { system: [] }), /lockdown/);
  }
  await writeFile(f.catalog, '{malformed');
  const [malformed] = await load(plugin, f.input, f.options);
  await assert.rejects(malformed['tool.definition']({ toolID: 'read' }, {}), /lockdown/);
  assert.equal(f.connections(), 0);
  assert.deepEqual(await readdir(f.directory), before, 'no state/key/network effects during lockdown');
});

test('disabled/omitted activation bypasses all initialization IO even through the host', async () => {
  const input = new Proxy({}, { get() { throw Error('no input access permitted'); } });
  for (const options of [undefined, {}, { enabled: false, get catalog() { throw Error('no catalog access'); } }])
    assert.deepEqual(await load(plugin, input, options), [{}]);
});

test('loader excerpts exactly match the immutable upstream commit', {
  skip: process.env.VERIFY_OPENCODE_SOURCE !== '1' && 'Opt-in pinned source fetch; npm run test:loader',
}, async () => {
  for (const [name, file] of excerpts) {
    const response = await fetch(`https://raw.githubusercontent.com/anomalyco/opencode/${commit}/packages/opencode/src/plugin/${file}`);
    assert.equal(response.ok, true);
    assert.ok((await response.text()).includes(await excerpt(name)), name + ' drifted from pinned source');
  }
});

test('null options and invalid enabled types return lockdown, never silent local mode', async () => {
  for (const options of [null, [], 'true', { enabled: 'true' }, { enabled: 'false' }, { enabled: 0 }, { enabled: null }]) {
    const [hooks] = await load(plugin, {}, options);
    assert.equal(typeof hooks?.['tool.execute.before'], 'function', 'invalid options must retain a blocking hook');
    await assert.rejects(hooks['tool.execute.before']({ tool: 'bash' }, {}), /lockdown/i);
  }
});
