# Shared VM harness runtime

✅ Source implementation for Pi, OMP, OpenCode and T3. **Not live-deployed or
enrolled-image accepted.** OpenCode V2 has separate disposable-image verification.
This leaf extends the existing VM
launcher, not workstation wrappers or component deployment lifecycles.

## Selected Make installation (ordinary account, never login-time builds)

After enrollment deploys the public source and root-owned build/activation policy,
use the normal SSH account in `<agents-source>/venv`. Current Dev/DevAI canonical
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
private activation lock; the two locks are never nested. Completed install-mode
reapply takes the source lock exclusively and publishes a complete immutable source
generation before atomically selecting it through the canonical Makefile.

That generation transition keeps an already-running legacy builder on its unchanged
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

Bootstrap creates no images. Schema 2 uses explicit `image: null` and initial
`default_harness: native-pi` (null on a genuinely fresh host). Native CLI uses the
existing installed binary as the non-root caller, not a bootstrap/build wrapper.
Native web remains until new backend checks pass. First successful `make` selects
the initial CLI/web default; additive installs never change it. OMP-first means
**no web default**, not Pi fallback. Bare T3 remains an honest managed-web URL.
Provider files, original homes and native unit/environment recovery data survive.

Activation uses a protected lock, durable pending journal, candidate policy and
atomic installed-policy replacement. Failed backend checks preserve native/current
defaults; failed rollback retains recovery evidence for retry. Installed-ID changes
are refused rather than pretending to support safe upgrades. Same-ID retry is a
no-op. See `14-runtime-contract.md` in the agent-harness-reset feature handoff for
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

Infrastructure install-mode reapply continuously enforces canonical
`hosts.<host>.default_harness` (omitted=`pi`, allowed=`pi|opencode`). Shared policies
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
- **OpenCode V2 only:** VM build invokes the maintained native `install_runtime`
  directly, resolving `@opencode/cli@latest`. No `opencode_version` setting or
  `OPENCODE_VERSION` build argument is required or consumed. Each selected build
  invalidates only the OpenCode install layer so cached `latest` is not mistaken
  for a new registry resolution. The install receipt records the resolved version;
  metadata lives under `.runtime/node_modules/@opencode/cli`. Image activation's
  immutable-ID/replacement rules remain unchanged.
  Managed web runs `opencode serve --hostname 0.0.0.0 --port <port>`.
  Explicit remote clients use `opencode --server <URL>` (not V1 `attach`).
  `entry.py` first-write seeds private `.config/opencode/opencode.json` from the
  canonical native V2 document: `agents`, `providers`, ordered `permissions`,
  models, request settings and public defaults are retained. Prompt references
  resolve to the original same-path resources. Literal public credential values
  are refused; provider keys remain `{env:...}` references, never copied tokens.
  The role may publish that **whole V2 public document** at the retained interface
  `<resources>/opencode-agents.json`; fresh images fall back to image defaults.
  Old agent-only manifests are rejected, not translated. Publish/check/ACL helper
  Python signatures and command names remain stable, but now consume V2 documents.
  The ACL plan includes each V2 `system` prompt (model-only overrides need no file).
  Optional `<resources>/opencode-config` supplies canonical `cli.json`,
  `plugins/first-prompt-title.js`, `plugins/background-subagents.js`,
  `tui-plugins/session-title.mjs` and the complete `tui-plugins/session-title/`
  package; otherwise image assets are used. Both standalone server plugins are
  explicitly registered by default in freshly seeded server config; title's CLI
  registration remains in canonical `cli.json`. Native background subagents are
  the default unless a call explicitly sets `background: false`; no external
  package/dependency installation is required. Existing private V1/V2 configurations
  receive the same required managed registrations while retaining unrelated plugins,
  options and preferences; upstream V2 owns legacy syntax compatibility. No global
  public policy/provider merge or bespoke whole-schema converter is introduced.
  Known prior managed defaults/assets migrate in the same HOME as documented below.
  No KDCO dependency install or publisher runs. Unknown modified assets fail without
  replacement; private credentials/session databases are not migration inputs.
  Restart OpenCode after
  initialization; no hot reload or live migration is claimed. Existing VM images
  need a reviewed rebuild/replacement, not merely resource reapply.

  **Source closure:** the VM component allowlist includes only the native installer,
  public V2 config, standalone server plugins, CLI/title package and readiness helper.
  The final VM overlay adds `entry.py`/`t3-start.sh` and public migration evidence
  `opencode_legacy.json`. Prompt bodies, commands and
  skills are deliberately **not** duplicated into image defaults: enrollment owns
  the read-only same-path resource tree with `system/`, `gsd/`, `commands/`, and
  `skills/`. Every canonical `{file:./system/...}` / `{file:./gsd/...}` reference
  must resolve there. OpenCode-specific canonical system personas live under
  `opencode/.opencode/config/system`; GSD source lives under `agent/gsd` (the
  canonical config's GSD link targets the runtime resource location). Portable
  `agent/system` is not assumed byte-identical to OpenCode's personas. Enrollment
  must supply its reviewed prompt bytes; VM startup never replaces shared resources.
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
Pi's adapter configures no native web password: the owned gateway must protect
all routes and firewall direct bridge access. T3 additionally retains its
native pairing/session authentication; gateway authentication is an outer gate,
not a replacement. Its API/WS header/cookie/Origin composition needs actual pinned
release acceptance. No TLS disabling. See the integration contract for exact
build commands, image-ID capture and cross-role handoff.

### OpenCode V2 backend secret and gateway handoff

```text
browser/client -> existing TLS + gateway auth -> loopback published backend
                                               Basic opencode:<backend secret>
                                               GET /api/info for readiness
```

Infrastructure must provision `<account OpenCode HOME>/.config/opencode/server-password`
as a physical, single-link, UID/GID-owned `0600` file, maximum 4096 bytes; one
trailing newline is allowed. This is a **separate backend secret**, not the gateway
user password or a provider token. Startup reads it into `OPENCODE_PASSWORD` only
inside the container before `serve` (also for explicit `--server` clients). Missing
or unsafe secrets fail closed. No password is generated or printed, baked into an
image, placed in public policy, or passed as a Docker environment/argv value.
The existing private HOME bind supplies it; no secret mount or public policy field
is introduced. Local standalone CLI does not require the backend password.

The infrastructure-owned gateway helper is outside `venv/` and must be updated
before activation: preserve existing outer auth for **all** routes and WebSockets,
replace client Authorization upstream with Basic `opencode:<backend secret>`,
retain streaming/WS forwarding and localhost publication, and verify authenticated
`GET /api/info` returning V2 `version` and integer `pid`. Test missing/wrong backend
auth returns `401`; never use `/global/health` or a root-page `200` as acceptance.
Do not log the injected header. Browser/frontend gateway auth remains independent.
`/opt/opencode-health.py` runs this same authenticated info probe inside the VM
image using `HOME` and `VENV_AGENT_PORT`, without credentials in argv/diagnostics.
It does not replace the gateway's end-to-end API/WS/auth checks.

Caller changes required: stop pinning OpenCode settings, publish the complete V2
public config and plugin/CLI assets (not KDCO), provision/share the backend secret with
the protected gateway, and use the V2 authenticated readiness path. No gateway or
infrastructure deployment changes are included in this leaf.

### Existing OpenCode HOME migration

Stop old sessions/services while idle before applying the maintained initializer;
it does not stop/restart them or claim hot migration. The brief `.vm-init.lock`
serializes initialization, not active application state writers. No alternate HOME,
V1 archive, backup tree, credential copy or recursive package deletion is created.

| Existing content | In-place behavior |
| --- | --- |
| Prior managed agent-only `config.json` | Recognize exact reviewed per-agent fingerprints, including valid subsets; move only those current public V2 defaults into native `opencode.json`/JSONC, exclude all privately overridden names, then retire the recognized old seed. Never add global provider/policy defaults to an existing HOME. |
| Lone private `config.json` | V2 does not load this old VM filename. Move its complete document to `opencode.json`, retaining settings and letting upstream normalize its syntax. |
| Private `opencode.json` / `opencode.jsonc` | Preserve settings; reconcile required plugin paths, remove only recognized retired wrapper registrations, retain unrelated entries/options. Existing legacy syntax is not a rejection condition. |
| Private agent/discovery directories without a config | Leave their content to upstream discovery; create managed registrations only, not global public policy/provider defaults. |
| Unknown private old + native configs together | Refuse to guess at policy precedence; preserve both for explicit reconciliation. An exact interrupted filename-move publication is recoverable/idempotent. |
| Regular title assets matching historical or current canonical bytes | Replace per-file with canonical links. Unknown edited files/links are retained and refused. |
| KDCO wrappers/package links | Unlink only the exact historical resource/image symlink targets, or exact historical wrapper re-export bytes. Never follow/delete a shared package or remove unknown private content. |
| Private CLI settings | Retain preferences/unrelated plugins and ensure managed title registration. |

The original VM seeder wrote only `$schema` + `agent`, with absolute same-path
prompt references, and could exclude private inline agent names. Recognition is
not a whole-canonical-config digest: `opencode_legacy.json` pins reviewed agent
and title fingerprints from commit `c8567a4f48a3b86a807aec28b474cca7b7bbb16c`.
Tests run the immutable historical projector for a valid two-agent subset and use
the actual historical title/wrapper bytes. Test controllers need that Git history;
disposable images receive only those public fixture bytes via stdin.

Deploy `opencode_legacy.json` next to any separately deployed `entry.py`; the VM
image already includes it. Evidence is read only by OpenCode migration, not other
harness startup. Public resources still require the full current V2 contract.
Config updates retain semantic settings and existing modes, use atomic publication
and content-drift checks, and never log private documents. Edited JSONC documents
are serialized as JSON (comments/formatting are not retained). Multi-file migration
is idempotent/retryable, not a transaction over application databases or concurrent
user edits. Unknown conflicts require explicit review, not forced cleanup.

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

V2 focused checks (from this repository root):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s venv/tests -p 'test_opencode_v2.py' -v
# Opt-in: a disposable VM-overlay image, no host state/resource/socket mounts:
VENV_OPENCODE_TEST_IMAGE=<disposable-image> PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s venv/tests -p 'test_opencode_v2.py' -v
```

Disposable OpenCode component/VM builds and mount-free startup can be checked
without enrollment or activation. Gateway/API/WS end-to-end auth, provider/model
calls, sshd/SCP/SFTP and resource enforcement still require a scoped canary.
A running-container observation is not gateway, provider or model acceptance.

V2 verification on this controller: maintained direct native installer and VM
overlay built successfully, resolving `@opencode/cli@latest` to `2.0.32`. The
mount-free, network-disabled disposable acceptance test passed for numeric non-root
startup, canonical seeding, both standalone plugins reporting native `active` status,
background-default/foreground-override hooks, exact canonical asset fingerprints,
all canonical prompt texts loaded through `/api/agent`, authenticated `/api/info`,
missing and wrong-password `401`, the private-file readiness helper, and no password
in captured server output. These checks made no provider/model calls. Builds used
the local legacy Docker builder and a disposable Node base, not the enrolled
BuildKit/pinned-base activation flow. The OMP build fixture now supplies a valid
source record/settings/hash/lock and exercises real snapshot verification, with
simulated root-custody metadata only. A source-drift regression verifies build and
activation are blocked. No production source-snapshot checks were weakened.
The full venv suite includes fresh-HOME and actual prior-release-HOME disposable
acceptance. The latter verifies same-HOME migration, active managed/unrelated
plugins, upstream loading of retained private V1 policy/agent overrides, and
preserved credential/database fixture bytes; no provider/model request is made.
**84 tests passed, no failures or skips**, with the rebuilt disposable VM overlay
and both fresh/prior-release HOME smoke tests enabled.
