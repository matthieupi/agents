# T3 Code — independent Docker component

The published `t3` CLI from `pingdotgg/t3code`, not hosted t3.chat. **Provider
selection remains `none`.** No other harness's image, executable, private home or
credentials are reused. Native-host installation and infrastructure are out of scope.

## ✅ Two-command workflow

From this directory, as a non-root Linux operator with existing local Docker access:

```sh
./t3code build
./t3code .
```

`build` uses checked-in artifact pins and the real npm lock; no prepared base,
manual image-ID export or review-flag environment setup is needed. It builds but
does not deploy. Only after Docker returns an immutable image ID and the wrapper
confirms it is loaded locally is it atomically saved in private host metadata.
Launch uses that image for **new workspaces only**. Existing profiles keep their
image across subsequent builds; changed explicit image inputs require recreation.

`.` means the current workspace. Relative paths are canonicalized before profile
validation; symlink components are refused rather than silently adopting aliases.
Paths containing spaces are preserved. `./t3code run .` is equivalent. To work on
another project, pass its narrow path instead of `.`; this command does not clone
or automatically import a project into T3.

**Delivery status:** host regressions and public artifact audits have run.
**No Docker build or running-container acceptance has run:** the implementation
session has no Docker CLI. The Dockerfile includes mandatory offline native/CLI
checks; their execution remains blocked, not waived. See verification below.

```text
runtime/pins.json + npm lock -> build -> private build.json (immutable image ID)
                                             |
                                      new profiles only
                                             v
t3code -> host.py -> Compose -> init -> foreground t3 serve
                       |                    |
                       +-- selected workspace (rw)
                       +-- shared agent root (ro)
                       +-- instance home (rw), NOT host registry
host 127.0.0.1 -> per-instance private bridge -> container 0.0.0.0
```

## 📍 Defaults, overrides and ownership

Requires Linux, Python 3, Bash, local Unix-socket Docker, BuildKit (`RUN
--network=none`) and Compose v2 supporting `create_host_path: false`. No Docker
installation or remote-host access is performed by these wrappers. Docker access
is effectively host-admin authority; the container receives no socket or CLI.
Rootless/user-namespace remapping and Docker Desktop require separate ownership
validation and are not accepted targets here.

| Input | Default / contract |
|---|---|
| `T3CODE_IMAGE` | Last successful local build for a **new** workspace; retained image for existing profiles. Override must be local `sha256:…` or an already-present `repository@sha256:…`, never a mutable tag. |
| `T3CODE_WORKSPACE` | Current directory; positional workspace takes precedence. Relative input supported. |
| `T3CODE_AGENT_ROOT` | Adjacent `../agent`, relative to the component location, not shell cwd. Override is an existing canonical absolute directory. |
| `T3CODE_STATE_ROOT` | Account-home `~/.local/state/t3code`; override is an existing canonical absolute private registry. |
| `T3CODE_PROVIDER` | `none`; all other selections and provider login fail clearly. |
| `T3CODE_PORT`, `T3CODE_CPUS`, `T3CODE_MEMORY` | `3773`, `2`, `4g`; run flags override these. Each instance needs a free port. |
| `T3CODE_BUILD_PLATFORM` | Native `linux/amd64` or `linux/arm64`. Both have pinned base manifests; neither was built here. Cross-build needs already configured Docker emulation. |

UID/GID come from the non-root invoking account, not environment overrides.
The default state path uses the account database, not inherited `HOME`/XDG values.
Missing default ancestors are created mode 0700; existing ancestors must be
operator-owned, symlink-free and not group/world-writable. The state root must
have matching UID/GID and private permissions. Existing unsafe paths fail with
reconciliation guidance; **no ownership or permission repair** is performed.

Workspace, agent and state roots must not overlap or expose the operator's whole
home/root. Thus the entire agents checkout is not a valid workspace when it also
contains the shared `agent/` root. Only the selected UID/GID is passed to Docker,
not supplementary groups. Use local storage with reliable flock/SQLite semantics.
Avoid `$` and control characters in paths. Wrappers ignore Compose `.env` and
ambient `COMPOSE_*`; `.env.example` is documentation, never sourced.

```text
~/.local/state/t3code/                 0700; never mounted
  .lifecycle.lock                     serializes launch/build/management
  build.json                          0600; successful image/platform/pin hash
  t3code-<uid>-<basename>-<hash>/       distinct canonical-workspace identity
    profile.json                      0600; immutable image and full launch inputs
    profile-history/<hash>.json        recovery configurations, NOT DB backups
    home/                             0700; mounted at /home/t3code
      .server.lock                    held for server lifetime
      base/                           userdata, worktrees, caches, secrets, identity
      logs/server.log                 private upstream stdout/stderr
```

Initialization preserves real private data and unknown link conflicts; it never
traverses repository worktrees or creates `.agents`, `.claude` or `t3.json` in the
workspace. Locks stop cooperative duplicate writers, not malicious same-UID users
or Docker administrators. Never replace lock inodes while they may be in use.

## 💻 Artifact/build contract

`runtime/pins.json` is the single build-pin source. It records the exact Node
24.20.0 Debian image tag/index digest, per-platform evidence, dated Debian/security
snapshots, T3 0.0.40 SRI, real lock SHA-256 and audited lifecycle scripts. The host
validates it before invoking the build. Ambient `NODE_IMAGE`, `BUILDER_IMAGE` and
old review flags cannot override it. See [ARTIFACTS.md](ARTIFACTS.md) for the actual
provenance checks, native-hook findings and update procedure.

The Dockerfile builds its own runtime and toolchain stages from the pinned
official image. Dated apt archives pin the OS resolution universe, including
transitives; Debian signature/hash verification stays enabled. Only historical
Release expiry checking is disabled. Runtime adds Git, CA roots, flock/util-linux
and libatomic; Python/make/g++ stay in the builder. No sudo, Docker CLI or privileged
helpers are added. The runtime tree is root-owned and non-writable to its user.

Clean `npm ci --ignore-scripts --include=optional` verifies locked tarballs, then
the installed hook inventory is checked. Audited hooks run via bounded `npm
rebuild --offline` with **network disabled**, using headers already in the pinned
Node image. They do not run on ordinary launch or on the host. The final runtime
stage must pass exact CLI/version, SQLite, native msgpackr, PTY and FFF search
checks as non-root with no network. An unsupported/missing native optional binary
therefore fails image creation rather than silently degrading into acceptance.

The build context allowlist excludes host state, environment files, credentials,
tests and audit caches. No mutable tag is written; no image is automatically
pulled at launch. Failed builds/capture leave the previous default, all profiles
and running containers unchanged. Registry digest images supplied explicitly must
already be loaded. Immutable identity is not a guarantee of vulnerability freedom
or bit-for-bit deterministic compilation.

## Commands

`./t3code` dispatches management below; otherwise it launches a workspace. The
`t3code-run` and `t3code-mgr` wrappers remain available. Use the exact instance name
printed at launch—no wildcard, `all`, force-clean, auto-update or service installer.

| `./t3code COMMAND` | Behavior |
|---|---|
| `build` | Build and capture default for future new workspaces; no deployment |
| `list` / `status NAME` | Registry-scoped container state, not readiness |
| `start NAME` | Start retained profile; create if absent, never implicitly replace |
| `stop NAME` | Stop only inspected instance, 60-second grace |
| `remove NAME` | Stop/remove exact container; retain home, profile, workspace, network |
| `recreate NAME --ack-stop` | Explicit replacement using current Compose and optional image/port/CPU/memory overrides |
| `logs NAME` | Private log, at most 64 KiB / 100 lines, no follow |
| `shell NAME` | Non-root operator shell, not an installer or second server |
| `pair NAME` | Create one-time pairing credential in the exact instance base |
| `auth NAME pairing list` / `auth NAME pairing revoke ID` | List/revoke pairing links |
| `auth NAME session list` / `auth NAME session revoke ID` | List/revoke persistent sessions separately |
| `provider NAME status` / `provider NAME login` | Unconfigured status / unsupported login |

Logs, shell, pairing, auth and provider exec require stdin/stdout/stderr to be
operator terminals. No arbitrary auth flags, alternate state path or administrative
session issuance. Do not record credentials in CI/shared logs. Revoking pairing
does not revoke established sessions. Logs render terminal controls visibly.
Management refuses foreign containers. Stop/remove remain usable after Compose
changes or missing former bind sources if private metadata/container identity is intact.

## ⚠️ Security and functional acceptance

- Provider `none` starts only the control surface. No authentication, paid task,
  account/model choice, discovery mapping or real provider acceptance is implied.
  Upstream T3 depends on provider SDKs (including Anthropic's SDK/platform artifacts);
  retaining that upstream lock is **not** selecting Claude or configuring/logging
  into it. No extra provider CLI is installed by this component.
- Shared resources mount read-only at `/opt/agent`; no generic T3 skills directory
  is invented. Future selected-provider discovery must be verified independently.
- Add `/workspace` using the supported UI after pairing. Headless `serve` does not
  auto-import cwd. Current researched thread default is **Full access**: select
  Supervised and prove rejected approvals cannot execute before functional use.
  Disable automatic pull/browser access unless separately approved.
- Compose drops all capabilities, sets no-new-privileges, read-only image, bounded
  tmpfs/log driver and CPU/memory/PID limits. No external DevAI network, host devices,
  Docker socket or broad home mount. Host publishing is loopback only, not an egress
  allowlist or protection from host admins/deliberately attached container peers.
- Remote use needs separate TLS/tunnel, WebSocket, long-stream timeout, origin/Host,
  cookie and bypass review. Pairing does not establish reachability or TLS. No
  Connect/Tailscale integration is configured.
- HTTP/WS auth-negative/revocation tests, telemetry/OTLP stored settings and actual
  egress remain unverified. `T3CODE_LOG_WS_EVENTS=false` is not a universal privacy
  control. Minimal TCP health means socket liveness only, not auth/provider readiness.
- Startup can print pairing credentials: upstream output stays in private
  `home/logs/server.log`, not shared Docker logs. Stop before rotating that file,
  retain 0600 and enforce private retention/disk-space policy; rotation is not automated.

## 🧪 Verification

Executed during this implementation (2026-09-08):

```sh
python3 -B -m unittest discover -s tests -v
python3 -B scripts/verify_build.py runtime
node scripts/audit-artifacts.mjs
python3 -B scripts/audit-hooks.py --source
```

All 19 regression tests passed. The suite covers relative/run-dot argv, actual wrapper processes using a
fake Docker executable, default root ownership/modes, symlink/overlap refusal,
workspace isolation, immutable successful-build capture, failure preservation,
retained profiles, explicit replacement guard, input tampering, remote/root guards
and stop/remove data preservation. Provider-none scripts and a real local TCP
health-probe connection also passed. The Docker boundary is simulated, not a running
Docker engine. Python/JS/shell syntax and Git whitespace checks also ran. Shellcheck
is unavailable. No host npm hooks executed.

**Blocked locally:** real `./t3code build`, Compose `config`, both architecture
native gates, startup/UI/auth HTTP/WS, read-only-filesystem behavior, SIGTERM,
streaming/resource discovery, state persistence/backup restoration and telemetry.
An existing authorized local Docker setup is the next prerequisite; do not install
privileged Docker or use a remote daemon to bypass it. Run the two commands against
a disposable workspace, then verify instance health and private logs. No live
credentials, paid tasks or remote infrastructure are implicitly authorized.

## Upgrade and rollback

1. Build a new image without touching active instances. Save the printed image ID.
2. Drain threads; stop only the intended instance. Back up its full stopped private
   home and profile consistently, including SQLite WAL and identity, with encryption
   and restricted access. Back up valuable workspace data separately.
3. Explicitly export `T3CODE_IMAGE='sha256:<new-id>'` and intended resource overrides,
   then `./t3code recreate NAME --ack-stop`. A later build alone never updates an
   existing profile. Shared root/workspace/home are not mutable through recreation.
   Prior profiles are saved by hash before stopping; they are not data backups.
4. If replacement fails, inspect private logs/status and retry `start` with that
   profile, or explicitly recreate with corrected inputs. The old container may
   have been removed; private data/history remain.
5. Roll back only with an approved prior immutable image and matching compatible
   stopped-state backup. Never point an older runtime at a migrated database without
   established compatibility. Restoring identity may revive sessions: revoke/rotate
   separately. No automated rollback, cleanup or ownership repair is performed.
