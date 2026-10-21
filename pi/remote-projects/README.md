# Pi managed projects — source-only adaptation

✅ Reuses **petrichor20211/pi-ssh-remote 0.1.12**, explicitly approved for #4.1.
This is **not cv/pi-ssh-remote** and not a new SSH adapter. The exact-context
source patch adds **228 lines and removes 24** from published `index.ts`; the
adjacent helper owns only catalog validation and factory-local selection intent.
SSH2 connection/key parsing, SFTP operations and Pi tool factories remain upstream.

**Not enabled or deployed.** No installer/entrypoint/start script, role, config,
vault, shared ignore file, PiWeb source, shared team artifact or Git index was changed.
The folder-local `.gitignore` excludes only `/.scratch/`.

## Files and provenance

| File | Purpose |
| --- | --- |
| `apply-upstream.py` | Exact-version patch, unique source contexts, enforced before/post/helper SHA-256; prints the full unified diff. No package installation. |
| `managed-projects.ts` | Production catalog helper copied next to patched `index.ts`. |
| `fixture.py` | Fetch/cache public tarball in isolated scratch; verify fixed SRI and all six files against fixed upstream commit. No archive-wide extraction or code execution. |
| `test-managed.mjs` | Fake SSH/catalog/SDK registration; actual pinned SDK tool factories exercise operations. |
| `test-paths.mjs` | Shared test-only allowlisted scratch path/ownership validation. |
| `test-sdk-smoke.mjs` | Real Pi 0.85.1 loader and two SDK sessions; cancelled selectors, no SSH/model requests. |
| `verify.py` | Rebuild fixture, reject wrong/double patch inputs, run tests and compare strict type diagnostics with untouched upstream. |
| `LICENSE.upstream` | Unmodified upstream MIT notice; applies to upstream source and included patch excerpts. |
| `SIGNATURES.md` | Callable/interface change surface and test-helper map. |

Upstream repository: <https://github.com/petrichor20211/pi-ssh-remote>

```text
Commit: 7c9b1f61b74e20e59ad7e9307ad3bb365c24774c
Tarball: https://registry.npmjs.org/pi-ssh-remote/-/pi-ssh-remote-0.1.12.tgz
SRI: sha512-OAJarFnnGnzVDsHKmKwITYhOb//pOWhbp9DXA6Nfd2nnkyt/8e/5D1bmakqimO+IGVpTzVRfXEkM77pAZ9mz2Q==
```

All six published files byte-matched this commit during implementation. Integrity
is an artifact-consistency check, not publisher-signature verification. Preserve
the original `LICENSE` in the future installed source directory.

### SHA-256 file manifest

| File | Before | After |
| --- | --- | --- |
| `index.ts` | `051f7addcdd00f690fab61cc8fb70b22c85114223b892be9df2480ddcdd42a87` | `c59152d32ca0746d5ac562e64e61f511e0dc39297cb3a573459168b0bfa81105` |
| `managed-projects.ts` | absent | `55be75cd1690e31889dfcdae97b2f49d4679eec37fc7eb3c68e7eb63fc115d38` |
| `package.json` | `ab127b3d7a3294c370ab5719fa238618d9d6b99b9143c97069c9599ead273051` | unchanged |
| `README.md` (upstream) | `b8f2f00490b79913c7ea5414a31dbd2938203bc7620b167949f662d69a8aa6ae` | unchanged |
| `README.zh-CN.md` | `3fb364212b07f4f201cae730a226499d7e4b6700745e1fa7d79f96fbf5fb6797` | unchanged |
| `CHANGELOG.md` | `54fda2cb92cec48d6935e0a0a752a741921b51f804ebbcc6b960c4d0277520ba` | unchanged |
| `LICENSE` | `765e300e3960a9b6a77e36cca2c448b4af551e2c18db517ba280d1af28668442` | unchanged |

## Managed-mode contract

```text
canonical grants -> controller-generated protected catalog
                              |
                     PI_PROJECT_CATALOG
                              |
       /remote select or project REF / own-session restore
                              |
               factory-local intent + metadata snapshot
                              |
          fresh catalog validation -> existing SSH2/SFTP tools
                  failure -> tool error, NEVER local fallback
```

Setting `PI_PROJECT_CATALOG` at factory creation enables managed project policy,
not automatic remote intent. **A fresh factory/session with no remote-session
metadata starts Local**, preserving existing local Pi. Remote attempts/restores
fail closed on empty, invalid or unreadable configured catalog paths. Absence of
the variable retains ordinary upstream mode; **the future managed deployment must
require this variable** and verify extension loading, not silently fall back to
an unpatched npm package. Requiring catalog configuration does not require users
to choose Local on every fresh login.

Catalog shape (public field names, not deployable example values):

```ts
{ projects: Array<{
  ref: string; label: string; address: string; port: number; user: string;
  cwd: string; identity_file: string; host_key_sha256: string;
  environment?: string; host_key?: string; workspace_name?: string;
}> }
```

- Exact canonical `environment.host` refs; unique entries; DNS/IP address; explicit
  account and integer port; canonical absolute cwd/key paths; nonempty labels;
  no control characters. Host fingerprint is 64 hex digits of the SHA-256 SSH
  public-key blob, compared through SSH2 `hostHash: "sha256"`/`hostVerifier`.
- Only the listed public entry fields are accepted. Root-level projection
  metadata may be retained. Disabled/revoked/unready projects must be **omitted**,
  not supplied as entries with an `enabled` flag. Empty catalog authorizes none.
- The controller owns authorization: User #4.1 grants team all enabled Dev
  `venv-*` projects, including future entries. This helper consumes that projection;
  it neither discovers hosts nor infers SysOps/account/network permissions.
- Provision the catalog and its entire directory ancestry root-controlled and
  not service-user-writable, replacing it atomically. The helper validates content,
  **not Unix ownership/ACLs/ancestry**. A user-writable catalog is not a security
  boundary. Provision a dedicated least-privileged execution identity; never
  controller keys. `identity_file` is a path, never key contents. Generate with
  normal 0600 permissions. Existing upstream file-kind/size/private-key parser
  reads the key only during connect; managed mode accepts usable unencrypted keys
  and never falls back to password, agent, cached passphrase or a prompt.
- Paths are shell-quoted for the existing parser/remote commands. Actual `pwd -P`
  must equal catalog cwd; do not project symlink or `~` workspace aliases.

### Selection, routing and persistence

| Surface | Managed behavior |
| --- | --- |
| Bare `/remote` | `ctx.ui.select` shows `label [ref]` plus **Local (explicit)**. On catalog error, notify and still offer Local. Error/cancellation never changes prior local/remote intent. |
| `/remote project REF` | Deterministic exact selection/connect; no LLM or raw SSH input. Intent is recorded before key/network work. |
| Model `remote` | `connect`/`reconnect` with optional exact `projectRef` (required if none selected), `status`, `exec` with `remoteCommand`. An idle accepted connect/reconnect records blocked remote intent **before** missing-ref/forbidden command/cwd/forwards validation. The previous ref is captured first for a valid reconnect. |
| `/remote reconnect`, `reload`, `status`, `exec COMMAND` | Use the same managed control policy. Managed exec takes a raw remote command, not upstream preview-option parsing. |
| User `/remote off` or `/remote local` | Explicit local choice; clears target and connection. No error-driven local fallback within a remote context. |
| Model disconnect/forget/off/forward/unforward/note/memory/chdir | Rejected. No hybrid tunnels, saved endpoint selection, local memory exception or persistent cwd changes. Use `cd` inside a remote command when needed; cwd is not a filesystem sandbox. |
| `read/write/edit/bash` | Local in local intent. In remote intent, revalidate before dispatch and each operation wrapper; SFTP rechecks catalog snapshot/client/generation after channel acquisition immediately before I/O, with channel cleanup in `finally`. SDK context cwd initializes local tools/path mapping. |
| Other model tools | In remote intent, `tool_call` blocks all names except the four covered tools and `remote`, including grep/find/ls and model-invoked child launchers. Local Pi is unchanged. |
| `user_bash` | Local intent returns no override. Remote intent returns ready remote operations or a full failing BashResult. Deferred operations revalidate and reject stale selection. No throw-only hook failure. |
| Connection loss/mutation errors | No automatic reconnect/replay in managed mode. Explicit reconnect required after loss. Unknown mutation outcome is returned as failure, not retried. Ordinary upstream reconnect remains unchanged. |
| Session start/new/reload/resume/fork | Only current-branch `pi-ssh-remote-project` metadata can restore an authorized project. No remote metadata means Local; malformed/unmigrated legacy remote records remain blocked. No global resume or shared active endpoint selection. |

Session entries contain only `{version, projectRef, local, workspace}`. Catalog
connection metadata and keys are never session grants. A saved explicit Local
choice restores local; malformed or revoked remote metadata stays blocked. Legacy
`pi-ssh-remote-state` records are not authorization and require explicit project
selection or Local rather than silently restoring endpoints or falling local.
An invalid connect input records no new target grant; missing-ref/forbidden-input
failures remain blocked on resume. Status errors and rejected model off actions
do not change intent. Managed mode
does not consume/write `credentialCache.resume`, endpoint config or known-host
files, migrate memories, or include the local-memory prompt. Upstream output
limit settings may still be read from shared HOME config; they cannot select or
authorize a target. Large output spills and SDK/session control data remain local.

Same-factory remote operations are bounded to one at a time; concurrent target
changes fail visibly rather than retargeting a pending write. Different factories
have independent state. **New context semantics:** `session_start` reads that
context's branch. A new branch without remote metadata starts Local even when the
factory previously served a remote session; it closes the old connection and
advances its generation first. A branch carrying its own remote metadata instead reauthorizes
or stays blocked on failure. This deliberate new-context transition is not a
connection/restore-error fallback or inheritance from another session.
Revocation cannot recall a command already dispatched to
the server. This is tool routing/authorization, not a sandbox against arbitrary
code executing with the service account's authority.

## Exact apply and verification steps

These are controller scratch instructions, **not VM/deployment commands**.
From the repository root:

```sh
python3 services/agents/pi/remote-projects/fixture.py
# Install public TEST dependencies only into the isolated fixture directory.
npm --prefix services/agents/pi/remote-projects/.scratch \
  --cache services/agents/pi/remote-projects/.scratch/npm-cache \
  install --ignore-scripts --no-save --package-lock=false \
  @earendil-works/pi-coding-agent@0.85.1 @earendil-works/pi-ai@0.85.1 \
  @earendil-works/pi-tui@0.85.1 ssh2@1.17.0 typebox@1.3.28 \
  typescript@5.9.3 @types/ssh2@1.15.5 @types/node@22.19.0
PYTHONDONTWRITEBYTECODE=1 python3 services/agents/pi/remote-projects/verify.py
```

Node **22.19.0+** is required by Pi; tests used 22.23.2. No private environment,
live socket, global package install or lifecycle script is needed. Cache is
isolated at `services/agents/pi/remote-projects/.scratch`, ignored only by this
folder's `.gitignore`. An explicit `PI_REMOTE_FIXTURE` override accepts only that
exact absolute path or `/tmp/opencode/pi-remote-projects`; arbitrary paths, aliases
and old outside-cache paths are rejected before writes. The optional external
location is not used here (`/tmp/opencode` is unwritable on this controller).
`fixture.py` checks scratch ownership/write permissions, an initialization marker,
symlink/hardlink outputs, and the fixed SRI even when using cached bytes.
It refuses an existing directory without its marker. `verify.py` resets only its
public fixture on each run and tests rejected override paths. SDK smoke runs use
fresh `sdk-smoke-*` subdirectories, isolated HOME/agent config, and in-memory
session/settings managers. Test subprocesses receive only PATH and scratch-local
HOME/TMPDIR/fixture settings; Jiti's filesystem cache is disabled. No old run data
is deleted.

The previous public cache at `/tmp/pi-remote-0.1.12-opencode` was **left untouched**:
no deletion, moving, or writes in this pass, to avoid disturbing another process.
It contains public package/test dependencies, not secrets. It is no longer a
supported fixture location. No public fixtures or dependencies are bundled in Git.

For the future installer owner, obtain the exact six verified published files in
a **new inactive package directory**. Then apply this exact patch (replace
`PACKAGE_DIR` with that absolute directory; do not run against live loaded source):

```sh
python3 services/agents/pi/remote-projects/apply-upstream.py "$PACKAGE_DIR" --check
python3 services/agents/pi/remote-projects/apply-upstream.py "$PACKAGE_DIR"
sha256sum "$PACKAGE_DIR/index.ts" "$PACKAGE_DIR/managed-projects.ts" "$PACKAGE_DIR/LICENSE"
```

`--check` emits the unified source diff/post digest without writing. Apply rejects
changed/upgraded/already-patched source, checks helper digest, and copies the helper
adjacent to `index.ts`. The `.js` import follows TypeScript source resolution;
the pinned SDK loader integration must validate this pair together. This Python
file is an exact source patch, not a runtime dependency or an installer framework.

Keep package metadata and MIT license intact. Install/resolve production peers
separately with exact Pi 0.85.1, ssh2 1.17.0 and typebox 1.3.28, and retain the
future installer's resolved dependency lock. Do not copy test `node_modules`,
TypeScript/test dependencies, or an unpatched npm registration into production.
Upstream package metadata still has ranges; it is **not a production lockfile**.
Load the patched source directory once via the owning Pi/SDK loader configuration,
verify no loader errors, provision the catalog/key, complete deterministic
selection/readiness, and only then consider host-scoped acceptance. None of those
installation or enablement steps was performed here.

## Verification and remaining gates

P1 correctness/fresh-local revision: **2026-09-08**. Updated production/helper
hashes above supersede the earlier verification-only revision.

✅ **20 test groups plus one real SDK smoke pass** (13 original groups with the
approved fresh-local expectations, plus seven regression groups). Tests use fake
SSH and real Pi SDK 0.85.1 tool factories:
catalog validation, two-factory same-cwd isolation, root catalog refresh/revocation,
unknown/invalid targets, trust/auth/key/cwd failures, cancel/Local, model-off and
unsupported-tool blocking, stale user-bash ops/result shape, no command/write/stream
error replay, concurrent control, own-history restore, and ordinary upstream
local/connect/reconnect/disconnect parity. Wrong/double patch inputs are rejected.

The P1 regressions pause authenticated SFTP acquisition, revoke/change catalog
metadata or invalidate the connection/context, then release the callback. All
write/read/stat cases assert **zero SFTP I/O**, an error result and channel closure.
Other regressions cover Local → missing-ref/forbidden-parameter connect/reconnect
with all four tools blocked and failing user-bash results; resume of those failed
attempts; fresh-local versus malformed/legacy remote history; Local availability
on catalog failure; and status/model-off/concurrency intent invariants. Seven
targeted groups were observed failing before the fixes and passing afterward.

The additional smoke uses actual `DefaultResourceLoader.reload()` and
`createAgentSession()` twice, loading the exact patched `index.ts`/adjacent helper
through the SDK TypeScript loader (including TypeBox imports). Both loaders report
zero errors; `/remote` and its `projectRef` schema are registered. Real
`session.prompt("/remote")` dispatch cancels selection without reaching a model
and preserves fresh Local intent. Invalid remote attempts then activate blocked
remote intent; real `bindExtensions`/RPC-mode UI and runner hooks return failing
BashResults and block unsupported tools. Two sessions sharing the same cwd retain separate
managers, tools and local/pending state after `/remote off` in only one session.
No local tools are executed in the smoke. Socket/TLS/fetch/SSH-connect guards
record **zero network attempts**. This is SDK integration, not a browser test or
a successful remote connection.

Verified test dependency versions: Pi coding-agent/agent-core/ai/tui **0.85.1**,
ssh2 **1.17.0**, extension/test-root typebox **1.3.28**, SDK-nested typebox **1.3.7**,
TypeScript **5.9.3**, `@types/ssh2` **1.15.5**,
`@types/node` **22.19.0**. `verify.py` asserts these installed versions. These are
direct test pins (plus checked SDK-nested core/TypeBox dependencies), not a
production transitive lock. SDK 0.85.1 ships its own nested dependency tree; the
checks do not assume those packages are hoisted to the test-root node_modules.

Strict TypeScript checking adds **zero diagnostics** over the original source.
Both have three pre-existing errors: two implicit-any SSH `hash` parameters and
the untyped `ctx.ui.custom<string | null>` call. This is baseline parity, **not a
clean upstream typecheck**. Patched diagnostics are `index.ts:705` and `:728`
(`TS7006`, implicit-any host-verifier hash), and `:859` (`TS2347`, untyped UI custom
generic); untouched upstream locations are `:703`, `:726` and `:857` respectively.
No real SSH authentication or browser integration was run. SDK write/edit
mutation-queue bookkeeping calls local
`realpath` and may serialize equal local paths across sessions; tests distinguish
this control bookkeeping from actual project file reads/writes or local shell
fallback. It did not mix remote targets.

⚠️ **Do not enable live until separate owners close these gates:**

1. Provision root-protected canonical catalog, independently authenticated host
   fingerprints, dedicated 0600 execution key, target account permissions and
   network reachability. Preserve existing team/browser authentication.
2. Installer loads/pins this exact patched source and helper for each server-side
   SDK session, binds lifecycle/UI, requires catalog configuration and blocks
   **remote-intent** work until ready while preserving fresh Local sessions.
   Test real SSH/key format, loader resolution, timeout/cancellation and selection
   UI on the concerned host before any wider rollout.
3. **PiWeb `!`/`!!` and direct `AgentSession.executeBash` bypass `user_bash`.** The
   PiWeb owner must emit/honor the hook and record replacement results as RPC does,
   or disable these paths. This extension cannot fix them within current ownership.
4. Browser explorer/uploads/downloads, file index, Git/worktrees and terminal
   panels are independent local backends. Route them to the authorized target or
   explicitly disable/label them; extension agent-tool parity is not panel parity.
5. The hook blocks model-invoked child **tools**, not other extensions' slash
   commands, helpers, shortcuts or arbitrary `child_process` launchers. Disable
   those entrypoints through their owners until children explicitly load this
   extension, receive a canonical ref, reauthorize and gate readiness. No browser
   child inheritance or slash-helper coverage is claimed.

Expanding browser/bash/child coverage requires expanded source ownership; no
unsupported browser adapter was invented here. No staging, commit, push or live
operation was performed. The required `/progress.txt` append was attempted but
failed with PermissionDenied (the absolute file is absent); no unrelated workspace
changelog was substituted. This owned handoff records the change and verification.
