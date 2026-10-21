import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createDispatch } from '../core.js';

// Reduced native v1.18.29 DTO fixtures. Relevant fields are from prompt.run,
// MessageV2.latest and compaction.process (see README source links).
export async function scenario(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'dispatch-lineage-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const messages = [];
  const options = { enabled: true, stateDirectory: path.join(root, 'state'), peers: [{ alias: 'worker', description: 'Worker', url: 'https://worker.invalid', username: 'opencode', passwordFile: '/private/password' }] };
  const ctx = { sessionID: 'ses_hub', directory: '/hub', ask: async () => {}, abort: new AbortController().signal };
  let posts = 0;
  const transport = async (_peer, route, body) => {
    if (route === '/session') return { id: 'ses_worker' };
    if (body) {
      posts++;
      messages.push({ info: { id: body.messageID, role: 'user', time: { created: messages.length }, agent: 'build', model: { providerID: 'mock', modelID: 'mock' } }, parts: body.parts });
      return null;
    }
    return messages.map((m, i) => ({ ...m, info: { ...m.info, sessionID: 'ses_worker', time: { created: i, ...m.info.time } } }));
  };
  let dispatch = createDispatch(options, transport);
  const task = JSON.parse(await dispatch.execute('task', { peer: 'worker', prompt: 'Work' }, ctx));
  return { messages, options, parentID: messages[0].info.id, posts: () => posts,
    restart: () => { dispatch = createDispatch(options, transport); },
    reply: async () => JSON.parse(await dispatch.execute('reply', { handle: task.handle, prompt: 'Next' }, ctx)),
    result: async () => JSON.parse(await dispatch.execute('result', { handle: task.handle }, ctx)) };
}

export function compact(f, { overflow = false, continuation = 'auto', suffix = '1' } = {}) {
  const original = f.messages.findLast(m => m.info.role === 'user');
  const user = { info: { ...original.info, id: `msg_compact_${suffix}`, time: { created: f.messages.length } }, parts: [{ type: 'compaction', auto: true, overflow }] };
  const summary = { info: { id: `msg_summary_${suffix}`, role: 'assistant', parentID: user.info.id, summary: true,
    time: { created: f.messages.length + 1, completed: f.messages.length + 2 }, finish: 'stop' }, parts: [{ type: 'text', text: 'Not a task result' }] };
  f.messages.push(user, summary);
  if (continuation === 'none') return { user, summary };
  const next = { info: { ...original.info, id: `msg_continue_${suffix}`, time: { created: f.messages.length } }, parts: continuation === 'replay'
    ? structuredClone(original.parts).map((p, i) => ({ ...p, id: `prt_replay_${suffix}_${i}`, messageID: `msg_continue_${suffix}`, sessionID: 'ses_worker' }))
    : [{ type: 'text', synthetic: true, metadata: { compaction_continue: true }, text: 'Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed.' }] };
  f.messages.push(next);
  return { user, summary, next };
}

export function answer(f, parentID, { error, suffix = '1' } = {}) {
  const message = { info: { id: `msg_answer_${suffix}`, role: 'assistant', parentID, time: { created: f.messages.length, completed: f.messages.length + 1 },
    ...(error ? { error: { name: 'UnknownError', data: { message: 'Private error' } } } : { finish: 'stop' }) }, parts: error ? [] : [{ type: 'text', text: 'Final after compaction' }] };
  f.messages.push(message);
  return message;
}
