# Native VM service inputs

📍 `pi`, `opencode`, `paseo-deamon` (intentional spelling), and `paseo-hub`
have ordinary Compose templates. This is assembled **source**, not a build,
deployment or acceptance record. Parent catalog/prerequisite/ingress integration
owns operational convergence; nested legacy-source retirement is complete.

```text
host.services -> ordinary catalog -> common/docker_service
                                    | finite public inputs
                                    | docker-compose.j2 -> docker-compose.yml
                                    | env.j2 -> protected .env
                                    v
                              native Compose build/up
```

There is no VM runtime policy, source manifest, image approval, activation broker,
registration, SSH alias or custom launcher in these inputs. The old `venv/` build
path is deleted. Workstation run/mgr wrappers and Pi/Claude static Compose remain
separate. Pi/OpenCode installer/init helpers remain VM build dependencies; native
start/manage scripts, OpenCode static Compose and the opt-in `runtime/` framework
are retired. Ordinary VM templates and their delivery inputs are unchanged.

Paperclip is an additional ordinary **base UI**, not an execution product. Its
[own contract](paperclip/README.md) uses a pinned published production image,
product-owned configuration preload, local app/PostgreSQL/credential state and
the same NSS account without HOME/workspace/socket mounts. The parent preparation
role owns its target-local missing-only secrets and internal bridge; native ingress
defaults deny-all until controlled first-admin setup. No company/agent bootstrap,
cloud mode or custom execution guard is added; an instance administrator remains
capable of deliberately configuring local adapters. Remote agents are deferred.

## Identity, paths and grants

Shared canonical inputs are `agent_account: agent`, `agent_home: /home/agent`,
`agent_workspace`, and `agent_docker_socket`. The prerequisite owner resolves
`agent_uid` and `agent_gid` from NSS. Those same numeric values are build arguments
and Compose runtime identity; all new images name that identity `agent` and use
`/home/agent`. Changing IDs requires a rebuild, not a runtime chown or identity
restoration. Base-image UID/GID collisions fail through native user/group tools.

Pi/OpenCode bind the account HOME and exact workspace. Only allowlist membership
emits both socket mount and `agent_docker_gid` supplementary group (resolved from
socket facts), plus `DOCKER_HOST`. There is no host-group enrollment or privileged
mode. Docker access remains host-root-equivalent. Same-UID services and shared HOME
are **not isolation boundaries**, even when a particular service lacks a socket.

Prerequisites create missing local directories without recursive repair:

| Service | Host paths owned by agent, private mode 0700 |
|---|---|
| Pi/OpenCode | HOME, workspace and required product config/state descendants |
| Daemon | `agent_home/.local/state/paseo-deamon/{daemon,provider}`; workspace |
| Hub | `agent_home/.local/state/paseo-hub` and its `.paseo` child |

Daemon mounts only its product state and workspace, not host HOME or workstation
SSH. Its ephemeral HOME uses the same account, not another identity. It installs
OpenCode in its own image and lets Paseo start the embedded provider process;
it never connects to the separately selected OpenCode web service. KDCO links are
published using the unchanged product helper before the existing daemon entry
validates native auth and locks state. No VM agent registration/default policy or
provider credentials are seeded.

Hub binds only its product state as container HOME. It has no provider HOME,
workspace, SSH or socket. Before rendering, S prepares an **internal** bridge using
`community.docker.docker_network` with native dynamic allocation. Compose references
the external network via `paseo_hub_network_name`, derived by S from the conventional
deployed service name, not canonical subnet/address configuration. S inspects its
IPv4 gateway as `paseo_hub_network_gateway`; native Paseo trusts exactly that `/32`.
After Compose, S inspects the container endpoint for ordinary host-nginx upstream
routing. There is **no published host port**, static IP or proxy network attachment.
Do not replace this with loopback publication. The `/home/paseo` mode-000 tmpfs
in both Paseo templates suppresses an upstream image VOLUME; it is not an execution
HOME, account or alias.

## Catalog contract for S

Use explicit `docker_service_workspace_path` and `docker_service_git_path` ending
in the nested product source directory, not inferred `services/<service>`. Use
separate generated output, `docker_service_build: true`,
`docker_service_env_sensitive: true`, and finite `docker_service_extra_files`.
Disable common role service-user creation: only the existing `agent` account is
used. Select solely through `services`; metadata must not enable a product.

The templates consume the current service's **flat** `service_config` mapping.
Canonical resource/image values come directly from `environments/devai/config.yml`;
S projects endpoint/auth metadata from its existing authorities, not new host fields:

| Fields | Type / constraint | Consumers |
|---|---|---|
| `container_port` | integer, unprivileged TCP port | all |
| `upstream_port` | S-derived integer, host loopback port | Pi, OpenCode, daemon |
| `memory_limit`, `pids_limit` | configured Compose memory string, positive integer | all |
| `cpus` | configured positive number; optional and omitted when absent on Hub | Pi/OpenCode/daemon configured; Hub currently absent |
| `hostnames` | unique exact DNS names; canonical for Hub, endpoint projection elsewhere | Pi allowed hosts; Paseo native config; OpenCode ingress |
| `version` | exact stable `X.Y.Z` string | OpenCode and daemon |
| `image` | configured upstream reference, passed unchanged; daemon has a digest, Hub currently `ghcr.io/getpaseo/paseo:latest` | both Paseo build bases; no new pin enforcement/admission |
| `opencode_version` | exact stable `X.Y.Z` string | daemon embedded provider |
| `opencode_build_context` | S-derived absolute path to finite public staging below | daemon only |
| `allowed_origins` | S-derived unique exact HTTPS origins from canonical endpoints; no reflection/wildcards | both Paseo native configs |
| `trusted_proxies` | S-observed exact proxy source CIDRs | daemon only |

Hub network facts are separate template inputs: `paseo_hub_network_name` and
`paseo_hub_network_gateway`. No `network_subnet`, `network_gateway` or
`container_address` service metadata is required. Existing Hub `password_ref`,
`password_environment`, `certificate_authority` and `dns` stay S-owned inputs.

`pi_web_password` and `opencode_server_password` are protected **gateway credential
facts only**, never native VM environment inputs. As in the old managed path,
Pi/OpenCode have no native web password: nginx protects every external route and
strips Authorization before proxying. Host publication stays loopback-only; direct
bridge access must remain restricted. VM commands explicitly unset native web auth
variables and do not source host HOME/dotfiles; workstation native auth is unchanged.
Preserve existing credential references; do not rotate/copy provider credentials.
Paseo separately receives protected `paseo_password_hash` and consumes only
the existing native bcrypt hash (cost 10..16; Hub's existing stricter derivation
can stay); no plaintext password env override. `config.json.j2` is an extra
template to `config.json`, mode 0600, **owned by agent**. S uses U's extra-template
owner/group/sensitive controls with `agent_uid`/`agent_gid` and protected rendering
(no-log/diff suppression). These controls are being added by U, not implemented here.

Both Paseo configs explicitly disable upstream `omp`. That setting is a security
restriction, **not retained OMP product support**. It remains after OMP source deletion.
Hub disables all six upstream providers; daemon enables only OpenCode. Native
Host/Origin/auth, disabled relay/MCP/service proxy/terminal hooks and voice features
remain explicit. Parent ingress must retain exact TLS/Host/Origin and streaming
behavior; a loopback backend or healthcheck does not supply those controls.

## Finite public build-input catalog

Paths below are product-relative; the daemon's parent-root mapping is specified
below. Dockerfile-specific ignore files exclude everything else,
including `.env`, runtime state and private configuration. Do **not** recursively
copy `.opencode`, a KDCO directory containing node_modules, HOME, or the repository.

| Product | `docker_service_extra_files` inputs |
|---|---|
| Pi | `Dockerfile.service`, `Dockerfile.service.dockerignore`, `scripts/entrypoint.sh` |
| OpenCode | `Dockerfile.service`, `Dockerfile.service.dockerignore`, `service-entrypoint.sh`, `scripts/entrypoint.sh`, `scripts/publish-plugins.mjs`, KDCO files and three entrypoints below |
| Daemon | `Dockerfile.service`, `Dockerfile.service.dockerignore`, `entry.py`; named public OpenCode context below |
| Hub | `Dockerfile.dockerignore`; conventional `Dockerfile` is copied by the common role |

OpenCode public package files under `.opencode/config/kdco/`:

```text
package.json  package-lock.json  upstream.json  README.md  LICENSE
background-agents.ts  notify.ts  worktree.ts
kdco-primitives/cmux.ts                 kdco-primitives/get-project-id.ts
kdco-primitives/index.ts                kdco-primitives/log-warn.ts
kdco-primitives/mutex.ts                kdco-primitives/shell.ts
kdco-primitives/temp.ts                 kdco-primitives/terminal-detect.ts
kdco-primitives/types.ts                kdco-primitives/with-timeout.ts
notify/backend.ts  notify/cmux.ts  notify/status.ts  notify/title.ts
worktree/launch-context.ts  worktree/state.ts  worktree/terminal.ts
```

Entrypoints: `.opencode/config/plugins/kdco-background-agents.ts`,
`kdco-notify.ts`, and `kdco-worktree.ts` in that same plugins directory.

Daemon's native named context contains **only** those OpenCode package/entrypoint
files plus `scripts/entrypoint.sh`, `scripts/publish-plugins.mjs` and
`service-entrypoint.sh`. This is a build dependency, not an OpenCode service
selection: daemon-only hosts still need these public inputs. Installer
`install_runtime()` and its package lock remain unchanged.

**Sibling delivery contract:** U is adding `docker_service_extra_files_source_path`,
defaulting to the selected service source. For daemon delivery, S explicitly selects
the nested agents source parent in the chosen workspace/Git mode. Finite entries
map `paseo-deamon/<file>` to `<file>` for daemon inputs above, and
`opencode/<file>` to `opencode-inputs/<file>` for the named context's exact files.
Set `service_config.opencode_build_context` to
`docker_service_path/opencode-inputs`. Compose/env/config template discovery stays
in `paseo-deamon`, not the parent. No `..`, whole-tree copy, duplicate maintained
installer, source manifest, extra service selection or bespoke builder is needed.
U/S delivery is pending integration; do not point the context at a private checkout.

Pi reuses the unchanged paired pins `0.85.1` / `0.9.0` from its existing installer
and the existing component VM npm install shape. OpenCode reuses
`install_runtime()`, including locked KDCO dependency installation. Pi/OpenCode
use a directly pinned official Node base, not T3's prepared image or pins file,
and Docker CLI `28.4.0-cli`. Ordinary distro package signatures remain enabled;
APT packages/transitive Pi dependencies are not fully snapshot-locked. No image
was pulled or built here, including the newly selected Docker CLI tag.

## Source retirement and retained owners

The maintained `venv/` controller, its Docker overlays/build controls, old Pi VM
Dockerfile, T3/OMP products/recipes and old Paseo runtime projection are deleted.
Strict transport now belongs to the parent's `scripts/ssh_transport.py`.
The opt-in workstation framework and its runtime-only public-resource publisher
are retired. Product plugin publication and both Pi/OpenCode `scripts/entrypoint.sh`
helpers remain. No VM registration, ACL plan or policy was relocated.
The deleted VM machinery was SHA/source publication and
image/gateway approval, not an established cryptographic signing system.

Framework-owned tests were removed; retained workstation coverage moved to
`tests/test_workstation.py`, excluding only OpenCode static Compose assertions.
Pi installer/init coverage remains under `pi/tests`; deleted native start/manage
cases were removed. Parent legacy tests require separate maintenance; the whole
test graph is not claimed clean. Ignored/private data remains protected. Source
retirement performs no deployed-state cleanup.

## Deferred acceptance

Targeted offline fixture tests and shell syntax checks cover the workstation
cleanup, not VM acceptance. After the whole code/config set is assembled:
native template/Compose checks, positive/negative
socket rendering, isolated image builds, NSS/UID collision behavior, KDCO discovery,
Paseo supervisor compatibility, auth/Origin and host-to-Hub bridge reachability
remain necessary. Pi's bounded HTTP health and Paseo's public health endpoint do
not prove authenticated sessions or providers. Live operations require separate
scope/data/recovery approval. No deletion from a deployed machine is claimed.
