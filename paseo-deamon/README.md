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

✅ **Paseo 0.12.0 has native OpenCode V2 support, not ACP.** Reviewed published
release source at gitHead `cafe4b01c8522ff39560241c5deb01427dc8dc5b`:
the provider registry selects `OpenCodeRuntimeClient`, which detects CLI V2
(minimum **2.0.10**) and imports `v2/agent`. Its V2 runtime launches
`opencode serve --hostname 127.0.0.1 --port 0`, generates a per-child
`OPENCODE_PASSWORD`, and connects with authenticated `@opencode/client` calls.
The server declares `@opencode/client: 2.0.10` alongside its legacy SDK; presence
of the legacy SDK does not mean the V2 path is absent. No adapter rewrite is needed.

Build validation requires exact stable Paseo **>=0.12.0**, matching CLI/server
packages, an exact declared V2 client dependency >=2.0.10 <3, and the compiled
registry/runtime-client/V2 agent/runtime modules. Paths follow the verified upstream
TypeScript build (`src` -> `dist/server`); packaging/dependency range drift fails
closed for review. This verifies packaging prerequisites, not execution or complete
dependency resolution. The selected exact-version/digest image still needs real
build, provider/session/tool and security acceptance. No selected digest was supplied
or inspected here. OpenCode alone resolves `latest`; Paseo remains pinned.

Pinned sources:
[registry](https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/server/src/server/agent/provider-registry.ts),
[selection](https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/server/src/server/agent/providers/opencode/runtime-client.ts),
[V2 runtime](https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/server/src/server/agent/providers/opencode/v2/runtime.ts),
[package](https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/server/package.json),
[build layout](https://github.com/getpaseo/paseo/blob/cafe4b01c8522ff39560241c5deb01427dc8dc5b/packages/server/tsconfig.server.json).

## Discovery mapping and identity

Sources below are relative to `services/agents` unless a variable is named.
Set source variables to **absolute, reviewed paths**, not an entire host HOME.

| Repository source / selector | Container discovery destination |
|---|---|
| `opencode/.opencode/config/opencode.json` / `OPENCODE_CONFIG_PATH` | `/home/paseo/.config/opencode/opencode.json` |
| `opencode/.opencode/config/cli.json` / `OPENCODE_CLI_CONFIG_PATH` | same directory, `cli.json` |
| `agent/commands` / `AGENT_RESOURCES_PATH/commands` | same directory, `commands/` |
| `agent/skills` / `AGENT_RESOURCES_PATH/skills` | same directory, `skills/` |
| `agent/system` / `AGENT_RESOURCES_PATH/system` | same directory, `system/` |
| `agent/gsd` / `AGENT_RESOURCES_PATH/gsd` | same directory, `gsd/` |
| `opencode/.opencode/config/plugins` / `OPENCODE_PLUGINS_PATH` | individual `plugins/first-prompt-title.js` and `plugins/background-subagents.js` read-only mounts |
| `opencode/.opencode/config/tui-plugins` / `OPENCODE_TUI_PLUGINS_PATH` | individual `tui-plugins/session-title.mjs` and `tui-plugins/session-title/tui.js` read-only mounts |
| `SSH_DIR_PATH` (existing identity selector convention) | `/home/paseo/.ssh`, read-only |
| `GITCONFIG_PATH` (existing identity selector convention) | `/home/paseo/.gitconfig`, read-only |
| `WORKSPACE_PATH` | `/workspace`, read-write; keep this path stable across recreations |

`HOME=/home/paseo`, `XDG_CONFIG_HOME=/home/paseo/.config`,
`OPENCODE_CONFIG_DIR=/home/paseo/.config/opencode`, and `OPENCODE_CONFIG` explicitly
point the inherited child environment at these destinations. `system/` is **not**
an independent agent registration mechanism: the canonical JSON owns agent names,
permissions and `{file:./system/...}` / `{file:./gsd/...}` system references.
No duplicate `~/.agents` discovery links are published. Repository resource trees
currently contain nested symlinks; review their resolved closure before exposure.
The component does not repair the shared trees or claim recursive discovery safety.

Canonical V2 title and background-subagent server plugins remain discoverable;
`cli.json` enables the session-title TUI plugin (not a Paseo UI extension).
Their executable code is deliberately trusted, not harmless data. Only these
explicit assets are mounted; stale KDCO wrappers cannot leak into discovery
through a whole-directory plugin mount. No KDCO source, build, publication or
startup link remains. Config-root package locks are not mounted.

The config root is a private, bounded, ephemeral tmpfs. It is not host state and is
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
startup; managed descendants mount read-only above it. Startup publishes no plugins
and creates no dependency links or copied trees.
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

No image build or provider session ran in this migration. OpenCode resolves
`@opencode/cli@latest` on every explicit uncached build; no OpenCode version input
is accepted. Paseo keeps its separate exact version/digest base contract.

1. Read current stable metadata (`npm view @opencode/cli dist-tags.latest` and
   `npm view @getpaseo/cli dist-tags.latest`, or the registry endpoints below).
   These commands query metadata; do not run `npm install` on the host.
2. Review the corresponding exact official image and release:
   `docker buildx imagetools inspect ghcr.io/getpaseo/paseo:<stable-version>`.
   Set `PASEO_BASE=ghcr.io/getpaseo/paseo:<stable-version>@sha256:<reviewed-digest>`.
   Select the native host platform; no implicit remote builder or emulation.
3. Set exact stable `PASEO_VERSION` (>=0.12.0) and a new local
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
Its Dockerfile-specific ignore file admits only startup code, the Paseo validator and the maintained native
installer. Public V2 config/plugins/resources are explicit runtime read-only mounts. No config credentials,
private runtime, other services or whole checkout are copied into the image.

Paseo installation is inherited from its official version/digest image; OpenCode
installation reuses `opencode/scripts/entrypoint.sh:install_runtime()` (the same
callable used by `venv/Dockerfile.opencode`). No independent package installer is
introduced. There is no separate publication helper. Build checks the exact scoped
package at `.runtime/node_modules/@opencode/cli/package.json`, native receipt,
and `opencode v<version>` output in an isolated build-only HOME; runtime state is
not used for probing. It records normalized `/opt/opencode-version.txt`, the
native `/opt/opencode-install.json` receipt and `/opt/paseo-version.txt`. Record those plus image
ID/digest/platform and source revision in local `progress.md` after a real build.
The floating OpenCode latest tag is intentionally not a reproducible dependency lock;
the existing native installer permits lifecycle hooks and registry access at build.

Updating means repeat metadata/release review, change explicit inputs, rebuild,
verify, then choose new private state or perform a separately reviewed state
migration/backup. No startup pull, package installer, update timer or automatic
activation. Compose `pull_policy: never`; later approved startup must use
`up --no-build --pull never`. **Do not run that now: target/account remain unresolved.**

### Caller/infrastructure handoff (outside this directory)

- Remove `OPENCODE_VERSION` from component build arguments/operator env/control files.
- Replace `OPENCODE_TUI_CONFIG_PATH` with `OPENCODE_CLI_CONFIG_PATH`, selecting
  canonical `opencode/.opencode/config/cli.json`, not the deleted `tui.json`.
- Add `OPENCODE_TUI_PLUGINS_PATH`, selecting canonical `config/tui-plugins`;
  retain `OPENCODE_PLUGINS_PATH` selecting canonical `config/plugins`.
- Keep private provider/Paseo state and existing identities separate and untouched.
  Existing private/modified OpenCode JSON can use V2's supported legacy reader;
  do not overwrite it with public defaults as a migration shortcut. This component
  neither scans nor deletes private HOME wrappers. Native lifecycle retirement of
  exactly recognized managed wrappers is owned elsewhere; unknown/private files
  must be preserved. No actual HOME or `/state` contents were accessed here.
- Recheck provider settings/config injected by the selected Paseo image against
  V2, including bridge plugins and permissions. Do not infer API compatibility
  from the CLI version or the SDK's `/v2` name. External control files were not edited.

## Method Signature Surface

```javascript
// verify-paseo.mjs (new)
export function validatePaseo(root, expected) // throws on unsupported/missing packaging
// tests/verify-paseo.test.mjs (new disposable fixture helper)
function fixture(t, version = "0.12.0")
```

```python
# entry.py (retained)
def validate_config(path: Path) -> dict: ...
def main() -> None: ...
# Removed: ensure_kdco_link(config_home: Path, source: Path) -> None
```

```text
# maintained dependency, reused read-only, not changed
opencode/scripts/entrypoint.sh: install_runtime()  [Bash subshell function]
# tests/test_component.py (unittest methods; no custom fixtures/helpers)
ComponentTests.test_native_auth_validation(self)
ComponentTests.test_v2_assets_are_explicit_and_read_only(self)
ComponentTests.test_mount_mapping_and_real_prompt_parity(self)
ComponentTests.test_confinement(self)
ComponentTests.test_maintained_installer_and_no_startup_install(self)
ComponentTests.test_real_compose_render(self)
```

## Verification and acceptance gates

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
node --test tests/verify-paseo.test.mjs
git diff --check -- paseo-deamon
```

Tests require existing PyYAML (no automatic install). They validate native auth
shape/modes, actual repository prompt references, mount parity and privilege
invariants. The render test invokes real `docker compose config`, without contacting
a daemon; it skips explicitly when Docker or its Compose plugin is absent. YAML parsing is not Compose
rendering. Synthetic bcrypt syntax is not an authentication test.

After a reviewed local build, with **fresh disposable state and a trusted empty
workspace**, inspect `opencode --help` and use that installed V2 release's native
discovery commands through Compose `run --rm --no-deps --entrypoint opencode paseo`
(no service ports). Do not assume V1 `debug`/`agent list` commands still exist.
Real discovery executes potentially trusted plugins; it is not part of the default
tests. Verify canonical agents/permissions, GSD commands, skills, both server
plugins and session-title CLI assets. Check logs for read-only/dependency errors and resolved links.
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
https://registry.npmjs.org/@opencode/cli/latest and
https://registry.npmjs.org/@getpaseo/cli/latest. Upstream contracts can drift; the
selected image's paths/version checks must pass before use.
