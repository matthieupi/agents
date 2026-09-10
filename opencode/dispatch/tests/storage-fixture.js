import * as fs from 'node:fs/promises';
import { createHash } from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import { createDispatch } from '../core.js';

export async function storageFixture(t) {
  const stateDirectory = await fs.mkdtemp(path.join(os.tmpdir(), 'dispatch-storage-'));
  const options = { enabled: true, stateDirectory, peers: [{ alias: 'worker', description: 'Worker',
    url: 'https://worker.invalid', username: 'opencode', passwordFile: '/private/password' }] };
  const ctx = { sessionID: 'ses_hub', directory: '/hub', ask: async () => {}, abort: new AbortController().signal };
  let now = 0;
  const calls = [], history = [];
  const runtime = { now: () => now, setTimeout: () => 1, clearTimeout: () => {} };
  const transport = async (_peer, route, body) => {
    calls.push({ route, body });
    if (route === '/session') return { id: 'ses_remote' };
    if (body) { history.push({ info: { role: 'user', id: body.messageID, sessionID: 'ses_remote', time: { created: history.length } }, parts: body.parts }); return; }
    return structuredClone(history);
  };
  const dispatch = createDispatch(options, transport, runtime); dispatch.start('/hub');
  t.after(async () => { await dispatch.dispose(); await fs.rm(stateDirectory, { recursive: true, force: true }); });
  const run = async (op, args) => JSON.parse(await dispatch.execute(op, args, ctx));
  const task = () => run('task', { peer: 'worker', prompt: 'Work' });
  const record = async handle => JSON.parse(await fs.readFile(path.join(stateDirectory, handle + '.json'), 'utf8'));
  const boxFile = path.join(stateDirectory, 'inbox-' + createHash('sha256').update(JSON.stringify([ctx.sessionID, ctx.directory])).digest('hex') + '.json');
  function complete(text = 'Private result text') {
    history.push({ info: { role: 'assistant', id: 'msg_answer_' + history.length, parentID: history.at(-1).info.id,
      sessionID: 'ses_remote', time: { created: history.length, completed: history.length + 1 }, finish: 'stop' }, parts: [{ type: 'text', text }] });
  }
  return { options, ctx, runtime, dispatch, calls, run, task, record, boxFile, complete, advance: ms => { now += ms; } };
}
