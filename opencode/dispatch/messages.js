import { isDeepStrictEqual } from 'node:util';

// v1.18.29 SessionPrompt.run + isOrphanedInterruptedTool. Completed native tools
// STILL require another model turn, unlike provider-executed/interrupted tools.
function terminal(message) {
  if (!message?.info.time?.completed) return 'pending';
  if (message.info.error) return 'failed';
  const hasToolCalls = message.parts.some(p => p.type === 'tool' && !p.metadata?.providerExecuted &&
    !(p.state?.status === 'error' && p.state.metadata?.interrupted === true));
  return message.info.finish && !['tool-calls', 'unknown'].includes(message.info.finish) && !hasToolCalls
    ? 'completed' : 'pending';
}

function autoContinue(message) {
  return message.parts.length === 1 && message.parts[0].type === 'text' &&
    message.parts[0].synthetic === true && message.parts[0].metadata?.compaction_continue === true;
}

function replayOf(source, message, rootID) {
  // Native overflow replay does not have a source message ID. Never infer it from
  // prompt text alone: require our copied metadata (or a previously verified native
  // continuation) AND identical text parts/context, apart from reassigned part IDs.
  const marked = source.parts.some(p => p.metadata?.dispatch_turn === rootID) || autoContinue(source);
  const parts = m => m.parts.map(({ id, messageID, sessionID, ...part }) => part);
  return marked && source.parts.length > 0 && source.parts.every(p => p.type === 'text') &&
    isDeepStrictEqual(parts(source), parts(message)) &&
    ['agent', 'model', 'format', 'tools', 'system'].every(k => isDeepStrictEqual(source.info[k], message.info[k]));
}

export function inspectMessages(messages, record) {
  const waiting = { state: record.phase === 'accepted' ? 'pending' : 'uncertain', text: '' };
  const blocked = reason => ({ state: 'blocked', reason, text: '' });
  if (!Array.isArray(messages)) return blocked('invalid_history');
  const ids = new Set();
  for (const m of messages) {
    if (!m?.info || typeof m.info.id !== 'string' || ids.has(m.info.id) ||
        !['user', 'assistant'].includes(m.info.role) || !Number.isFinite(m.info.time?.created) ||
        !Array.isArray(m.parts) || m.parts.some(p => !p || typeof p.type !== 'string') ||
        m.info.sessionID !== record.remote) return blocked('invalid_history');
    ids.add(m.info.id);
  }
  // Native MessageV2.latest: creation time, then lexicographic ID (not array order,
  // completed time or locale collation). The REST list is unfiltered full history.
  const ordered = [...messages].sort((a, b) => a.info.time.created - b.info.time.created ||
    (a.info.id < b.info.id ? -1 : a.info.id > b.info.id ? 1 : 0));
  const start = ordered.findIndex(m => m.info.id === record.message && m.info.role === 'user');
  if (start < 0) return messages.length ? blocked('submission_not_visible') : waiting;
  let user = ordered[start], latest, compaction;
  for (const m of ordered.slice(start + 1)) {
    if (m.info.role === 'user') {
      if (m.parts.length === 1 && m.parts[0].type === 'compaction' && m.parts[0].auto === true && !compaction) {
        compaction = { user: m, source: user, summary: undefined };
        latest = undefined;
        continue;
      }
      if (!compaction || terminal(compaction.summary) !== 'completed') return blocked('unrelated_or_unsupported_user');
      const continued = autoContinue(m) && ['agent', 'model'].every(k => isDeepStrictEqual(m.info[k], compaction.user.info[k]));
      const replayed = compaction.user.parts[0].overflow === true && replayOf(compaction.source, m, record.message);
      if (!continued && !replayed) return blocked('unrelated_or_unsupported_user');
      user = m; latest = undefined; compaction = undefined;
    } else if (compaction) {
      if (m.info.summary === true && m.info.parentID === compaction.user.info.id) compaction.summary = m;
      else return blocked('unexpected_compaction_assistant');
    } else if (!m.info.summary) {
      if (m.info.parentID !== user.info.id) return blocked('unrelated_assistant');
      latest = m;
    }
  }
  if (compaction) {
    const state = terminal(compaction.summary);
    if (state === 'failed') return { state, reason: 'compaction_failed', text: '' };
    if (state === 'completed') return blocked('compaction_continuation_missing');
    return waiting;
  }
  const state = terminal(latest);
  return { state: state === 'pending' ? waiting.state : state,
    text: (latest?.parts ?? []).filter(p => p.type === 'text' && typeof p.text === 'string').map(p => p.text).join('\n').slice(0, 16000) };
}
