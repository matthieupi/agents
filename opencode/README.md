# OpenCode - Native and Container Workflows

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
promotion. Matching runtime reuse and installation allow dirty checkouts. Failed
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
`plugin/`/`plugins/` files, excluding caches/node_modules. Either existing config
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

## Docker workflow (existing)

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Edit .env with your API keys

# 2. Create workspace
mkdir -p workspace

# 3. Build & start
docker compose up -d --build

# 4. Attach to OpenCode
docker exec -it opencode opencode
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

### Agent-started Browser UI

Pre-publish a LAN-accessible port when the container starts, then ask the
agent inside that container to start the web server later:

```bash
OPENCODE_SERVER_PASSWORD=secret ./opencode --agent-web-port 4096 /path/to/project
```

The wrapper checks that the host port is free before creating the container,
publishes `0.0.0.0:4096 -> container 4096`, and exposes these environment
variables to the agent:

```bash
OPENCODE_AGENT_WEB_PORT=4096
OPENCODE_AGENT_WEB_BIND_HOST=0.0.0.0
OPENCODE_AGENT_WEB_URL=http://localhost:4096
```

Inside OpenCode, run `/start-web` to launch the server on the pre-published
port. Because this mode exposes the web server on the LAN by default, set
`OPENCODE_SERVER_PASSWORD` before using it on a shared network.

### Rebuild image

```bash
./opencode -r .                 # Rebuild CPU and GPU images
./opencode rebuild              # Rebuild image + refresh workspace containers
./opencode rebuild gpu          # Rebuild CUDA devel GPU image + refresh containers
./opencode rebuild all          # Rebuild CPU and GPU images + refresh containers
```

### Dangerous mode (auto-approve all permissions)

```bash
./opencode -d                   # Skip permission prompts
```

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
