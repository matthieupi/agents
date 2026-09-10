import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, readFile, writeFile, readdir, stat } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createDispatch } from '../core.js';
import DispatchPlugin from '../index.js';

async function background(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'dispatch-background-'));
  const instances = [], timers = new Map(), histories = new Map(), calls = [], asks = [];
  const snapshots = new Map(); // Simulated native user-part metadata, retained across plugin restarts.
  let now = 0, serial = 0, offline = false, intercept;
  const options = { enabled: true, stateDirectory: path.join(root, 'state'), peers: [{ alias: 'worker',
    description: 'Worker', url: 'https://worker.invalid/', username: 'opencode', passwordFile: '/private/password' }] };
  const ctx = { sessionID: 'ses_hub', directory: '/hub', ask: async p => asks.push(p), abort: new AbortController().signal };
  const runtime = { now: () => now,
    setTimeout: (fn, delay) => { const id = ++serial; timers.set(id, { fn, delay }); return id; },
    clearTimeout: id => timers.delete(id) };
  const transport = async (peer, route, body, signal) => {
    calls.push({ route, body, signal });
    if (intercept) await intercept(route, body, signal);
    if (offline) throw Error('offline');
    if (route === '/session') { const id = `ses_remote_${++serial}`; histories.set(id, []); return { id }; }
    const remote = route.split('/')[2], messages = histories.get(remote);
    if (body) {
      messages.push({ info: { role: 'user', id: body.messageID, sessionID: remote, time: { created: messages.length } }, parts: body.parts });
      return null;
    }
    return structuredClone(messages);
  };
  function create(config = options, directory = '/hub') {
    const d = createDispatch(config, transport, runtime); d.start(directory); instances.push(d);
    const snapshot = d.snapshot;
    d.snapshot = async (sessionID, messageID) => {
      const key = JSON.stringify([sessionID, directory, messageID]);
      if (!snapshots.has(key)) snapshots.set(key, { messageID });
      await snapshot(sessionID, messageID, snapshots.get(key));
    };
    return d;
  }
  const dispatch = create();
  t.after(async () => { await Promise.all(instances.map(d => d.dispose())); await rm(root, { recursive: true, force: true }); });
  const execute = async (d, op, args, context = ctx) => JSON.parse(await d.execute(op, args, context));
  const task = async (context = ctx) => execute(dispatch, 'task', { peer: 'worker', prompt: 'Work' }, context);
  const record = async handle => JSON.parse(await readFile(path.join(options.stateDirectory, handle + '.json'), 'utf8'));
  async function complete(handle, text = 'Done', failed = false) {
    const r = await record(handle), messages = histories.get(r.remote);
    messages.push({ info: { role: 'assistant', id: `msg_answer_${++serial}`, parentID: r.message, sessionID: r.remote,
      time: { created: messages.length, completed: messages.length + 1 },
      ...(failed ? { error: { name: 'UnknownError', data: { message: 'private error' } } } : { finish: 'stop' }) },
    parts: [{ type: 'text', text }] });
  }
  const messages = (id, sessionID = ctx.sessionID) => [{ info: { role: 'user', id, sessionID, time: { created: 1 } },
    parts: [{ type: 'text', text: 'User request', metadata: {
      dispatch_snapshot: structuredClone(snapshots.get(JSON.stringify([sessionID, ctx.directory, id]))),
    } }] }];
  const context = async (d, id, sessionID = ctx.sessionID) => {
    const output = messages(id, sessionID); await d.transform(output); return output[0].parts.at(1)?.text ?? '';
  };
  return { options, ctx, runtime, timers, calls, asks, dispatch, create, execute, task, record, complete, context, messages,
    advance: amount => { now += amount; }, offline: value => { offline = value; },
    intercept: fn => { intercept = fn; } };
}

test('loop uses deterministic durable backoff, GET-only recovery and no background prompts', async t => {
  const f = await background(t), task = await f.task();
  assert.match(f.asks[0].metadata.authorization, /background read-only polling/);
  assert.equal((await f.record(task.handle)).authorization, 'approved-v1');
  await f.dispatch.poll(); assert.equal(f.calls.length, 2);
  for (const delay of [5000, 5000, 10000, 20000, 40000, 80000, 160000, 300000]) {
    f.advance(delay); await f.dispatch.poll();
    const r = await f.record(task.handle);
    assert.ok(r.nextPoll > 0); assert.ok(r.attempts <= 7);
  }
  assert.equal(f.calls.filter(c => !c.body).length, 8);
  const count = f.calls.length;
  await f.dispatch.poll(); assert.equal(f.calls.length, count);
  await f.dispatch.dispose();
  const restarted = f.create(); await restarted.poll(); assert.equal(f.calls.length, count);
  f.advance(300000); f.offline(true); await restarted.poll();
  assert.equal(f.calls.length, count + 1);
  assert.equal(f.calls.filter(c => c.body).length, 2);
  assert.equal(f.asks.length, 1);
});

test('terminal persistence stops fetching, recovers offline and keeps private per-turn results across replies', async t => {
  const f = await background(t), task = await f.task();
  await f.complete(task.handle); f.advance(5000); await f.dispatch.poll();
  const first = await f.record(task.handle); assert.ok(first.resultID);
  const before = f.calls.length;
  f.advance(1000000); await f.dispatch.poll(); assert.equal(f.calls.length, before);
  await f.dispatch.dispose(); const restarted = f.create(); f.offline(true);
  await restarted.poll();
  const cached = await f.execute(restarted, 'result', { handle: task.handle });
  assert.equal(cached.text, 'Done'); assert.equal(cached.cached, true); assert.equal(f.calls.length, before);
  f.offline(false);
  assert.equal((await f.execute(restarted, 'reply', { handle: task.handle, prompt: 'Next' })).state, 'accepted');
  await f.complete(task.handle, 'Second'); f.advance(5000); await restarted.poll();
  const second = await f.record(task.handle); assert.notEqual(second.resultID, first.resultID);
  await restarted.snapshot(f.ctx.sessionID, 'msg_next');
  const text = await f.context(restarted, 'msg_next');
  assert.ok(text.includes(first.resultID)); assert.ok(text.includes(second.resultID));
  for (const file of await readdir(f.options.stateDirectory)) {
    assert.equal((await stat(path.join(f.options.stateDirectory, file))).mode & 0o077, 0);
    const content = await readFile(path.join(f.options.stateDirectory, file), 'utf8');
    assert.ok(!content.includes('/private/password')); assert.ok(!content.includes('https://'));
  }
});

test('snapshot includes only results ready before user boundary; retries and restart preserve even empty selection', async t => {
  const f = await background(t), task = await f.task();
  await f.dispatch.snapshot(f.ctx.sessionID, 'msg_turn1');
  await f.complete(task.handle); f.advance(5000); await f.dispatch.poll();
  assert.equal(await f.context(f.dispatch, 'msg_turn1'), '');
  await f.dispatch.snapshot(f.ctx.sessionID, 'msg_turn1');
  assert.equal(await f.context(f.dispatch, 'msg_turn1'), '');
  await f.dispatch.snapshot(f.ctx.sessionID, 'msg_turn2');
  const first = await f.context(f.dispatch, 'msg_turn2'); assert.match(first, /UNTRUSTED PEER DATA/);
  const later = await f.task(); await f.complete(later.handle, 'Arrived between tool calls');
  f.advance(5000); await f.dispatch.poll();
  assert.equal(await f.context(f.dispatch, 'msg_turn2'), first);
  const output = f.messages('msg_turn2'); await f.dispatch.transform(output); await f.dispatch.transform(output);
  assert.equal(output[0].parts.length, 2);
  await f.dispatch.dispose(); const restarted = f.create();
  assert.equal(await f.context(restarted, 'msg_turn1'), '');
  assert.equal(await f.context(restarted, 'msg_turn2'), first);
  // Nothing is acknowledged merely because transform ran, including failed-provider attempts.
  await restarted.snapshot(f.ctx.sessionID, 'msg_turn3');
  const next = await f.context(restarted, 'msg_turn3');
  assert.match(next, /Arrived between tool calls/); assert.match(next, /Done/);
});

test('session, directory, peer removal/change, legacy and denied approval cannot authorize background fetch or context', async t => {
  const f = await background(t);
  const denied = { ...f.ctx, ask: async () => { throw Error('denied'); } };
  assert.equal((await f.task(denied)).state, 'unavailable');
  f.advance(10000); await f.dispatch.poll(); assert.equal(f.calls.length, 0);
  const task = await f.task(); await f.complete(task.handle); f.advance(5000); await f.dispatch.poll();
  await f.dispatch.snapshot(f.ctx.sessionID, 'msg_one');
  assert.equal(await f.context(f.dispatch, 'msg_one', 'ses_other'), '');
  for (const d of [f.create(f.options, '/other'), f.create({ ...f.options, peers: [] }),
    f.create({ ...f.options, peers: [{ ...f.options.peers[0], url: 'https://changed.invalid/' }] })]) {
    const count = f.calls.length; await d.poll(); await d.snapshot(f.ctx.sessionID, 'msg_other');
    assert.equal(await f.context(d, 'msg_one'), ''); assert.equal(await f.context(d, 'msg_other'), '');
    assert.equal(f.calls.length, count);
  }
  const legacy = await f.task(), r = await f.record(legacy.handle); delete r.authorization;
  await writeFile(path.join(f.options.stateDirectory, r.handle + '.json'), JSON.stringify(r));
  const count = f.calls.length; f.advance(10000); await f.dispatch.poll(); assert.equal(f.calls.length, count);
  assert.deepEqual(await DispatchPlugin({}, { ...f.options, enabled: false }), {});
});

test('bounded poll batch and rotating bounded context do not starve queued results', async t => {
  const f = await background(t), handles = [];
  for (let i = 0; i < 7; i++) { const task = await f.task(); handles.push(task.handle); await f.complete(task.handle, '\u0000'.repeat(16000)); }
  f.advance(5000); const before = f.calls.length;
  await f.dispatch.poll(); assert.equal(f.calls.length - before, 4);
  await f.dispatch.poll(); assert.equal(f.calls.length - before, 7);
  const seen = new Set();
  for (let i = 0; i < 2; i++) {
    const id = `msg_turn_${i}`; await f.dispatch.snapshot(f.ctx.sessionID, id);
    const text = await f.context(f.dispatch, id); assert.ok(text.length < 20000);
    for (const handle of handles) if (text.includes(handle)) seen.add(handle);
    // Continuous arrivals must join behind older entries, not monopolize the next batch.
    for (let j = 0; j < 4; j++) { const task = await f.task(); await f.complete(task.handle, 'New'); }
    f.advance(5000); await f.dispatch.poll();
  }
  assert.equal(seen.size, 7);
});

test('restart repairs a missing terminal pointer from the inbox without refetch; failures persist without raw errors', async t => {
  const f = await background(t), task = await f.task();
  await f.complete(task.handle, 'Partial assistant output', true); f.advance(5000); await f.dispatch.poll();
  const r = await f.record(task.handle); assert.ok(r.resultID); delete r.resultID;
  await writeFile(path.join(f.options.stateDirectory, r.handle + '.json'), JSON.stringify(r));
  await f.dispatch.dispose(); const restarted = f.create(); f.advance(10000); f.offline(true);
  const before = f.calls.length; await restarted.poll(); assert.equal(f.calls.length, before);
  assert.ok((await f.record(task.handle)).resultID);
  const result = await f.execute(restarted, 'result', { handle: task.handle });
  assert.equal(result.state, 'failed'); assert.equal(result.text, 'Partial assistant output');
  await restarted.snapshot(f.ctx.sessionID, 'msg_failed');
  const text = await f.context(restarted, 'msg_failed');
  assert.match(text, /failed/); assert.ok(!text.includes('private error'));
});

test('stale locks do not starve other due handles and permission denial does not alter prior authorization', async t => {
  const f = await background(t), tasks = [];
  for (let i = 0; i < 5; i++) tasks.push(await f.task());
  tasks.sort((a, b) => a.handle.localeCompare(b.handle));
  const locked = tasks[0];
  await writeFile(path.join(f.options.stateDirectory, locked.handle + '.lock'), '', { mode: 0o600 });
  const before = f.calls.length; f.advance(5000); await f.dispatch.poll();
  assert.equal(f.calls.length - before, 4);
  const r = await f.record(tasks[1].handle);
  assert.equal((await f.execute(f.dispatch, 'reply', { handle: r.handle, prompt: 'Denied' },
    { ...f.ctx, ask: async () => { throw Error('denied'); } })).state, 'unavailable');
  assert.deepEqual(await f.record(r.handle), r);
});

test('authorization is not persisted while approval waits; concurrent cancellation cannot be resurrected by it', async t => {
  const f = await background(t);
  let entered, release; const ready = new Promise(resolve => { entered = resolve; });
  const gate = new Promise(resolve => { release = resolve; });
  const task = f.task({ ...f.ctx, ask: async () => { entered(); await gate; } });
  await ready; await f.dispatch.poll(); assert.equal(f.calls.length, 0);
  assert.equal((await readdir(f.options.stateDirectory)).filter(n => /^[a-f0-9-]{36}\.json$/.test(n)).length, 0);
  await f.dispatch.cancel(f.ctx.sessionID); release(); const result = await task; assert.equal(result.state, 'accepted');
  f.advance(10000); const before = f.calls.length; await f.dispatch.poll(); assert.equal(f.calls.length, before);
  // Only a fresh later approval participates in the new epoch.
  const fresh = await f.task(); await f.complete(fresh.handle, 'New approval'); f.advance(5000); await f.dispatch.poll();
  await f.dispatch.snapshot(f.ctx.sessionID, 'msg_fresh'); assert.match(await f.context(f.dispatch, 'msg_fresh'), /New approval/);
  const epochFile = (await readdir(f.options.stateDirectory)).find(n => n.startsWith('cancel-'));
  await writeFile(path.join(f.options.stateDirectory, epochFile), '{}');
  await assert.rejects(f.dispatch.snapshot(f.ctx.sessionID, 'msg_corrupt_epoch'));
  assert.equal((await f.task()).state, 'unavailable');
});

test('disposal aborts in-flight GET and clears timer without rescheduling; cancellation survives restart', async t => {
  const f = await background(t), task = await f.task();
  let entered; const ready = new Promise(resolve => { entered = resolve; });
  f.intercept(async (route, body, signal) => {
    if (!body) { entered(); await new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(Error('aborted')), { once: true })); }
  });
  f.advance(5000);
  const [{ fn, delay }] = f.timers.values(); assert.equal(delay, 1000); f.timers.clear();
  const tick = fn(); await ready; await f.dispatch.dispose(); await tick;
  assert.equal(f.timers.size, 0); assert.equal(f.calls.at(-1).signal.aborted, true);
  const before = f.calls.length; f.advance(1000000); await f.dispatch.poll(); assert.equal(f.calls.length, before);
  f.intercept(undefined); const restarted = f.create(); await restarted.cancel(f.ctx.sessionID);
  await restarted.dispose(); const again = f.create(); await again.poll(); assert.equal(f.calls.length, before);
  await f.complete(task.handle);
  // Explicit inspection remains authorized separately, but does not resurrect cancelled background delivery.
  assert.equal((await f.execute(again, 'result', { handle: task.handle })).state, 'completed');
  await again.snapshot(f.ctx.sessionID, 'msg_after_cancel'); assert.equal(await f.context(again, 'msg_after_cancel'), '');
});

test('poll and reply serialize; old poll cannot overwrite new submission or lose old completed result', async t => {
  const f = await background(t), task = await f.task(); await f.complete(task.handle, 'First');
  let entered, release; const ready = new Promise(resolve => { entered = resolve; });
  const gate = new Promise(resolve => { release = resolve; });
  let once = true;
  f.intercept(async (_route, body) => { if (!body && once) { once = false; entered(); await gate; } });
  f.advance(5000); const polling = f.dispatch.poll(); await ready;
  const replying = f.execute(f.dispatch, 'reply', { handle: task.handle, prompt: 'Next' });
  release(); await polling; assert.equal((await replying).state, 'accepted');
  const r = await f.record(task.handle); assert.equal(r.resultID, undefined); assert.equal(r.attempts, 0);
  await f.dispatch.snapshot(f.ctx.sessionID, 'msg_after_reply'); assert.match(await f.context(f.dispatch, 'msg_after_reply'), /First/);
});

test('aborted submission revokes polling authorization; ambiguous non-aborted submit is inspected, never replayed', async t => {
  for (const abort of [true, false]) {
    const f = await background(t), controller = new AbortController();
    f.intercept(async route => { if (route.endsWith('/prompt_async')) { if (abort) controller.abort(); throw Error('ambiguous'); } });
    const task = await f.task({ ...f.ctx, abort: controller.signal }); assert.equal(task.state, 'unavailable');
    f.intercept(undefined); f.advance(10000); await f.dispatch.poll();
    assert.equal(f.calls.filter(c => !c.body).length, abort ? 0 : 1);
    assert.equal(f.calls.filter(c => c.route.endsWith('/prompt_async')).length, 1);
  }
});

test('native hooks freeze before save, accept empty transform input, skip synthetic boundaries and dispose', async t => {
  const f = await background(t), task = await f.task(); await f.complete(task.handle); f.advance(5000); await f.dispatch.poll();
  const hooks = await DispatchPlugin({ directory: '/hub' }, f.options); t.after(() => hooks.dispose());
  const output = f.messages('msg_native')[0];
  await hooks['chat.message']({ sessionID: f.ctx.sessionID }, { message: output.info, parts: output.parts });
  assert.equal(output.parts.length, 1); // Not persisted into chat.message output / transcript.
  await hooks['experimental.chat.messages.transform']({}, { messages: [output] }); assert.equal(output.parts.length, 2);
  await hooks['experimental.chat.messages.transform']({}, { messages: [] });
  const synthetic = f.messages('msg_synthetic')[0]; synthetic.parts[0].synthetic = true;
  await hooks['chat.message']({ sessionID: f.ctx.sessionID }, { message: synthetic.info, parts: synthetic.parts });
  await hooks['experimental.chat.messages.transform']({}, { messages: [synthetic] }); assert.equal(synthetic.parts.length, 1);
  const mixed = f.messages('msg_native'); mixed.push(...f.messages('msg_foreign', 'ses_foreign'));
  await hooks['experimental.chat.messages.transform']({}, { messages: mixed }); assert.equal(mixed[0].parts.length, 1);
  await hooks['experimental.chat.messages.transform']({}, { messages: [{ info: { role: 'user' }, parts: [] }] });
  // Native ordering is raw lexicographic ID, not localeCompare (Z < a), nor array order.
  const older = f.messages('msg_Z')[0], newer = f.messages('msg_a')[0];
  await hooks['chat.message']({ sessionID: f.ctx.sessionID }, { message: newer.info, parts: newer.parts });
  await hooks['experimental.chat.messages.transform']({}, { messages: [newer, older] });
  assert.equal(newer.parts.length, 2); assert.equal(older.parts.length, 1);
  const inboxFile = (await readdir(f.options.stateDirectory)).find(n => n.startsWith('inbox-') && n.endsWith('.json'));
  const lock = path.join(f.options.stateDirectory, inboxFile.replace('.json', '.lock'));
  await writeFile(lock, '', { mode: 0o600 });
  const retry = f.messages('msg_snapshot_retry')[0];
  await assert.doesNotReject(hooks['chat.message']({ sessionID: f.ctx.sessionID }, { message: retry.info, parts: retry.parts }));
  assert.equal(retry.parts.length, 1); await rm(lock);
  await hooks['chat.message']({ sessionID: f.ctx.sessionID }, { message: retry.info, parts: retry.parts });
  // The failed decision remains empty on retry; do not acquire arrivals after its boundary.
  await hooks['experimental.chat.messages.transform']({}, { messages: [retry] }); assert.equal(retry.parts.length, 1);
  await hooks.event({ event: { type: 'message.updated', properties: { info: { sessionID: f.ctx.sessionID,
    error: { name: 'MessageAbortedError' } } } } });
  const cancelled = f.messages('msg_cancelled')[0];
  await hooks['chat.message']({ sessionID: f.ctx.sessionID }, { message: cancelled.info, parts: cancelled.parts });
  await hooks['experimental.chat.messages.transform']({}, { messages: [cancelled] }); assert.equal(cancelled.parts.length, 1);
  await hooks.dispose();
});
