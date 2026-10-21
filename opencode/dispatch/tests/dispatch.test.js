import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, chmod, symlink, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import https from 'node:https';
import { EventEmitter } from 'node:events';
import { createDispatch, privateRead, request } from '../core.js';
import DispatchPlugin from '../index.js';

async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'dispatch-test-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const passwordFile = path.join(root, 'password');
  await writeFile(passwordFile, 'protected-secret\n', { mode: 0o600 });
  const peer = { alias: 'worker', description: 'Reviews code', url: 'https://worker.invalid/', username: 'opencode', passwordFile };
  const options = { enabled: true, peers: [peer], stateDirectory: path.join(root, 'state') };
  const calls = [], asks = [], messages = [];
  const ctx = { sessionID: 'ses_hub', directory: '/hub', abort: new AbortController().signal, ask: async p => asks.push(p) };
  const transport = async (...args) => {
    calls.push(args);
    if (args[1] === '/session') return { id: 'ses_remote' };
    if (args[1].endsWith('/message')) {
      // Full native history includes users, IDs, session IDs and creation times.
      for (const [i, m] of messages.entries()) {
        m.info.id ??= `msg_fixture_${String(i).padStart(4, '0')}`;
        m.info.sessionID = 'ses_remote';
        m.info.time = { created: i, ...m.info.time };
      }
      return messages;
    }
    messages.push({ info: { id: args[2].messageID, role: 'user' }, parts: args[2].parts });
    return null;
  };
  const dispatch = createDispatch(options, transport);
  const run = async (op, args = {}, context = ctx) => JSON.parse(await dispatch.execute(op, args, context));
  return { root, peer, options, ctx, calls, asks, messages, transport, dispatch, run };
}

test('disabled no-op and invalid enabled configuration keeps unavailable tools', async () => {
  assert.deepEqual(await DispatchPlugin({}, {}), {});
  const hooks = await DispatchPlugin({}, { enabled: true });
  assert.equal(Object.keys(hooks.tool).length, 5);
  let asked = false;
  assert.match(await hooks.tool.dispatch_task.execute({}, { ask: async () => { asked = true; } }), /unavailable/);
  assert.ok(asked);
});

test('public catalog, permission, durable task, restart, result correlation and reply', async t => {
  const f = await fixture(t);
  assert.deepEqual(await f.run('peers'), [{ alias: 'worker', description: 'Reviews code' }]);
  const task = await f.run('task', { peer: 'worker', prompt: 'Review this' });
  assert.equal(task.state, 'accepted');
  assert.equal(f.calls[1][1], '/session/ses_remote/prompt_async');
  const message = f.calls[1][2].messageID;
  const record = await readFile(path.join(f.options.stateDirectory, task.handle + '.json'), 'utf8');
  for (const forbidden of ['protected-secret', 'password', 'Review this', 'https:']) assert.ok(!record.includes(forbidden));
  assert.equal((await f.run('status', { handle: task.handle })).state, 'pending');
  f.messages.push({ info: { role: 'assistant', parentID: 'msg_unrelated', time: { completed: 1 }, finish: 'stop' }, parts: [] });
  assert.equal((await f.run('status', { handle: task.handle })).state, 'blocked');
  f.messages.pop(); // The valid task continues once the foreign fixture is removed.
  f.messages.push({ info: { role: 'assistant', parentID: message, time: { completed: 1 }, finish: 'stop' }, parts: [{ type: 'text', text: 'Done' }, { type: 'reasoning', text: 'hidden' }] });
  const restarted = createDispatch(f.options, f.transport);
  const result = JSON.parse(await restarted.execute('result', { handle: task.handle }, f.ctx));
  assert.equal(result.state, 'completed'); assert.equal(result.text, 'Done');
  assert.equal((await f.run('reply', { handle: task.handle, prompt: 'Follow up' })).state, 'accepted');
  assert.equal(f.calls.filter(c => c[1] === '/session').length, 1);
  assert.ok(f.asks.every(a => a.permission.startsWith('dispatch_') && a.always.length === 0));
  assert.ok(!JSON.stringify(f.asks).includes('protected-secret'));
});

test('ownership, directory, endpoint changes and permission denial cannot contact peer', async t => {
  const f = await fixture(t);
  const task = await f.run('task', { peer: 'worker', prompt: 'Review' });
  f.calls.length = 0;
  for (const ctx of [{ ...f.ctx, sessionID: 'ses_other' }, { ...f.ctx, directory: '/other' }, { ...f.ctx, ask: async () => { throw Error('secret'); } }]) {
    assert.equal((await f.run('result', { handle: task.handle }, ctx)).state, 'unavailable');
  }
  const changed = createDispatch({ ...f.options, peers: [{ ...f.peer, url: 'https://other.invalid/' }] }, f.transport);
  assert.equal(JSON.parse(await changed.execute('status', { handle: task.handle }, f.ctx)).state, 'unavailable');
  assert.equal((await f.run('status', { handle: '../escape' })).state, 'unavailable');
  assert.equal(f.calls.length, 0);
});

test('ambiguous prompt acceptance retains handle without replay; pending reply refused', async t => {
  const f = await fixture(t);
  let posts = 0;
  const d = createDispatch(f.options, async (...args) => {
    if (args[1].endsWith('/prompt_async')) { posts++; throw Error('credential-bearing transport failure'); }
    return f.transport(...args);
  });
  const task = JSON.parse(await d.execute('task', { peer: 'worker', prompt: 'Run' }, f.ctx));
  assert.equal(task.state, 'unavailable'); assert.ok(task.handle);
  assert.ok(!JSON.stringify(task).includes('credential-bearing'));
  assert.equal(JSON.parse(await d.execute('status', { handle: task.handle }, f.ctx)).state, 'uncertain');
  assert.equal(JSON.parse(await d.execute('reply', { handle: task.handle, prompt: 'Again' }, f.ctx)).state, 'unavailable');
  assert.equal(posts, 1);
});

test('strict peer validation and protected credential files', async t => {
  const f = await fixture(t);
  for (const url of ['http://worker.invalid', 'https://user:pass@worker.invalid', 'https://worker.invalid/path', 'https://worker.invalid/?x=1', 'https://worker.invalid/#x']) {
    assert.throws(() => createDispatch({ ...f.options, peers: [{ ...f.peer, url }] }));
  }
  assert.throws(() => createDispatch({ ...f.options, peers: [f.peer, f.peer] }));
  await chmod(f.peer.passwordFile, 0o644);
  await assert.rejects(privateRead(f.peer.passwordFile, 4096));
  await chmod(f.peer.passwordFile, 0o600);
  await symlink(f.peer.passwordFile, path.join(f.root, 'link'));
  await assert.rejects(privateRead(path.join(f.root, 'link'), 4096));
  await assert.rejects(privateRead(f.peer.passwordFile, 2));
});

test('mocked native HTTPS verifies TLS, sends Basic only there, rejects redirects/errors/secret echoes', async t => {
  const f = await fixture(t);
  let status = 200, payload = '{"id":"ses_remote"}', calls = 0;
  t.mock.method(https, 'request', (url, options, callback) => {
    calls++;
    assert.equal(url.protocol, 'https:');
    assert.equal(options.rejectUnauthorized, true);
    assert.equal(options.agent, false);
    assert.equal(options.headers.Authorization, 'Basic ' + Buffer.from('opencode:protected-secret').toString('base64'));
    const req = new EventEmitter();
    req.destroy = error => { req.emit('error', error); req.emit('close'); };
    req.end = () => queueMicrotask(() => {
      const res = new EventEmitter(); res.statusCode = status;
      res.destroy = () => {};
      callback(res); res.emit('data', Buffer.from(payload)); res.emit('end'); req.emit('close');
    });
    return req;
  });
  assert.deepEqual(await request(f.peer, '/session', {}), { id: 'ses_remote' });
  for (const code of [301, 302, 307, 308, 401, 500]) {
    status = code;
    await assert.rejects(request(f.peer, '/session', {}), /no local fallback/);
  }
  assert.equal(calls, 7); // No redirect follow-up or retry.
  status = 200; payload = '{"text":"protected-\\u0073ecret"}';
  await assert.rejects(request(f.peer, '/session', {}));
  payload = 'x'.repeat(1024 * 1024 + 1);
  await assert.rejects(request(f.peer, '/session', {}));
});

test('concurrent replies submit once; stale mutation locks are not stolen', async t => {
  const f = await fixture(t);
  const task = await f.run('task', { peer: 'worker', prompt: 'Review' });
  f.messages.push({ info: { role: 'assistant', parentID: f.calls[1][2].messageID, time: { completed: 1 }, finish: 'stop' }, parts: [] });
  const results = await Promise.all([f.run('reply', { handle: task.handle, prompt: 'First' }), f.run('reply', { handle: task.handle, prompt: 'Second' })]);
  assert.equal(results.filter(r => r.state === 'accepted').length, 1);
  assert.equal(f.calls.filter(c => c[1].endsWith('/prompt_async')).length, 2);
  const last = f.calls.filter(c => c[1].endsWith('/prompt_async')).at(-1);
  f.messages.push({ info: { role: 'assistant', parentID: last[2].messageID, time: { completed: 1 }, finish: 'stop' }, parts: [] });
  await writeFile(path.join(f.options.stateDirectory, task.handle + '.lock'), '', { mode: 0o600 });
  assert.equal((await f.run('reply', { handle: task.handle, prompt: 'Again' })).state, 'unavailable');
  assert.equal(f.calls.filter(c => c[1].endsWith('/prompt_async')).length, 2);
});

test('summary/tool-call completion is not task completion; error details are not exposed', async t => {
  const f = await fixture(t);
  const task = await f.run('task', { peer: 'worker', prompt: 'Review' });
  const parentID = f.calls[1][2].messageID;
  f.messages.push({ info: { role: 'assistant', parentID, time: { completed: 1 }, finish: 'stop', summary: true }, parts: [{ type: 'text', text: 'summary' }] });
  f.messages.push({ info: { role: 'assistant', parentID, time: { completed: 1 }, finish: 'tool-calls' }, parts: [] });
  assert.equal((await f.run('status', { handle: task.handle })).state, 'pending');
  f.messages.push({ info: { role: 'assistant', parentID, time: { completed: 1 }, error: { message: 'private error' } }, parts: [] });
  const result = await f.run('result', { handle: task.handle });
  assert.equal(result.state, 'failed'); assert.equal(result.text, '');
  assert.ok(!JSON.stringify(result).includes('private error'));
});

test('unsafe state and aborted/denied calls cannot create remote sessions', async t => {
  const f = await fixture(t);
  const controller = new AbortController(); controller.abort();
  assert.equal((await f.run('task', { peer: 'worker', prompt: 'Run' }, { ...f.ctx, abort: controller.signal })).state, 'unavailable');
  assert.equal((await f.run('task', { peer: 'worker', prompt: 'Run' }, { ...f.ctx, ask: async () => { throw Error(); } })).state, 'unavailable');
  await symlink(f.root, f.options.stateDirectory);
  assert.equal((await f.run('task', { peer: 'worker', prompt: 'Run' })).state, 'unavailable');
  assert.equal(f.calls.length, 0);
});

test('plugin system hook and opt-in resources expose only public peer labels', async t => {
  const f = await fixture(t);
  const hooks = await DispatchPlugin({}, f.options);
  const output = { system: [] };
  await hooks['experimental.chat.system.transform']({}, output);
  assert.match(output.system[0], /Reviews code/);
  for (const privateValue of [f.peer.url, f.peer.username, f.peer.passwordFile, 'protected-secret']) assert.ok(!output.system[0].includes(privateValue));
  assert.deepEqual(Object.keys(hooks.tool).sort(), ['dispatch_peers', 'dispatch_reply', 'dispatch_result', 'dispatch_status', 'dispatch_task']);
  const profile = JSON.parse(await readFile(new URL('../examples/hub.config.json', import.meta.url), 'utf8'));
  assert.equal(profile.plugin.length, 1);
  assert.ok(Object.values(profile.permission).every(p => p === 'ask'));
  const command = await readFile(new URL('../commands/dispatch.md', import.meta.url), 'utf8');
  assert.match(command, /\$ARGUMENTS/); assert.match(command, /Never substitute native task/);
});
