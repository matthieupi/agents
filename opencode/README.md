# OpenCode - Native and Container Workflows

## Standard VM Compose service

`docker-compose.j2`, `env.j2` and `Dockerfile.service` use the ordinary service
flow; see [the shared VM contract](../VM-SERVICES.md). The image reuses
`install_runtime()` and locked KDCO inputs; startup only links the baked plugins.
VM registration/public agent projection and SSH aliases are not part of this
path. The old managed controller is retired. No executable checks or builds ran
for this change; workstation/native contracts below are unchanged.

## Native workspaces in the workstation container

The workstation Compose environment and `opencode-run` launcher enable
`OPENCODE_EXPERIMENTAL_WORKSPACES=1` on the shared backend at container startup.
The launcher automatically recreates legacy keepalive containers on the next
launch. All attached TUIs and browser clients then use that backend; setting the
flag only on a client does not enable workspaces on an already-running server.
`opencode shell <container>` also supplies the flag to the new shell, including
for older containers; OpenCode launched from that shell inherits it. Already
running processes are unchanged.
With the new backend running, enter `/warp` and select **Worktree** to create a
native workspace and move the current conversation there in the same TUI. Select
an existing workspace to reuse it. No fork or new terminal is required.

This experimental workflow is separate from KDCO's `worktree_create` tool, which
retains its terminal-launch behavior. The native creation dialog does not provide
plan-derived branch names, the KDCO `/var/worktree` setting, or credential symlink
setup. Do not rely on Warp to transfer uncommitted primary-checkout changes.

For direct Compose launches (rather than `opencode-run`), existing containers need
recreation, not just `docker restart`, to receive the new container environment.
Coordinate an idle window for all sessions first. From
`services/agents/opencode`, using the existing deployment environment/overrides:

```sh
docker compose config --quiet
docker compose up -d --no-deps --force-recreate opencode
docker compose exec opencode printenv OPENCODE_EXPERIMENTAL_WORKSPACES
```

The final command should print `1`. Attach a TUI to the backend as shown below.
Before using Warp for real implementation, smoke-test it in a
disposable credential-free repository: verify a relative file operation and a
native subagent both use the selected worktree, and that the original checkout
remains unchanged. Source configuration alone is not runtime verification.

## Optional hub-only dispatch

The standalone [dispatch plugin](dispatch/README.md) delegates to existing OpenCode
v1.18.29 peers using native Basic authentication over verified HTTPS. It is **not
installed or enabled automatically**. Its five `dispatch_*` tools provide public
peer discovery, durable session-owned async task handles, follow-up prompts and
explicit status/result retrieval. Task/reply approval also covers background polling
and bounded queued-result context on future user turns in the original session and
directory—never a transcript notification, forced model turn or local fallback.
The package includes opt-in `/dispatch`, a public-config setup skill and local mock
tests. Passwords stay in preexisting protected files, not chat or config. No peer
callbacks, gateway, infrastructure changes or changes to KDCO enablement are involved.

## KDCO plugins: enabled through normal discovery

The committed [KDCO source and provenance](.opencode/config/kdco/README.md) provide
background agents, worktrees and notifications. Three `plugins/kdco-*.ts` static
re-exports are auto-discovered. Helpers and dependencies live in sibling `kdco/`,
outside even recursive plugin scans. No custom loader, activation flag, OCX,
source downloader, or inactive receipt remains.

| Path | Dependency installation and publication |
|---|---|
| CPU/GPU workstation | Image installs defaults; `init.sh` checks/reuses the actual mounted `kdco/` graph under a shared lock, otherwise links installed image defaults |
| Native | `install` checks/reuses checkout `.opencode/config/kdco` under the same package-local lock; `initialize-home` links that package and three entrypoints |
| Standard VM Compose | Image installs the same package; product startup links baked plugins into private HOME, without enrollment or VM registration |
| Opt-in runtime | Image installs the package non-root and startup links it even without shared resources; all source bytes/lock are bound to the existing resolution/receipt |

Private config, root package manifests, provider credentials and unrelated plugins
are not overwritten. Conflicting managed names or redirected private directories
fail with their contents preserved. Managed links receive later shared-source
edits; unlike ordinary copied defaults, they are not first-write-only snapshots.
Keep the source available wherever its HOME is mounted. Workstation init, native
install and VM image installation use a `flock` on `kdco/.kdco-install.lock`. Under that
lock the existing helper compares both manifests and the actual installed tree's
file contents, directory paths and symlink targets against `.kdco-install.json`.
Unchanged launches do not invoke npm or use the network. Missing/changed inputs,
missing/damaged dependencies or an absent/invalid stamp require `npm ci`; a marker
alone never proves that dependencies are present. The stamp is a reuse check, not
a signed security attestation. No plugin code is imported by these checks.

**Real installs/updates still require all sessions using that shared graph to be
idle.** This includes the first check of an older installation without a stamp.
The lock serializes installers, not running sessions. An in-place npm failure may
leave dependencies incomplete; the success stamp is invalidated before npm and
only replaced atomically after success. Retry the normal installation while idle.
Native failure before executable promotion preserves the executable, not the
previous dependency graph. No dependency rollback or live-update safety is claimed.

**Factories and hooks now run at OpenCode startup.** Installation itself only
publishes files/links and installs dependencies; it does not import plugins.
Worktree opens SQLite, delegation creates local storage, and notify inspects
terminal state. Native worktree deletion automatically stages/commits changes and
force-removes the worktree on idle, even if commit fails. Review project shell
hooks before using it. Headless VM/container terminal launches and desktop
notifications may be unavailable; no host sockets or extra permissions are added.

OpenCode 1.18.29 loader/build source was reviewed; all three factories were smoke
tested with Bun 1.3.11 and locked dependencies in disposable HOME without invoking
tools/events/providers. This is not full OpenCode/provider/platform acceptance.
`npm audit` reports two moderate findings (`uuid` and `node-notifier`); no breaking
force-fix was applied. See package provenance for the approved artifact-read patch.
No deployments or running sessions are updated by these edits. Quit/restart only
the selected idle OpenCode session after its normal installation/reapply.
Existing workstation images must be rebuilt before using the updated mounted
`init.sh`, which expects the image's publication helper. VM products instead bake
the same public inputs through native Docker builds; there is no enrollment step.

### KDCO verification commands

```sh
flock -x opencode/.opencode/config/kdco/.kdco-install.lock node opencode/scripts/publish-plugins.mjs install opencode/.opencode/config/kdco
node --test opencode/tests/plugins.test.mjs
bun test opencode/tests/plugins-smoke.test.ts
python3 -B -m unittest discover -s runtime/tests -p test_kdco_plugins.py -v
python3 -B -m unittest discover -s opencode/tests -p 'test_plugin_install_*.py' -v
# Optional real npm install/reuse/repair verification, entirely in disposable directories:
KDCO_REAL_NPM_TEST=1 python3 -B -m unittest discover -s opencode/tests -p 'test_plugin_install_*.py' -v
# From the infrastructure repository root:
python3 -B -m unittest discover -s tests -p test_kdco_plugins.py -v
```

Bun is a test prerequisite, not an additional production installation. The Node
test's dependency-resolution check requires the preceding npm install. Tests use
temporary directories; no real provider, worktree deletion or desktop event runs.

## Native lifecycle

Native OpenCode executes **locally as the supplied account**, not inside a sandbox
or remote-only adapter. Docker workflows below remain independent and unchanged.
Root must never execute editable checkout scripts or Git; infrastructure-owned
wrappers must reject root before loading these scripts.

### Environment and ownership contract

| Input | Contract |
|---|---|
| `OPENCODE_USER` | Existing named non-root account; both UID and EUID must match |
| `OPENCODE_REPO` | Default `/srv/agents`; full user-owned Git clone, not a worktree/submodule |
| `OPENCODE_ROOT` | Must equal `$OPENCODE_REPO/opencode` (default) |
| `OPENCODE_PREFIX` | Must equal `$OPENCODE_ROOT/.runtime` (default) |
| `OPENCODE_UNIT` | Default `opencode.service`; read-only status only |
| `OPENCODE_VERSION` | **Install only:** required exact stable `X.Y.Z`; no default/latest |
| `OPENCODE_BRANCH` | Update/update-check only: required assigned local branch |
| `OPENCODE_PREVIOUS_REPO` | Optional initialize-home input: explicit known old checkout for link migration |
| `OPENCODE_WORKSPACE` | Launch only: existing canonical absolute directory, including workspaces outside checkout |
| `OPENCODE_PORT` | Service only: decimal `1024..65535`, no leading zeroes |
| `OPENCODE_SERVER_PASSWORD` | Service only: mandatory nonempty secret, never argv |
| `OPENCODE_SERVER_USERNAME` | Optional service username; upstream default otherwise |
| Provider credentials | Service/session only, supplied securely or through user authentication |

HOME/UID/GID come from passwd. The account must own its existing home, checkout
and component. Home and checkout cannot overlap; canonical paths outside `/opt`
are required. No service environment file is sourced. Start sets HOME, USER,
LOGNAME, all XDG config/data/cache/**state** paths beneath passwd HOME,
`OPENCODE_CONFIG_DIR=$HOME/.config/opencode` and `OPENCODE_DISABLE_AUTOUPDATE=1`.
It clears `OPENCODE_BIN_PATH`, `OPENCODE_TEST_HOME`, `NODE_OPTIONS`, `NODE_PATH`.
Session arguments are passed unchanged and VERSION is not needed at launch.

### Commands and integration order

```text
Ansible: account + OS pins/tools + full checkout + protected wrappers/unit/secrets
    |
    +-- OPENCODE_USER: entrypoint.sh install          -> opencode/.runtime ONLY
    +-- OPENCODE_USER: entrypoint.sh initialize-home  -> missing defaults/known links
    |                  (supply PREVIOUS_REPO here for first migration)
    +-- OPENCODE_USER: start.sh service | session [CLI arguments...]
```

**Install never initializes the home.** The deployment role must call
`initialize-home` separately after install, passing any migration input. This
avoids duplicate setup and first-migration failures. Both operations share a
nonblocking component lifecycle lock with explicit updates.

Ansible owns OS dependencies and their approved pins: Bash, coreutils, flock,
getent, `/usr/bin/git`, `/usr/bin/node`, `/usr/bin/npm`, certificates and workload
tools. NodeSource-bundled npm is acceptable; no standalone npm package or APT
input is required here. Scripts create no accounts, units or login hooks and
perform no privilege escalation or service control.

Service foreground-execs exactly:

```text
opencode web --hostname 127.0.0.1 --port <supplied port> --mdns false
```

Extra service flags are rejected. Infrastructure owns TLS/WebSocket proxying,
firewall/access policy and protected environment files outside the checkout.
The proxy must reach the host's loopback; do not expose the backend publicly.
Credentials remain environment-only and must never enter Git or deployment logs.

### Installation, compatibility and failure handling

Install stages `opencode-ai@$OPENCODE_VERSION` under ignored `.build.*`, using
`env -i`, isolated HOME/XDG/config/cache/state and distinct empty user/global
npmrc files. Public HTTPS npm registry/config/cache variables also reach nested
npm children. Standard npm lifecycle is explicitly **enabled**, as the exact
non-root account, with optional platform packages. Install is bounded at 600
seconds; verification at 30 seconds, with kill grace. No user auth/plugins are
loaded for verification: only `--version` runs from the isolated HOME, with no
inherited executable/test-home/Node overrides or provider/web credentials.

The staged npm install is **local**, with `--no-save --package-lock=false`, not
`--global`. Global npm exports `npm_config_global=true` to postinstall children;
the vendor's fallback would then install under `temp/lib/node_modules` while
reading `temp/node_modules`. Local mode preserves that expected fallback layout.
Runtime metadata lives at `.runtime/node_modules/opencode-ai/package.json`;
`.runtime/bin/opencode -> ../node_modules/.bin/opencode` keeps the public launch
path unchanged and remains valid after promotion. An old global-layout runtime
is rebuilt on reapply, preserving it if the replacement fails.

Published evidence reviewed for this conversion:
- [`1.18.29` registry metadata](https://registry.npmjs.org/opencode-ai/1.18.29)
  declares `bin/opencode.exe`, exact optional architecture packages and
  `node ./postinstall.mjs`.
- [Its postinstall](https://unpkg.com/opencode-ai@1.18.29/postinstall.mjs) selects
  architecture/libc/AVX variants, copies the compiled binary, probes `--version`,
  and may use nested npm to obtain a fallback platform package.
- [Its CLI entrypoint](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/index.ts)
  registers `--version` through yargs' version handler rather than launching a
  session. Verification uses that path, not normal auth/plugin initialization.
- The old documentation's `1.2.15` was an example, **not a deployment pin**.
  Do not infer `--ignore-scripts` compatibility from its older launcher fallback.

Neither version is selected by these scripts. The caller must supply an approved
exact pin; metadata review and mocked tests do not establish real binary/platform
compatibility. Validate that pin's installation, version, loopback web/auth and
CLI behavior on the concerned host before wider rollout.

Package name/version and actual binary `--version` must match before reuse or
promotion. Plugin dependencies are independently checked/reused, or installed from
the npm lock when their inputs or installed bytes differ.
Matching runtime reuse and installation allow dirty checkouts. Failed
build/verification preserves the previous runtime and retains the ignored stage
and logs. Promotion is verified again; failure attempts to restore the previous
runtime. The two renames are **not crash-atomic**: inspect `.build.*/previous`
after interruption. Stop the concerned unit and drain sessions through protected
administrator tools before replacing an in-use runtime. No private-state rollback
is implied. Lifecycle scripts have the account's filesystem access: sanitized
environment is not a sandbox, and a top-level pin is not a transitive lockfile.

### Home resources and explicit updates

`initialize-home` directly links only `commands`, `skills`, `system`, `gsd` to
`$OPENCODE_REPO/agent/`; it does not use Pi's agents mapping. Only literal current
or explicitly supplied previous targets are reused/retargeted. Known duplicate
`~/.agents` resource links are removed; unknown links/real directories are
preserved and fail clearly. Redirected private roots/plugin directories are
refused, never followed to modify Docker or external state.

Only missing committed defaults from `opencode/.opencode/config` are copied:
`opencode.json`/`opencode.jsonc`, `tui.json`, package manifests/lockfile and
`plugin/`/`plugins/` files except managed `plugins/kdco-*.ts`, excluding caches/node_modules. Either existing config
format prevents both formats being seeded; if neither exists, tracked JSON wins
over JSONC. Complete temporary files are published exclusively, so existing or
concurrently created files win. Existing plugin lists/config are never rewritten.
Private auth, data, cache and state stay outside Git and unchanged. Copied defaults
do not receive later repository edits automatically; review/merge deliberately.

```text
manage.sh status                   read-only unit properties
manage.sh version                  isolated --version; no VERSION input required
manage.sh update-check FULL_SHA    fetch/validate without moving HEAD
manage.sh update FULL_SHA          clean-tree, assigned-branch fast-forward only
```

Updates require a full lowercase SHA on the fetched assigned origin branch and
a descendant of local HEAD. Tracked/untracked changes, detached/wrong branches,
divergence and ignored-file collisions are refused. Ignored runtime/build state
is allowed. Git fetch is bounded at 120 seconds and output suppressed to avoid
credential-bearing URLs. `merge --ff-only --no-overwrite-ignore` preserves the
branch; no reset, detach, clean, commits, pushes, hook skipping or config writes.
No install/service action is implicit; infrastructure owns source approval and
activation. The lock cannot coordinate arbitrary editor/Git/service operations.

### Verification

Run from the agents repository root:

```bash
bash -n opencode/scripts/entrypoint.sh opencode/scripts/start.sh opencode/scripts/manage.sh
python3 -B -m unittest discover -s opencode/tests -v
# If installed:
shellcheck -x -P opencode/scripts opencode/scripts/{entrypoint,start,manage}.sh
```

Tests run as a real non-root user with temporary Git repositories and fake package
fixtures; account lookup and normal package installation are mocked. When npm and
Node are available, an **offline real-npm** test installs two local fixture
tarballs only: a parent's postinstall invokes a child install and checks the
vendor-expected `node_modules` path. It proves old global mode fails and local
production installation succeeds through verification/promotion. Real npm config
parsing is also checked when available. This validates npm fallback geometry,
**not live OpenCode/VM compatibility**. Root execution is tested when the runner
is root; non-root runs check root-guard ordering. No network packages, host-global
dependencies, accounts, services or VM operations are installed/run by the suite.

## Docker workstation workflow

Each container runs one foreground `opencode web` backend on internal port 4096.
TUIs attach to it; browser clients use the same backend and session store. Init
runs once per container start, not on each attach. Closing a TUI does not stop the
backend; use `opencode stop <name>` when finished.

```text
TUI (docker exec attach) ---> container backend :4096 <--- browser
                                                        via explicit host mapping
```

**No host ports are published by default**, including when `--port` is used
without a web mode. Only `--web`, `--wlan`, or `--publish`
requests host publication. The backend binds `0.0.0.0` **inside the container**,
so Docker-network peers (and hosts with direct container routing) can reach it
even without published ports. This is not network isolation. Set
`OPENCODE_SERVER_PASSWORD` before creation on untrusted/shared networks; username
defaults to `opencode`. HTTP Basic auth is not encryption; use a trusted network
or a TLS reverse proxy for remote access.

The launcher waits up to 120 seconds for authenticated `/global/health` readiness
before attaching or reporting a browser endpoint. A failed probe never launches
another server. Inspect `opencode logs <name>` for startup/dependency errors and
retry after resolving them. Creation/reuse is serialized with host `flock` per
container name within this checkout; the lock is released before TUI attachment.
The launcher requires host `flock` and `timeout` (Linux util-linux/coreutils).

Legacy lifecycle, permission, exposure, resources, GPU, or mount mismatches cause
automatic recreation **without confirmation**, interrupting attached clients.
Repeat the same flags to reuse a container. Omitting a previous web/publish option
removes that publication by recreation. To attach to an existing exposed backend
without changing its launch configuration, use the direct `docker exec ... attach`
command below. Persistent config/data/cache mounts survive recreation.

Readiness and TUI attach inherit credentials from the **container environment**;
changing the invoking shell's password does not rotate a reused backend. Remove
the container and relaunch with the new credentials to rotate them. Credentials
are not printed in launcher commands or stored in compatibility labels.

The health helper is both copied into images and mounted by the launcher/Compose,
so older images do not need to contain that new file just to recreate a container.
Old OpenCode binaries without compatible `web`/`attach` commands need an image
update. Existing plugin installation prerequisites still require rebuilding old
images as described above. Direct Compose users must recreate their containers.

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Edit .env with your API keys

# 2. Create workspace
mkdir -p workspace

# 3. Build & start
docker compose up -d --build

# 4. Check readiness, then attach to the shared backend
docker exec opencode node /opt/harness/backend-health.mjs --wait
docker exec -it opencode opencode attach http://127.0.0.1:4096 --dir /workspace
```

## Usage with Wrapper Scripts

The `opencode` wrapper manages per-workspace containerized instances.

### Guided launcher

```bash
./opencode menu                # Open an interactive command builder
./opencode tui                 # Same as menu
```

The guided launcher uses [`gum`](https://github.com/charmbracelet/gum) to present common run, web, GPU, rebuild, and container-management options. It shows the generated `./opencode ...` command before executing it, so the normal CLI remains the source of truth.

### Interactive TUI (default)

```bash
./opencode                      # Run in current directory
./opencode /path/to/project     # Run in specific directory
```

### Browser UI

`--web`/`--wlan` ensure the backend is ready, print its endpoint, and return;
they do not start a second backend or hold a foreground browser session. Open
the printed URL in your browser. Custom host ports always map to container 4096
(for example, `--web 4097` publishes `127.0.0.1:4097:4096`).

```bash
./opencode -w                   # Run browser UI locally on http://localhost:4096
./opencode --web 4096 .         # Run browser UI locally on a specific port
./opencode --web --port 4096 .  # Equivalent explicit port form
./opencode --wlan 4096 .        # Expose browser UI on the LAN
```

For LAN access, set `OPENCODE_SERVER_PASSWORD` so the web server is protected:

```bash
OPENCODE_SERVER_PASSWORD=secret ./opencode --wlan 4096 /path/to/project
```

To attach a TUI without changing the exposed backend's launch configuration, use
the container name reported by the launcher:

```bash
docker exec -it <container-name> opencode attach http://127.0.0.1:4096 --dir /workspace
```

This attaches to the existing backend; it does not start another server.

### Rebuild image

```bash
./opencode -r .                 # Rebuild CPU and GPU images
./opencode rebuild              # Rebuild image + refresh workspace containers
./opencode rebuild gpu          # Rebuild CUDA devel GPU image + refresh containers
./opencode rebuild all          # Rebuild CPU and GPU images + refresh containers
```

Workstation CPU/GPU images intentionally install **`opencode-ai@latest`**, not a
pinned version. This is latest-at-build policy: running containers have automatic
updates disabled. A cached Docker build may reuse the old npm install layer,
including `./opencode update`, which pulls the base image but still allows cache.
To force a current npm release, build without cache from this directory:

```bash
docker build --pull --no-cache -t lab/opencode:latest .
docker build --pull --no-cache -f Dockerfile.gpu -t lab/opencode:gpu .
```

Then remove the affected workspace containers with `./opencode remove <name>`
and relaunch them (image tags alone do not invalidate reused containers).
Schedule updates when clients are idle. The manager's `update`/`rebuild` commands
already remove workspace containers after their builds. This policy does not
change the separate native/VM pinned-version workflow.

### Dangerous mode (auto-approve all permissions)

```bash
./opencode -d                   # Skip permission prompts
```

`-d` sets server-wide `OPENCODE_PERMISSION='{"*":"allow"}'`, affecting **every
TUI and browser client of that backend**, subject to OpenCode's agent-specific
permission rules. Without `-d`, the wrapper supplies `{}` and leaves configured
permissions intact; it does not promise that the underlying config asks for
approval. Toggling `-d` recreates the container. No unsupported permission flag is
passed to `opencode attach`.

### GPU access

```bash
./opencode --gpu .              # Run with all host GPUs available
./opencode -gpu .               # Same as --gpu
./opencode --gpu 0 .            # Run with GPU device 0 available
./opencode --gpu 0,1 .          # Run with GPU devices 0 and 1 available
./opencode --web 4096 --gpu .   # Combine browser UI and GPU access
```

GPU mode requires the host Docker engine to support GPU containers through the NVIDIA Container Toolkit. Validate the host first:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

GPU access is an explicit opt-in because agent-run commands can consume significant VRAM, compute, power, and thermal headroom.

When `--gpu` is used, the wrapper runs `lab/opencode:gpu` instead of the default `lab/opencode:latest` image. The GPU image is based on NVIDIA CUDA devel and includes CUDA compiler/toolkit headers, Python 3.11 development headers, and native build tools for packages that compile extensions.

### Container resources

```bash
./opencode --cpus 4 --memory 8g .             # Run with 4 CPUs and 8 GB memory
./opencode --web 4096 --cpus 2 --mem 4g .    # Combine web port and resource limits
./opencode --gpu 1 --cpus 8 --memory 32g .   # GPU workload with larger limits
```

Defaults are `--cpus 8.0` and `--memory 16g`. Changing CPU, memory, web port, or GPU settings for an existing workspace container recreates that container because Docker applies those settings when the container is created.

### Extra published ports

Use `--publish`/`-p` to expose arbitrary ports for dev servers that agents start inside the container.

```bash
./opencode --publish 3000 .                    # host 3000 -> container 3000
./opencode --publish 5173:5173 .               # host 5173 -> container 5173
./opencode -p 3000 -p 5173:5173 .              # expose multiple ports
./opencode -p 127.0.0.1:8080:80 .              # localhost 8080 -> container 80
./opencode -p 0.0.0.0:8080:80 .                # LAN 8080 -> container 80
```

Inside the container, the server must listen on `0.0.0.0`, not only `localhost`, for Docker port publishing to work.

### Custom directory mounts

Use `--volume`, `--volumes`, or `-v` to bind additional existing host directories
into the workspace container. The default access is read-write; use `:ro` for
reference material that the agent must not modify.

```bash
./opencode -v /home/me/reference:/reference:ro .
./opencode --volume ./shared-data:/data:rw .
./opencode -v /srv/docs:/docs:ro -v /srv/assets:/assets .
```

The format is `HOST_DIR:CONTAINER_DIR[:ro|rw]`. Host paths are canonicalized and
must already exist as directories; container destinations must be absolute.
Destinations are intentionally unrestricted, so a custom mount can shadow an
existing path if requested. Treat that as a deliberate Docker-level override.

Docker mounts are fixed when a container is created. Changing, adding, or omitting
custom volumes on a later invocation recreates that workspace container; finish or
detach active sessions first.

### Container management

```bash
./opencode list                 # List all containers
./opencode rebuild              # Rebuild image + refresh containers
./opencode stop <name|all>      # Stop container(s)
./opencode start <name>         # Start a stopped container
./opencode remove <name|all>    # Remove container(s)
./opencode clean                # Remove stopped containers
./opencode fclean               # Force clean: stop all, then remove
./opencode logs <name>          # Show container logs
./opencode shell <name>         # Open bash shell in container
```

## Directory Structure

```
opencode/
├── Dockerfile              # Container definition
├── Dockerfile.gpu          # CUDA devel GPU container definition
├── docker-compose.yml      # Service orchestration
├── .env.example            # Environment template
├── .env                    # Your config (git-ignored)
├── opencode.json           # OpenCode app config (reference)
├── opencode                # Main CLI wrapper
├── opencode-menu           # Guided launcher menu
├── opencode-mgr            # Container management script
├── opencode-run            # Runtime execution script
├── .opencode/
│   ├── config/             # OpenCode config (persisted)
│   │   └── opencode.json
│   ├── data/               # Session & auth data (persisted)
│   └── cache/              # Provider/plugin cache (persisted)
├── ssh/                    # SSH keys for remote access
│   ├── id_ed25519          # Agent private key
│   ├── id_ed25519.pub      # Agent public key
│   ├── config              # SSH client config
│   ├── known_hosts         # Known host keys
│   └── authorized_keys     # Keys allowed to access
└── workspace/              # Your projects (mounted)
```

## Configuration

### Shared project agent folder

On startup, this service links its home config directly to the shared `agent/` resource root for cross-harness commands and skills.

- Shared editable resources live in `/opt/agent/commands` and `/opt/agent/skills`
- `/opt/agent/prompts` carries shared prompt-oriented content alongside commands
- OpenCode links `~/.config/opencode/{commands,skills,system,gsd}` directly to that shared source; duplicate legacy `~/.agents` links are removed
- Existing real home directories are preserved by moving them aside to `.local*` backups if they conflict during startup

### Arbitrary config directory

Yes: OpenCode supports an arbitrary config directory through `OPENCODE_CONFIG_DIR`, but this service now keeps the default home path so behavior stays aligned with Claude-style home + project discovery.

This service sets:

```bash
OPENCODE_CONFIG_DIR=/home/opencode/.config/opencode
```

This service keeps `~/.config/opencode` as the active config directory and links shared resources directly from `/opt/agent` into it during startup via `init.sh`.

Project-shared resources come directly from `/opt/agent`, so you do not need a separate project `.opencode/` for shared commands/skills.

OpenCode does not share markdown `agents/` definitions with Claude/Pi. Its agent schema is different, so this bootstrap only shares `commands/` and `skills/` with OpenCode and leaves `.opencode/agents/` harness-specific.

### Shared home defaults

Shared default agents, commands, and skills live under the shared workspace `agent/` tree, mounted in the container as `/opt/agent`, and OpenCode links them into its home config during startup via `init.sh`.

- `../agent/commands/` -> `~/.config/opencode/commands`
- `../agent/skills/` -> `~/.config/opencode/skills`
- `../agent/system/` -> `~/.config/opencode/system`
- `../agent/gsd/` -> `~/.config/opencode/gsd`

Only the `prompts/commands`, `skills/`, and OpenCode-native `gsd/` prompt defaults are applied to OpenCode. Shared `agents/` stay Claude/Pi-only unless they are converted to OpenCode's native schema.

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | No* | Anthropic Claude API key |
| `OPENAI_API_KEY` | No* | OpenAI API key |
| `GEMINI_API_KEY` | No* | Google Gemini API key |
| `OPENROUTER_API_KEY` | No* | OpenRouter API key |
| `OLLAMA_HOST` | No | LAN Ollama server URL |
| `WORKSPACE_PATH` | No | Project directory (default: `./workspace`) |
| `GIT_AUTHOR_NAME` | No | Git commit author name |
| `GIT_AUTHOR_EMAIL` | No | Git commit author email |
| `SSH_DIR_PATH` | No | SSH directory path (default: `./ssh`) |

*At least one LLM provider API key is required.

### OpenCode Config (`.opencode/config/opencode.json`)

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "openai/gpt-6",
  "small_model": "openai/gpt-5-mini",
  "permission": "allow",
  "provider": {
    "openai": {
      "options": { "apiKey": "{env:OPENAI_API_KEY}" }
    }
  }
}
```

System agents inherit the global `openai/gpt-6` model unless overridden. The
default TUI theme is `opencode`, set in `.opencode/config/tui.json`.
Quit and restart OpenCode after changing these settings; running sessions retain
their loaded configuration.

### Supported Providers

OpenCode supports 75+ providers. Common ones pre-configured:
- **Anthropic** (Claude) - via `ANTHROPIC_API_KEY`
- **OpenAI** (GPT) - via `OPENAI_API_KEY`
- **Ollama** (local models) - via `OLLAMA_HOST`
- **OpenRouter** - via `OPENROUTER_API_KEY`

## SSH Access to Remote Machines

The agent has a dedicated SSH key for accessing test/remote machines.

### Granting Access to a Remote Machine

1. Copy the agent's public key:
```bash
cat ssh/id_ed25519.pub
```

2. Add it to the target machine's authorized_keys:
```bash
echo "ssh-ed25519 AAAA... opencode-agent@xmist.dev" >> ~/.ssh/authorized_keys
```

3. Configure host aliases in `ssh/config`:
```
Host test-server
    HostName 192.168.1.100
    User deploy
    IdentityFile ~/.ssh/id_ed25519
```

## Security Notes

- Container runs as non-root user (`opencode:1000`)
- API keys never baked into image
- SSH keys mounted read-only
- Workspace and config/data are the only writable mounts
- Agent SSH key is separate from personal keys for isolation
- Auto-updates disabled in container (`OPENCODE_DISABLE_AUTOUPDATE=1`)

## Network

Default: joins `devai-xmist` external network. For standalone:

```yaml
networks:
  devai-xmist:
    driver: bridge
```

## Troubleshooting

### Permission denied on workspace
```bash
sudo chown -R 1000:1000 workspace/
```

### Container won't start
```bash
docker compose logs opencode
```

### Image not found
```bash
cd /path/to/services/opencode
docker compose build
# or
./opencode -r .
```

### OAuth login is requested again
```bash
# Keep these directories between runs/restarts:
ls -la data/auth.json
ls -la cache/
```

## License

MIT
