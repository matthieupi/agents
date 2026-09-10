---
name: dispatch-setup
description: Use ONLY to configure the opt-in hub OpenCode dispatch plugin with public peer metadata and references to preexisting protected password files.
---

# Dispatch setup

Read the installed dispatch README and examples/hub.config.json first. Confirm the
hub profile location, plugin's absolute file URL, private state directory and each
peer's alias, description, HTTPS origin, username and preexisting passwordFile path.
Descriptions must contain non-whitespace text; surrounding whitespace is trimmed.
Only public configuration belongs in this interaction. Never ask for a password,
read/cat a password file, source an environment file, print credentials, put a secret
in chat/tool arguments, or create/rotate a credential. If a protected file is absent,
stop: an operator must provision it outside this chat before continuing.

With normal edit permission, merge only the dispatch tuple and dispatch_* ask
permissions into the selected public config; preserve existing plugins and settings.
Do not change KDCO enablement or enable unrelated disabled plugins. Do not
place credentials in OpenCode config or add a top-level peers key. Keep all peer
metadata nonsecret; aliases/descriptions are intentionally visible to the model.
Require HTTPS origin only (no userinfo, path prefix, query or fragment). Password
files must be absolute, owned by the runtime UID, regular, non-symlink, mode 0600
or stricter; their parents and the private state directory need trusted ownership.
Explain that same-UID local tools are not isolated from files by this plugin.

Opt in to /dispatch by copying only commands/dispatch.md to the chosen OpenCode
commands directory; install only this skill folder in the chosen skills directory.
Keep the complete package (including inbox.js and storage.js) outside auto-discovery folders. Do not change services,
infrastructure, peer config, TLS validation or networking. Do not probe peers with
shell requests. Confirm the public diff, then tell the user to quit and restart
OpenCode and verify dispatch_* tools appear. The user can explicitly approve a
dispatch task afterwards. Explain that task/reply approval includes durable read-only
background polling and queued context on future USER turns in the originating session
and directory; no callbacks, transcript notifications or forced model turns. Private
state now contains result text. Retain handles for explicit status/result, which can
use stored terminal results offline. Stable result IDs may repeat: snapshots are
exposure attempts, not delivery acknowledgements. Disabling/removing the plugin or
peer requires restart; unchanged bindings can resume previously approved work when
re-enabled. An observed native session abort revokes older background approvals, not
remote execution. Read the README's storage-cap and cancellation limitations before
enabling. Frozen result IDs live in native user-part metadata, not an ever-growing
dispatch snapshot file; result text remains in private dispatch storage. Capacity is
reserved before remote mutations. Storage exhaustion skips optional context instead
of blocking ordinary chat; explicit inspection may return a cache warning. Unsafe
state and authorization errors still fail closed. Missing tools mean stop, not local fallback.
