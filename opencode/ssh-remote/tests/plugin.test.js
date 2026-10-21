import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, writeFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import plugin from '../index.js';
import { fixture } from './fixture.js';

test('disabled/default is an exact no-op before any inputs are accessed', async () => {
  const input = new Proxy({}, { get() { throw Error('input accessed'); } });
  assert.deepEqual(await plugin(input), {});
  assert.deepEqual(await plugin(input, { enabled: false, catalog: '/missing', stateDirectory: '/missing' }), {});
});

test('options/catalog fail closed without network', async t => {
  const f = await fixture(t);
  const assertLocked = async options => {
    const hooks = await plugin(f.input, options);
    await assert.rejects(hooks['tool.definition']({ toolID: 'bash' }, {}), /lockdown/);
  };
  for (const override of [{ timeoutMs: 600001 }, { catalog: 'relative' }, { project: 'fake.missing' }, { extra: true }])
    await assertLocked({ ...f.options, ...override });
  for (const override of [{ host_key_sha256: 'SHA256:base64' }, { port: 0 }, { cwd: '/a/../b' }, { password: 'not-allowed' }]) {
    await f.save([{ ...f.target, ...override }]);
    await assertLocked(f.options);
  }
  await f.save([f.target, f.target]);
  await assertLocked(f.options);
  assert.equal(f.connections(), 0);
});

test('permission deny and path injection precede SSH; catalog is rechecked after ask', async t => {
  const f = await fixture(t);
  const hooks = await plugin(f.input, f.options);
  await assert.rejects(hooks.tool.write.execute({ filePath: 'new', content: 'x' }, f.ctx('s', async () => { throw Error('Plan edit deny'); })), /Plan edit deny/);
  await assert.rejects(hooks.tool.read.execute({ filePath: '../escape' }, f.ctx()), /outside/);
  await assert.rejects(hooks.tool.apply_patch.execute({ patchText: '*** Begin Patch\n*** Add File: /outside\n+x\n*** End Patch' }, f.ctx()), /outside/);
  await assert.rejects(hooks.tool.read.execute({ filePath: 'x' }, f.ctx('s', async () => f.save([]))), /revoked/);
  assert.equal(f.connections(), 0);
  assert.ok(!(await readdir(f.directory)).includes('state'));
});

test('config guards preserve auth/provider and permissions; unknown definitions fail before model', async t => {
  const f = await fixture(t);
  const hooks = await plugin(f.input, f.options);
  const cfg = { permission: { edit: 'deny' }, agent: { plan: { permission: { edit: 'deny' } } }, plugin: ['provider-auth'], provider: { example: {} }, mcp: { fake: { type: 'local', command: ['false'] } } };
  await hooks.config(cfg);
  assert.deepEqual(cfg.permission, { edit: 'deny' });
  assert.equal(cfg.agent.plan.permission.edit, 'deny');
  assert.deepEqual(cfg.plugin, ['provider-auth']);
  assert.deepEqual(cfg.mcp.fake, { enabled: false });
  assert.equal(cfg.snapshot, false); assert.equal(cfg.lsp, false); assert.equal(cfg.formatter, false);
  assert.deepEqual(cfg.watcher.ignore, ['**']);
  await assert.rejects(hooks['tool.definition']({ toolID: 'mcp_private' }, {}), /Unreviewed/);
  await assert.rejects(hooks['tool.definition']({ toolID: '__proto__' }, {}), /Unreviewed/);
  await assert.rejects(hooks['tool.execute.before']({ tool: 'skill', sessionID: 's' }), /Unsupported/);
  await assert.rejects(hooks['shell.env']({}, {}), /Local shell/);
  assert.equal(f.connections(), 0);
});

test('malformed replacement catalog fails without echoing its contents', async t => {
  const f = await fixture(t);
  const hooks = await plugin(f.input, f.options);
  await writeFile(f.options.catalog, '{"private-fixture-nonce": INVALID}');
  await assert.rejects(hooks.tool.read.execute({ filePath: 'x' }, f.ctx()), error => {
    assert.equal(error.message, 'Invalid project catalog JSON');
    assert.ok(!error.message.includes('private-fixture-nonce'));
    return true;
  });
  assert.equal(f.connections(), 0);
});

test('session bindings isolate launches, children, resumes and parallel targets', async t => {
  const f = await fixture(t);
  const a = await plugin(f.input, f.options);
  const system = { system: [] };
  await a['experimental.chat.system.transform']({ sessionID: 'root' }, system);
  assert.match(system.system[0], /fake\.project/);
  const second = { ...f.target, ref: 'fake.other' };
  await f.save([f.target, second]);
  const b = await plugin(f.input, { ...f.options, project: second.ref });
  f.parents.set('child', 'root');
  for (const id of ['root', 'child'])
    await assert.rejects(b['experimental.chat.system.transform']({ sessionID: id }, { system: [] }), /target mismatch/);
  const results = await Promise.allSettled([a, b].map(h => h['experimental.chat.system.transform']({ sessionID: 'race' }, { system: [] })));
  assert.equal(results.filter(r => r.status === 'fulfilled').length, 1);
  await b['experimental.chat.system.transform']({ sessionID: 'independent' }, { system: [] });
  const bad = await plugin({ ...f.input, client: { ...f.input.client, session: { get: async () => ({ error: 'missing' }) } } }, f.options);
  await assert.rejects(bad['experimental.chat.system.transform']({ sessionID: 'lookup-failed' }, { system: [] }), /lookup failed/);
  assert.equal(f.connections(), 0);
});

test('MCP status rejects active or unverified servers before model dispatch', async t => {
  const f = await fixture(t);
  const h = await plugin(f.input, f.options);
  for (const data of [{ injected: { status: 'connected' } }, { injected: { status: 'failed' } }, null]) {
    f.input.client.mcp.status = async () => ({ data });
    await assert.rejects(h['experimental.chat.system.transform']({ sessionID: 's' }, { system: [] }), /MCP must be disabled/);
  }
  f.input.client.mcp.status = async () => ({ data: { known: { status: 'disabled' } } });
  await h['experimental.chat.system.transform']({ sessionID: 's' }, { system: [] });
  assert.equal(f.connections(), 0);
});

test('localhost helper: file operations, hashes, patches, shell data and no local fallback', async t => {
  const f = await fixture(t);
  const h = await plugin(f.input, f.options);
  const call = (op, args, session = 's') => h.tool[op].execute(args, f.ctx(session));
  const odd = "file ';$(touch NEVER_EXECUTED).txt";
  await call('write', { filePath: odd, content: 'hello\n' });
  assert.equal((await call('read', { filePath: odd })).output, 'hello\n');
  await assert.rejects(call('write', { filePath: odd, content: 'wrong' }, 'other'), /conflict/);
  await call('edit', { filePath: './' + odd, oldString: 'hello', newString: 'world' });
  assert.equal(await readFile(path.join(f.target.cwd, odd), 'utf8'), 'world\n');
  await writeFile(path.join(f.target.cwd, odd), 'external\n');
  await assert.rejects(call('edit', { filePath: odd, oldString: 'world', newString: 'wrong' }), /conflict/);
  await call('read', { filePath: odd });
  await call('apply_patch', { patchText: `*** Begin Patch\n*** Update File: ${odd}\n*** Move to: moved.txt\n@@\n-external\n+patched\n*** Add File: added.txt\n+added\n*** End Patch` });
  assert.equal(await readFile(path.join(f.target.cwd, 'moved.txt'), 'utf8'), 'patched\n');
  assert.match((await call('glob', { pattern: '*.txt' })).output, /moved.txt/);
  assert.match((await call('grep', { pattern: 'patched', include: '*.txt' })).output, /patched/);
  assert.equal((await call('bash', { command: "printf 'remote-shell'", description: 'fixture' })).output, 'remote-shell');
  const nonzero = await call('bash', { command: 'exit 7' });
  assert.equal(nonzero.metadata.exit_code, 7);
  assert.equal(nonzero.title, '[fake.project] bash');
  assert.ok(f.permissions.every(p => p.always.length === 0 && p.patterns.every(pattern => pattern.startsWith('fake.project:'))));
  assert.ok(f.permissions.some(p => p.permission === 'edit'));
  await f.save([{ ...f.target, port: f.target.port + 1 }]);
  const count = f.connections();
  await assert.rejects(call('bash', { command: 'touch LOCAL_FALLBACK' }), /endpoint changed/);
  assert.equal(f.connections(), count);
  assert.ok(!(await readdir(f.target.cwd)).includes('NEVER_EXECUTED'));
  assert.ok(!(await readdir(f.directory)).includes('LOCAL_FALLBACK'));
});

test('read limits and visible truncation do not grant unseen-file writes', async t => {
  const f = await fixture(t);
  await writeFile(path.join(f.target.cwd, 'many-lines'), 'line\n'.repeat(1100));
  const h = await plugin(f.input, f.options);
  const read = await h.tool.read.execute({ filePath: 'many-lines' }, f.ctx());
  assert.equal(read.metadata.truncated, true);
  assert.match(read.output, /truncated/);
  await assert.rejects(h.tool.write.execute({ filePath: 'many-lines', content: 'lost lines' }, f.ctx()), /conflict/);
  const partial = await h.tool.read.execute({ filePath: 'many-lines', offset: 2, limit: 1 }, f.ctx());
  assert.match(partial.output, /^line\n\n\[remote output truncated\]$/);
  assert.equal(partial.metadata.truncated, true);
});
