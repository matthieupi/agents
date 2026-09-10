# Shared VM harness runtime

✅ Source implementation for Pi, OMP, OpenCode and T3. **Not live-deployed or
Docker-build-accepted on this controller.** This leaf extends the existing VM
launcher, not workstation wrappers or component deployment lifecycles.

## SSH installation (on demand, not at bootstrap/login)

After enrollment deploys the public source and root-owned build/activation policy,
use the normal SSH account in `<agents-source>/venv`. For the existing DevAI native
source location this is **`/srv/agents/venv`** (enrollment must retain/project the
canonical `standalone_agents_repo`, not create a second source tree):

```sh
cd /srv/agents/venv
make pi                 # or: make omp / make opencode / make t3
```

Do **not** use `sudo make`. Make builds only the selected component/dependencies
using the existing Dockerfiles and cached layers, then sends only its immutable
local image ID to the protected root launcher through sudo. Missing maintained
Docker context allowlists fail closed. BuildKit uses the explicit local socket;
no remote builder, prune, implicit latest lookup or all-harness target is added.
OMP/OpenCode on x86 require SSE4.2 on every exposed processor before any Docker
work; OMP remains amd64-only. Pi/T3's Node paths do not inherit the Bun gate.

Bootstrap creates no images. Schema 2 uses explicit `image: null` and initial
`default_harness: native-pi` (null on a genuinely fresh host). Native CLI uses the
existing installed binary as the non-root caller, not a bootstrap/build wrapper.
Native web remains until new backend checks pass. First successful `make` selects
the lasting CLI/web default; additive installs never change it. OMP-first means
**no web default**, not Pi fallback. Bare T3 remains an honest managed-web URL.
Provider files, original homes and native unit/environment recovery data survive.

Activation uses a protected lock, durable pending journal, candidate policy and
atomic installed-policy replacement. Failed backend checks preserve native/current
defaults; failed rollback retains recovery evidence for retry. Installed-ID changes
are refused rather than pretending to support safe upgrades. Same-ID retry is a
no-op. See `14-runtime-contract.md` in the agent-harness-reset feature handoff for
exact enrollment inputs and gateway phase obligations. **Gateway phase wiring is
required before activation can succeed; no live readiness is implied here.**

## Public commands

```text
venv-agents pi|omp|opencode [-- <app arguments>]
venv-agents pi|opencode|t3 --web
venv-agents pi|opencode|t3 --web-status
venv-agents pi|opencode|t3 --web-stop
venv-agents t3                 # honest managed web entry, not a conversational CLI
venv-agents default [--web]    # dynamic default for original/default SSH account
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
No implicit pull/build, provider login, token copy or repair. Native is an explicit
initial default only, never a fallback for an uninstalled/broken selected harness.

`web_ready: true` is accepted only as part of a valid root-owned policy containing
the explicit `web.default_harness`, enrolled `web.default_account`, and
`web.base_hostname`. Enrollment sets it **after** owned proxy/auth preparation;
each activation separately gates new backend/API/WebSocket acceptance. Schema 1
remains readable for existing all-installed policies, but cannot activate images.
Runtime does not infer authentication from `/`, read
secret env files, or claim that a boolean verifies a gateway. Public policy carries
no provider/web credentials.

Each account normally uses `<state>/<harness>/home`. Optional `native_pi_home`
must equal the account's physical NSS HOME and match its UID/GID, with safe modes
and ancestors. Only Pi mounts that original HOME at the original absolute path;
no application state or provider tokens are copied. Native HOME, state and shared
binds cannot overlap. No account HOME or its ancestor is a shared bind.

Resources are read-only at the original absolute path, also supplied as
`VENV_AGENT_RESOURCES`. Preserve the existing Pi AGENTS.md symlink's target by
enrolling that same resource directory. The adapter refuses a broken legacy
AGENTS.md link instead of replacing it. Workspace is a narrow, physical same-path
bind; neither a host checkout ancestor nor a broad HOME mount is added.

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

An existing valid instance owned by another enrolled account can report its URL,
but the caller cannot stop it, replace it or initialize its private state. New
Pi and selected-default web creation is restricted to `web.default_account`. Concurrent create
losers inspect the winner without starting/removing it. A `created` state is
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
  container-private libnss-wrapper files; existing native state is preserved.
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

## SSH behavior preserved

`login_shell.py` and `transport.py` are unchanged. Arbitrary SSH commands use
`bash --noprofile --norc -c` with original bytes/status; forced TTY does not turn a
command into autoentry. Infra's root-owned profile handles interactive login once,
then returns to the normal shell. Enrollment must retire legacy hooks to avoid a
second autoentry loop. Sysops remains an ordinary shell account.

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
