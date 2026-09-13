# Paseo execution daemon + managed OpenCode

📍 Component only; spelling **paseo-deamon** is intentional. No Ansible wiring,
target/account selection, deployment, hub change, shared-runtime change or adapter
patch is included. Do not deploy until the acceptance gates below pass.

```text
future TLS proxy -> loopback published Paseo :6767
                          |
                          +-> upstream OpenCode adapter -> opencode serve child
                                 | managed config (RO)
                                 | dedicated provider state (RW)
                                 + workspace + execution egress
```

OpenCode is installed in the same image. Paseo owns its child process; do not
configure an existing OpenCode URL or start a second server in this component.
Pi and other CLIs are not installed or assumed. The existing hub stays on its
existing internal/no-egress network; this separate Compose bridge permits provider,
Git and package-registry egress. It is not a destination-filtering firewall.

## Discovery mapping and identity

Sources below are relative to `services/agents` unless a variable is named.
Set source variables to **absolute, reviewed paths**, not an entire host HOME.

| Repository source / selector | Container discovery destination |
|---|---|
| `opencode/.opencode/config/opencode.json` / `OPENCODE_CONFIG_PATH` | `/home/paseo/.config/opencode/opencode.json` |
| `opencode/.opencode/config/tui.json` / `OPENCODE_TUI_CONFIG_PATH` | same directory, `tui.json` |
| `agent/commands` / `AGENT_RESOURCES_PATH/commands` | same directory, `commands/` |
| `agent/skills` / `AGENT_RESOURCES_PATH/skills` | same directory, `skills/` |
| `agent/system` / `AGENT_RESOURCES_PATH/system` | same directory, `system/` |
| `agent/gsd` / `AGENT_RESOURCES_PATH/gsd` | same directory, `gsd/` |
| `opencode/.opencode/config/plugins` / `OPENCODE_PLUGINS_PATH` | same directory, `plugins/` (all four current entrypoints) |
| `opencode/.opencode/config/kdco` | image-installed locked package, linked as same directory's `kdco/` |
| `SSH_DIR_PATH` (existing identity selector convention) | `/home/paseo/.ssh`, read-only |
| `GITCONFIG_PATH` (existing identity selector convention) | `/home/paseo/.gitconfig`, read-only |
| `WORKSPACE_PATH` | `/workspace`, read-write; keep this path stable across recreations |

`HOME=/home/paseo`, `XDG_CONFIG_HOME=/home/paseo/.config`,
`OPENCODE_CONFIG_DIR=/home/paseo/.config/opencode`, and `OPENCODE_CONFIG` explicitly
point the inherited child environment at these destinations. `system/` is **not**
an independent agent registration mechanism: the canonical JSON owns agent names,
permissions and `{file:./system/...}` / `{file:./gsd/...}` prompt references.
No duplicate `~/.agents` discovery links are published. Repository resource trees
currently contain nested symlinks; review their resolved closure before exposure.
The component does not repair the shared trees or claim recursive discovery safety.

Plugin entrypoints stay enabled, including `first-prompt-title.js` and the three
KDCO plugins. Their executable code is deliberately trusted, not harmless data.
KDCO source/dependencies are baked using the maintained lock; rebuild whenever its
source/lock or the mounted KDCO entrypoints change. Do not mix incompatible revisions.
The config-root `package-lock.json` is not mounted: it is not agent registration,
and KDCO owns a separate maintained nested manifest/lock.

The config root is a private, bounded, ephemeral tmpfs so startup can create the
single `kdco/` symlink to its immutable baked source. It is not host state and is
discarded on recreation. Every managed config file, resource tree, plugin, SSH
directory and Git file remains an explicit read-only descendant mount. OpenCode may
attempt its own dependency preparation when loading a project; this component adds
**no** startup installer and does not disable plugin/skill discovery to conceal
failures. Read-only managed config, local plugins, built-in provider plugins and
fresh-cache behavior require actual image acceptance. Project-triggered package/tool
downloads are distinct from installing/updating daemon/CLI binaries and remain
execution authority of trusted projects. Do not call this an offline runtime.

## Private state and confinement

Prepare new, disjoint, UID-owned **0700** directories:

| Selector | Container target | Ownership |
|---|---|---|
| `PASEO_STATE_PATH` | `/state/paseo` (`PASEO_HOME`) | Paseo session/device/log state only |
| `PASEO_PROVIDER_STATE_PATH` | `/state/provider` | fresh OpenCode `data/`, `cache/`, `state/` via XDG |
| `PASEO_CONFIG_PATH` | `/state/paseo/config.json`, read-only | protected native config, owner-only 0600/0400 |

Never select the existing OpenCode server's data/cache/state or HOME; never overlap
either state directory with the workspace, identities, config sources, or each
other. Host path review is mandatory: runtime locks cannot identify an unrelated
server's state. The component holds advisory locks on both state roots across exec;
all launches sharing them must honor those locks. One instance only. Authenticate
providers independently into this new state; do not copy credentials. No provider
secrets are baked, forwarded implicitly, or included in Compose examples.

Numeric `PASEO_UID:PASEO_GID` defaults to `1000:1000`; startup rejects UID/GID zero.
Other numeric identities require host permissions and live SSH/tool compatibility
testing (the image passwd account is UID 1000). There is no root startup chown,
sudo, socket, Docker group, privileged broker or host-network mode. Capabilities
are dropped and no-new-privileges is enabled; rootfs is read-only. Writable paths
are the workspace, dedicated state and bounded `/tmp`. The upstream anonymous HOME
volume is suppressed by a tiny `/home/paseo` tmpfs owned by the configured numeric
UID/GID. A second, equally private bounded tmpfs at
`/home/paseo/.config/opencode` prevents root-owned bind-target parents from blocking
startup; managed descendants mount read-only above it. Startup creates only an exact
symlink from `kdco/` to the immutable baked KDCO source—no dependency tree is copied.
No host HOME is mounted.

Read-only SSH means no interactive known-host enrollment here. Supply reviewed
known_hosts beforehand and least-privilege keys; do not disable verification.
Use an empty dedicated SSH directory and empty Git file when no identity is needed.
Workspace content and config plugins can execute with all these granted rights;
this is a container boundary, not per-agent credential isolation.

## Native auth configuration

`config.example.json` is deliberately **not startable**. Native shape:

```text
version: 1
daemon.listen: string (container default 0.0.0.0:6767)
daemon.auth.password: bcrypt hash string ($2a/$2b/$2y, cost 10..16)
daemon.relay.enabled: false
daemon.mcp.enabled: false
features.webUi.enabled: true
worktrees.root: /workspace/.paseo-worktrees
```

As the selected ordinary account, prepare a private new staging home and place the
example there as `config.json`. With an already installed, reviewed Paseo version:

```sh
paseo daemon set-password --home /absolute/private/staging-home
```

Use its interactive prompt, never passwords in env, argv, URLs, shell history or
examples. This writes the native bcrypt hash. Set `PASEO_CONFIG_PATH` to that
owner-only file. Do not point the command at a live daemon or the read-only mounted
file. A built image can also run this native command with `--entrypoint paseo`,
`--user <uid>:<gid>`, `--network none` and **only** the private staging-home bind;
no published ports. No such operation was run in this workstream.

Startup rejects missing/example/plaintext auth and insecure ownership/mode, then
executes the upstream foreground supervisor. Upstream schema validation still owns
the complete config. Change auth through the protected source and explicitly
recreate later; no auto-restart/reload workflow is introduced. Bcrypt does not
replace TLS. Static web UI and `/api/health` are public upstream; verify other HTTP
and WebSocket surfaces reject missing/incorrect passwords before acceptance.

## Explicit build/update (native commands only)

No build ran here. Registry metadata observed on 2026-09-12: OpenCode **1.18.30**,
Paseo CLI **0.8.0**. These are observations, not installed-version evidence or a
compatibility claim. The website still labels 0.8 beta; use registry/release
verification rather than inferring freshness from prose.

1. Read current stable metadata (`npm view opencode-ai dist-tags.latest` and
   `npm view @getpaseo/cli dist-tags.latest`, or the registry endpoints below).
   These commands query metadata; do not run `npm install` on the host.
2. Review the corresponding exact official image and release:
   `docker buildx imagetools inspect ghcr.io/getpaseo/paseo:<stable-version>`.
   Set `PASEO_BASE=ghcr.io/getpaseo/paseo:<stable-version>@sha256:<reviewed-digest>`.
   Select the native host platform; no implicit remote builder or emulation.
3. Set exact stable `PASEO_VERSION`, `OPENCODE_VERSION`, and a new local
   `PASEO_IMAGE` tag. Set all required source/state/identity variables above.
   Use a private operator env file (never commit it). Compose does not hash secrets
   and its render must never contain plaintext passwords.
4. From this directory, with an explicitly inspected **local** Docker context:

```sh
docker context inspect <local-context>
docker --context <local-context> compose --env-file /absolute/private/component.env config --format json
docker --context <local-context> compose --env-file /absolute/private/component.env build --pull --no-cache paseo
docker --context <local-context> image inspect <new-local-image-tag>
```

Review context endpoint AND Buildx builder endpoint before building. Do not run
against TCP/SSH/remote Docker. `--pull` is an explicit build-time base refresh,
constrained by its digest, not startup behavior. The Dockerfile context is exactly
`services/agents` (`..` in Compose), Dockerfile `paseo-deamon/Dockerfile`.
Its Dockerfile-specific ignore file admits only startup code, the maintained native
installer, publication helper and KDCO public sources/lock. No config credentials,
private runtime, other services or whole checkout are copied into the image.

Paseo installation is inherited from its official version/digest image; OpenCode
installation reuses `opencode/scripts/entrypoint.sh:install_runtime()` (the same
callable used by `venv/Dockerfile.opencode`). No independent package installer is
introduced. Required helper is copied to `component/scripts/publish-plugins.mjs`.
Build checks actual OpenCode output and both Paseo package versions; records them
in `/opt/opencode-version.txt` and `/opt/paseo-version.txt`. Record those plus image
ID/digest/platform and source revision in local `progress.md` after a real build.
Exact direct versions are not a fully reproducible OS/transitive-dependency lock;
the existing native installer permits lifecycle hooks and registry access at build.

Updating means repeat metadata/release review, change explicit inputs, rebuild,
verify, then choose new private state or perform a separately reviewed state
migration/backup. No startup pull, package installer, update timer or automatic
activation. Compose `pull_policy: never`; later approved startup must use
`up --no-build --pull never`. **Do not run that now: target/account remain unresolved.**

## Method Signature Surface

```python
# entry.py (new)
def validate_config(path: Path) -> dict: ...
def ensure_kdco_link(config_home: Path, source: Path = KDCO_SOURCE) -> None: ...
def main() -> None: ...
```

```text
# maintained dependency, reused read-only, not changed
opencode/scripts/entrypoint.sh: install_runtime()  [Bash subshell function]
# tests/test_component.py (new unittest methods; no custom fixtures/helpers)
ComponentTests.test_native_auth_validation(self)
ComponentTests.test_kdco_link_is_safe_and_never_copies(self)
ComponentTests.test_mount_mapping_and_real_prompt_parity(self)
ComponentTests.test_confinement(self)
ComponentTests.test_maintained_installer_and_no_startup_install(self)
ComponentTests.test_real_compose_render(self)
```

## Verification and acceptance gates

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check -- paseo-deamon
```

Tests require existing PyYAML (no automatic install). They validate native auth
shape/modes, actual repository prompt references, mount parity and privilege
invariants. The render test invokes real `docker compose config`, without contacting
a daemon; it skips explicitly when Docker is absent. YAML parsing is not Compose
rendering. Synthetic bcrypt syntax is not an authentication test.

After a reviewed local build, with **fresh disposable state and a trusted empty
workspace**, use native Compose `run --rm --no-deps --entrypoint opencode paseo
debug config`, `debug skill`, and `agent list` (no service ports). These commands
execute real discovery and potentially trusted plugins; they are not part of the
default tests. Verify canonical agents/permissions, GSD commands, skills and four
local plugin paths. Check logs for read-only/dependency errors and resolved links.
Use only private disposable output: resolved configuration can contain credentials.
Do not run discovery against the existing server HOME. Global config dependency
preparation/plugin loading must pass without introducing a startup installer;
if it fails, extend the maintained build-time ingredient in a separately scoped
change rather than disabling discovery or making shared config writable.

| Gate still required | Evidence needed |
|---|---|
| Local build/platform | actual version files, image ID, native platform, upstream entrypoint compatibility |
| Real discovery | complete agents/commands/skills/plugins, fresh-cache behavior, no symlink loops |
| Paseo integration | provider availability, Paseo-owned `opencode serve` child, successful session/tool work |
| Security | missing/wrong auth rejected for API/WS, correct bcrypt auth succeeds, no child port published |
| State/runtime | provider login in new state, lock exclusion, signal/restart behavior, arbitrary UID if selected |
| Network/TLS | execution egress, loopback bind, future proxy HTTP + WS routing, exact hostnames/trusted proxies |
| Infrastructure | explicit target/account/path decisions and later Ansible wiring; hub unchanged |

No live port was exposed. Default publication is configurable loopback
`PASEO_BIND_ADDRESS=127.0.0.1`, `PASEO_PORT=6767`; changing the address is an explicit
exposure decision, not a TLS substitute. Future TLS integration must keep native
auth, route WebSocket upgrades, constrain hostnames and trusted proxies, and avoid
attaching this execution daemon to the hub's internal network just to gain routing.

Read-only references: upstream `docs/docker.md`, configuration docs at
https://paseo.sh/docs/configuration, official `docker/base/Dockerfile` and its
`paseo-docker-entrypoint`, plus registry metadata at
https://registry.npmjs.org/opencode-ai/latest and
https://registry.npmjs.org/@getpaseo/cli/latest. Upstream contracts can drift; the
selected image's paths/version checks must pass before use.
