# Paseo execution daemon + native OpenCode V2

📍 The spelling **paseo-deamon** is intentional. The maintained VM interface is an
ordinary Compose service, not the retired runtime/venv lifecycle. These are source
changes only: no image build, live deployment or provider acceptance is claimed.

## Standard VM Compose service

`docker-compose.j2`, `env.j2`, `config.json.j2` and `Dockerfile.service` retain the
ordinary service catalog interface and canonical `agent` NSS UID/GID. See
[VM service inputs](../VM-SERVICES.md) for parent delivery and ingress ownership.

```text
parent finite public staging -> named opencode-inputs build context
                               installer + publisher + service wrapper
parent config delivery ------> /opt/opencode-defaults + /opt/agent (read-only)
                               |
                        shared service-entrypoint
                               |
                        native Paseo supervisor
                               |
                        embedded OpenCode V2 child
```

The inherited `/opt/opencode/service-entrypoint.sh` makes one config-publication
call before executing the daemon entrypoint:

```sh
node /opt/opencode/component/scripts/publish-plugins.mjs config /opt/opencode-defaults /opt/agent "$OPENCODE_CONFIG_DIR"
```

The named context contains only `scripts/entrypoint.sh`,
`scripts/publish-plugins.mjs` and `service-entrypoint.sh`. Public config and resource
trees are runtime mounts, not copied checkout contents or image dependencies.
The local service build context admits only `entry.py` and `verify-paseo.mjs`.
Parent delivery must include the verifier alongside the existing entrypoint.
See the [shared update/conflict contract](../opencode/README.md#shared-workstation-configuration-on-vm-consumers).

The VM HOME is ephemeral. Only dedicated daemon/provider state and the workspace
are writable host binds; no workstation SSH, Git identity or provider HOME is
mounted. Authenticate providers independently into this state, without copying
credentials. Shared config keeps canonical models, agents and permissions; no
separate VM agent policy or registration is introduced.

## Build and provider compatibility

- Select an externally reviewed official `PASEO_BASE` image pinned by version and
  digest and matching exact stable `PASEO_VERSION` **>=0.12.0**. Existing configured
  image/version values are not silently replaced by this source change.
- Both Dockerfiles execute `verify-paseo.mjs` against the installed CLI/server
  packages. It checks exact package versions, the native `@opencode/client` V2
  dependency and published V2 provider module paths. Paseo 0.12.0's published
  server contains actual V2 runtime detection; old adapters are not supported by
  merely changing a version string. Packaging drift requires explicit review.
- OpenCode uses `opencode/scripts/entrypoint.sh:install_runtime()` to install
  **`@opencode/cli@latest`** at build time into the scoped
  `/opt/opencode/component/.runtime` prefix. The shared verifier checks installed
  package metadata against isolated native CLI output. No OpenCode version input
  is required; startup never installs or updates the CLI.
- Images record `/opt/opencode-version.txt`, `/opt/opencode-install.json` and
  `/opt/paseo-version.txt`. Record those alongside image ID/digest, platform and
  source revision after a real build. `latest` is intentional, not a reproducible
  transitive dependency lock; refresh only through an explicit reviewed rebuild.

Paseo owns embedded OpenCode and its generated secured backend credential. Do not
start another `serve` wrapper, configure an external OpenCode URL, publish the
child port or substitute the parent web service's password. Paseo native bcrypt
auth, Host/Origin controls and parent TLS ingress remain separate boundaries.

## Native auth, state and confinement

`entry.py` retains native owner-only bcrypt config validation and advisory locks on
both state roots across exec. Prepare disjoint UID-owned mode-0700 daemon and
provider directories, and an agent-owned mode-0600 protected `config.json`.
`config.json.j2` consumes the existing protected hash, never a plaintext password
environment override. Parent rendering must suppress logs/diffs for this file.

For standalone preparation, `config.example.json` is deliberately not startable.
As the selected ordinary account, use a fresh private staging HOME and an already
reviewed Paseo CLI's interactive native command:

```sh
paseo daemon set-password --home /absolute/private/staging-home
```

Do not place passwords in argv, environment, URLs, examples or shell history, and
do not run this against a live daemon or read-only mounted config. No credential
generation or live-state operation was performed by this merge.

The VM service retains read-only rootfs, dropped capabilities,
`no-new-privileges`, bounded tmpfs, loopback publication and native healthcheck.
Only OpenCode is enabled; other providers, relay, MCP, service proxy, terminal
hooks and voice features remain disabled. Public `/api/health` does not establish
authenticated API/WebSocket or provider acceptance.

## Retained standalone Compose interface

`compose.yaml` / `Dockerfile` remain a separate local component interface, not the
VM identity/delivery contract. The build context is the repository parent (`..`),
with a finite Dockerfile-specific ignore file. Runtime UID/GID defaults remain
`1000:1000`; the image remaps only its existing account and image-owned paths.
No root startup chown, host account changes or privilege grants are introduced.

Set reviewed absolute paths; never select a whole HOME or existing server state:

| Selector | Container destination |
|---|---|
| `WORKSPACE_PATH` | `/workspace`, read-write |
| `PASEO_STATE_PATH` | `/state/paseo`, private daemon state |
| `PASEO_PROVIDER_STATE_PATH` | `/state/provider`, fresh provider XDG state |
| `PASEO_CONFIG_PATH` | `/state/paseo/config.json`, read-only |
| `OPENCODE_CONFIG_PATH` | `~/.config/opencode/opencode.json`, read-only V2 config |
| `OPENCODE_CLI_CONFIG_PATH` | same directory, `cli.json` |
| `AGENT_RESOURCES_PATH/{commands,skills,system}` | same directory, matching resource tree |
| `OPENCODE_PLUGINS_PATH` | same directory, `plugins/` |
| `OPENCODE_TUI_PLUGINS_PATH` | same directory, `tui-plugins/` |
| `SSH_DIR_PATH`, `GITCONFIG_PATH` | `~/.ssh`, `~/.gitconfig`, read-only |

Here `~` means `/home/paseo`. Supply a dedicated empty SSH directory and Git file
if no identity is needed. Pre-enroll reviewed known_hosts; never disable host
verification. Config/plugin/resource trees are trusted executable inputs: inspect
their symlink closure and do not mount dependency trees or private files.
No obsolete resource projection or plugin dependency installation is revived.

Select a local `PASEO_IMAGE` tag, `PASEO_BASE`, `PASEO_VERSION` and source/state
paths in a private operator env file. Inspect both Docker context and Buildx
builder endpoints before a separately approved local build:

```sh
docker context inspect <local-context>
docker --context <local-context> compose --env-file /absolute/private/component.env config --format json
docker --context <local-context> compose --env-file /absolute/private/component.env build --pull --no-cache paseo
docker --context <local-context> image inspect <new-local-image-tag>
```

Do not build against TCP/SSH/remote Docker. Later approved startup uses
`up --no-build --pull never`; this source work authorizes no activation.
Standalone loopback publication defaults to `127.0.0.1:6767`; bridge execution
egress is not a destination-filtering firewall or a substitute for TLS.

## Verification and deferred acceptance

```sh
node --test paseo-deamon/tests/verify-paseo.test.mjs
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s paseo-deamon/tests -p 'test_service.py' -v
git diff --check -- paseo-deamon
```

Rendering requires Jinja2/PyYAML and Compose config support. To bypass a Docker
CLI shim or missing plugin, explicitly select a standalone Compose executable:

```sh
DOCKER_COMPOSE_BINARY=/absolute/path/to/docker-compose PYTHONDONTWRITEBYTECODE=1 \
  /workspace/opencode-migration-checks/bin/python -m unittest discover -s paseo-deamon/tests -p 'test_service.py' -v
```

The override accepts an executable path, not a shell command. Tests invoke it
directly (without the `docker compose` prefix), with isolated HOME/Docker config.
An unsupported default Docker Compose config command skips with this setup hint;
invalid templates and a broken explicit override still fail. Render cases cover
Paseo, Paperclip with/without its socket grant, and OpenCode with/without its socket
grant, including backend auth, exact serve arguments and health-helper COPY closure.

Tests use synthetic temporary package fixtures and rendered public templates;
they do not install packages, access credentials or touch live state. The old
component/projection test suite and progress document are retired, not restored.
Cross-file checks derive the publisher command from the shared entrypoint and
resolve its installed source through all three service Dockerfiles. Disposable
COPY-layout fixtures execute both daemon wrapper chains with a stub publisher
and terminal service, proving the installed path is reached exactly once before
handoff. They are not image builds: only absolute fixture paths are rebased;
account switching and actual daemon/sshd execution are not exercised.

🧪 Still required after parent integration: finite-input delivery including the
verifier, native image builds on the selected platform, actual version records,
fresh-state native config/agent/skill/plugin discovery, V2 provider session/tool
work, generated child password behavior, correct/wrong/missing auth for API/WS,
exact Host/Origin/TLS/streaming ingress, state exclusion and signal/restart tests.
Preserve existing parent credential custody; do not rotate or copy secrets to
make acceptance pass.
