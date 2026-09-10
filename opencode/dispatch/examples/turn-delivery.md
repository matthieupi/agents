# Next-user-turn delivery example

All IDs and results below are illustrative. No peer calls are needed for setup.

```text
User turn A: "Ask worker to review this change."
  dispatch_task approval:
    submit + background GET polling + future user-turn context (durable)
  Tool returns handle H; acceptance is not completion.
  The hub may finish answering. It does not wait in a model polling loop.

Background: worker completes turn M1.
  Store result R1 = hash(H, M1) in the private origin-bound inbox.
  Stop fetching this completed turn. No model call or transcript message.

User turn B: "What should we do next?"
  chat.message freezes R1's ID in native user-part metadata (no result text there).
  Each model step can see the same labeled untrusted R1 excerpt.
  A provider failure/retry does not consume R1.

  dispatch_reply(H, "Address the finding") gets a NEW approval.
  Live verification precedes the follow-up POST; its submitted turn is M2.
  Background finishes R2 while this user turn is still running.
  R2 is NOT inserted between tools/model calls in turn B.

User turn C:
  A new snapshot may include R2, plus retained R1 according to rotation.
  R1's repeated ID means repeated context, not another completion.
```

✅ `dispatch_result(H)` explicitly retrieves the **latest submitted turn's** result,
up to 16000 characters, from private storage when terminal—even if the peer is now
offline. A reply still requires live peer history; the cache cannot authorize a POST.

⚠️ Inbox context is not a chat/transcript notification and not proof of successful
model consumption. Four bounded excerpts rotate without deletion. If more are queued,
later user turns expose the rest. Native synthetic continuations do not open fresh
snapshots. No further user turn means no automatic model response.

If dispatch storage is full, the user message keeps an **empty** snapshot and chat
continues without queued results. A retry of that persisted message stays empty,
even after storage recovery; only a fresh user turn tries a new selection. New remote
task/reply mutations require a durable result-capacity reservation first. Explicit
inspection can still return a completed result with a cache warning if caching fails;
do not promise offline retrieval for that uncached output.

Quit/restart OpenCode after plugin/config changes. Disabling the plugin stops its
runtime; re-enabling the same binding can resume prior approvals. Consult the README
for local abort revocation, private storage limits and recovery rules.
