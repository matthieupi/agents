import { test } from 'node:test';
import assert from 'node:assert/strict';
import { scenario, compact, answer } from './fixtures.js';

test('unrelated user turn explicitly blocks result correlation', async t => {
  const f = await scenario(t);
  f.messages.push({ info: { id: 'msg_external', role: 'user' }, parts: [{ type: 'text', text: 'Unrelated work' }] });
  f.messages.push({ info: { id: 'msg_external_answer', role: 'assistant', parentID: 'msg_external', time: { completed: 1 }, finish: 'stop' }, parts: [{ type: 'text', text: 'Do not consume' }] });
  const result = await f.result();
  assert.equal(result.state, 'blocked');
  assert.ok(!result.text.includes('Do not consume'));
  assert.equal((await f.reply()).state, 'unavailable'); assert.equal(f.posts(), 1);
});

test('auto compaction continuation correlates across restart and repeated compactions', async t => {
  const f = await scenario(t);
  const first = compact(f);
  const second = compact(f, { overflow: true, continuation: 'replay', suffix: '2' });
  answer(f, second.next.info.id);
  f.restart();
  const result = await f.result();
  assert.equal(result.state, 'completed'); assert.equal(result.text, 'Final after compaction');
  assert.notEqual(first.next.info.id, f.parentID);
  assert.equal((await f.reply()).state, 'accepted');
});

test('overflow replay preserves dispatch metadata and follows its new parent ID', async t => {
  const f = await scenario(t);
  // Native overflow replay needs preceding user history (e.g. an earlier reply).
  f.messages.unshift({ info: { id: 'msg_prior', role: 'user', time: { created: 0 } }, parts: [{ type: 'text', text: 'Earlier turn' }] });
  f.messages[1].info.time.created = 1;
  const { next } = compact(f, { overflow: true, continuation: 'replay' });
  answer(f, next.info.id);
  const result = await f.result();
  assert.equal(result.state, 'completed'); assert.equal(result.text, 'Final after compaction');
});

test('compaction continuation later failure supersedes old stop-with-tools', async t => {
  const f = await scenario(t);
  const old = answer(f, f.parentID);
  old.parts.push({ type: 'tool', state: { status: 'completed' } });
  const { next } = compact(f, { overflow: true });
  answer(f, next.info.id, { error: true, suffix: 'failed' });
  const result = await f.result();
  assert.equal(result.state, 'failed'); assert.equal(result.text, '');
});

test('unmarked legacy overflow replay is blocked, not inferred from identical text', async t => {
  const f = await scenario(t);
  delete f.messages[0].parts[0].metadata;
  const { next } = compact(f, { overflow: true, continuation: 'replay' });
  answer(f, next.info.id);
  assert.equal((await f.result()).state, 'blocked');
});

test('compaction markers cannot bridge an intervening unrelated user', async t => {
  const f = await scenario(t);
  const { next } = compact(f);
  f.messages.splice(3, 0, { info: { id: 'msg_other', role: 'user', time: { created: 2.5 } }, parts: [{ type: 'text', text: 'Other' }] });
  answer(f, next.info.id);
  const result = await f.result();
  assert.equal(result.state, 'blocked'); assert.equal(result.text, '');
});

test('completed compaction without continuation is explicitly blocked; summary error is failed', async t => {
  const f = await scenario(t);
  const { summary } = compact(f, { continuation: 'none' });
  assert.equal((await f.result()).state, 'blocked');
  summary.info.error = { name: 'ContextOverflowError', data: { message: 'Private' } };
  const result = await f.result();
  assert.equal(result.state, 'failed'); assert.equal(result.text, '');
});

test('changed replay content, missing native marker and manual compaction are blocked', async t => {
  for (const mutation of ['text', 'marker', 'manual']) {
    const f = await scenario(t);
    const { user, next } = compact(f, { overflow: true, continuation: mutation === 'marker' ? 'auto' : 'replay' });
    if (mutation === 'text') next.parts[0].text = 'Unrelated work';
    if (mutation === 'marker') delete next.parts[0].metadata;
    if (mutation === 'manual') user.parts[0].auto = false;
    answer(f, next.info.id);
    const result = await f.result();
    assert.equal(result.state, 'blocked'); assert.equal(result.text, '');
  }
});

test('in-progress compaction stays pending and known completion without followup can be polled again', async t => {
  const f = await scenario(t);
  const { summary, next } = compact(f);
  f.messages.pop();
  const completed = summary.info.time.completed;
  delete summary.info.time.completed;
  assert.equal((await f.result()).state, 'pending');
  summary.info.time.completed = completed;
  assert.equal((await f.result()).reason, 'compaction_continuation_missing');
  f.messages.push(next); answer(f, next.info.id);
  assert.equal((await f.result()).state, 'completed');
});
