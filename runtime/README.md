# Opt-in harness runtime — offline implementation

The OpenCode recipe includes the same [enabled KDCO plugins](../opencode/.opencode/config/kdco/README.md)
as CPU/GPU/native/VM paths. Sources and locked dependencies are baked under
`/opt/opencode-defaults`; startup publishes only managed links into private HOME.
The source, entrypoints, publication helper and dependency lock are bound into the
existing source hash/build context/image receipt. Normal OpenCode startup invokes
the factories and hooks; installation does not. No extra sockets or permissions.

✅ Workstation installation, explicit protected VM activation delegation, five image
recipes and foreground startup readiness have offline implementations/tests.
Protected VM enrollment/control upgrades and gateway replacement/staging/recovery
also exist; see [the protected VM contract](../venv/README.shared.md).
**This is not a deployment-ready or runtime-accepted MVP:** no image has been built
or accepted in this workstream, no target was enabled, and the remaining gaps below
still apply. The historical installer-delegation warning in the VM handoff is now
superseded by the interface documented here.

This opt-in interface does not replace existing workstation wrappers, direct
run/mgr commands, native lifecycle, Compose files, state, links or defaults.
The separately approved KDCO plugin work extends the legacy OpenCode image/native
installers too; `opencode .` and `opencode --web` still use the production path.

## Explicit component interface

The following are the implemented interfaces, **not a record of executed builds**.
Use an ordinary account; installer and launcher reject root/sudo invocation.

```sh
make -C runtime update HARNESS=opencode
# Resolve compatible stable inputs, refresh exact base, generate lock, build.
# Prints local sha256 image ID; does NOT activate it.

make -C runtime build HARNESS=opencode
# Requires an existing exact resolution with matching catalog/public sources.

make -C runtime activate HARNESS=opencode IMAGE=sha256:<64-lowercase-hex>
# Default scope: publish a workstation new-path selection for future launches.

make -C runtime activate HARNESS=opencode IMAGE=sha256:<64-lowercase-hex> \
  SCOPE=vm VM_CONFIG=/etc/venv-agents/build.json TARGET=<environment>:<host>
# Explicit VM selection: delegates only to the deployed protected launcher.
# VM_CONFIG is the existing configured paths.build_settings, not a new file to create.

python3 -B runtime/runtime.py run opencode --workspace . -- --help
python3 -B runtime/runtime.py run opencode --workspace . --web --port 4096
```

No schedule, login hook, watcher, automatic activation, image pruning or legacy
dispatcher redirection is installed. Explicit VM activation may replace a selected
image only through the reviewed protected transaction. Workstation activation only
selects future launches. Make exports selectors as data, never shell source.

| Harness | Catalog modes | Platforms | Current evidence |
|---|---|---|---|
| Pi | CLI, web | amd64, arm64 | Recipe/argv tests; no new-path runtime acceptance |
| OMP | CLI only | amd64, every CPU must have SSE4.2 | Recipe/argv tests; Bun npm packaging not built |
| OpenCode | CLI, web | amd64, arm64 | Recipe/argv tests; no new-path runtime acceptance |
| T3 | Web only | amd64, arm64 | Startup lock/private logs; actual pairing/auth not accepted |
| Claude | Workstation CLI only | amd64, arm64 | Recipe only; release range needs independent review |

Native host/platform matching is mandatory; no implicit emulation. GPU and
`--privileged` requests are rejected. There is no Claude VM enrollment.

## Resolution and receipts

`harnesses.json` owns package sources, compatible half-open release ranges and image
recipes. Pi, OMP, OpenCode and T3 lower bounds reference existing repository
versions, **not fresh upstream compatibility verification**. Claude's major range
is provisional. Do not infer compatibility from version ordering alone.

At explicit `update`:

1. Select the newest non-prerelease package releases inside each catalog range.
2. Independently resolve Node and its per-platform external image digest; retain
   the multi-platform index digest separately. Resolve Bun as OMP's own package.
3. Record the current UTC-day Debian snapshot and InRelease SHA256 evidence.
   Unavailable metadata fails; no fallback to floating package sources.
4. Generate npm v3 lock in a numeric-user container with lifecycle scripts off.
   All direct and transitive packages require registry URLs and SHA512 integrity.
5. Build only the chosen harness in a freshly created allowlisted context using
   `--no-cache`, a digest base and `--pull=false`. Downloads and scripts are split:
   `npm ci --ignore-scripts`, then non-root `npm rebuild --offline` with BuildKit
   `--network=none`. A hook that needs an unrecorded download must fail.
6. Inspect the resulting exact local image ID/platform/labels and publish a
    private receipt. No activation follows the build.

### OpenCode plugin provenance

`install.py` uses one explicit source-to-context map for hashing and copying.
OpenCode adds `../opencode/.opencode/config/kdco/` public files, three static
`plugins/kdco-*.ts` entrypoints and `scripts/publish-plugins.mjs` to
`resolution.source.public_files`. The public file list in `upstream.json` supplies
the finite vendored source closure; every actual byte (including the documented
security patch) is hashed. Other harnesses retain their four-input source closure.
Builds reject missing/symlinked inputs, stale resolutions and copied bytes that
changed after validation. The copied plugin lock must satisfy the existing npm v3,
registry-only, SHA512 integrity rules and match its exact package manifest.

Ordinary `npm ci --ignore-scripts` installs as `node` into the separate nested
package, not the selected harness graph or private config-root manifest. No source
downloads or inactive receipts remain. The harness's own non-root offline rebuild
is unchanged. Sources and dependencies remain visible outside the HOME bind;
startup links them into discovery even without optional shared resources. When VM
resources contain the approved plugin projection, startup uses that shared source.
Private provider/global policy fields and unrelated plugins remain untouched.

Old OpenCode resolutions lack these inputs and cannot build with the new source;
when a build is separately authorized, run the existing explicit
`make -C runtime update HARNESS=opencode`. Do not edit receipts or reuse old image
approvals. Receipt schema and protected VM projection remain unchanged; their
source/resolution digests change normally. Existing selected images are not
rewritten or automatically replaced. No builds or activation were run for this
integration; image/platform acceptance remains separate from offline tests.

Each image retains its lock and `os-packages.tsv`. Debian snapshot apt sources
keep archive signature checking; `Check-Valid-Until: no` permits later replay of
the recorded historical snapshot rather than treating it as current freshness.
APT metadata and base availability, BuildKit support, and offline package-hook
behavior remain untested with real images. InRelease hashes are receipt evidence;
APT verifies signatures, not the receipt's recorded InRelease hash itself.

State is under `~/.local/state/agents-runtime`, private mode 0700, receipts 0600:

- `<harness>-resolution.json`: exact package lock, catalog/source digests, base
  platform/index digests, Debian snapshot and resolution timestamp.
- `<harness>-<image-hex>.json`: immutable-ID build receipt, build timestamp and
  startup contract version. Earlier receipts are retained.
- `<harness>-selected.json`: explicit workstation selection, never a legacy default.
- `agents-runtime-<...>.json`: launch contract, granted authority and source evidence.

Receipts are ordinary-account records, **not root trust evidence**. Do not pass
them to a privileged service as authorization. Build/host Docker access remains
host-root-equivalent with the current rootful local endpoint.

### Protected VM delegation

The equivalent direct installer command is:

```sh
python3 -B runtime/install.py activate opencode sha256:<64-lowercase-hex> \
  --scope vm --vm-config /etc/venv-agents/build.json --target <environment>:<host>
```

Use the actual canonical build-settings path and target. No machine detection or
ambient variable changes the default workstation scope. Direct installer VM options
on build/update or workstation activation are refused; Make passes its activation
selectors only to `activate`. The installer requires:

- Physical, single-link, root-owned config/launcher/policy files; every ancestor
  must be root-owned and non-group/world-writable. Symlinks and set-ID modes are refused.
- The existing config's `command`, native `platform` and local socket matching the
  maintained builder. Policy is the protected launcher's fixed
  `/etc/venv-agents/policy.json`, not a caller-selectable alternate policy.
- Explicit target equality with both policy and shared-runtime opt-in; the actual
  ordinary UID/GID and passwd identity must match an enrolled account. Ambient
  `USER`, `SUDO_USER`, Docker contexts and provider variables confer no authority.
- A private matching local build receipt whose harness/platform/contract/resolution
  digest/source digest/revision exactly match the reviewed protected image projection.
  Old source revisions remain eligible: activation does not require today's checkout
  to match an earlier build. Claude VM activation remains unsupported.

```text
private build receipt + root-owned config/policy -> ordinary-user preflight
    -> /usr/bin/sudo -n -- <configured-command> activate <harness> <local-ID>
    -> protected caller/target/seal/image/transition checks -> transaction
```

Only the finite harness/ID operation crosses sudo, with a minimal environment. No
receipt, config path, source path, policy, target override or extra grants are passed
to root. The launcher independently validates authorization and image identity;
these local preflight checks do not replace it. Launcher exit status is propagated,
and no workstation selection is written, even after a successful VM activation.
There is no installer timeout that kills an in-flight protected recovery transaction.
On interrupted activation use the protected recovery flow; do not delete journals.

## Privileges, HOME and source

Default run: numeric caller UID/GID, dropped capabilities, no-new-privileges,
read-only root filesystem, bounded temporary filesystem, memory/swap/CPU/PID limits,
bridge network, loopback-only web port and **no container Docker socket/group/env**.
The client endpoint is explicitly local; ambient Docker contexts are not forwarded.
The image provides NSS-wrapper support for arbitrary numeric non-root owners.

Independent options:

| Option | Effect |
|---|---|
| `--docker-socket` | Bind the validated selected local socket; add its exact group and `DOCKER_HOST`. This grants host-root-equivalent authority with rootful Docker. Docker CLI is not included by this implementation. |
| `--cap-add NET_BIND_SERVICE` | Add only the currently allowlisted capability; no SYS_ADMIN or catch-all grant. |
| `--root-user` | Container root with baked startup only; no mutable resource/startup binds. Workspace is read-only; HOME is disposable tmpfs, not existing private state. |
| `--resources <public-dir>` | Explicit public skills/commands/system subtree, mounted read-only at `/opt/agent`. Operator owns exposure review; never pass a checkout containing private state. |
| `--live-source <public-bundle>` | Physical ordinary-owned directory containing exactly `entry.py` and `harnesses.json`, bound at its identical host/container path. No broad checkout bind. |
| `--checkout-write` | Independently permit writes to that live public startup bundle; invalid in baked mode. |
| `--state-slot <name>` | Separate private HOME, useful for a deliberately fresh image/state test. No credential copying or state migration. |

The default source is the image's baked startup. Live bundles require explicit
preparation/review; exporting and maintaining that bundle from a checkout is not
automated yet. Host edits are visible through the bind, but do not reload already
running Python/processes or installed dependencies. Launch records retain the Git
revision and public-content digest. Rollback to an old image uses that image's baked
startup unless the operator explicitly chooses a live bundle again.

### Config-only public agent publication

Before using a reviewed resource tree with `--resources`, publish its registration
manifest as the tree's ordinary owner:

```sh
make -C runtime resources RESOURCES=/absolute/reviewed/public/agent
```

This target reuses the maintained `venv/entry.py` projector/publisher and
`opencode/.opencode/config/opencode.json` as the sole metadata source. It emits
only the `agent` map with relative prompt references into `opencode-agents.json`;
it does not copy providers, plugins, models or global policy. No second metadata
template or generator is maintained. The destination must already exist, contain
the canonical physical `system/` and `gsd/` prompt files, and belong to the caller.
The target verifies those exact paths, not the whole checkout; exposure review
of all other bound content remains the operator's responsibility. It does not
copy resource trees or follow their unrelated links.

Publication is exclusive and idempotent for identical bytes; a stale/conflicting
manifest fails without overwrite. Missing or redirected prompts also fail the
target (an already published manifest is retained). This explicit preparation
does not build/activate images, seed a HOME, grant ACLs or alter running sessions.
Existing manifest conflicts require review, not automatic replacement.

Shared-runtime enrollment reuses the same role publication, exact-path ACL and
per-account readability checks against the configured policy resource root before
control promotion, independently of the legacy registration toggle. That include
is resource-only: it does not seed legacy private HOMEs. Common startup seeds the
selected runtime HOME from the manifest using container-visible prompt paths;
existing private configuration/policy and agent overrides retain precedence.

Every state slot is image-bound before first execution. An image change over that
HOME fails closed: image rollback does not reverse databases or provider-state
writes. Select a **new empty** slot, or keep using the original image. A reviewed
same-HOME migration/backup/restore path is not implemented. Existing unbound HOME
contents are never adopted or recursively repaired.

Runs stay foreground, forward signals/status and hold an exclusive per-slot writer
lock. A remaining new-path container for that HOME also blocks launch after a killed
adapter. No container is automatically adopted, killed or deleted to clear a conflict.
T3 additionally keeps an image-level server lock and private log; starting it does
not pair a browser or validate a provider.

### Workstation web startup readiness

Foreground `--web` holds the same writer lock while waiting up to 60 seconds for
startup (individual Docker/HTTP probes are bounded and can finish after the deadline;
a late result is never reported ready). Before printing the loopback URL it verifies
the full container contract and running state, HTTP `/`, and the harness API:
Pi `/api/sessions` JSON, OpenCode `/global/health` with `healthy: true`, or T3's
unauthenticated API and WebSocket rejection. It rechecks the same exact container ID
after the probes. Requests use direct loopback HTTP, bounded response sizes, no
ambient proxy/credentials and no redirect following.

On startup failure only a freshly validated exact container ID may be stopped.
Unknown ownership/authority drift is retained; the local attached Docker client is
killed/reaped without forwarding a cleanup signal into an unverified container.
Retained containers continue blocking a second HOME writer and require explicit
inspection/recovery. Successful startup remains foreground and returns the worker's
exit status. This is a startup gate, not a restart daemon or continuous health monitor.
T3 denial checks do not prove successful pairing, authenticated WebSocket use, or
provider operation. Protected VM staging and authenticated gateway checks are owned
by the existing VM launcher/gateway, not by this workstation supervisor.

## Verification and remaining implementation

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s runtime/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s venv/tests -v
git diff --check
```

New tests stub external Docker/npm/network operations. Legacy characterization
executes copied dispatchers with harmless sibling recorders and verifies tracked
production harness trees match Git HEAD. It does **not** yet provide the complete
stubbed run/mgr environment/mount matrix requested by plan12.

Remaining implementation/acceptance boundaries:

- Full legacy run/mgr/native/Compose characterization, not just dispatcher tests.
- Independent upstream release review and actual five-image builds/startup checks;
  package-hook behavior and platform availability cannot be proven by fixtures.
- Config-only OpenCode registration and canonical resource publication are offline
  tested end to end. Actual OpenCode discovery in a built image and T3 paired
  browser/provider parity remain unverified; no private credentials are copied.
- Per-target checkout custody/exposure review, reviewed image projections and exact
  backward-compatible state transitions before VM activation. Compiler, sealed
  promotion, protected adapter and coupled replacement/recovery already exist;
  their presence does not authorize target enablement or establish migration safety.
- Workstation same-HOME image migration remains intentionally blocked; use a fresh
  state slot. Docker CLI is not packaged for the optional socket grant.
- Plan13 integration and full online acceptance, explicitly outside this pass.

Legacy VM replacement refusal remains when shared opt-in is absent. Target guards,
seals and the independent resource-rollout hold remain binding. Never execute this
mutable checkout as root or promote its controls outside the reviewed Ansible flow.
