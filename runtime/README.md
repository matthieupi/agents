# Opt-in workstation runtime

This explicit interface supports **Pi, OpenCode and Claude**. It does not replace
existing run/mgr wrappers, native workstation scripts, static Compose, private
state or defaults. Ordinary VM services instead use [VM-SERVICES.md](../VM-SERVICES.md).
T3/OMP recipes and managed-VM delegation are retired; no privileged activation or
VM compatibility fallback remains.

## Existing workstation commands

Run as an ordinary account, never root/sudo:

```sh
make -C runtime update HARNESS=opencode
make -C runtime build HARNESS=opencode
make -C runtime activate HARNESS=opencode IMAGE=sha256:<64-lowercase-hex>
python3 -B runtime/runtime.py run opencode --workspace . -- --help
python3 -B runtime/runtime.py run opencode --workspace . --web --port 4096
```

`update` resolves compatible stable inputs, refreshes the exact base, generates a
lock and builds. `build` consumes the matching existing resolution. `activate`
selects a built local image only for future workstation launches; it never changes
a running container. The direct installer accepts only `--scope workstation`.
No schedules, login hooks, automatic activation, pruning or VM selectors exist.

| Product | Modes | Native platforms |
|---|---|---|
| Pi | CLI, web | amd64, arm64 |
| OpenCode | CLI, web | amd64, arm64 |
| Claude | CLI | amd64, arm64 |

## Build/install contract retained

`harnesses.json` owns package ranges and recipes. The original reviewed lower
bounds remain, and Claude's major range still needs independent release review.
Version ordering is not compatibility proof. Native host/platform matching is
required; no implicit emulation.

Explicit update resolves Node's platform/index digests and a dated Debian snapshot,
generates an npm v3 lock with registry URLs and SHA512 integrity, and builds a fresh
finite public context. Dependency downloads use `npm ci --ignore-scripts`;
non-root package hooks use an offline rebuild with BuildKit network disabled.
APT archive signatures remain enabled. The package locks, source fingerprints,
image labels/IDs and local receipts retain their existing workstation build/reuse
contract; none are consumed by a VM service or privileged approval process.

OpenCode's finite context retains KDCO public sources, locked dependencies, three
static plugin entrypoints and the existing publication helper. Dependencies are
baked outside HOME and startup links them without importing plugin code during
installation. OpenCode startup does run factories/hooks; desktop features may be
unavailable in headless containers. No additional sockets or permissions are added.

State remains under `~/.local/state/agents-runtime`, with private directories and
receipts. A state slot binds its HOME to one image; an image change requires a new
empty slot. No private-state adoption, recursive repair or migration is performed.
Catalog/source changes require an explicit update before a new build; old receipts
and ignored state are not deleted or converted by this source cleanup.

## Foreground execution and authority

Defaults remain numeric caller UID/GID, dropped capabilities, no-new-privileges,
read-only rootfs, bounded tmpfs/memory/swap/CPU/PIDs, bridge networking and
loopback-only web publication. No Docker socket/group is passed by default.
The image provides NSS-wrapper support for arbitrary non-root numeric owners.

| Opt-in flag | Existing behavior |
|---|---|
| `--docker-socket` | Bind the selected local socket, exact supplementary group and DOCKER_HOST; host-root-equivalent authority. Docker CLI is not packaged here. |
| `--cap-add NET_BIND_SERVICE` | Only the catalog allowlisted capability. |
| `--root-user` | Baked startup only; no mutable resources, read-only workspace and disposable HOME. |
| `--resources <path>` | Reviewed public resource tree, read-only at `/opt/agent`; never pass private state. |
| `--live-source <path>` | Physical ordinary-owned bundle containing exactly `entry.py` and `harnesses.json`. |
| `--checkout-write` | Explicitly permit writes to that live bundle, not a broad checkout. |
| `--state-slot <name>` | Independent private HOME; no credential copying. |

GPU and privileged-container requests are rejected. Runs remain foreground and
hold a per-slot writer lock. Leftover containers block another HOME writer; they
are not adopted or deleted implicitly. Web startup checks the full container
contract, HTTP root and Pi `/api/sessions` or OpenCode `/global/health`; it prints
the loopback URL only after readiness. Failure may stop only an exactly revalidated
owned container. This is bounded startup supervision, not provider/browser acceptance.

## Public config preparation

```sh
make -C runtime resources RESOURCES=/absolute/reviewed/public/agent
```

This calls `opencode/scripts/public-resources.py` with the canonical OpenCode JSON.
Only its public agent map is published as `opencode-agents.json`; no providers,
global policy, plugins or credentials are copied. The existing resource directory
must belong to the publisher and contain the exact physical `system/` and `gsd/`
prompts. Publication is exclusive/idempotent for identical bytes; conflicts fail
without replacement. Missing/redirected prompts fail and retain any publication,
as before. No ACL grants, HOME seeding, image selection or running-session changes
occur here. Opt-in runtime startup alone retains its config-only first-write seed
and preserves private policy/overrides. This is not VM registration.

## Offline verification and remaining gaps

The runtime tests cover the supported Pi/OpenCode/Claude contracts and explicitly
reject retired harnesses and VM activation selectors. Workstation selection tests
verify receipts and image identity, preserve the previous selection on failure,
and never delegate to a privileged launcher. Legacy dispatch assertions exercise
supported wrappers rather than comparing source bytes to the current Git HEAD.

Run the offline suites without Docker, npm or external network operations:

```sh
python3 -B -m unittest discover -s runtime/tests -v
python3 -B -m unittest discover -s opencode/tests -v
```

These suites passed after retirement-test reconciliation. Actual image/platform/
package-hook acceptance, provider use, full workstation characterization and live
fresh-state behavior remain deferred; mocked contracts are not live acceptance.
