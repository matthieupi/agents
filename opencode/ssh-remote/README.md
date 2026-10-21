# Optional OpenCode SSH project tools

✅ **Default off, one immutable project per launch.** This is a small JavaScript
plugin, not a remote OpenCode server, filesystem mount, task backend or sandbox.
Nothing in this directory activates it, enrolls a project, or changes native
installation/global configuration. Normal launches retain native local tools.

## Authorization and explicit launch

**Do not use the fake catalog as authorization.** Controller #4.1 must supply an
OpenCode-specific authorized catalog projection after explicit source-host grants,
dedicated-key enrollment, host-key verification and network authorization. An
existing `team` Pi grant does **not** authorize `agent-devteam`. This implementation
creates no new-source grant and probes no real projects.

1. Keep the complete package (including `remote.py`) outside OpenCode's auto-loaded
   `.opencode/plugin(s)` and `.opencode/tool(s)` directories.
2. In this package directory only, install with Node 22/npm 10:
   `npm ci --ignore-scripts --no-audit --no-fund`. No Bun, tsc, global dependency,
   daemon or remote helper installation is required by this package.
3. After authorization, adapt `examples/remote.config.json` into a separate,
   explicitly selected profile. All example paths, keys, hashes and hosts are fake.
   Use an absolute file URL for `index.js` and an absolute projected catalog path.
4. From a neutral/empty local directory, launch with
   `OPENCODE_CONFIG=/absolute/path/to/remote.config.json opencode` (or the native
   web/serve invocation). **Quit and restart** after any profile change; startup
   settings are not hot-reloaded. Start a **new session** when switching target or mode.
5. For local mode, remove the remote profile from the launch and restart. Do not
   add a duplicate disabled plugin to counteract an inherited enabled entry.
   `disabled.config.json` illustrates a standalone no-op, not an override mechanism.

Provider/authentication plugins and their configuration are preserved. Review
other tool-overriding plugins: later overrides or config hooks can undermine
routing. This plugin cannot filter all other local plugin code.

### Startup lockdown and the loader boundary

OpenCode v1.18.29 **logs and swallows plugin factory failures**, then continues
without those hooks. Therefore enabled startup validation must not simply throw.
After this module successfully imports, invalid options/catalog/selected target or
state-directory configuration return **lockdown hooks**. These apply the same
supported snapshot/LSP/formatter/watcher/MCP restrictions and reject the system
transform, every tool definition/execution hook, and covered local shell paths with
an explicit `SSH remote lockdown` error. Null/non-object options or non-boolean
`enabled` values (including `"true"`) also lock down. Omitted options/`enabled`, or
literal `enabled: false`, remain immediate `{}` with no initialization IO.

**Import failure is not protected by these hooks.** A missing/unreadable entry,
dependency resolution failure, syntax error, incompatible runtime, skipped plugin
or wrong launch profile can prevent the factory from running at all. The native
loader may then continue with local tools. No in-plugin code can guard that case.
This residual risk **blocks production activation in this pass**; this is not a
failure-safe launcher. No independent guard/proxy or global configuration is installed.

Before any later authorized deployment/launch, separately validate the exact entry
URL, package/lock/runtime, profile selection and actual hook registration in that
environment. From the package directory run `npm ci --ignore-scripts --no-audit
--no-fund`, the regression/schema/source checks below, and the explicitly selected
native engine fixture. That fixture must fail with **the lockdown diagnostic**, not
merely any nonzero exit, when enabled against an invalid target. Quit/restart and
repeat validation after changing runtime, dependencies or profile. These smoke checks
provide evidence, not an automatic guard against a later import failure. Blanket
native `read`/`edit`/`bash` permission denies are **not an independent fallback guard**:
same-name filtering also disables the corresponding custom remote tools.

### Options and catalog (#4.1, no second registry)

| Option | Contract |
| --- | --- |
| `enabled` | Literal `true` enables; omitted/`false` returns `{}` before IO; invalid types return lockdown hooks |
| `project` | Exact #4.1 `environment.host` ref, fixed for the entire launch |
| `catalog` | Absolute JSON path, maximum 1 MiB; read again on every dispatch and after permission checks |
| `stateDirectory` | Optional absolute private directory; defaults to `$XDG_STATE_HOME/opencode-ssh-remote` or `~/.local/state/opencode-ssh-remote` |
| `timeoutMs` | Positive integer, default 120000, maximum 600000; per-bash timeout can only shorten it |

```text
{projects: [{ref, label, address, port, user, cwd,
             identity_file, host_key_sha256}]}
```

Optional `environment`, `host_key` and `workspace_name` metadata are accepted but
do not select routing. The selected entry must be unique and complete. `cwd` is
an absolute canonical POSIX path; `identity_file` is an absolute controller path
to a dedicated unencrypted private key (owned regular non-symlink file, mode 0600
or stricter, at most 64 KiB). No SSH agent, password, keyboard-interactive, ambient
SSH config, ProxyCommand, remote key transfer or authentication fallback is used.
`host_key_sha256` is exactly 64 lowercase hex characters: SHA-256 of the **raw SSH
public-key blob**, as supplied by SSH2 `hostHash: 'sha256'`. It is not OpenSSH's
`SHA256:<base64>` display or a hash of an authorized_keys line. Never treat an
unverified ssh-keyscan result as a trust anchor.

Refs follow #4.1's canonical `[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9-]*` grammar,
at most 256 characters. Slashes, colons, underscores, uppercase, extra dots and
wildcard selectors are not accepted as a selected ref.

Selected endpoint/label changes, revocation, missing entries and malformed catalogs
fail closed. Unrelated entries may change. No automatic retry or local fallback.
Catalog rechecks are point-in-time checks, not a distributed authorization lease;
revocation cannot retroactively cancel an already-running request.

## Flow and session ownership

```text
model tool -> validate catalog + normalize paths -> ctx.ask
           -> re-read catalog -> verify SDK session ancestry
           -> immutable private binding -> final catalog check
           -> pinned SSH -> python3 -c '<fixed bundled source>'
                           stdin: ONE JSON line, kept open
                           stdout: bounded JSON response
```

Bindings contain only `{ref, fingerprint}` in SHA-256-session-ID-named files, not
credentials, paths, commands or file content. Fingerprints include the selected
connection fields and label. Complete mode-0600 binding files are atomically
published without overwriting an existing binding. The state directory must be
owned by the current UID and have no group/other permissions. Always retain and
reuse the **same** state directory across launches/targets; deleting it or using
a different directory discards the protection.

SDK parent lookup is required, recursively, even for resumed/child sessions;
lookup failures, cycles and target mismatches reject execution. There is no
mutable process-global current target. File hashes are in-memory per session and
normalized absolute remote path; resumed sessions must read again before updating
existing files. Child sessions get the same launch target but not a parent's read
hashes. Local `task` remains native subagent orchestration, not remote task execution.

**Disabled mode cannot enforce saved remote history.** It registers no hooks and
does not read bindings. Consequently there is no cross-mode history protection:
start a new session instead of resuming remote history in a local launch.

## Tools, permissions and file semantics

Native-shaped definitions: `read(filePath, offset?, limit?)`,
`write(filePath, content)`, `edit(filePath, oldString, newString, replaceAll?)`,
`apply_patch(patchText)`, `glob(pattern, path?)`, `grep(pattern, path?, include?)`,
`bash(command, workdir?, timeout?, description?)`.

- Every remote operation calls `ctx.ask` for `read`/`glob`/`grep`, `edit` for all
  mutation tools, or `bash`. File patterns stay `ref:/absolute/path`. Bash patterns
  are `ref:encodeURIComponent(canonicalCwd):command`: only cwd is encoded, with
  colons encoded as `%3A` and percent signs as `%25`; the complete command is the
  opaque suffix after the second colon. For example, ref `example.fake-project`,
  cwd `/srv/work:one` and command `printf 'a:b'` produce
  `example.fake-project:%2Fsrv%2Fwork%3Aone:printf 'a:b'`. A colon in cwd cannot
  collide with a command prefix. Metadata shows target, operation and arguments.
  `always: []` avoids creating broad remembered grants. Existing permission and
  agent objects are not loosened; native Plan `edit: deny` still applies through
  OpenCode's merged agent/session ruleset. Configure remote path/command policies
  against these **target-qualified patterns**: native local-path rules and native
  bash AST/prefix analysis are not equivalent. This is not a command-policy sandbox.
  OpenCode uses **last matching rule wins**: place broad defaults first and narrow
  target/cwd/command exceptions afterward. Review existing remote Bash rules when
  upgrading from the old raw-cwd syntax; do not assume an old pattern still applies.
- Read-only and mutation paths resolve inside the selected root. The helper rejects
  symlink components/escapes, hard-link aliases, binary/non-UTF-8 files and `..`
  traversal. `read` is for regular text files, not browser/directory/image parity;
  use `glob` for file listings. Offset is one-based. Search uses remote ripgrep,
  remote ignore rules and no global rg config, not a separate pattern engine.
- Existing writes/edits/patches need the session's read/result hash. Unread paths
  send explicit `null`, permitting creation **only if still absent**. Hashes from
  successful full read/write/edit/patch responses update session state. Partial
  reads (omitted prefix/suffix, including offset beyond EOF), byte/frame clipping,
  and Node's visible line cap are marked truncated. A truncated reply **deletes**
  affected cached hashes, even if an earlier full read or write established them.
  Subsequent existing-file write/edit/delete requires a fresh, complete, unclipped
  read within the line/output cap. Paging is not accumulated into a full-read hash.
   External changes produce conflicts, not retries. Files that cannot fit within
   a complete qualifying read cannot be mutated with these file tools in v1.
- Patches support Begin/End Patch, Add/Delete/Update/Move and exact unique context
  hunks (`@@` or `@@ exact anchor`). Numeric unified-diff ranges, fuzzy/ambiguous
  contexts and unsupported shapes fail. Paths/hunks are validated before writes.
  Ordinary file modes are retained; ownership/ACL/xattrs are not copied. Replacements
  are atomic **per file**, not multi-file transactions, locking or compare-and-swap
  against arbitrary concurrent writers. Errors/disconnects can have partial effects;
  inspect/read again rather than automatically retrying mutations.
- Remote Bash/Python 3/ripgrep must already exist; the helper rejects UID 0. Bash
  runs `/bin/bash -lc` with the remote account's real authority and login startup
  environment; it can leave cwd, use authorized sudo, or access other hosts. It is
  not confined by file-tool root validation.

### Protocol and bounds

```text
request:  {operation, cwd, args, expected: {absolute_path: sha256_or_null},
           timeout_ms, max_output_bytes}
success:  {ok: true, output, files: [{path, sha256}], exit_code?, truncated?}
failure:  {ok: false, error: "bounded diagnostic"}
```

Only static bundled Python enters the shell command, safely single-quoted. Dynamic
paths/content/commands/regexes travel solely in JSON stdin. Input is at most 1 MiB
(tool argument budget reserves framing/hash space); output defaults to 32 KiB and
1000 visible lines. JSON wire and SSH stderr have independent hard caps. Truncation
is explicitly marked; tool titles/metadata include the target ref and exit code.
Remote mode sets native tool-output thresholds to 2000 lines/64 KiB so these
bounded results do not create overflow-file references under this configuration.

Input stays open until completion. Timeout/cancellation closes stdin/channel/SSH;
the helper monitors EOF and stops its owned subprocess group. Deliberately
detached/setsid processes escape containment. Authentication and execution share
the transport deadline; connection/key/helper failures never invoke local project
filesystem operations or local shell fallback. Local state/config/session/output
bookkeeping remains expected.

## Honest coverage — not a security boundary

| Surface | Remote-mode behavior |
| --- | --- |
| Seven model project tools | Same-name plugin overrides to pinned SSH |
| Question/todo/task/plan-exit/invalid | Reviewed local orchestration; session target checks still apply |
| Unknown custom tool IDs | `tool.definition` rejects before normal registry model dispatch; execute hook also rejects |
| MCP | All configured entries disabled at config hook; SDK status must confirm only disabled servers before model dispatch; lookup failures/unreviewed executions rejected; other plugins may undermine configuration |
| Skill/LSP/webfetch/websearch/list/batch/code-mode | Known unsupported tools disabled in config and rejected before execution |
| Snapshot/LSP/formatter/watcher | `snapshot: false`, `lsp: false`, `formatter: false`, watcher ignore `**` |
| Covered `!` shell and PTY environment paths | `shell.env` throws; verified against pinned prompt and PTY environment adapter source |
| Browser file/Git/attachments/internal reads | **Not universally intercepted or remotely routed**; do not use them as remote project interfaces |
| Native discovery and other plugin code | Remain local; additional skill paths/URLs cleared, but internal/default discovery is not universally intercepted |

The system prompt describes the fixed target and **model-tool scope**, not an
alternate browser filesystem. Do not promise UI parity or hide unsupported UI
controls as if they worked remotely. Prefer an empty local working directory.

## Method Signature Surface

```text
index.js
  default async SshRemotePlugin(input, options = {})
  async initializeRemote(input, options)
  async configureRemote(cfg)
  lockdown()
  normalize(root, value)
  async selected(catalog, ref)
  async checkCatalog()
  async checkMcp()
  async bind(id, seen = new Set())
  async execute(operation, raw, ctx)
  reviewed(id)
  hooks: config(cfg), tool.definition({toolID}, output),
         tool.execute.before({tool, sessionID}), shell.env(),
         experimental.chat.system.transform({sessionID}, output)
transport.js
  async runRemote(target, request, {signal} = {})
tests/fixture.js
  async fixture(t, mode = 'helper')
tests/pinned-loader.js
  async load(factory, input, options)
  async excerpt(name)
remote.py (separate helper ownership)
  dispatch(request), main()
```

## Verification and pinned sources

```sh
npm test
npm run test:helper
npm run test:schema
npm run test:loader
OPENCODE_TEST_BINARY=/absolute/path/to/reviewed/opencode npm run test:engine
```

Node tests use real loopback-only `ssh2.Server` fixtures, temporary generated
Ed25519 keys, temporary project directories and helper subprocesses. They cover
default no-op, denial before SSH, catalog revocation/drift, path injection,
session/parent/resume/race isolation, file hashes/conflicts/patches, no local
fallback, bad pins/authentication/stalls, bounds and cancellation/deadlines.
Fixtures close servers/connections and wait for helper cleanup. The Python helper
suite is self-contained in `tests/test_remote_helper.py` in this package.

`npm run test:schema` fetches **only the public** schema and uses the controller's
existing Python `jsonschema` to fully validate the fake OpenCode profiles. It does
not install anything. The ordinary suite performs offline example checks and
skips that optional live-schema check. `npm run test:loader` verifies the vendored
loader excerpts against the pinned public source. Ordinary tests execute those
actual `applyPlugin`/Effect catch excerpts offline, with built-in Node type erasure
(experimental in Node 22), not a rewritten approximation of the catch behavior.

The opt-in native engine fixture was also run against **OpenCode 1.18.29**: the real
`debug agent fixture --tool bash` path rejects schema-valid profiles with a missing
selected target or invalid `enabled` type using the registered lockdown diagnostic.
It uses a temporary neutral cwd/HOME/XDG directories, no enabled providers or auth
environment, disabled default plugins/model fetching, and a read-only config
directory to prevent automatic dependency installs outside this package. A native
Bash sentinel must remain absent, no SSH connection may occur, and fixture cleanup
removes engine state. This covers CLI/registry startup rejection, **not** a live
model conversation, browser UI, every engine path or import-time failure protection.
Production enrollment/activation remain out of scope.

The positive `tests/native-engine.test.js` fixture also runs the actual installed
**1.18.29 `opencode run`** against a loopback-only OpenAI-compatible HTTP server.
That server scripts one SSE `read("shadow.txt")` tool call followed by a stop
response; no real provider, API key, model fetch or model cost is involved. The
local cwd and remote SSH cwd contain different contents at that same relative path.
The test verifies exactly one SSH helper execution, the normalized remote request,
remote content in the provider's tool-result message (not the local shadow), a
completed native tool event with object-result title/target metadata, the final
response and a persisted session target binding. The plugin's session/MCP SDK calls
are **not mocked** in that process; successful remote system transformation and
execution pass through the real SDK/server paths.

Only the fixture target/path receives read permission. HOME/XDG/cwd remain isolated,
default plugins/project configuration/model fetching are disabled, and
the read-only config directory prevents dependency installation outside this package.
HTTP input, engine output and runtime are bounded; cleanup kills the test-owned
engine process group and closes HTTP/SSH listeners and helpers. This proves the
positive model-tool route is usable, not just that invalid startup can be rejected.
It does **not** expand coverage to all model/tool combinations or remove the
import-time failure/production-activation limitation described above.

Verified public npm pins: `@opencode-ai/plugin@1.18.29` (it pins SDK `1.18.29`),
`ssh2@1.17.0`; exact transitive graph/integrities in `package-lock.json`.
SDK types inspected: plugin `dist/index.d.ts` (`Plugin`, `Hooks`), `dist/tool.d.ts`
(`ToolContext.ask`, result shape), SDK `dist/gen/types.gen.d.ts`
(`Session.parentID`, `SessionGetData`, `McpStatusData`, `McpStatusResponses`) and
`dist/gen/sdk.gen.d.ts` (`Session.get`, `Mcp.status`).
The input client is the SDK **v1** API: `session.get({path: {id}, query: {directory},
throwOnError: true})`, yielding `{data: Session}`; not the v2 `sessionID` shape.
MCP uses `mcp.status({query: {directory}, throwOnError: true})`, yielding a
`data` name-to-status map; all present statuses must be `disabled`.

Source baseline: OpenCode **v1.18.29**, commit
`16747470f976aca3d362ad730bcd3fe82ecc2c9a`:

- [tool/registry.ts](https://github.com/anomalyco/opencode/blob/16747470f976aca3d362ad730bcd3fe82ecc2c9a/packages/opencode/src/tool/registry.ts): builtins followed by custom tools, plugin tool context and definition hooks.
- [plugin/index.ts](https://github.com/anomalyco/opencode/blob/16747470f976aca3d362ad730bcd3fe82ecc2c9a/packages/opencode/src/plugin/index.ts) and [plugin/shared.ts](https://github.com/anomalyco/opencode/blob/16747470f976aca3d362ad730bcd3fe82ecc2c9a/packages/opencode/src/plugin/shared.ts): actual factory application, swallowed initialization failures, hook registration and propagation. Vendored MIT-licensed excerpts are in `tests/fixtures/`.
- [session/tools.ts](https://github.com/anomalyco/opencode/blob/16747470f976aca3d362ad730bcd3fe82ecc2c9a/packages/opencode/src/session/tools.ts): same-ID assignment order, before-execute guard, merged agent/session `ctx.ask`.
- [session/prompt.ts](https://github.com/anomalyco/opencode/blob/16747470f976aca3d362ad730bcd3fe82ecc2c9a/packages/opencode/src/session/prompt.ts) and [plugin/pty-environment.ts](https://github.com/anomalyco/opencode/blob/16747470f976aca3d362ad730bcd3fe82ecc2c9a/packages/opencode/src/plugin/pty-environment.ts): covered `shell.env` paths. This does not establish universal browser/PTY interception across server variants.
- [permission/index.ts](https://github.com/anomalyco/opencode/blob/16747470f976aca3d362ad730bcd3fe82ecc2c9a/packages/opencode/src/permission/index.ts) and [agent/agent.ts](https://github.com/anomalyco/opencode/blob/16747470f976aca3d362ad730bcd3fe82ecc2c9a/packages/opencode/src/agent/agent.ts): permission evaluation and Plan defaults.
- [Official config schema](https://opencode.ai/config.json): plugin `[path, arbitrary options object]` tuples, snapshot/formatter/LSP/watcher/MCP and tool-output settings, checked 2026-09-08. The public schema is mutable; rerun its opt-in test when upgrading.
