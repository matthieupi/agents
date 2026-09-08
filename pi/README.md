# Pi lifecycle — native VM and retained Docker workflows

## Native lifecycle

**Native UI and CLI launch with LOCAL execution under `PI_USER`.**
This is not a remote-only adapter or an agent sandbox. Remote-only DevAI activation
still requires validated adapters and containment. This pass installs only Pi and
Pi Web; OpenCode/OMP native porting is deferred. Docker files, wrappers, `init.sh`,
and the checked-in `.pi` tree remain independent and unchanged.

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
  Linux needs compilation. Ansible supplies compiler/Python/Node headers;
  dependency scripts run as `PI_USER`, with `--ignore-scripts=false`.

### Ownership and configuration contract

```text
Ansible: accounts + OS packages/pins + checkout + unit + environment
                         |
                         v
PI_USER: entrypoint.sh install --> pi/.runtime + missing home defaults
PI_USER: start.sh              --> foreground pi-web / interactive pi
```

The checkout is the **whole agents repository**, user-owned and editable. Root
must never execute its Pi scripts or Git. There is no root provisioning command,
build account, shared native framework or manifest. Administrators use protected
systemctl directly; these editable scripts never control services.

| Input | Contract |
|---|---|
| `PI_USER` | Existing named non-root account; process UID must match exactly |
| `PI_REPO` | Default `/srv/agents`; canonical absolute checkout owned by PI_USER |
| `PI_ROOT` | Default `$PI_REPO/pi`; must equal that component path |
| `PI_PREFIX` | Default `$PI_ROOT/.runtime`; must equal that generated runtime path |
| `PI_UNIT` | Default `pi.service`; existing Ansible-owned unit, read-only status only |
| `PI_WORKSPACE` | Required at launch: existing canonical directory outside the Pi component; the whole editable checkout may be the workspace |
| `PI_BRANCH` | Required for explicit updates; assigned local branch, e.g. `agents/devai-team` |
| `PI_PREVIOUS_REPO` | Optional install/initialize-home migration input; previous checkout, e.g. `/srv/pi/repo` |
| `PI_PORT` | Required service port, decimal `1024..65535`, no leading zeroes |
| `PI_WEB_PASSWORD` | Required service secret; never placed on argv |
| `PI_WEB_ALLOWED_HOSTS` | Exact proxy hostnames if needed; does not change loopback binding |

HOME comes from `getent passwd`, must be owned by PI_USER, and must not overlap
the checkout. Canonical paths outside `/opt` are required; redirected private
Pi state is refused. Scripts do not source `.env` or root-only service secrets.
Ansible supplies separate install and runtime environments. Provider/web variables
remain available to launched sessions/services, but never to npm build children.

### Commands and installation

All native commands run explicitly **as PI_USER**, never root:

```bash
bash "$PI_REPO/pi/scripts/entrypoint.sh" install
bash "$PI_REPO/pi/scripts/entrypoint.sh" initialize-home
bash "$PI_REPO/pi/scripts/start.sh" session -p "Review this checkout"
bash "$PI_REPO/pi/scripts/start.sh" service
bash "$PI_REPO/pi/scripts/manage.sh" status
bash "$PI_REPO/pi/scripts/manage.sh" version
bash "$PI_REPO/pi/scripts/manage.sh" update-check "$REVIEWED_FULL_SHA"
bash "$PI_REPO/pi/scripts/manage.sh" update "$REVIEWED_FULL_SHA"
```

Ansible exclusively supplies system Node >=22.19.0, `/usr/bin/npm`, Git, Bash,
coreutils, flock, getent, compiler/Python/headers and certificates. No APT work or
OS pins are implemented here; `PI_BUILD_USER` is no longer used.

Install stages npm under `$PI_ROOT/.build.*`, using `env -i`, an empty HOME/cache
and **distinct empty npm user/global config files**. The install timeout is 600
seconds with a kill grace; verification calls are bounded too. Package metadata,
`pi --version`, Pi Web help and native PTY loading are checked before reuse or
promotion. A matching runtime is reused. Install does **not** require a clean
checkout, so agent edits and branch commits survive reapply.

Build/verification failure leaves the existing runtime untouched and retains the
ignored stage/logs. Promotion failure attempts to restore the previous runtime;
the promoted path is verified again before removing the stage. The two renames
are not crash-atomic: after interruption inspect `.build.*/previous` before
recovery. Install then initializes missing home defaults as the same user. It
never starts/stops a service. Drain sessions and stop the concerned unit through
administrator-owned tools before replacing an in-use runtime.

The runtime, build directories and `.lifecycle.lock` are Git-ignored. A shared Pi
lock serializes install, standalone initialization and explicit updates; it does
not coordinate arbitrary user edits or direct systemctl calls. Dependency scripts
are trusted supply-chain code with PI_USER's filesystem access, **not sandboxed**
by the clean environment. Exact top-level versions do not fully lock transitive
dependencies. Real concerned-host package/service validation remains required.

### Explicit Git updates and home preservation

Updates require a clean tracked/untracked tree, the assigned `PI_BRANCH`, and a
full lowercase SHA. Ignored runtime/build state is allowed. Both commands fetch
the assigned origin branch without tags; the requested SHA must be on its history
and a descendant of local HEAD. `update-check` leaves HEAD unchanged. `update`
uses `merge --ff-only --no-overwrite-ignore`, preserving the branch and refusing
divergence or ignored-file collisions. No reset, clean, forced checkout, commits,
pushes, config writes, dependency installs or service actions. Git output from
fetch is suppressed to avoid exposing credential-bearing URLs. Branch selection
does not enforce GitHub permissions; infrastructure owns source approval and any
future server-side publication restrictions.

`initialize-home` retains `~/.pi/agent`, auth, sessions, databases, model settings
and real user resource directories. Only `agents`, `prompts`, `skills` links whose
literal targets match the new checkout or explicitly supplied previous checkout
are reused/repointed. Unknown links and real directories are preserved with a
notice. No `.agents` discovery tree is created or removed.

Only missing tracked settings, TypeScript extensions and JSON themes are copied
from the committed checkout defaults. Existing files, including concurrently
created files, win. No auth, sessions, OMP config/databases, Docker model endpoints
or ignored npm state are seeded. Linked shared resources reflect checkout edits;
copied defaults/private config do not automatically change with later repo edits.
Review and merge those deliberately. Generated runtime packages are not commit-back
source, and this checkout is not the upstream npm packages' source history.

Migration retains the existing passwd home and `/srv/pi/repo`, `/srv/pi/runtime`,
unit and service credentials for protected-SHA rollback. These scripts neither
delete nor rewrite the old deployment. Publication and live cutover require later
explicit approval and infrastructure's normal source preflight.

### Launch behavior and verification

```text
cd "$PI_WORKSPACE"
pi-web --hostname 127.0.0.1 --port "$PI_PORT" --no-open   # service
pi [arguments...]                                      # session
```

The [pinned Pi CLI](https://github.com/earendil-works/pi/blob/d981de1229ef899957bbe968bc8dcda02a21f477/packages/coding-agent/src/main.ts)
uses cwd for new sessions; resuming may select saved cwd. The UI launches Next
from the installed package directory, not PI_WORKSPACE; choose the project in
the UI. Shell cwd is not UI isolation. A Pi tool extension alone does not cover
UI filesystem/Git/terminal routes. Keep remote-only activation disabled until
adapters, authenticated proxy transport and containment are validated separately.

```bash
python3 -B -m unittest discover -s pi/tests -v
for script in pi/scripts/*.sh; do bash -n "$script"; done
```

Tests use non-root temporary Git/build/launch fixtures and a real npm config-only
probe. They do not install controller dependencies or change live services. The
actual-root refusal test skips on non-root runners; fixture Git/install tests
skip on root runners. Docker workflows below retain their original lifecycle.

## Retained Docker workflows

The rest of this document describes the container lifecycle only; its
paths and security assumptions do not apply to native VMs.

Dockerized [Pi](https://pi.dev) for local and remote development workflows.
OMP now has its own [standalone Docker CLI component](../omp/README.md), image,
wrappers and state. `pi --oh` and `pi-run --agent-cli` are removed; use `../omp/omp`.
This is a source extraction, not a live cutover: existing images/containers still
need deliberate rebuilding/recreation. Never delete old state as part of that work.

## Quick Start

```bash
# 1. Configure
cp .env.example .env

# 2. Create a workspace directory if you want a default bind mount
mkdir -p workspace

# 3. Build and start
docker compose up -d --build

# 4. Attach to Pi
docker exec -it pi pi
```

## Wrapper Usage

The `pi` wrapper manages per-workspace containerized instances.

```bash
./pi
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
│       ├── config.yml       # retained legacy OMP rollback sentinel
│       ├── models.json
│       ├── models.yml       # retained legacy OMP defaults
│       └── sessions/
└── ssh/
```

## Persistence

The harness mounts `./.pi` at `/home/pi/.pi` for vanilla Pi only.
`settings.json`, `models.json`, `keybindings.json`, `auth.json`, extensions,
themes and Pi sessions stay here. No OMP state is mounted by the new OMP component.

**Legacy migration hold:** tracked `config.yml` and `models.yml`, their ignore
exceptions, and all ignored OMP state are intentionally retained pending the
[offline migration preflight](../omp/README.md#offline-migration-and-rollback).
Keep `config.yml`: old OMP images may otherwise migrate/rename Pi settings on
rollback. Legacy `agent.db` contains secrets; never commit it or copy the entire
Pi state into OMP. Nothing performs an automatic migration.

This service persists that path from `./.pi`, including:

- `auth.json` for `/login` and provider auth state
- `settings.json` for global Pi settings
- `models.json` for custom/self-hosted provider definitions
- `sessions/` for saved session history
- `extensions/` for auto-loaded local extensions
- `extension-library/` for manually loaded extension bundles
- `themes/` for custom themes
- legacy OMP private files remain protected but are not used by this Pi image

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
```

Use `models.json` for Pi. The retained OMP YAML is historical rollback state,
not active Pi configuration.

For the local stack, the default config uses the Ollama container directly:

```text
http://ollama:11434/v1
```

This works because Pi now joins the same external Docker network as the `ollama` service. Do not use `localhost` here unless Ollama is running inside the same container.

If Ollama runs on another host, update `./.pi/agent/models.json` to that reachable URL.
OMP provider configuration is independent under `../omp/.omp/agent/models.yml`.

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

Named `ext-*` presets remain Pi-only. The standalone OMP component does not
install these extensions; they explicitly spawn `pi` and use Pi-specific APIs.

If you are already inside the Pi container and want the raw Pi CLI, use the bundle files under `~/.pi/agent/extension-library/pi-vs-claude-code/` together with the explicit extension stack from `~/.pi/agent/extensions/`.

## Security Notes

- Container runs as non-root user (`pi:1000`)
- API keys are not baked into the image
- Legacy `.pi/agent/agent.db` is ignored secret state, retained for offline migration/rollback
- SSH keys are mounted read-only
- Pi intentionally operates with minimal built-in safety rails; use container isolation as your boundary
- This image keeps parity with the existing agent containers and allows sudo inside the container

## Troubleshooting

OMP build/setup instructions now live in [OMP's README](../omp/README.md).
Rebuilding Pi does not migrate or retire legacy OMP state.

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
