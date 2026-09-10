import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs/promises';
import { createInbox } from '../inbox.js';
import { storageFixture } from './storage-fixture.js';
import DispatchPlugin from '../index.js';

test('storage exhaustion freezes an empty marker without blocking the user or acquiring later results on retry', async () => {
  let failed = true, writes = 0;
  const box = { sequence: 0, results: {}, turns: {} };
  const inbox = createInbox({ read: async () => structuredClone(box), valid: () => true,
    locked: async (_name, fn) => fn(), write: async () => { writes++; if (failed) throw Object.assign(Error('disk full'), { code: 'ENOSPC' }); } });
  const marker = {};
  await assert.doesNotReject(inbox.freeze({ sessionID: 'ses_hub', directory: '/hub' }, marker, 'approved-v1'));
  failed = false;
  box.results['a'.repeat(64)] = { id: 'a'.repeat(64), owner: 'ses_hub', directory: '/hub', authorization: 'approved-v1', exposed: 1 };
  await inbox.freeze({ sessionID: 'ses_hub', directory: '/hub' }, marker, 'approved-v1');
  assert.equal(writes, 1); assert.deepEqual(marker.ids, []);
  assert.equal(await inbox.context({ sessionID: 'ses_hub', directory: '/hub' }, undefined, 'approved-v1'), '');
});

test('ordinary user turns do not accumulate snapshots in the result inbox', async () => {
  let box = { sequence: 0, results: {}, turns: {} };
  const inbox = createInbox({ read: async () => structuredClone(box), valid: () => true,
    locked: async (_name, fn) => fn(), write: async (_name, value) => { box = structuredClone(value); } });
  for (let i = 0; i < 100; i++) await inbox.freeze({ sessionID: 'ses_hub', directory: '/hub' }, { messageID: 'msg_' + i }, 'approved-v1');
  assert.equal(Object.keys(box.turns ?? {}).length, 0);
});

test('full inbox refuses task and reply before remote mutation', async t => {
  const f = await storageFixture(t), task = await f.task(); f.complete();
  await f.run('result', { handle: task.handle });
  const box = JSON.parse(await fs.readFile(f.boxFile, 'utf8'));
  box.padding = 'x'.repeat(16 * 1024 * 1024 - Buffer.byteLength(JSON.stringify(box)) - 32);
  await fs.writeFile(f.boxFile, JSON.stringify(box));
  const before = f.calls.filter(c => c.body).length;
  assert.equal((await f.task()).state, 'unavailable');
  assert.equal((await f.run('reply', { handle: task.handle, prompt: 'Next' })).state, 'unavailable');
  assert.equal(f.calls.filter(c => c.body).length, before);
});

test('explicit result is returned even if a known storage failure prevents caching', async t => {
  const f = await storageFixture(t), task = await f.task(); f.complete();
  f.runtime.open = async (...args) => {
    const fd = await fs.open(...args);
    return { writeFile: async () => { throw Object.assign(Error('disk full'), { code: 'ENOSPC' }); }, sync: () => fd.sync(), close: () => fd.close() };
  };
  const result = await f.run('result', { handle: task.handle });
  assert.equal(result.state, 'completed'); assert.equal(result.text, 'Private result text');
  assert.ok(result.cacheWarning);
});

test('full inbox cannot block native chat; empty decision survives native persistence, restart and storage recovery', async t => {
  const f = await storageFixture(t), task = await f.task(); f.complete();
  await f.run('result', { handle: task.handle });
  const box = JSON.parse(await fs.readFile(f.boxFile, 'utf8'));
  box.sequence = 9;
  for (const result of Object.values(box.results)) result.exposed = 9;
  box.padding = '';
  box.padding = 'x'.repeat(16 * 1024 * 1024 - Buffer.byteLength(JSON.stringify(box)));
  await fs.writeFile(f.boxFile, JSON.stringify(box));
  const hooks = await DispatchPlugin({ directory: '/hub' }, f.options); t.after(() => hooks.dispose());
  const output = { message: { role: 'user', id: 'msg_full', sessionID: f.ctx.sessionID, time: { created: 1 } }, parts: [{ type: 'text', text: 'Ordinary chat' }] };
  await assert.doesNotReject(hooks['chat.message']({ sessionID: f.ctx.sessionID }, output));
  assert.deepEqual(output.parts[0].metadata.dispatch_snapshot.ids, []);
  const persisted = structuredClone(output);
  await hooks.dispose();
  delete box.padding; await fs.writeFile(f.boxFile, JSON.stringify(box));
  const restarted = await DispatchPlugin({ directory: '/hub' }, f.options); t.after(() => restarted.dispose());
  await restarted['chat.message']({ sessionID: f.ctx.sessionID }, persisted);
  await restarted['experimental.chat.messages.transform']({}, { messages: [{ info: persisted.message, parts: persisted.parts }] });
  assert.equal(persisted.parts.length, 1);
  const fresh = { message: { ...output.message, id: 'msg_fresh' }, parts: [{ type: 'text', text: 'Next chat' }] };
  await restarted['chat.message']({ sessionID: f.ctx.sessionID }, fresh);
  await restarted['experimental.chat.messages.transform']({}, { messages: [{ info: fresh.message, parts: fresh.parts }] });
  assert.equal(fresh.parts.length, 2);
  const files = { message: { ...output.message, id: 'msg_file_only' }, parts: [{ type: 'file', mime: 'image/png', url: 'data:image/png;base64,' }] };
  await restarted['chat.message']({ sessionID: f.ctx.sessionID }, files);
  assert.equal(files.parts.length, 2); assert.equal(files.parts[1].text, ''); assert.equal(files.parts[1].ignored, true);
  assert.ok(files.parts[1].metadata.dispatch_snapshot.ids.length);
});

test('unsafe state and permission errors are not classified as optional capacity failures', async t => {
  for (const error of [Object.assign(Error('permission'), { code: 'EACCES' }), Error('unsafe mode'), SyntaxError('corrupt JSON')]) {
    const inbox = createInbox({ read: async () => { throw error; }, valid: () => true, locked: async (_name, fn) => fn(), write: async () => {} });
    await assert.rejects(inbox.freeze({ sessionID: 'ses_hub', directory: '/hub' }, {}, 'approved-v1'), e => e === error);
  }
  const f = await storageFixture(t), task = await f.task(); f.complete();
  await fs.chmod(f.boxFile, 0o644);
  assert.equal((await f.run('result', { handle: task.handle })).state, 'unavailable');
  const before = f.calls.length;
  const denied = { ...f.ctx, ask: async () => { throw Error('permission denied'); } };
  assert.equal(JSON.parse(await f.dispatch.execute('task', { peer: 'worker', prompt: 'No' }, denied)).state, 'unavailable');
  assert.equal(f.calls.length, before);
});

test('failed cancellation persistence suppresses context without blocking ordinary chat', async t => {
  const f = await storageFixture(t);
  f.runtime.open = async () => { throw Object.assign(Error('disk full'), { code: 'ENOSPC' }); };
  await assert.rejects(f.dispatch.cancel(f.ctx.sessionID));
  const marker = { messageID: 'msg_cancel_storage' };
  await assert.doesNotReject(f.dispatch.snapshot(f.ctx.sessionID, marker.messageID, marker));
  assert.deepEqual(marker.ids, []);
});

test('admission reservations serialize concurrent submissions and protect capacity for admitted results', async () => {
  const limit = 16 * 1024 * 1024;
  let box = { sequence: 0, results: {}, reservations: {}, padding: '' };
  // Room for one worst-case result, not two.
  box.padding = 'x'.repeat(limit - 200000);
  let queue = Promise.resolve();
  const inbox = createInbox({ read: async () => structuredClone(box), valid: () => true,
    locked: (_name, fn) => { const current = queue.then(fn); queue = current.catch(() => {}); return current; },
    write: async (_name, value) => { box = structuredClone(value); } });
  const first = { handle: 'first', message: 'msg_first', owner: 'ses_hub', directory: '/hub', peer: 'worker', binding: 'binding', authorization: 'approved-v1' };
  const second = { ...first, handle: 'second', message: 'msg_second' };
  const admissions = await Promise.allSettled([inbox.reserve(first), inbox.reserve(second)]);
  assert.equal(admissions[0].status, 'fulfilled'); assert.equal(admissions[1].status, 'rejected');
  await inbox.put(first, { state: 'completed', text: '\u0000'.repeat(16000) });
  assert.equal((await inbox.get(first)).text.length, 16000);
  assert.equal(Object.keys(box.reservations).length, 0);
});
