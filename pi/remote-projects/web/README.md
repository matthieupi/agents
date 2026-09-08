# Bounded PiWeb remote browser support

✅ **Source-only first slice. No live deployment or installer changes.**

Reuse PiWeb's existing browser, SDK sessions, extension dialogs and SSH extension.
Remote chat/tools and browser `!`/`!!` can use the registered extension. This is
**not remote explorer, Git, worktree or PTY support**.

## Scope and behavior

```text
Browser chat / ! / !! --> existing PiWeb AgentSessionWrapper
                              |
                              +--> SDK emitUserBash --> extension result / operations
                              |                        (existing SSH2 implementation)
                              +--> Local default only when session intent is Local

Current SDK session ID --> native local-panel requests --> SDK current branch
                                                        | Local: existing handler
                                                        | Remote/unknown: HTTP 409
```

- `AgentSessionWrapper.send()` waits for extension binding and follows SDK
  `emitUserBash` / `recordBashResult` / `executeBash` semantics. SDK hook errors
  are reported through `onError` (the SDK catches thrown handlers internally).
  Missing routing for remote intent, hook failures, and missing session context
  never select default local operations. Busy, abort, persistence/history and
  default sanitized Local execution are retained.
- The actual native lookup is **`getRpcSession(id)`**. Its wrapper exposes
  **`inner.sessionManager.getBranch()`**. There is no invented
  `getSessionWrapper()` or session-manager getter.
- Live SDK branch history is authoritative; inactive sessions use the existing
  path resolver plus `SessionManager.open(path).getBranch()`, with ID validation.
  There is no second target registry. Unknown/empty/duplicate bound IDs reject.
- The canonical `../../.pi/agent/extension-library/remote-project-mode.ts` is
  copied **verbatim** into PiWeb `lib/` at apply time. Its checksum is pinned;
  a sibling change requires explicit review/repinning. Pending, invalid and legacy
  remote records stay Remote. Fresh/no-entry sessions are Local; only the
  canonical explicit Local record clears recorded remote intent.
- Browser context carries the current session ID through files (including
  downloads/uploads/watchers), file index, Git, worktrees and terminal requests.
  Existing `sourceSessionId` file plumbing is reused. Initial session restoration
  is fail-closed until mode resolves. The existing session-state endpoint gains
  `projectMode`; no new route or transport is introduced.
- Remote/unknown mode unmounts local native panels and displays **“available in
  Local mode”** / **“Remote panels are off”**. Local file markdown previews and
  `@` indexing are also disabled. Browser `!` is **not blanket-disabled**: routed
  remote operations/results remain usable.
- The explicit local project picker, session catalogue and local control/settings
  APIs intentionally remain local. They are not remote mirrors or remote selectors.
  Remote selection and explicit Local remain the existing extension commands/UI.

⚠️ **This is not RBAC or a security sandbox.** PiWeb Basic is a shared service-owner
login. Session IDs are context identifiers, not authorization grants. Omitting a
session ID deliberately retains unbound local/control use. A service owner can
select Local, edit extensions/settings, or run local code. Keep the upstream
Basic/Host/Origin and path-containment protections plus real SSH account/network
controls; none are replaced here.

Mode presentation refreshes through the existing state endpoint once per second;
server admission checks do not trust that UI cache. Already-admitted operations
and open streams are not a transactionally revoked execution lease. Local terminal
views disconnect on unmount and use the existing terminal expiry behavior.

## Public inputs and provenance

| Input | Pin |
|---|---|
| PiWeb source | `8463025a321b8a660e9c27b1fa9e1938e1e84c1f` |
| Source archive SHA-256 | `f47707b9dbc2e29ef76b7b5909867cae951c6c520a9cc0fa02f690a57e8ad649` |
| Public PiWeb comparator | `@agegr/pi-web@0.9.0`, report SRI verified by `fetch.py` |
| SDK | `@earendil-works/pi-coding-agent@0.85.1`, report SRI verified by `fetch.py` |
| Canonical helper SHA-256 | `01f211cd703a3150fbd723fcaad0df965e0e1922d05c8e9df6026bea616324da` |

The pinned git commit's manifest says **0.8.11**, while published npm 0.9.0
identifies that commit. Both were inspected; their SDK dependency pins agree.
The source build is explicitly labelled **0.9.0-remote.1**, not misrepresented as
byte-identical upstream 0.9.0. Archive/SRI checks establish content consistency,
not publisher signatures. Upstream MIT notices remain in the fetched source and
packed distribution.

`pi-web.patch` is ordinary readable unified source diff: **29 files, +266/-81
lines, 48,548 bytes**. `patch-files.json` lists every path and before/after SHA-256.
The helper is a separate copied build input, not a second implementation in the
patch. No compiled binaries, downloaded packages or scratch state are tracked.

## Build/apply path

Prerequisites: non-root Linux user, Node >=22.19, npm, Python 3, `patch`, and
compiler/make/Python prerequisites for node-pty. No global package installation.

From this directory, in a fresh scratch workspace:

```sh
python3 build.py
python3 test-apply.py
python3 run.py node "$PWD/test-package.mjs"
```

`build.py` performs:

1. Download public inputs through HTTPS and verify pinned source checksum/npm SRIs.
2. Extract a fresh `.scratch/rebuild/pi-web-<commit>`; reject an existing destination.
3. Verify **every original source file**, dry-run/apply with zero fuzz, verify all
   patched file hashes, copy the checksum-verified canonical helper.
4. Run `npm ci --ignore-scripts` using the upstream dependency lock; explicitly
   rebuild node-pty in scratch. All child commands use `run.py` with an allowlisted
   environment, isolated HOME/agentDir/cache, no inherited provider/SSH/Git secrets.
5. Run focused real-SDK/HTTP/React tests, upstream tests, native `npm run build`
   (`next build --webpack`), and `npm pack`.
6. Write `.scratch/out/build-provenance.json` with exact input/output checksums.

Allow **at least 10 minutes** for a cold build including dependency installation
and tracing. Build-script subprocesses have no artificial short timeout. If an
external command runner interrupts the build, preserve the scratch for inspection;
after checking its state, resume the native build/pack commands via
`run.py --source <owned-scratch-source>`, then run
`provenance.py <owned-scratch-source>`. Do not deploy partial `.next` output.

For application alone, after `fetch.py` and extraction of the verified archive:

```sh
python3 apply.py <owned-scratch-pristine-source>
```

Wrong versions, changed original files, repeated application and changed canonical
helper inputs fail instead of opportunistically matching minified output. No
global prototype patching, git credentials, git publication or root build is used.

## Verification recorded 2026-09-08

| Check | Result |
|---|---|
| Public PiWeb + SDK report SRIs and source SHA-256 | Passed |
| Clean apply; unexpected version; repeated apply | Passed |
| Real SDK/PiWeb focused suite | **14/14 passed** |
| Native PiWeb regression suite | **950/950 passed** |
| Focused ESLint over changed production modules | Clean, no warnings/errors |
| Native production build including TypeScript/tracing | Completed |
| Native npm pack | Completed |
| Scratch npm install 0.9.0 then replace with packed artifact | Passed |
| Installed package loopback HTTP + Basic/Host/Origin + bound-route checks | Passed |
| Real SSH, provider/model requests, hydrated browser E2E, live deployment | **Not performed** |

Focused tests cover real SDK returned operations and replacement results, history,
default Local bash, explicit Local restore, async hook busy/abort, hook failures,
missing hook/context, actual HTTP handlers across all local-only route methods,
live/persisted sessions, same-cwd session isolation, canonical pending/legacy intent,
and React static Local-only boundary rendering. SSH operations use deterministic
test adapters, **not a real SSH connection**. This lane does not re-prove the
sibling's complete managed SSH extension or child-tool policy.

Artifact: `.scratch/out/agegr-pi-web-0.9.0-remote.1.tgz` — **6,151,584 bytes**.

```text
patch SHA-256
588a0414a79c2906ec9b9e409a372c31b9dbc2bc77379fa14bef0a687d557ff9

artifact SHA-256
5fd0ae26bf8fabe5d1d8f6773c6f83ed6f753fb31d7aa1cd62dd12b6bd5264c7
```

These identify this build; timestamps/build IDs can change a later package digest.
Use the provenance generated for the artifact actually handed to the installer.

## Installer handoff / remaining gaps

- Later, the component installer must consume a checksum-pinned built tarball
  instead of public 0.9.0, retain the existing launcher/service/auth configuration,
  and keep this source/helper/SDK/extension revision set together. **No installer
  integration was changed here.** The scratch replacement test verifies npm package
  shape/startup, not infrastructure rollout.
- Preserve the patched managed extension registration in the service user's HOME
  and its canonical configuration/credentials. The browser uses the existing
  per-session SDK resource loader; this patch does not install the extension.
- Do not let an ordinary upstream update replace the patched package unnoticed.
  The derived version is a prerelease and not an automatic semver upgrade over
  0.9.0; install the exact artifact intentionally.
- Validate hydrated browser slash dialogs/selection, same-session multi-tab mode
  changes, authenticated real SSH operations and post-reprovision integration on
  the concerned Team machine when that deployment lane is released. Team remained
  held for reprovision throughout this work.
- Native remote files/Git/index/worktrees/PTY remain explicitly unsupported. Local
  child/default helper policy is the sibling agent's responsibility, not a new
  daemon or transport introduced here.
- Existing webpack warning in session HTML export remains unchanged. Initial
  command-runner timeouts were resolved by rerunning the build with more time;
  no incomplete artifact is reported as successful. See `progress.txt` for details.
