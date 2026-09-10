import { test } from 'node:test';
import assert from 'node:assert/strict';
import { scenario } from './fixtures.js';

test('stop with a native tool is not terminal and later failure supersedes it', async t => {
  const f = await scenario(t);
  f.messages.push({ info: { id: 'msg_a', role: 'assistant', parentID: f.parentID, time: { completed: 1 }, finish: 'stop' },
    parts: [{ type: 'tool', state: { status: 'completed' } }, { type: 'text', text: 'Not done' }] });
  assert.equal((await f.result()).state, 'pending');
  f.messages.push({ info: { id: 'msg_b', role: 'assistant', parentID: f.parentID, time: { completed: 2 }, error: { name: 'UnknownError' } }, parts: [] });
  assert.equal((await f.result()).state, 'failed');
});

test('latest assistant overrides older completion even when history is out of order', async t => {
  const f = await scenario(t);
  f.messages.push({ info: { id: 'msg_early', role: 'assistant', parentID: f.parentID, time: { created: 1, completed: 2 }, finish: 'stop' }, parts: [{ type: 'text', text: 'Old' }] });
  f.messages.push({ info: { id: 'msg_later', role: 'assistant', parentID: f.parentID, time: { created: 3 } }, parts: [{ type: 'text', text: 'Working' }] });
  assert.equal((await f.result()).state, 'pending');
  const latest = f.messages.at(-1);
  latest.info.time.completed = 4; latest.info.finish = 'stop'; latest.parts[0].text = 'Final';
  f.messages.reverse();
  const result = await f.result();
  assert.equal(result.state, 'completed'); assert.equal(result.text, 'Final');
});

test('native terminal exceptions and finish reasons', async t => {
  // Each case is a distinct turn: verified terminal results are now immutable cache entries.
  for (const [parts, finish, expected] of [
    [[{ type: 'tool', metadata: { providerExecuted: true }, state: { status: 'completed' } }], 'stop', 'completed'],
    [[{ type: 'tool', state: { status: 'error', metadata: { interrupted: true } } }], 'stop', 'completed'],
    [[{ type: 'tool', state: { status: 'completed', metadata: { interrupted: true } } }], 'stop', 'pending'],
    ...['length', 'content-filter', 'error'].map(finish => [[], finish, 'completed']),
    ...['unknown', 'tool-calls', ''].map(finish => [[], finish, 'pending']),
  ]) {
    const f = await scenario(t);
    f.messages.push({ info: { id: 'msg_answer', role: 'assistant', parentID: f.parentID,
      time: { created: 1, completed: 2 }, finish }, parts });
    assert.equal((await f.result()).state, expected);
  }
});

test('stop with tools waits for later completion; native ID breaks creation-time ties', async t => {
  const f = await scenario(t);
  f.messages.push({ info: { id: 'msg_a', role: 'assistant', parentID: f.parentID, time: { created: 1, completed: 4 }, finish: 'stop' },
    parts: [{ type: 'tool', state: { status: 'completed' } }, { type: 'text', text: 'Before tool result' }] });
  assert.equal((await f.result()).state, 'pending');
  f.messages.push({ info: { id: 'msg_b', role: 'assistant', parentID: f.parentID, time: { created: 1, completed: 3 }, finish: 'stop' }, parts: [{ type: 'text', text: 'After tool result' }] });
  f.messages.reverse();
  const result = await f.result();
  assert.equal(result.state, 'completed'); assert.equal(result.text, 'After tool result');
});
