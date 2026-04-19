# Pi - Containerized Coding Agent

Dockerized [Pi](https://pi.dev) for local and remote development workflows.

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
│       ├── models.json
│       └── sessions/
└── ssh/
```

## Persistence

Pi keeps `~/.pi/agent` as its canonical config/state directory and links shared resources from `~/.agents` into it.

This service persists that path from `./.pi`, including:

- `auth.json` for `/login` and provider auth state
- `settings.json` for global Pi settings
- `models.json` for custom/self-hosted provider definitions
- `sessions/` for saved session history
- `extensions/` for auto-loaded local extensions
- `extension-library/` for manually loaded extension bundles
- `themes/` for custom themes

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

For the local stack, the default config uses the Ollama container directly:

```text
http://ollama:11434/v1
```

This works because Pi now joins the same external Docker network as the `ollama` service. Do not use `localhost` here unless Ollama is running inside the same container.

If Ollama runs on another host, update `./.pi/agent/models.json` to that reachable URL and rebuild/restart the Pi container.

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

If you are already inside the Pi container and want the raw Pi CLI, use the bundle files under `~/.pi/agent/extension-library/pi-vs-claude-code/` together with the explicit extension stack from `~/.pi/agent/extensions/`.

## Security Notes

- Container runs as non-root user (`pi:1000`)
- API keys are not baked into the image
- SSH keys are mounted read-only
- Pi intentionally operates with minimal built-in safety rails; use container isolation as your boundary
- This image keeps parity with the existing agent containers and allows sudo inside the container

## Troubleshooting

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
