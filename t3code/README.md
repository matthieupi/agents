# T3 Code — independent Docker component

**Source-only delivery: unbuilt, untested, and not deployment-ready.** This is
the published `t3` CLI from `pingdotgg/t3code`, not hosted t3.chat. No provider
has been selected. No dependency hooks, builds, containers, logins, tests, or
workstation acceptance were executed for this implementation. The user owns
the deferred test implementation and workstation acceptance.

## What is delivered, and what is blocked

- Dockerfile, one Compose container specification, host dispatcher/run/manager,
  private-home initialization, foreground server, and provider-neutral dispatcher.
- **Build blocked:** `runtime/package.json` intentionally has no T3 dependency,
  and `runtime/package-lock.json` is intentionally absent. The research candidate
  `t3@0.0.40` is not an approved release pin. No fabricated lock or mutable fallback.
- **Provider blocked:** only `T3CODE_PROVIDER=none` is implemented. Status reports
  `unconfigured`; login and other provider selections fail. A supported provider
  requires separate artifact approval and concrete bootstrap/discovery code.
- **Acceptance blocked:** native modules, CLI parity, auth HTTP/WS, permissions,
  telemetry, shared-resource discovery, streaming, persistence and recovery remain
  unverified. A listening socket does not establish any of these.
- Native installation/service management, infrastructure deployment, remote
  exposure, Pi/OMP adapters and agent Docker access are out of scope.

No other harness's executable, image, private home or credentials are reused.
The shared agents README was left unchanged to avoid editing another owner's lane.

```text
t3code -> t3code-run -> host.py -> Compose -> init -> start -> t3 serve
       -> t3code-mgr -----------^                      |
                                                     +-> private home/base
host loopback -> isolated per-instance bridge -> container port
shared agent/ ------------------ read-only ----------> /opt/agent
```

## Artifact preparation — required before a build

The release owner must:

1. Approve an exact T3 release, its registry identity, tarball SHA-512 SRI,
   signatures/provenance and publishing commit. The plan's source research anchor
   `b5d89038ae72142038dfa8cf69d49b7a607fe98e` is **not** a release provenance claim.
2. Replace the blocked manifest description and set its sole dependency to
   `"t3": "<approved-exact-version>"`. Generate a real npm v3 lock in a clean
   credential-free environment, initially without hooks, then review all resolved
   artifacts. Keep the exact manifest and lock together. Every non-root lock
   entry must use an exact registry tarball and SHA-512 integrity. If real package
   metadata cannot meet that contract, review it explicitly; do not weaken the gate
   merely to make installation pass.
3. Audit installation hooks and native/optional binaries, including independently
   pinned and integrity-checked secondary downloads. `npm ci --ignore-scripts`
   is followed by `npm rebuild`; scripts are **not** blanket-disabled at delivery.
4. Supply two compatible, reviewed **prepared** base images with recorded OS
   package snapshots/pins and architecture. No mutable `apt` step is hidden here.
   Runtime requires Node/npm, Bash, coreutils, `flock` (util-linux), Git, CA roots
   and the native libraries required by the approved dependency set. The builder
   additionally needs its native toolchain and `timeout`. Runtime must not carry
   compilers, sudo, Docker CLI/socket, SSH credentials or privileged helper tools.
   Use matching Node patch, ABI, libc/OS and architecture. Review base environment,
   npm configuration, inherited volumes, entrypoints, privileges and SBOM too.
5. Supply these nonsecret build inputs explicitly:

| Input | Required contract |
|---|---|
| `NODE_IMAGE` | Prepared runtime reference with exact Node patch-leading tag **and** SHA-256 digest |
| `BUILDER_IMAGE` | Prepared builder reference with exact tag **and** SHA-256 digest |
| `NODE_VERSION` | Exact matching Node patch; research recommends supported Node 24 LTS |
| `T3_VERSION` | Approved exact T3 release |
| `T3_INTEGRITY` | Approved tarball SHA-512 SRI |
| `PACKAGE_LOCK_SHA256` | SHA-256 of the reviewed real lockfile |
| `T3CODE_BUILD_PLATFORM` | Reviewed `linux/amd64` or `linux/arm64` |
| `PREPARED_BASES_REVIEWED` | `yes` only after base review |
| `INSTALL_HOOKS_REVIEWED` | `yes` only after dependency-hook review |

The review flags record an operator decision; they are not signature verification
or evidence of native-module compatibility. Installation is unprivileged and
bounded to 900 seconds per npm phase. Installed runtime files are root-owned and
non-writable. The build context allowlist excludes homes, `.env`, host wrappers
and credentials. Never pass private npm configuration or secrets as build args.

After the gates are resolved, from this component directory:

```sh
./t3code-mgr build
# Review the result; explicitly select the returned sha256 image ID for launch.
export T3CODE_IMAGE='sha256:<actual-reviewed-local-image-id>'
```

`build` does not tag over an image, stop a container, or deploy its output. The
wrapper checks base-reference/review gates before Docker uses either base. Direct
`docker build` bypasses that host preflight and is not the supported entry point.
Starting never pulls; externally approved repository-digest images must already
be present in the selected local daemon. A digest identifies bytes, not approval.

## Workstation setup and inputs

Requires Linux, Python 3 (standard library only), Bash, a local Unix-socket Docker
daemon, and Compose v2 with long bind syntax and `create_host_path: false` support.
Run as a non-root operator with a nonzero primary GID and existing Docker access.
Docker access is effectively host-admin authority; the container receives none
of it. Rootless/user-namespace remapping and Docker Desktop are **not accepted**
targets: matching numeric bind ownership must be established separately.

Use a disposable checkout for first acceptance. Supply canonical absolute,
symlink-free paths with no control characters or `$`. State, workspace and shared
agent roots must not overlap. In particular, do not use the entire agents checkout
as `/workspace` if it contains the shared root. Bind access is only the selected
UID/GID; supplementary groups are not inherited. Use local storage with reliable
`flock` and SQLite semantics, not unreviewed NFS/CIFS storage.

`.env.example` is documentation, **not** a sourced shell program. Wrappers ignore
Compose `.env` and ambient `COMPOSE_*` overrides. Export values explicitly:

```sh
# Replace these placeholders with your own narrow, canonical paths.
export T3CODE_STATE_ROOT='/absolute/private/t3code-state'
export T3CODE_AGENT_ROOT='/absolute/shared/agent'
export T3CODE_WORKSPACE='/absolute/disposable/project'
export T3CODE_PROVIDER=none
# Create STATE_ROOT as your operator account: directory mode 0700, correct UID/GID.
# Do not recursively chown or chmod existing state to bypass a refusal.
./t3code-run --port 3773 --cpus 2 --memory 4g "$T3CODE_WORKSPACE"
```

The image variable above is also required. Port defaults to 3773, CPUs to 2 and
memory to 4g; each additional instance needs a free host port. UID/GID are derived
from the operator, not trusted from environment overrides. `T3CODE_WORKSPACE`
defaults to the current directory. `T3CODE_STATE_ROOT` and `T3CODE_AGENT_ROOT` have
no defaults. No directories are silently mounted from a broad host home.

The host state root is a **registry**. Compose receives only the chosen instance's
`home/` as its `T3CODE_STATE_ROOT`, never the registry itself:

```text
<state-root>/                       0700, operator-owned, not mounted
  .lifecycle.lock                  serializes wrapper mutations
  t3code-<uid>-<basename>-<hash>/    identity includes canonical workspace hash
    profile.json                   0600, data only, never sourced
    profile-history/<hash>.json     retained configurations, NOT database backups
    home/                          0700, mounted at /home/t3code
      .server.lock                 held for the server's lifetime
      base/                        userdata, worktrees, caches, secrets, identity
      logs/server.log              private upstream stdout/stderr
```

Initialization uses umask 077, checks managed roots without following links,
refuses unknown conflicts, and never repairs ownership or traverses repository
worktrees. Existing private content is preserved. Do not remove or replace lock
files while any process can be using the state. The locks prevent cooperative
duplicate startup, not a malicious same-UID process or Docker administrator.

## Commands

`./t3code` dispatches management commands below; otherwise it launches a workspace
(`./t3code run ...` explicitly selects launch). Use the exact name printed at launch.
No wildcard, `all`, force-clean, auto-update or service-installer commands exist.

| Command (`./t3code-mgr ...`) | Behavior |
|---|---|
| `list` / `status NAME` | Registry-scoped container state; not readiness |
| `start NAME` | Start retained profile, or create it if container is absent; no implicit replacement |
| `stop NAME` | Stop only the inspected instance, with a 60-second grace period |
| `remove NAME` | Stop/remove only that container; keep state, profile, workspace and network |
| `recreate NAME --ack-stop` | Explicit replacement using reviewed current Compose and optional image/port/CPU/memory overrides |
| `logs NAME` | Last at most 64 KiB / 100 lines of private log, including after exit/removal; no follow |
| `shell NAME` | Non-root operator shell; do not start a second server |
| `pair NAME` | Create a one-time pairing credential in this exact base directory |
| `auth NAME pairing list` / `auth NAME pairing revoke ID` | List/revoke pairing links |
| `auth NAME session list` / `auth NAME session revoke ID` | List/revoke persistent sessions separately |
| `provider NAME status` / `provider NAME login` | Unconfigured status / clear unsupported-login error |

Logs, shell, pairing, auth and provider exec require an operator terminal on
stdin/stdout/stderr. No auth flag passthrough, alternate base directory or
administrative session issuance is exposed. The auth grammar follows researched
source, **not executed-release evidence**. Do not record pairing output in CI,
terminal recordings or shared logs. Revoking a pairing link does not revoke an
already issued session. The log viewer renders terminal control characters as
visible escapes rather than executing upstream terminal escape sequences.

Profiles bind the image, account, mounts, workspace identity and Compose content.
Changed launch inputs fail instead of silently recreating a server. Recovery
stop/remove still work after a Compose edit or missing bind-source directory,
provided the private registry and container ownership/mount identity remain intact.
The manager refuses foreign/mismatched containers rather than adopting them.

## Security, project setup and remaining acceptance

- Host publishing is `127.0.0.1` only; the server binds `0.0.0.0` inside a separate
  per-instance bridge. This is **not an egress allowlist**, and host/Docker admins
  or deliberately attached peers are not excluded by loopback publishing.
- Compose drops capabilities, enables no-new-privileges, uses a read-only image
  filesystem, bounded `/tmp`, PID/CPU/memory limits, and no restart policy. Native
  module/provider compatibility with these settings has not been exercised.
- `/opt/agent` is runtime-mounted read-only, **not** image-baked. No discovery
  mapping is created while provider selection is open. Skills, commands, agents,
  prompts and subagents are not automatically interoperable. A future approved
  provider must define and demonstrate its own discovery roots; no hot reload
  or shared-resource consumption is claimed today.
- Add `/workspace` through supported T3 UI project setup after pairing. Headless
  `serve` deliberately does not auto-import cwd. No workspace `.agents`, `.claude`
  or `t3.json` is created or modified by initialization.
- Current researched T3 defaults new threads to **Full access**. Explicitly choose
  Supervised and prove rejected approvals cannot execute before functional use.
  Disable automatic pull and browser access unless separately approved. Container
  flags are not a substitute for application approval semantics.
- Pairing does not provide HTTPS, firewall policy or WS proxy support. Any access
  beyond workstation loopback needs a separately approved private TLS/tunnel setup,
  WS upgrades, long streaming timeouts, origin/Host/cookie review and blocked bypass.
  No Connect, Tailscale socket or external DevAI network is configured here.
- WS event logging is set to false, but persisted OTLP settings, analytics,
  updates, crash reporting and actual network egress remain unaudited. Do not
  infer privacy or disabled telemetry from an unset variable.
- Upstream output is kept in a private local file because startup may print
  pairing credentials. Docker's bounded local driver captures only wrapper output.
  **Private server-file rotation is not automated**; stop the instance before
  rotating it, retain mode 0600, and apply a restricted retention/disk-space policy.
- Docker health uses a minimal TCP connection only. It creates no session and
  guesses no HTTP route; even `healthy` means socket liveness, not auth, HTTP/WS
  readiness, provider functionality or permission enforcement.

The user-owned later acceptance must cover these boundaries plus native PTY/search,
SIGTERM/provider shutdown, resource discovery, streaming/reconnect, persistence,
disk/permission failures and backup restoration in a disposable local instance.
Do not use live credentials, paid tasks, `team.devai` or remote hosts implicitly.

## Upgrade, failure recovery and rollback

1. Build/review a new content-addressed image **without touching the old instance**.
2. Drain active threads. Stop only `NAME`. Make a consistent, encrypted, restricted
   backup of the complete private home and profile; include SQLite WAL state and
   identity. Never casually copy a live SQLite DB. Also back up valuable workspace
   data separately. No automated backup or restore is provided.
3. Export the reviewed `T3CODE_IMAGE` and, only if intended, `T3CODE_PORT`,
   `T3CODE_CPUS` or `T3CODE_MEMORY`. Clear stale override values. Run
   `./t3code-mgr recreate NAME --ack-stop`. The shared root/workspace/home cannot
   be changed via recreation. Previous profiles are saved by content hash before
   any stop/removal; retries do not overwrite earlier history.
4. If creation/start fails, state and profile history remain, but the old container
   may already be removed. Inspect `status` and private `logs`; correct the cause
   and use `start` for the same profile or explicit recreation for changed inputs.
   A start request is not evidence of successful startup.
5. Roll back only with an approved previous image and compatible state. Stop/remove
   only this instance first. Restore its complete consistent home from the matching
   backup while stopped, preserve ownership, and use an explicitly reviewed Compose
   revision plus prior profile values for recreation. **Never run an older image
   against migrated state without established compatibility.** Profile history is
   recovery metadata, not a substitute for that backup. Restoring auth identity can
   revive sessions: revoke/rotate separately when required.

No rollback, workstation deployment or acceptance was performed in this delivery.
