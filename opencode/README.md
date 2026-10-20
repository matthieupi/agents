# OpenCode V2 — server-first workflows

All maintained OpenCode installation paths resolve **`@opencode/cli@latest`**.
There is no operator-supplied OpenCode version pin. Resolved versions and install
receipts record what was installed; they do not make `latest` reproducible.
Application auto-update is disabled: use the owning install/build lifecycle.
Docker cache can retain an older npm layer; use `--pull --no-cache` when deliberately
refreshing latest, then repeat disposable acceptance before rollout.

```text
public config/resources -> private HOME discovery links + persistent state
                              |
                              v
                       one opencode serve
                              ^
                              +-- opencode --server http://127.0.0.1:<port>
                              +-- explicitly published browser/API clients
```

Docker runs the foreground server, not an idle keepalive or separate `web` process.
Closing a TUI leaves the server running. Use the client helper, not bare `opencode`
which could create an independent runtime. V1 `attach` and `/start-web` are retired.
Readiness is authenticated **`GET /api/info`** with V2 version validation (the
workstation helper also checks PID), not an HTML `200` or V1 `/global/health`.

## Standard VM Compose service

`docker-compose.j2`, `env.j2` and `Dockerfile.service` use the
[ordinary VM service flow](../VM-SERVICES.md). Native start/manage scripts, static
OpenCode Compose, the managed `venv/` controller and opt-in `runtime/` framework
are retired. CPU/GPU workstation dispatcher/menu/run/mgr and installer/init helpers
remain. T3, OMP and GSD are retired; no enrollment, registration or SSH alias
fallback replaces them. Source retirement does not clean deployed HOME or machines.

### Backend authentication and external ingress

V2 requires a protected **`opencode_backend_password`** fact, rendered by `env.j2`
as **`OPENCODE_PASSWORD`**. The service fails closed if that password is missing.
Compose runs `opencode serve` with explicit hostname/port/CORS and **no mDNS flag**;
its native healthcheck is `node /opt/opencode/backend-health.mjs <port>`.

The external nginx owner must first authenticate the client using the existing
gateway credential, then **replace** upstream `Authorization` with Basic auth for
`opencode:<backend credential>`. Forwarding the client's credential or stripping
Authorization to reach an anonymous backend is incompatible with V2. This required
gateway/secret integration is **outside this repository**; these templates do not
establish deployment acceptance. Keep existing gateway/provider credential
references; no secret rotation or provider-credential copying is authorized here.
Host publication remains loopback-only; direct bridge reachability must be restricted.

The separately hosted admin client at `opencode.intellagent.network` remains owned
by the infrastructure repository's `agent/opencode-ui` role. Preserve exact allowed
origins, TLS, Host/Origin enforcement, CORS preflight, streaming and authenticated
WebSocket behavior. Do not assume the old V1 ticket/API behavior proves V2 browser
compatibility. Validate positive and negative API/WS flows through the gateway.

### Shared workstation configuration on VM consumers

The parent `tasks/services/opencode-config.yml` delivers tracked regular files
from `opencode/.opencode/config/` and `agent/`, preserving known discovery links
without following them. It does not curate a separate agent list or rewrite
models, permissions, providers or plugins. Ignored/untracked files, Git metadata,
provider credentials and private HOME are not public delivery inputs. Missing or
redirected tracked files and unreviewed symlink layouts fail explicitly.

```text
maintained config + shared agent resources
    -> <service_base_path>/agent-config (root-owned public source)
    -> /opt/opencode-defaults + /opt/agent (read-only container binds)
    -> selected files/resources linked into private HOME/.config/opencode
       auth/session/cache/state remain private and persistent
```

Standalone OpenCode, Paseo's embedded OpenCode and Paperclip daemon use the same
publication helper. Paperclip initializes as `agent` before starting root-owned
sshd; root's HOME is not initialized. Paseo has ephemeral HOME and separate
persistent provider state. The static Hub UI gets agents from the selected backend,
not Hub-local config.

Despite its retained filename, `scripts/publish-plugins.mjs` is a **V2 config-only
publisher**, invoked as:

```sh
node scripts/publish-plugins.mjs config SOURCE_CONFIG RESOURCES DESTINATION_CONFIG
```

It installs no dependencies and imports no plugin code. It publishes selected
config/CLI/plugin assets and `commands`, `skills`, `system` links, **not a symlink
of the full source config directory**. Exact known managed links/snapshots/assets
can be reconciled and exact retired managed links/wrappers removed. Unknown config
(including conflicting `opencode.jsonc`), modified loaders, private files and
redirected private directories are preserved and block conflicting publication.
Unrelated plugins are not silently deleted. Review project-local discovery too:
workstation init rejects discovered obsolete `kdco-*` loaders. No KDCO package,
dependency install or GSD resource publication remains.

**Updates:** pull reviewed commits, then reapply through the scoped ordinary
Ansible service flow. `workspace_copy` uses controller-index membership and
working-tree content; `git` materializes the agents submodule at the
**parent-recorded commit**, not a floating branch. Publish nested commit and parent
gitlink together. There is no startup Git pull or new repository credential.
Quiesce every shared-config consumer on the selected host first: publication is
not a transactional live update. Config-only delivery requests Compose recreation,
not image rebuild; installer/entrypoint/build-input changes require the image build
path. A pull alone or restart before delivery is insufficient. Recreate affected
idle consumers, inspect effective config/plugin/prompt loading through the authenticated
backend on one host, then expand. Do not redeploy static Hub UI to change agents.

## Workstation quick start and client lifecycle

Requires Docker Engine, Bash, Python 3, `realpath`, Linux `flock` and `timeout`.
Guided menus additionally use [`gum`](https://github.com/charmbracelet/gum).
Run from `agents/opencode/`; configure provider access separately.

```sh
# Run as your non-root user on the Docker host, not inside another container.
# The wrapper does not source .env; provider access remains separately configured.
mkdir -p workspace ssh
./opencode -r ./workspace           # build CPU, start/reconcile server, attach TUI
./opencode menu                    # alias: tui
```

Every server requires a password, including loopback/TUI-only use. The local wrapper
automatically generates and reuses a random backend credential in
`.opencode/workstation-private/backend-password`: owner-only directory `0700`, file
`0600`, excluded from Git/build context and not explicitly mounted. A directory lock and
atomic publication serialize concurrent first launches. Invalid, redirected,
hard-linked, wrong-owner or incorrectly permissioned credentials fail closed without
reset or ownership repair. Preserve this directory across launches/rebuilds.

Explicit `OPENCODE_PASSWORD` takes precedence; `OPENCODE_SERVER_PASSWORD` is the
fallback when the preferred value is unset/empty. Overrides neither replace nor
rotate the saved local password; removing an override returns to the saved value.
No infrastructure Vault access is needed. Managed VM Vault reuse is **not** part of
this local path, and the VM service authentication contract above is unchanged.
Like provider state, the saved file is accessible to the same UID if the checkout
is selected as a workspace or exposed through a custom bind; this is not isolation
from trusted local agents. Do not share the private directory or enable shell tracing
around credential-bearing wrapper invocations.
Username is fixed to **`opencode`**. The client inherits credentials from the
container environment, not client argv/URLs; Docker administrators can inspect
that environment. Provider login may be interactive; an API key is not required
for every authentication method.

The launcher waits up to 90 seconds for authenticated readiness and never starts
a second server on probe failure. Web modes ensure readiness, print the endpoint
and return; they do not hold a browser session. To attach without changing launch
settings, use the container name reported by the launcher:

```sh
docker exec -it <container-name> bash /opt/harness/docker-client.sh
```

### Retained flags and management

```sh
./opencode /path/to/project
./opencode -w                      # loopback browser/API, host port 4096
./opencode --web 5000 .             # 127.0.0.1:5000 -> container 4096
./opencode --web --port 5000 .      # equivalent
./opencode --wlan 4096 .            # explicit LAN publication
./opencode -d .                    # --dangerous: client --auto; denies still apply
./opencode --cpus 4 --memory 8g .   # --mem alias; defaults 8.0 CPUs / 16g
./opencode --gpu .                 # -gpu alias; all GPUs, lab/opencode:gpu
./opencode --gpu 0,1 --cpus 8 --memory 32g .
./opencode --web 4096 --gpu .
./opencode --publish 3000 .
./opencode -p 5173:5173 -p 127.0.0.1:8080:80 .
./opencode -v /srv/docs:/docs:ro --volume ./shared-data:/data:rw .
./opencode --privileged .          # alias: --priviliged; full host-root access

./opencode -r .                    # rebuild CPU, reconcile/start server, attach TUI
./opencode -r --gpu 0,1 .          # rebuild GPU only, use explicitly selected GPUs
./opencode rebuild                 # CPU build + refresh workspace containers
./opencode rebuild gpu             # GPU build + refresh workspace containers
./opencode rebuild all             # both; update is a rebuild alias
./opencode list                    # alias: ls
./opencode stop <name|all>
./opencode start <name>
./opencode remove <name|all>        # alias: rm
./opencode clean                   # stopped containers; clean -f / fclean stops first
./opencode logs <name>
./opencode shell <name>
```

No host port is published by default; `--port` alone does not publish. The backend
uses Docker's default networking; there is no `devai-xmist` network prerequisite.
Provider DNS/reachability remains the caller's responsibility.
Port 4096 is reserved: use web options, not `-p`, for it. `--agent-web-port` is
removed. Extra ports accept `PORT`, `HOST:CONTAINER` or explicit
`127.0.0.1|0.0.0.0:HOST:CONTAINER`; unqualified mappings normally expose all host
interfaces. Dev servers must listen on `0.0.0.0` inside the container. Docker
network peers may reach the backend even without host publication. Basic auth is
not encryption: LAN use needs deliberate firewall/TLS/access controls.

`--volume`, `--volumes`, `-v` accept existing host directories as
`HOST_DIR:ABSOLUTE_CONTAINER_DIR[:ro|rw]` (default rw). Sources are canonicalized;
destinations can shadow existing mounts, a deliberate Docker-level override.
GPU requires NVIDIA Container Toolkit and compatible drivers; the CUDA 12.4.1
devel image includes compiler/toolkit, Python 3.11 headers and native build tools.
Verify host GPU support independently before enabling it.

⚠️ `--privileged` adds `--privileged --pid=host -v /:/host:rw` to this container.
Passwordless sudo permits host-root execution, including `sudo nsenter --target 1
--mount --uts --ipc --net --pid --root --wd -- uptime`. This grants every agent,
plugin and client full Docker-host control, not read-only/time-limited access.
Privileged containers use restart policy `no`; ordinary ones use `unless-stopped`.
Manual restart retains privileges. Relaunch without the flag to recreate without
them; stopping/starting is insufficient. This is independent of `--dangerous`.

### Automatic replacement and persistence

Ordinary launches **automatically stop/remove/recreate without confirmation** when
image ID, lifecycle/config fingerprint, credentials, resources, GPU, ports, volumes
or privilege mode differ. **Active sessions are interrupted**; this behavior is
intentional and user-authorized, not a live migration. Repeat all desired flags
for reuse; omitting a publication/mount removes it by recreation. Matching running
containers are reused; stopped/stale containers are recreated. `start` does not
reconcile settings. Manager rebuild/update removes owned workspace containers
across profiles. All manager operations require this canonical checkout/user's
`dev.xmist.opencode.workstation` ownership label and exclude Compose-labelled services,
including explicitly named targets. Legacy unlabelled containers are not adopted or
deleted; launch stops on such a name collision. Review actual ownership before any
manual removal. Names use workspace basenames (plus `-gpu`); equal basenames collide.
CPU/GPU containers have separate names but share canonical state.

| Workstation host path | Container use |
|---|---|
| `.opencode/config` | `/opt/opencode-defaults`, read-only maintained public source |
| `.opencode/home-config` | `~/.config/opencode`, private writable directory with selected managed links |
| `.opencode/data` | `~/.local/share/opencode`, sessions/provider authentication |
| `.opencode/cache`, `.opencode/state` | private persistent XDG cache/state |
| `.opencode/workstation-private` | protected local backend credential; no dedicated bind |
| `../agent` | `/opt/agent`, writable shared commands/skills/system resources |
| selected workspace | `/workspace`, writable project |
| `SSH_DIR_PATH` (default `./ssh`) | `~/.ssh`, read-only dedicated keys/config/known_hosts |

Wrapper builds create the named account/HOME using the invoking non-root **UID:GID**;
containers run with that identity. Root/sudo launches and mismatched image accounts
are rejected; use `-r` to rebuild for the correct user, not runtime chown. Shared image
tags are local defaults, so another user's rebuild may require rebuilding again.
Ordinary checkout/application-state directories are not rejected based on ownership
or permissions; normal filesystem access errors still apply. Redirected paths remain
rejected, and the backend credential directory retains strict owner-only protection.
New state directories are `0700`; existing state is never reset or permission-repaired.

Use the local Docker host filesystem and Unix-socket daemon, not a remote Docker
context or a container with differently mapped host paths. A local socket alone does
not prove filesystem identity. All normal bind sources must already exist on the
daemon host (`--mount` fails rather than creating root-owned directories); paths with
commas are unsupported. Create the dedicated SSH directory explicitly, even if empty.
No host-path translation, account impersonation or automatic mount repair is supplied.
Retain private paths
across replacement; do not delete auth/session databases to troubleshoot. V1 database
conversion and real old-session recovery remain unverified. Retained bytes do not
prove compatibility or rollback. Workstation images include passwordless sudo and
writable shared resources: they are trusted development environments, not sandboxes.
Provision least-privilege remote accounts and verified SSH known_hosts separately.

## V2 configuration and plugins

- Canonical `.opencode/config/opencode.json` uses native V2 `agents`, `providers`,
  ordered `permissions`, `system` references and `request` settings. Default model
  is `openai/gpt-6-astra`; native `title` agent uses `openai/gpt-5-mini`.
  `DevOps` is selectable/callable (`mode: "all"`); `DevOps Junior` is hidden.
- Automatic compaction is disabled: `{auto: false, buffer: 50000}`. The buffer is
  not an enabled token trigger or a verified long-session request-size fix.
- `plugins/background-subagents.js` defaults native subagent calls to background
  **only when omitted**. Explicit `background: false` works for every agent,
  including write-capable ones; native permissions/depth checks still apply.
  Prefer completion notifications and dependency-driven work over polling/barriers.
- `plugins/first-prompt-title.js` owns initial title generation through the native
  hook, preserves custom titles and leaves persistence/concurrent renames to the
  host. Optional bounded OpenAI lookup uses `OPENCODE_TITLE_API_KEY` (fallback
  `OPENAI_API_KEY`), `OPENCODE_TITLE_BASE_URL` (full chat-completions URL), and
  `OPENCODE_TITLE_MODEL` (default `gpt-4.1-mini`). Failure/missing credentials
  falls back to a first-prompt-derived title.
- `cli.json` selects theme `opencode` and `./tui-plugins/session-title`. Its shim
  loads a display-only sanitized, colored title (up to 35 graphemes) at
  `prompt.footer.status`, not a replacement footer/title generator. See
  [title details](.opencode/config/tui-plugins/README.md). Title-specific environment
  overrides are not automatically forwarded by the wrapper/template.
- Global permissions are permissive with per-agent overrides. Read-only role
  descriptions are not filesystem sandboxes. Provider env variables alone do not
  register arbitrary providers; use the native provider schema.

`OPENCODE_EXPERIMENTAL_WORKSPACES=1` is set on the workstation backend; all clients
use that backend. Verify native worktree relative-file/subagent behavior in a
disposable repository before real use; do not assume credential links or dirty
checkout changes transfer. Markdown agents shared with Pi/Claude are not OpenCode's
native agent registry.

## Retained installer/init helper

As an existing named non-root `OPENCODE_USER` (both UID/EUID must match), call
`scripts/entrypoint.sh install` and separately `initialize-home` while consumers
are idle. Defaults are `OPENCODE_REPO=/srv/agents`,
`OPENCODE_ROOT=$OPENCODE_REPO/opencode`, `OPENCODE_PREFIX=$OPENCODE_ROOT/.runtime`.
The home/checkout/component must be account-owned canonical non-overlapping paths
outside `/opt` for these direct helper calls. Ordinary VM image builds reuse the
installer functions under their own build-account/path setup.

Install resolves latest into ignored staging using isolated HOME/XDG/npm settings,
verifies package metadata and binary version, then promotes `.runtime/bin/opencode`.
Failed stages/logs remain; attempted runtime restoration is not crash-atomic or a
private-state rollback. `initialize-home` uses the shared config publisher, not a
full source-directory symlink. Locks serialize cooperating installers/publishers,
not active sessions. Infrastructure owns accounts/tools/secrets and service control;
these scripts create no units, escalate no privileges and source no service env file.
There are **no native start/manage commands** to restore.

## Integrations and evidence boundary

- **Paseo:** requires actual native V2 adapter packaging, not merely a newer version
  label. Published **0.12.0** source/package layout was verified; its adapter uses
  per-child passwords and an authenticated V2 client (minimum CLI 2.0.10).
  `verify-paseo.mjs` is a required build input checking >=0.12.0, matching CLI/server
  packages, exact V2 client dependency and V2 provider modules. This is not live
  image/provider/session/tool acceptance. Keep its state separate from workstation state.
- **Paperclip:** retained SSH transport/callback evidence does **not** establish
  OpenCode V2 adapter compatibility. V2 session/tool/provider acceptance is unverified;
  do not assume a `latest` adapter supports V2 or is safe to activate.
- [dispatch](dispatch/README.md) and [ssh-remote](ssh-remote/README.md) remain
  **default-off, V1-targeted**, not ported or established compatible with V2.

Prior disposable install/server smoke resolved latest to **2.1.1** and passed;
that is evidence, not a pin or production acceptance. This documentation pass runs
no installs, providers or deployments. Useful source checks from the repository root:

```sh
git diff --check
node --test opencode/tests/config.test.mjs opencode/tests/service-entrypoint.test.mjs
python3 -B -m unittest discover -s opencode/tests -p 'test_backend.py' -v
python3 -B tests/test_workstation.py -v  # isolated fake Docker/temp HOME; no builds
```

For failures inspect `./opencode logs <name>` or the deployed service's Compose
logs, then check password inputs, path ownership and the preserved conflict named
by the publisher. Live gateway API/WS, providers, GPU, footer rendering and real
old-session recovery require separate acceptance. No deployment acceptance is claimed.
