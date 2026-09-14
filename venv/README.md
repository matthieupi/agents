# Shared VM harness runtime

✅ Source implementation for Pi, OMP, OpenCode and T3. **Not live-deployed or
Docker-build-accepted on this controller.** This leaf extends the existing VM
launcher, not workstation wrappers or component deployment lifecycles.

## Selected Make installation (ordinary account, never login-time builds)

After enrollment deploys the public source and root-owned build/activation policy,
use the shared `agents` execution account in `<agents-source>/venv`. Current Dev/DevAI canonical
enrollment source is `/var/lib/venv-agents/source`; retained native/editable checkouts
are not imported as root. Infrastructure enrollment invokes this same target for an
absent desired image on fresh and completed hosts:

```sh
make -C /var/lib/venv-agents/source/venv pi
# Standalone alternatives: omp / opencode / t3
```

Do **not** use `sudo make`. Make builds only the selected component/dependencies
using the existing Dockerfiles and cached layers, then sends only its immutable
local image ID to the protected root launcher through sudo. Missing maintained
Docker context allowlists fail closed. BuildKit uses the explicit local socket;
no remote builder, prune, implicit latest lookup or all-harness target is added.
OMP/OpenCode on x86 require SSE4.2 on every exposed processor before any Docker
work; OMP remains amd64-only. Pi/T3's Node paths do not inherit the Bun gate.

Each build holds a shared root-owned public build-source lock for exact manifest
verification and the complete Docker source-reading phase, then verifies that same
snapshot before releasing it. Activation happens afterward under the existing
private activation lock; the two locks are never nested. Completed enrollment
reapply takes the source lock exclusively and publishes a complete immutable source
generation before atomically selecting it through the canonical Makefile.

That generation transition keeps an already-running builder on its unchanged
old tree during the first refresh; it does not rely on process inspection or a quiet
timing window. New Make invocations use the lock-aware immutable generation. Direct
`python build.py` is not a supported update interface. Freshness remains warning-only:
source changes emit an explicit warning and update a separate root-owned public
maintenance receipt beside the configured source tree. Enrollment/shared-runtime
seals, authorization, defaults, image IDs and activation records are not rewritten.
Lock, generation and receipt paths derive from the configured source root, and the
stable lock inode is created once rather than replaced. Drift in source artifacts
corresponding to sealed launcher/login controls is warned and retained, never copied
over or falsely resealed.

Warning-only applies to the **old freshness bytes**, not to lock or custody checks.
After validating the new immutable generation, reapply warns about and replaces an
old/drifted dispatcher or malformed old maintenance receipt. A crash after dispatcher
publication is recovered by recognizing the exact dispatcher for the fully verified
generation and completing its receipt under the same source lock. Unsafe ownership,
path structure, lock state, or new-generation integrity still fails closed, and the
role refuses to continue to a build unless the fresh generation was selected.

Build settings are read while the source lock is held and checked byte-for-byte again
before releasing it. The resulting image ID remains governed by the existing image
and activation contracts. The maintenance receipt is diagnostic provenance; it is
not cryptographic image-to-source attestation and is not passed to privileged
activation.

Bootstrap creates no images. Schema 2 uses explicit `image: null` and null initial
CLI/web defaults. First successful activation selects each still-null default only
when that harness owns the corresponding requested interface; additive installs
never change an established default. OMP is CLI-only and T3 is web-only. Provider
files and the shared agents HOME are never copied or deleted by activation.
The `t3` command is only a convenience for its enabled web entry, not a CLI
capability; it refuses application arguments and an unselected web interface.

Activation uses a protected lock, the private `image-install.json` journal, a
candidate policy and atomic installed-policy replacement. Recovery validates that
only the selected image and still-null interface defaults changed; an already
published policy is gateway-finalized rather than rolled back. Failed backend checks
preserve current defaults; failed rollback retains recovery evidence for retry.
Successful first installation also finalizes the gateway before retiring its
image-install journal. A failed
finalization retains the published policy and journal for an idempotent retry;
it never rolls back a committed image.
Installed-ID replacements are refused rather than pretending to support safe
upgrades. Same-ID retry is a no-op after recovery. See `14-runtime-contract.md`
in the agent-harness-reset feature handoff for
exact enrollment inputs and gateway phase obligations. **Gateway phase wiring is
required before activation can succeed; no live readiness is implied here.**

## Controller-only default selection

The protected launcher now accepts `select-default pi` or `select-default opencode`
as **controller root**, only for an already-installed, healthy schema-2 harness.
This is not granted by enrolled-user sudoers and never builds, replaces an image,
starts/stops a container, changes service enablement, or edits credentials/HOME.
The existing ordinary-account Make/image activation interface is unchanged.

Selection holds the existing activation lock, verifies owned routing and the full
gateway auth checks, then publishes gateway routing and the CLI/web policy defaults.
The protected `select-default-pending.json` journal binds exact previous/candidate
policies. Failure before policy publication restores the old routes without stopping
either service. Publication is the commit point: interrupted finalization preserves
the new default. Repeating the command recovers the journal before applying the
requested selection; even an unchanged selection checks backend health.
Foreign site/auth/policy drift is refused, not repaired. Failed recovery retains its
journal and blocks image activation and enrollment maintenance. Candidate cleanup
is durable before the journal is retired.

Infrastructure reapply continuously enforces the first ordered
`venv_agents.targets.<host>.harnesses` entry as the canonical routing default; it must be Pi or
OpenCode because the routing default owns both CLI and web interfaces. Shared policies
retain their exact sealed adapter, grants and image receipts; selection uses the
installed-policy status path, not replacement-candidate authorization. Normal
reapply recovers a pending selection through the sealed launcher while lending only
the exact existing activation lock. The selector cannot accept another lock inode.

Matching maintained controls are promoted by the enrollment owner through its
existing journal and overlay seal; do not copy over sealed files manually. The
original bootstrap record is preserved. This is not an image/source upgrade API:
installed replacement refusal, CPU gates and shared image evidence remain in force.

An optional `web.default_hostname` separates the default URL from `base_hostname`,
which remains the named-harness and certificate parent. The gateway translates only
the exact Pi alias Origin/Host to the existing upstream identity, keeping installed
Pi container environment/contract bytes unchanged. Foreign Origins are not rewritten.
Hostname promotion preserves TLS scope and uses exact-file rollback plus TLS/auth
acceptance. Shared hostname changes require a reviewed adapter version supporting
the hostname seal. No live deployment or acceptance is implied by these source changes.

## Public commands

```text
venv-agents pi|omp|opencode [-- <app arguments>]
venv-agents pi|opencode|t3 --web
venv-agents pi|opencode|t3 --web-status
venv-agents pi|opencode|t3 --web-stop
venv-agents t3                 # honest managed web entry, not a conversational CLI
venv-agents default [--web]    # dynamic default for the shared execution account
venv-agents validate           # public JSON stdin; no mutation
venv-agents validate-runtime   # public JSON stdin; current non-root account checks
```

`--args` also introduces app arguments. Arguments never become Docker options.
Web arguments are fixed; OMP has no web adapter. OpenCode's `serve`/`web` app
commands cannot bypass the managed web entry through the CLI interface. PATH
aliases/account enrollment belong to infrastructure, not this runtime.

## Policy and state ownership

The launcher loads root-owned `/etc/venv-agents/policy.json`, validates protected
ancestors, exact account UID/GID, physical shared binds, private state, immutable
images, approved socket and existing memory/CPU/PID/cgroup limits. Image/network
enrollment and aggregate resource-slice installation remain infrastructure-owned.
No implicit pull/build, provider login, token copy, historical default, or repair.

`web_ready: true` is accepted only as part of a valid root-owned policy containing
the explicit `web.default_harness` and `web.base_hostname`. Every selected harness
points to the same explicit execution account, and policy `accounts` contains only
that owner.
Enrollment sets readiness **after** owned proxy/auth preparation; each activation
separately gates new backend/API/WebSocket acceptance. Only schema 2 is accepted.
Runtime does not infer authentication from `/`, read
secret env files, or claim that a boolean verifies a gateway. Public policy carries
no provider/web credentials.

Every selected harness uses the shared execution account's physical NSS HOME at
the same absolute path inside its containers. Harness lifecycle locks live under
one separate private state root. HOME identity must match the shared UID/GID and
cannot overlap workspace, resources or lifecycle state. No application state or
provider tokens are copied.

Resources are read-only at the original absolute path, also supplied as
`VENV_AGENT_RESOURCES`. Preserve the existing Pi AGENTS.md symlink's target by
enrolling that same resource directory. The adapter refuses a broken legacy
AGENTS.md link instead of replacing it. Workspace is a narrow, physical same-path
bind; neither a host checkout ancestor nor a broad HOME mount is added. When the
controller policy includes the configuration-owned `worktree` path, it is a
separate writable identical-path bind and part of web-container drift detection.
Its absence adds no fallback or inferred mount.

## Managed web lifecycle

```text
root-owned policy + current account
    -> inspect unique VM/harness name
       -> owned existing instance: validate identity/config, report status/URL
       -> absent: validate own state -> brief startup lock
          -> Docker atomic create -> detached start -> running-state check
             -> failure: remove only the newly returned container ID
```

Names are `venv-agents-<environment>.<inventory-host>-<harness>-web`. Dot encodes
the target separator without collapsing distinct VM names. Labels bind target,
harness, mode, account, UID/GID and configuration fingerprint. Existing containers
must also match actual image/user/argv, environment, resource limits, mounts and
loopback publication. Foreign or drifted containers are never adopted/restarted.

New web creation is restricted to the sole shared execution account recorded in
`harnesses.<name>.account`. Concurrent create losers inspect the winner without
starting/removing it. A `created` state is
reported as such, not falsely called application-ready. Exited instances require
explicit owner stop/removal before another start.

Stop sends a 30-second Docker stop, then removes the exact inspected ID; HOME
survives. Status/stop remain available after readiness is revoked. CLI holds
`.session.lock`; web holds a separate `.web-start.lock` only through startup.
Image resource initialization has a brief lock, never a session-duration web
lock. Pi CLI and Pi web can therefore coexist. Application-level concurrent state
semantics still need canary acceptance; the launcher does not rewrite app stores.

## VM image adapters and auth boundary

- **Pi:** existing paired component release build. Numeric UID/HOME works through
  container-private libnss-wrapper files; activation does not migrate native state.
  Web argv is `pi-web --hostname 0.0.0.0 --port <port> --no-open`.
- **OMP:** existing component application image, VM-only resource references to
  its native `.omp/agent` layout. The workstation init's fixed passwd identity and
  writable `/opt/agent` requirements are deliberately not used. No OMP web claim.
- **OpenCode:** VM build invokes its maintained native installer at an exact
  supplied version, not the workstation image's `@latest`. Web uses `opencode web
  --hostname 0.0.0.0 --port <port>`; updates are disabled by the existing env knob.
  `entry.py` owns agent registration and the approved KDCO plugin publication for future startup and the
  infrastructure role's existing-installation reapply. It projects only the public
  canonical agent map, preserving exact case, `all`/`subagent` modes, temperature,
  description and explicit per-agent permissions. `system/` alone is not native
  OpenCode agent discovery. No global provider/model/default/permission is copied.
  The role supplies `<resources>/opencode-agents.json`; startup atomically seeds
  private `.config/opencode/config.json` only when absent. v1.18.29 loads this
  before `opencode.json` and `opencode.jsonc`. Existing inline agent overrides are
  excluded wholesale. Existing global policy, discovery directories, legacy or
  ambiguous configuration cause a reported skip rather than a permissions merge.
  The agent seed is first-write-only: existing configs/files are never overwritten.
  Separately, approved KDCO sources/dependencies are linked from shared
  `<resources>/opencode-plugins` (or installed image defaults on fresh image startup)
  into private `kdco/` and three `plugins/kdco-*.ts` entrypoints. This plugin scope
  is active even when private policy prevents agent seeding; no policy is rewritten.
  Conflicting managed names are preserved and rejected. Shared npm installation
  is serialized and checks actual installed-tree plus manifest/lock fingerprints
  as resource owner during enrollment; unchanged graphs skip npm. Genuine updates
  require idle sessions and failed in-place npm may leave partial dependencies.
  Image npm installation runs at build,
  not during startup. See the [KDCO risks and provenance](../opencode/.opencode/config/kdco/README.md).
  Restart the selected OpenCode session when idle after seeding; no hot reload or
  automatic CLI/web restart is claimed. Existing images need only the maintained
  Ansible reapply, not a rebuild; defaults and sealed source snapshots stay intact.
- **T3:** existing pinned Dockerfile, lock, offline native hooks and final image
  smoke unchanged. VM startup calls its existing private initializer, keeps its
  `/home/t3code` server lock/logging and supplies the actual same-path workspace to
  `t3 serve`. No fake T3 CLI, provider setup or generic skills-discovery claim.

The common overlay supplies Python, libnss-wrapper and an explicitly pinned Docker
CLI binary. It never executes host-editable startup code as root or changes host
passwd entries. Docker socket/group access is intentionally **VM-root-equivalent**;
accounts and containers are not security boundaries. Resource budgets and dropped
capabilities are operational conventions, bypassable by a Docker-authorized agent.

Web publishes only to `127.0.0.1` on the VM, with the existing dedicated bridge.
Pi/OpenCode's adapter configures no native web password: the owned gateway must
protect all routes and firewall direct bridge access. T3 additionally retains its
native pairing/session authentication; gateway authentication is an outer gate,
not a replacement. Its API/WS header/cookie/Origin composition needs actual pinned
release acceptance. No TLS disabling. See the integration contract for exact
build commands, image-ID capture and cross-role handoff.

## Restricted SSH aliases

Selected CLI-capable harness names are distinct locked, home-less SSH aliases.
`login_shell.py` accepts only an interactive SSH session with no original command,
loads the physical root-owned schema-2 policy and executes the exact alias harness
as `agents` through a finite sudoers rule. Arbitrary commands, SFTP, forwarding,
tunnels, user rc and direct `agents` SSH are denied. Alias UIDs remain distinct and
receive neither Docker membership nor runtime policy ownership. Sysops remains a
separate administrative shell account.

## 🧪 Verification and remaining acceptance

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s services/agents/venv/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_venv_agents*.py' -v
```

New tests exercise actual account-local files, state preservation and flock plus
Docker argv/API lifecycle fixtures. Existing tests exercise real Bash/PTY,
OpenSSH `-G`, structured transport and Ansible pre-mutation failure paths.
On 2026-09-08: **60 source tests passed** (29 on-demand regressions plus 31 existing
runtime/adapter tests); **111 infrastructure tests ran, 108 passed and 3 existing
real-Nginx tests skipped**. Activation tests simulate root identity and gateway/
Docker effects; policy files, atomic publication, recovery journals and locks are
real. These counts do not establish that peer on-demand enrollment wiring is complete.

No Docker binary exists here: all image builds, native startup, gateway/API/WS,
sshd/SCP/SFTP protocol and resource enforcement acceptance remain a later scoped
canary. A running-container observation is not auth, provider or model acceptance.
