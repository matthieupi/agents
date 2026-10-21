# Optional hub-only OpenCode dispatch

✅ Default off; standalone plugin targeting **OpenCode v1.18.29**, Node 22+.
No gateway, pairing, public-key enrollment, incoming callbacks, peer installation,
deployment or changes to KDCO enablement. The hub sends native Basic
authentication over verified HTTPS to existing OpenCode servers.

## Explicit opt-in

1. Keep this complete package outside `.opencode/plugin(s)` and `tool(s)` directories.
   In this directory run `npm ci --ignore-scripts --no-audit --no-fund`.
2. Adapt [examples/hub.config.json](examples/hub.config.json) to an explicitly selected
   public profile. All example paths/hosts are placeholders. Merge, do not replace,
   existing plugins/permissions. No new top-level OpenCode config keys are introduced.
3. Have an operator provision password files **outside chat** first. Use absolute
   paths, regular non-symlink files owned by the runtime UID, mode 0600 or stricter,
   at most 4096 bytes. One final LF/CRLF is removed; other newline/NUL bytes fail.
   Do not put secrets in the profile, repository, prompts or command arguments.
4. Choose a stable private `stateDirectory` outside Git and model workspaces, with
   trusted ancestors. It is created mode 0700; existing unsafe ownership/mode or a
   symlink at the final directory is rejected. State files are mode 0600.
5. Optionally copy only [commands/dispatch.md](commands/dispatch.md) into the selected
   OpenCode `commands/` directory for `/dispatch`, and the
   [skills/dispatch-setup](skills/dispatch-setup/SKILL.md) folder into `skills/`.
   These resources are deliberately not added to the shared agent resource links.
6. Launch with `OPENCODE_CONFIG=/absolute/path/to/hub.config.json opencode` using
   your normal launch interface. **Quit and restart** after config/plugin changes.
   Confirm all five tools registered before delegating. Missing tools mean stop.

`enabled` omitted/false performs no IO. Invalid enabled configuration leaves
unavailable tools registered after successful import. Import/dependency failures
are outside this protection: the upstream loader can continue without the plugin.
This is delegation, **not** a sandbox or a lockdown of ordinary hub local tools.
The plugin never runs a task locally; the command explicitly forbids model fallback.

### Peer configuration

Each peer has exactly `{alias, description, url, username, passwordFile}`. Aliases
are unique lowercase letters/digits/hyphens starting with a letter, max 64 chars;
descriptions must be nonempty after trimming, max 500 input chars; advertised
descriptions are trimmed. Only aliases/descriptions enter system context and
`dispatch_peers`. URLs must be HTTPS origins without credentials, path prefixes,
queries or fragments. The peer's server working directory/default agent/model and
permissions determine execution; the hub cannot select arbitrary peer directories.
Credentials are read only during approved requests (including authorized background GETs), never persisted in handles or
included in tool metadata/errors. HTTPS uses explicit certificate validation,
no redirects, no custom agent and no mutation retries. Requests time out after 30 seconds;
responses are capped at 1 MiB. Raw errors/bodies are not returned. Responses echoing
the current plaintext password or Basic header (including JSON-escaped strings) fail.

This is not a defense against a malicious peer encoding/exfiltrating secrets, other
plugins, or local tools running as the credential-owning UID. Protect the hub's
tool permissions and filesystem separately. Native Basic credentials authorize the
server account, not a peer-side per-task capability. Use only trusted endpoints.

## Tools and durable ownership

| Tool | Arguments | Behavior |
|---|---|---|
| `dispatch_peers` | none | Public alias/description catalog; no network |
| `dispatch_task` | `peer, prompt` | Approve submission + background polling/context; create peer session and submit async prompt |
| `dispatch_reply` | `handle, prompt` | Same approval scope for a new turn; fresh peer verification of prior completion/failure |
| `dispatch_status` | `handle` | Stored terminal state, otherwise one explicit message poll; no text |
| `dispatch_result` | `handle` | Stored terminal result (works offline), otherwise one explicit poll; latest submitted turn |

Every valid operation calls `ctx.ask` with its namespaced tool permission, alias
pattern and `always: []`; configured permission policy still controls whether a UI
prompt appears. No peer credentials or endpoint details enter the permission metadata.
Names are prefixed to avoid replacing native `task`. Prompts are capped at 32000 bytes.
Task/reply descriptions and permission metadata explicitly encompass **read-only
background polling and repeated result context on future user turns**, surviving
restart. Authorization is persisted only after `ctx.ask` resolves. No background
code calls `ask`. Legacy records without this approval remain explicit-only;
status/result approval does not grant background authorization.

```text
hub session -> approval -> private intent -> HTTPS peer session/prompt_async
     |
     +-- bounded GET polling -> private per-turn completed-result inbox
                                     |
next USER chat.message -> frozen IDs in native user-part metadata (including empty selection)
                                     |
model loop messages.transform -> snapshot context only (no transcript write)
```

Handles survive plugin restart and require the **exact originating session ID and
directory**. Child, forked or unrelated sessions cannot adopt them. Keep the same
state directory. Records contain handle/owner/directory, peer alias, a configuration
hash, peer session/message IDs, submission phase, approval epoch and polling state,
but no prompt/password. **The separate inbox now stores assistant result text**;
treat the entire private state directory as potentially sensitive task data.
Peer config changes invalidate old handles after restart (password content rotation
at the same file path does not). Config is snapshotted at startup, not hot-reloaded.
State updates use fsync plus atomic rename and directory fsync on a local POSIX FS.

### Background lifecycle and next-user-turn context

- One unreferenced timer per plugin instance wakes one second after the preceding
  cycle finishes. A cycle makes at most **four sequential inspections**, with no
  overlapping cycles. Each turn first becomes eligible five seconds after submission.
  Subsequent GET spacing is 5, 10, 20, 40, 80, 160, then 300 seconds (capped), for
  pending, blocked, uncertain and transport-error outcomes alike. Spacing is persisted
  **before** IO. It is deterministic, not jittered; no POST is ever replayed.
  If saving that deadline fails, an in-memory deadline still enforces the same
  exponential backoff. Lock failures also back off per handle; directory-scan failures
  back off for the instance. Unpersistable deadlines cannot survive process restart.
- Restart scans only records for the plugin instance's exact directory, configured
  peer binding and approved epoch. Completed/failed records are not fetched again
  every tick. If the inbox write survived but the handle update did not, recovery
  restores the terminal pointer from the inbox without another peer fetch.
- `chat.message` freezes at most four result IDs into `TextPart.metadata.dispatch_snapshot`
  on the native user message, before native persistence. This metadata contains only
  the user message ID and selected result IDs, **not result text**; native model
  conversion excludes it. File-only input receives an empty ignored text part for
  the marker. The result inbox stores no growing per-user-turn snapshot map.
  Messages arriving at this boundary are
  ordered by the inbox lock. Results committed after that snapshot wait for another
  user turn, even if many model/tool iterations run in the current turn.
  Synthetic-only input/compaction continuations do not open a new snapshot.
- `experimental.chat.messages.transform` gets **empty input `{}`** in v1.18.29.
  We derive session identity from a single-session message history and select the
  latest user by creation time then ID, matching native ordering. Missing/ambiguous
  identity or missing snapshot means no inclusion—not a late snapshot. It adds
  ephemeral, labeled **untrusted peer data** to that user's model-context parts.
  There is no dispatch-initiated `session.prompt`, `prompt_async`, message API write, callback,
  notification, local hub service or forced model turn for result delivery.
- A snapshot contains at most four stable result IDs, keyed by **handle + submitted
  message ID**, so replies cannot overwrite an earlier turn's queued result. Each
  excerpt has at most 4000 characters, also bounded after JSON escaping; the whole
  added context is under 20000 characters. New results join the end of a durable
  round-robin order. Older results are not starved by continuous new arrivals.
  Large results receive an excerpt rather than blocking later entries.

**Exposure is not acknowledgement.** Freezing a snapshot advances only scheduling
bookkeeping; neither hook marks a result “delivered”, consumes it, nor claims a
successful provider request. Snapshots—including empty ones—are persisted by native
user-message storage and reused by model retries/restarts. Results remain in rotation
on later user turns. This is **at-least-once context exposure attempts**, with
intentional duplicates, not exactly-once delivery or proof the model/user saw it.
No user turn means no exposure. **Known storage failures degrade to no dispatch
context, not an ordinary-chat outage.** An empty marker is set before snapshot IO;
on capacity, lock contention, disk-full, quota, IO or read-only-filesystem failure it stays empty and
native user-message creation proceeds. Reusing that marker never retries selection
after storage recovery. The transform never creates a missing snapshot or selects
later arrivals. Fresh user turns can try again. Permission/unsafe-state errors,
corrupt JSON and invalid approval epochs are not treated as capacity failures;
they still fail closed with a sanitized hook error. An in-progress/failed local
cancellation suppresses dispatch context rather than obstructing ordinary chat.
This cannot keep native chat alive if its **own** database filesystem is full.

If a client deliberately recreates a user message without its previously persisted
metadata, that is a new hook invocation, not a native model retry; preserve the
marker when replaying input. Missing metadata in an existing model-loop history
always means no injection. Legacy inbox `turns` maps are discarded on the next
successful inbox write; pre-upgrade user messages without native markers receive
no automatic context until a fresh user turn. Results remain retained/retrievable.
If compaction removes/replaces
the snapshotted user, context waits for the next real user turn; it is not guessed
onto a synthetic continuation. Other plugins remain outside this trust boundary.

Explicit status/result still requires its own permission and can return the latest
stored terminal result offline (`cached: true`, stable `resultID`). If explicit
inspection succeeds but caching hits a known storage failure, tools return
the inspected state/text with `cached: false` and `cacheWarning`; retain that output,
because offline availability is not guaranteed. Authorization and peer-inspection
errors are not swallowed by this caching fallback. Terminal records
are observations, not continuous remote-session monitoring: later external edits
are not reflected in the cache. **Reply always checks live history again**, under
the handle lock, before submitting. Keep dispatch-created peer sessions exclusive.

`dispose` clears the timer and aborts in-flight requests; accepted approvals remain
durable for restart. An aborted task/reply submission disables that turn's polling.
Observed native `message.updated` with `MessageAbortedError`, or `session.deleted`,
revokes existing background approvals for that originating session and aborts its
active poll. This is local cancellation, **not remote task cancellation**. A later
explicit task/reply approval authorizes only its new turn. Native events are
fire-and-forget, so abort-event revocation is best-effort until the event is observed
and its private epoch is persisted; it is not a synchronous remote cancel API.
Existing results remain explicitly retrievable with permission after cancellation.

See [examples/turn-delivery.md](examples/turn-delivery.md) for the user-visible flow.

`accepted` means HTTP 204, **not completion**. `pending` means no terminal evidence
yet; `uncertain` means the submit outcome is unknown. Inspection uses the **latest
correlated assistant**, ordered by `time.created`, then lexicographic ID, matching
native `MessageV2.latest` (not array order or the first finished response).
`completed` requires a completed timestamp plus native loop-exit semantics: a
nonempty finish other than `tool-calls`/`unknown`, without non-provider-executed,
non-interrupted tool parts. Even **completed** native tools require another model
turn when the provider returns `stop`. The native exceptions are part-level
`metadata.providerExecuted`, or `state.status: error` with
`state.metadata.interrupted: true`. A latest completed assistant error is `failed`.
`completed` means the turn ended, not that the task succeeded: finish reasons such
as `length` may indicate an incomplete answer without an explicit assistant error.
Result text comes only from the latest correlated assistant, may be partial, and
is capped at 16000 characters. Summaries, tool/reasoning parts and raw peer errors
are not exposed. Large histories fail the response cap rather than claiming completion.

### Compaction lineage and blocked states

New submissions attach nonsecret `metadata.dispatch_turn: <submitted message ID>`
to their text part. The pinned native prompt schema accepts this field; its model
message conversion does not forward user text metadata. Overflow replay copies it
while replacing message/part IDs. No extra local state fields or prompt copies are
required. Inspection follows only the observed chain within this dispatch-created
session, starting at the stored submitted user ID:

```text
submitted user -> auto compaction user -> successful summary
                                        |
                 +----------------------+----------------------+
                 v                                             v
native synthetic compaction_continue             overflow replay of marked text
                 |                                             |
                 +------------> new user -> latest assistant <--+
```

Auto-continuations must have exactly the native synthetic text-part shape and
`metadata.compaction_continue: true`, with matching agent/model. Replays require
the overflow flag, retained dispatch metadata (or a previously verified native
auto-continuation), identical text parts except reassigned IDs, and matching copied
user context. **Identical prompt text alone is never sufficient.** Repeated
compactions and restarts are supported. A summary error returns `failed`, not an
old task result.

`blocked` carries a nonsecret `reason` and no result text. It refuses reply submission
when history is invalid, another user/assistant intervenes, lineage is unsupported,
the submitted user is absent from nonempty history, or a completed summary has no
recognized follow-up. Legacy unmarked overflow replays are blocked rather than
guessed. Manual compaction and plugin-generated alternative user prompts are not
adopted. An in-progress summary remains pending; `compaction_continuation_missing`
can be a transient snapshot between native writes or disabled auto-continuation.
An explicit later poll may resolve it. Never treat blocked as success or retry the
task locally. Inspect persistent blocks through authorized peer operator tools.

The native continuation marker is explicitly **not a stable upstream contract**;
reverify it before upgrading. Markers provide correlation, not authentication
against a malicious peer or API client copying metadata. Reserve dispatch-created
sessions for dispatch: these are snapshot checks, not a lock against external peer
clients modifying history or submitting work between polling and a reply POST.

## Deliberate limitations / recovery

- Background polling runs only while the enabled plugin instance is alive. Removing
  the plugin/peer or disabling it takes effect after quitting/restarting OpenCode;
  there is no hot config reload. Re-enabling the same binding resumes its durable
  approvals unless cancelled. Changing permission policy alone does not revoke a
  previously approved task capability; disable/remove the plugin to stop all polling.
- `reply` is a continuation prompt, not a remote permission/question response.
  Peer-side interactive approval must be handled on the peer. An approval-waiting task can
  remain pending indefinitely; HTTP 204 async errors may only reach peer event/log
  channels and are not always represented in messages. No event subscription here.
- No remote cancel tool, listing/recovery UI, attachments, history pagination,
  exactly-once submission, automatic cleanup or mutation retries. Aborting a hub request
  does not cancel peer execution. Keep returned handles in the originating session.
- An ambiguous create can leave an orphan peer session; an ambiguous prompt can
  already be running. Never resubmit blindly. Inspect private records and peer
  session through authorized operator tools outside chat before deciding recovery.
- In-process queues plus exclusive per-handle locks serialize polls, explicit reads
  and replies. Per-origin inbox locks serialize completion and snapshot transactions.
  Across processes a busy lock fails closed; no lock is stolen. A process crash
  can leave a lock; it is never automatically stolen. Only after stopping competing
  hub processes and reconciling the peer should an operator remove that handle's
  stale `.lock` (not its `.json`), including an inbox lock if affected. Losing state
  loses access through this plugin. Run one active instance per directory/state pair
  where practical; multiple processes share safety locks, not a global request quota.
- Inbox files (`inbox-<origin hash>.json`) retain results and admission reservations,
  with a **16 MiB per-origin cap**. Before creating a remote session or submitting a
  task/reply prompt, dispatch durably reserves **128 KiB per submitted turn** under
  the origin inbox lock. Admission includes existing bytes plus all outstanding
  reservations; worst-case JSON-escaped result text and identity size are bounded.
  Concurrent admissions cannot promise the same capacity. A full inbox refuses new
  task/reply mutations before any POST; existing cached results stay readable.
  Completion replaces its reservation with the retained result. These are logical
  inbox-budget reservations, not physical filesystem preallocation: later filesystem
  failure can still prevent caching, which explicit inspection reports separately.
  Failed/ambiguous submissions retain reservations conservatively; no automatic
  mutation replay or reservation reclamation is attempted.
- There is no silent result eviction or acknowledgement-based deletion. At capacity,
  polling backs off, optional exposure can be skipped, and ordinary native chat
  continues. State scans scale with retained handle count. Monitor private
  storage; stop the plugin and preserve a private backup before operator-directed
  archival/reset or reconciliation of abandoned reservations. A reset may lose handle
  result access. No unbounded in-memory task fan-out or per-task timers are used.
- Atomic writers clean their private `.UUID` temporary file across write, sync and
  close failures, without replacing the last committed JSON before successful temp
  close. Cleanup also runs if close throws. Unlink failure or process termination
  can still leave recovery evidence; do not blindly delete private state. A directory
  fsync failure **after rename** can report failure with the new file already visible.
- Same-UID edits and symlinked/untrusted ancestor directories are outside the state
  boundary. Private state is not encrypted. No real-server/native-engine integration
  or production rollout has been performed by this change.

## Pinned API evidence and tests

Reviewed upstream tag `v1.18.29`:
- [Plugin tool context](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/plugin/src/tool.ts): `sessionID`, `directory`, `abort`, `ask`.
- [Hook types](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/plugin/src/index.ts): `dispose`, `chat.message`, messages transform with `{}` input.
- [Plugin lifecycle](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/plugin/index.ts): instance directory binding, sequential awaited transforms, directory-filtered fire-and-forget events, scope finalizer invoking `dispose`.
- [SDK routes](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/sdk/js/src/gen/sdk.gen.ts) and types: `POST /session`, `POST /session/{id}/prompt_async` with `messageID` and text `parts`, `GET /session/{id}/message`.
- [Actual session handlers](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/server/routes/instance/httpapi/handlers/session.ts): async prompt forks work and returns NoContent; message list without limit returns history.
- [Native Basic auth](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/server/auth.ts) and [identifier format](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/id/id.ts).
- [Native prompt loop](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/session/prompt.ts): `createUserMessage` calls `chat.message` before `sessions.updateMessage`/parts; `runLoop` calls messages transform with `{}` before `toModelMessagesEffect` on every model step. Also `hasToolCalls`, `isOrphanedInterruptedTool` and prompt input schema.
- [Message ordering/conversion](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/session/message-v2.ts): `latest`/`isAfter`, full history ordering and user metadata exclusion from model text.
- [Compaction processing](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/session/compaction.ts): auto compaction part, successful summary, overflow replay copy and synthetic `compaction_continue` metadata.
- [Native schemas](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/schema/src/v1/session.ts): `TextPartInput.metadata`, `CompactionPart`, assistant/tool metadata.
- [Processor lifecycle](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/session/processor.ts): completion timestamps, interrupted tools and compaction/error outcomes.

Run from this directory: `npm test`. Tests use temporary private files, an injected
peer transport and mocked native HTTPS, not network calls to peers. The dependency
lock pins the plugin package; public upstream review is separate from offline tests.
Mocks verify contracts, not real TLS handshakes or native loader compatibility.
Regression DTO fixtures in `tests/fixtures.js` cover native tool-stop/later completion
and failure, creation-time/ID ordering, overflow replay, repeated auto-continuations,
legacy/unrelated prompt refusal, summary failure and missing/late continuation.
`tests/background.test.js` uses an injected clock/timer and transport for polling
bounds/backoff, offline/restart recovery, permission denial, binding isolation,
frozen snapshots/retries, fairness, per-turn results, cancellation/disposal and
poll/reply races. Hook tests model the inspected native call shapes but do not boot
the native engine or contact any peer.
`tests/atomic-write.test.js`, `tests/inbox-capacity.test.js` and
`tests/storage-backoff.test.js` inject filesystem errors and exercise full-capacity
chat, native-metadata retry recovery, concurrent reservation admission, uncached
explicit results, security-error propagation and failed-deadline-write backoff.

### Method Signature Surface

```text
+ DispatchPlugin(input, options = {})
+ createDispatch(options, transport = request, runtime = {})
+ privateRead(file, maxBytes)
+ request(peer, route, body, signal)
+ directory()
+ save(record)
+ write(name, value)
+ read(name, limit = 8192)
+ locked(name, action)
+ valid(record)
+ cancellationName(ctx)
+ authorization(ctx)
+ capture(record, result)
+ records()
+ poll()
+ tick()
+ start(directory)
+ dispose()
+ cancel(sessionID)
+ snapshot(sessionID, messageID, marker)
+ transform(messages)
+ load(handle, ctx)
+ inspect(record, signal)
+ inspectMessages(messages, record)
+ terminal(message)
+ autoContinue(message)
+ replayOf(source, message, rootID)
+ execute(operation, args, ctx)
+ hash(value)
+ id(value)
+ fail()
+ leaks(value)
+ tool.execute(args, ctx)
+ experimental.chat.system.transform(_input, output)
+ chat.message(hook, output)
+ experimental.chat.messages.transform(_input, output)
+ event({ event })
+ createInbox({ read, write, locked, valid })
+ reserve(record)
+ checkCapacity(box)
+ key(value)
+ owner(record)
+ name(ctx)
+ resultID(record)
+ load(ctx) // inbox
+ put(record, result)
+ get(record)
+ freeze(ctx, marker, authorization)
+ context(ctx, marker, authorization)
+ atomicWrite(directory, name, value, filesystem = { open })
+ capacityError()
+ isStorageFailure(error)
+ storageFixture(t) // storage fault fixture
+ fixture(t)  // test helper
+ scenario(t)  // regression fixture
+ compact(f, { overflow = false, continuation = 'auto', suffix = '1' } = {})
+ answer(f, parentID, { error, suffix = '1' } = {})
+ background(t) // background test fixture
+ create(config = options, directory = '/hub') // fixture
+ execute(d, op, args, context = ctx) // fixture
+ task(context = ctx) // fixture
+ record(handle) // fixture
+ complete(handle, text = 'Done', failed = false) // fixture
+ messages(id, sessionID = ctx.sessionID) // fixture
+ context(d, id, sessionID = ctx.sessionID) // fixture
+ transport(peer, route, body, signal) // fixture
+ runtime.now() // fixture
+ runtime.setTimeout(fn, delay) // fixture
+ runtime.clearTimeout(id) // fixture
+ advance(amount) // fixture
+ offline(value) // fixture
+ intercept(fn) // fixture
```
