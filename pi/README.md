# Pi lifecycle — native VM and retained Docker workflows

## Native `/srv/pi` lifecycle

**Native UI and CLI launch with LOCAL execution under `PI_USER`.**
This is not a remote-only adapter or an agent sandbox. The remote-only DevAI
deployment must remain disabled in Ansible until its adapter and containment
are implemented and validated; generic native launch is not gated on that work.
The native scripts install upstream Pi and a community web UI, not Docker, OMP,
or Claude. The existing Docker files, wrappers, `init.sh`, and checked-in `.pi`
tree remain unchanged. Native provisioning never invokes the container initializer.

### Chosen UI and verified upstream evidence (2026-09-05)

**Default selection: [`agegr/pi-web`](https://github.com/agegr/pi-web), published
as `@agegr/pi-web@0.9.0`, paired with `@earendil-works/pi-coding-agent@0.85.1`.**
These exact versions are maintained together in `scripts/entrypoint.sh`; runtime
environment variables cannot replace the pins. The UI embeds the same pinned Pi
SDK; installing a CLI wrapper does not intercept its SDK calls.

Selected for its published CLI, shared Pi state and documented headless launch.
It is a community UI, not an official Pi default or a remote-execution boundary.

Verified release-specific contracts:

- [Published UI metadata](https://registry.npmjs.org/@agegr/pi-web/0.9.0):
  `pi-web` executable, Node `>=22.19.0`, Pi dependencies exactly `0.85.1`,
  release source SHA `8463025a321b8a660e9c27b1fa9e1938e1e84c1f`.
- [Pinned CLI option parser](https://github.com/agegr/pi-web/blob/8463025a321b8a660e9c27b1fa9e1938e1e84c1f/bin/pi-web-options.js):
  `--hostname`, `--port`, `--no-open`; password via `PI_WEB_PASSWORD`, username `pi`.
  This lifecycle always supplies `--hostname 127.0.0.1` and an explicit port.
- [UI launch implementation](https://github.com/agegr/pi-web/blob/8463025a321b8a660e9c27b1fa9e1938e1e84c1f/bin/pi-web.js):
  launches the bundled production Next server and wires its child lifecycle.
  Our shell uses foreground `exec`; systemd must manage the complete cgroup.
- [Published Pi metadata](https://registry.npmjs.org/@earendil-works/pi-coding-agent/0.85.1):
  upstream package's `pi` executable is `dist/bundle/cli.js`; package includes
  shrinkwrap. This is the current upstream scope, not an OMP substitute.
- [node-pty 1.1.0 distribution](https://unpkg.com/node-pty@1.1.0/prebuilds/):
  only macOS/Windows prebuilds. Linux needs compilation. `build-essential` and
   Python are required; dependency install scripts run as a separate non-root account.
  The UI's own [postinstall](https://github.com/agegr/pi-web/blob/8463025a321b8a660e9c27b1fa9e1938e1e84c1f/bin/prepare-terminal.js)
  is a macOS permission workaround, not a Linux build substitute.

### Ownership and configuration contract

```text
Ansible: accounts + dedicated checkout + apt sources/pins + unit + environment
                        |
                        v
root entrypoint provision --> non-root npm build --> root-owned runtime
                        |
                        +--> PI_USER: seed missing home defaults

systemd User=PI_USER / login hook --> start.sh --> foreground pi-web / interactive pi
                                                LOCAL execution as PI_USER
```

The checkout is the **agents repository**, with `pi/` and `agent/` at its root;
do not clone the infrastructure repository or reuse a dirty Docker checkout.

| Input | Contract |
|---|---|
| `PI_ROOT` | Default `/srv/pi`; root-owned, no writable or symlink ancestors |
| `PI_REPO` | Default `$PI_ROOT/repo`; dedicated root-owned Git checkout |
| `PI_PREFIX` | Default `$PI_ROOT/runtime`; root-owned native runtime, disjoint from checkout |
| `PI_USER` | Required existing named non-root account; home derived from passwd, owned by that user, separate from deployment |
| `PI_BUILD_USER` | Required for provision; separate existing non-root account. Operator must exclude credentials, sudo and privileged groups; scripts verify only account identity and distinct nonzero UID |
| `PI_UNIT` | Default `pi.service`; Ansible-created systemd unit, inactive/failed for provision/update |
| `PI_APT_PACKAGES` | Required exact `package=version` list for `ca-certificates git nodejs npm ripgrep python3 openssh-client build-essential`; extras also need pins |
| `PI_WORKSPACE` | Required at launch: existing canonical absolute directory, outside deployment and `/opt`; CLI/launcher cwd, **not** UI session containment or remote target authorization |
| `PI_PORT` | Required for service, decimal `1024..65535`; no implicit/random/public port |
| `PI_WEB_PASSWORD` | Required service secret supplied by Ansible/systemd; never placed on argv |
| `PI_WEB_ALLOWED_HOSTS` | Exact external proxy hostnames, supplied by Ansible if needed; never changes loopback binding |

Use a supported Debian/Ubuntu image with Bash, coreutils, util-linux (`flock`,
`runuser`), Git, systemd and apt already available for bootstrap. Apt sources and
exact package versions come from inventory, not hardcoded distribution versions.
Node must be at least `22.19.0` at `/usr/bin/node`, npm available on the system
PATH. Provide compiler/Node headers or permitted header-download access for
node-gyp. Target npm must permit dependency scripts for the non-root build; an
npm policy that blocks node-pty compilation must not be silently ignored.

Ansible exclusively owns accounts, units, login hooks, proxy/TLS, secret delivery,
firewall, SSH identity/host-key trust and target policy. No units or accounts are
created here. The loopback HTTP listener cannot be reached directly from the
separate nginx VM: protected backend transport is still an infrastructure gate,
not permission to bind public/LAN HTTP. Authentication and TLS remain mandatory.

### Commands (on the intended VM only)

Supply the contract above through administrator-managed configuration; scripts
do not source a repo `.env`, run sudo, or install anything at session startup.

```bash
# Administrator, with approved inventory environment and a stopped unit:
bash /srv/pi/repo/pi/scripts/entrypoint.sh provision
bash /srv/pi/repo/pi/scripts/manage.sh version
bash /srv/pi/repo/pi/scripts/manage.sh status
bash /srv/pi/repo/pi/scripts/manage.sh logs
bash /srv/pi/repo/pi/scripts/manage.sh stop
bash /srv/pi/repo/pi/scripts/manage.sh update-check "$REVIEWED_FULL_SHA"
bash /srv/pi/repo/pi/scripts/manage.sh update "$REVIEWED_FULL_SHA"

# Native LOCAL execution (not permission to enable remote-only DevAI):
# Run these explicitly as PI_USER, with its supplied environment:
bash /srv/pi/repo/pi/scripts/start.sh service
bash /srv/pi/repo/pi/scripts/start.sh session
# Administrator entrypoints for the supplied native unit:
bash /srv/pi/repo/pi/scripts/manage.sh start
bash /srv/pi/repo/pi/scripts/manage.sh restart
```

`update-check` fetches the explicit 40-character lowercase commit SHA into
`FETCH_HEAD`, but does not change HEAD or install packages. Both update commands
hold the lifecycle lock and reject tracked, untracked **and ignored** checkout
state. `update` additionally requires a stopped unit, then checks out the exact
commit detached, without overwriting ignored files. It does not automatically
provision or restart. No `pull`, moving branch/tag, reset, clean or auto-rollback.
The checkout SHA is a revision lock, **not** a signature verification mechanism;
origin/access and commit approval belong to the administrator. Updates affect the
whole dedicated agents checkout, including shared resources, not just `pi/`.

`stop` requires only root authorization and a valid `PI_UNIT` (default
`pi.service`); it bypasses account/path checks, recursive audits and the lifecycle
lock so damaged deployments and busy installers cannot prevent emergency stop.
Start/restart still take the lifecycle lock. Close unmanaged CLI sessions separately.

Provisioning uses an empty staging prefix and private npm HOME. It runs npm and
dependency scripts as `PI_BUILD_USER`, verifies metadata, native PTY loading,
`pi --version` and `pi-web --help` as `PI_USER`, then promotes the root-owned
runtime. A matching verified runtime is reused on repeated provisioning. Failed
stages remain at the reported `.build.*` path for administrator inspection. If a
promotion rename fails, an old runtime may be under `previous/` there; there is
**no automatic rollback**. Successful promotion removes the old staged runtime.
Drain unmanaged CLI sessions before changing runtime or checkout; systemd status
does not prove that all manually started sessions have exited.

Top-level Pi/UI versions are exact; the UI still has transitive npm semver ranges
and no published shrinkwrap. Fresh installs are **not a fully reproducible supply
chain lockset**. Preserve/review resolved dependency evidence during target-image
validation before production acceptance. No controller installation is required.

`runuser` is an account switch, **not a sandbox**: dependency scripts can access
anything permitted to the builder, use the network and leave background processes.
Changing runtime ownership does not prove those processes have exited or make
build output trustworthy. Runtime verification also executes built code as
`PI_USER`. Treat dependencies as trusted supply-chain input; stronger build
containment and artifact review are external responsibilities.

### Home preservation and remote-only deployment boundary

`initialize-home` runs as `PI_USER`, creates private `~/.pi/agent`, links
`agents`, `prompts`, and `skills` to the checkout's shared `agent/` tree, and seeds
only missing tracked settings, TypeScript extensions and JSON themes. It never
overwrites existing files or relocates conflicting resources; conflicts fail
with their path. It does not add a second `.agents` discovery tree. Review any
existing discovery tree for duplicate resources before eventual activation.

Pi/OMP auth, databases, sessions, model settings, prompts and skills remain
untouched. No Docker auth/state is copied from the checkout. Docker-specific
`models.json`/`models.yml` defaults are deliberately not seeded into native home;
Ansible/provider configuration must supply reachable, authorized endpoints.
Seeded extensions are preserved, not claimed compatible or remote-safe at the
new pin. Existing `config.yml` and OMP `agent.db` are never modified.

The launch commands are:

```text
cd "$PI_WORKSPACE"
pi-web --hostname 127.0.0.1 --port "$PI_PORT" --no-open   # service
pi [arguments...]                                      # session
```

The [pinned Pi CLI](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/main.ts)
uses process cwd for new sessions; resuming a session can select its saved cwd.
The pinned UI parser accepts no workspace positional argument or `--cwd` flag.
Its launcher starts Next from the installed **package directory**, not
`PI_WORKSPACE`; select the intended local project in the UI. Shell cwd is not
UI session isolation. Both UI and CLI can operate locally with the account's
permissions, including extensions and UI filesystem/Git/terminal routes.

Keep remote-only DevAI activation **disabled in Ansible** until the separate
adapter work verifies:

- Current Pi callback signatures; strict validated target/SSH host keys and
  successful pre-mount for every worker/session; isolated target/cwd.
- Bash/read/write/edit/search, cancellation, RPC bash, extension-spawned agents,
  disconnects and target revocation, with no local fallback.
- UI SDK session creation plus file/upload/Git/worktree/package-management and
  [local PTY routes](https://github.com/agegr/pi-web/blob/8463025a321b8a660e9c27b1fa9e1938e1e84c1f/lib/terminal-manager.ts).
  A Pi tool extension alone does not cover these routes. The upstream launcher
  starts Next from the package directory, so shell cwd alone is not session isolation.
- Browser session/auth behavior and externally enforced containment. Merely
  declaring an adapter ready cannot satisfy the VM plan's remote-only policy.

### Verification

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s pi/tests -v
bash -n pi/scripts/entrypoint.sh pi/scripts/start.sh pi/scripts/manage.sh
# If available:
shellcheck -x -P pi/scripts pi/scripts/{entrypoint,start,manage}.sh
```

Run from the agents repository. Tests mock package/service/network operations;
launch tests execute fixture binaries without an adapter override. No live
installation, server, provider session, proxy or remote adapter is exercised.
Root-only tests are explicitly skipped when running unprivileged.

## Retained Docker workflows

The rest of this document describes the existing container lifecycle only; its
paths, optional OMP runtime and security assumptions do not apply to native VMs.

Dockerized [Pi](https://pi.dev) and [Oh My Pi](https://omp.sh) for local and remote development workflows. Upstream Pi remains the default; use `--oh` to launch the OMP runtime from the same image.

## Quick Start

```bash
# 1. Configure
cp .env.example .env

# 2. Create a workspace directory if you want a default bind mount
mkdir -p workspace

# 3. Build and start
docker compose up -d --build

# 4. Attach to either installed agent
docker exec -it pi pi
docker exec -it pi omp
```

## Wrapper Usage

The `pi` wrapper manages per-workspace containerized instances.

```bash
./pi
./pi --oh
./pi --oh /path/to/project
./pi --oh -p "Review this repo"
./pi --oh --login
./pi /path/to/project
./pi build
./pi login
./pi ext-agent-team
./pi ext-agent-chain /path/to/project
./pi ext-pi-pi
./pi -p "Summarize this repo"
./pi list
./pi shell pi-myproject
```

The wrapper is command-first:

- `pi build` rebuilds the image
- `pi --oh` launches OMP instead of upstream Pi
- after an optional leading workspace path, OMP arguments are forwarded unchanged, including `-r`/`--resume`
- an immediate `--login` after `--oh` is reserved by the harness and publishes the existing OAuth callback ports
- `pi login` starts Pi with OAuth callback ports published
- `pi ext-agent-team` launches Pi with the dispatcher/team-grid orchestration preset
- `pi ext-agent-chain` launches Pi with the sequential chain orchestration preset
- `pi ext-pi-pi` launches Pi with the pi-pi meta-agent preset
- `pi -p "Prompt"` sends a prompt to the Pi CLI explicitly
- a bare path like `pi /path/to/project` still opens Pi in that workspace

## Directory Structure

```text
pi/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── README.md
├── pi
├── pi-run
├── pi-mgr
├── .pi/
│   └── agent/
│       ├── extensions/
│       ├── extension-library/
│       ├── themes/
│       ├── settings.json
│       ├── config.yml
│       ├── models.json
│       ├── models.yml
│       └── sessions/
└── ssh/
```

## Persistence

The harness mounts `./.pi` at `/home/pi/.pi` for both runtimes. Pi uses this path natively; OMP is explicitly configured with `PI_CONFIG_DIR=.pi` and `PI_CODING_AGENT_DIR=/home/pi/.pi/agent`.

File ownership is intentionally split so both agents can coexist:

- `settings.json`, `models.json`, and `auth.json` belong to upstream Pi
- `config.yml`, `models.yml`, and `agent.db` belong to OMP
- `extensions/`, `extension-library/`, `themes/`, and shared resource links are visible to both

Do not remove `config.yml`: its presence prevents OMP from migrating and renaming Pi's `settings.json` on startup. OMP credentials are stored in ignored `agent.db` state and must not be committed.

This service persists that path from `./.pi`, including:

- `auth.json` for `/login` and provider auth state
- `settings.json` for global Pi settings
- `models.json` for custom/self-hosted provider definitions
- `sessions/` for saved session history
- `extensions/` for auto-loaded local extensions
- `extension-library/` for manually loaded extension bundles
- `themes/` for custom themes
- OMP databases, plugins, caches, and install identity (ignored by Git where appropriate)

## Shared Project Folder

Pi initializes its own home links to the shared `agent/` resource root when the container starts.

- Shared editable agent assets live in the shared root at `/opt/agent` with nested `commands/`, `prompts/`, and `skills/`
- Pi links `~/.pi/agent/{agents,prompts,skills}` and `~/.agents/*` back to that shared source
- Existing real home directories are preserved by moving them aside to `.local*` backups if they conflict during startup

## Starter Project Agent Teams and Chains

This repository now ships starter project-local orchestration assets under `.agents/agents/` (visible to Pi through the symlinked `.pi/agents/` path).

Included starter agents:
- `scout`
- `builder`
- `reviewer`
- `docs-writer`

Included starter team sets:
- `core`
- `delivery`
- `docs`
- `triage`

Included starter chains:
- `plan-build-review`
- `safe-infra-change`
- `docs-refresh`
- `triage-and-review`

Use them with:

```bash
./pi ext-agent-team
./pi ext-agent-chain
./pi ext-pi-pi
```

## Shared Home Defaults

Shared default agents, commands, and skills now live under the shared workspace `agent/` tree, mounted in the container as `/opt/agent`, and Pi links them into its home config during startup via `init.sh`.

- `../agent/` -> `~/.agents/agents` -> `~/.pi/agent/agents`
- `../agent/prompts/` -> `~/.agents/prompts` -> `~/.pi/agent/prompts`
- `../agent/skills/` -> `~/.agents/skills` -> `~/.pi/agent/skills`

## Common Flows

Authenticate with an API key from your shell or `.env`:

```bash
docker exec -it pi pi
docker exec -it pi omp
```

Authenticate using Pi's provider login flow:

```bash
pi login
# then run /login inside Pi
```

`pi login` publishes the fixed OAuth callback ports on `127.0.0.1` only for that login session:

- `1455` for OpenAI Codex
- `8085` for Google Gemini CLI
- `51121` for Google Antigravity
- `53692` for Anthropic

Normal `pi` sessions do not publish OAuth ports, so they do not block other workspaces.

If `pi login` says the OAuth ports are already in use, stop the other login-enabled Pi container and retry.

If `/login` opens a browser and lands on `localhost:1455/...` with a 404 or connection error, recreate the workspace container with `pi login`:

```bash
services/pi/pi-mgr remove pi-<workspace>
pi login
```

For OpenAI specifically, if Pi shows a prompt asking for the callback URL, copy the full browser URL after login and paste it back into Pi.

Configure local or self-hosted providers by editing:

```text
.pi/agent/models.json
.pi/agent/models.yml
```

Use `models.json` for Pi and `models.yml` for OMP. Both checked-in files define the same Ollama service endpoint.

For the local stack, the default config uses the Ollama container directly:

```text
http://ollama:11434/v1
```

This works because Pi now joins the same external Docker network as the `ollama` service. Do not use `localhost` here unless Ollama is running inside the same container.

If Ollama runs on another host, update both `./.pi/agent/models.json` (Pi) and `./.pi/agent/models.yml` (OMP) to that reachable URL, then rebuild/restart the container.

## Local UI Customizations

This Pi service now keeps local extension customizations in persisted state:

- Auto-loaded daily-driver extensions live in `./.pi/agent/extensions/`
- On-demand extension bundles live in `./.pi/agent/extension-library/`
- Custom themes live in `./.pi/agent/themes/`

Current auto-loaded stack:

- `cross-agent.ts`
- `first-prompt-title.ts`
- `session-replay.ts`
- `startup-table.ts`
- `subagent-widget.ts`
- `system-select.ts`
- `theme-cycler.ts`
- `tool-counter.ts` (footer shows context bar, current context token estimate, cumulative token/cost totals, and tool counts)
- `vim-chat-editor.ts`

Current on-demand bundle directory:

- `./.pi/agent/extension-library/pi-vs-claude-code/`
  - `tool-counter-widget.ts`
  - `subagent-widget.ts`
  - `agent-team.ts`
  - `agent-chain.ts`
  - `pi-pi.ts`

After changing files under `extensions/` or `themes/`, run `/reload` inside Pi.

Theme behavior:

- `./.pi/agent/settings.json` controls the persisted default theme (currently `nord`)
- The imported `themeMap.ts` helpers now respect that persisted theme for the auto-loaded extension stack, including built-in themes like `dark` and `light`
- When you launch Pi manually with explicit `-e` extension flags, the primary extension's mapped theme can still take over for that custom stack

Notable commands from the current default stack:

- `/theme` to pick or switch themes
- `/replay` to open session replay
- `/system` to switch persona/system prompt from discovered agent files
- `/startup-table-refresh`, `/startup-table-on`, and `/startup-table-off` to control the startup resource header
- `/sub <task>` to launch a background subagent widget
- `/subcont <id> <prompt>` to continue a finished subagent conversation
- `/subrm <id>` and `/subclear` to remove one or all subagent widgets
- cross-agent command discovery from `.claude/`, `.gemini/`, and `.codex/` command/agent folders when present

Named extension presets exposed by the host wrapper:

```bash
./pi ext-agent-team
./pi ext-agent-chain
./pi ext-pi-pi
./pi ext-agent-team /path/to/project -p "Draft the agent team layout for this repo"
./pi ext-pi-pi --login
```

These presets rebuild the current explicit daily-driver stack with `--no-extensions`, prepend the requested bundle (`agent-team.ts`, `agent-chain.ts`, or `pi-pi.ts`) so its mapped theme/title stays primary, and avoid double-loading the auto-discovered defaults.

Named `ext-*` presets remain Pi-only. OMP can load many legacy Pi extensions, but the orchestration extensions in this repository explicitly spawn the `pi` executable and use Pi-specific tool names. Under OMP, prefer its built-in `task` tool and Agent Hub until those extensions are deliberately ported.

If you are already inside the Pi container and want the raw Pi CLI, use the bundle files under `~/.pi/agent/extension-library/pi-vs-claude-code/` together with the explicit extension stack from `~/.pi/agent/extensions/`.

## Security Notes

- Container runs as non-root user (`pi:1000`)
- API keys are not baked into the image
- OMP auth stored in `.pi/agent/agent.db` is ignored and must be treated as secret state
- SSH keys are mounted read-only
- Pi intentionally operates with minimal built-in safety rails; use container isolation as your boundary
- This image keeps parity with the existing agent containers and allows sudo inside the container

## Troubleshooting

### Upgrade OMP

OMP and Bun are pinned by Docker build arguments. Upgrade by changing the defaults in `Dockerfile`, rebuilding, and recreating containers; do not run `omp update` inside a durable container.

```bash
docker build \
  --build-arg BUN_VERSION=1.4.0 \
  --build-arg OMP_VERSION=18.0.4 \
  -t lab/pi:latest .
./pi fclean
```

`omp setup` is interactive. Run it after the container starts (`./pi --oh`), never during image construction. Workspace-native OMP configuration still belongs in each project's `.omp/` directory; only the user-level root is redirected to `.pi`.

Image missing:

```bash
docker compose build
```

Container logs:

```bash
docker compose logs pi
```

Permission issue on workspace:

```bash
sudo chown -R 1000:1000 workspace/
```
