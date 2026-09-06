# OpenCode - Native and Container Workflows

[OpenCode](https://opencode.ai/) for local and remote development workflows. Native lifecycle scripts are independent of the existing Docker wrappers and do not modify Docker configuration or state.

## Native lifecycle

Native UI and CLI execute **locally** with the supplied account's permissions;
they are not a sandbox or remote-only adapter. Remote-only DevAI deployment must
remain disabled in Ansible until its adapter and containment are validated.

The default native deployment is `/srv/opencode`. Use a **dedicated root-owned clone of the agents repository**, not an agent-editable workspace or a Git worktree/submodule checkout with a `.git` file. The scripts require an existing named non-root account and home; they never create accounts, grant sudo, install units, or write login hooks.

```text
Ansible (account, checkout, pins, unit, secrets, login hook, proxy/TLS/access)
    |
    +-- root: entrypoint.sh provision ----> pinned runtime + non-root home setup
    +-- root: manage.sh -----------------> systemd / locked Git checkout update
    |
    +-- User=opencode: start.sh service --> exec opencode web (127.0.0.1)
    +-- login user:    start.sh session --> exec opencode [CLI arguments]

/srv/opencode/
  repo/agent/{commands,skills,system,gsd}  shared resources, root-owned
  repo/opencode/scripts/                 this native lifecycle
  runtime/                               root-owned npm prefix
  .lifecycle.lock                        shared provision/update lock
<account home>/.config/opencode/          preserved user config + direct resource links
<account home>/.local/share/opencode/     private sessions and authentication
<account home>/.cache/opencode/           private runtime/plugin cache
```

### Exact environment contract

These are process environment variables, **not a shell file sourced by the scripts**. Ansible should pass provisioning/management inputs through its command environment. systemd reads its own protected `EnvironmentFile`; login hooks supply the session environment separately.

| Variable | Required / default | Consumer |
|---|---|---|
| `OPENCODE_USER` | Required existing named account; UID must not be 0 | All scripts |
| `OPENCODE_ROOT` | `/srv/opencode` | All scripts; lock and temporary installer files |
| `OPENCODE_REPO` | `${OPENCODE_ROOT}/repo` | All scripts; agents repository root, not `opencode/` |
| `OPENCODE_PREFIX` | `${OPENCODE_ROOT}/runtime` | All scripts; npm runtime prefix, disjoint from checkout |
| `OPENCODE_UNIT` | `opencode.service`; simple name ending in `.service` | Provision and management |
| `OPENCODE_VERSION` | Required exact stable `X.Y.Z`; example: `1.2.15` | Provision only |
| `OPENCODE_APT_PACKAGES` | Required single-line whitespace-separated `package=version` pins | Provision only |
| `OPENCODE_WORKSPACE` | Required existing absolute directory; supplied account needs access | Service/session |
| `OPENCODE_PORT` | Required decimal `1024..65535`, without leading zeroes | Service only |
| `OPENCODE_SERVER_PASSWORD` | Required nonempty secret; never placed in CLI arguments | Service only |
| `OPENCODE_SERVER_USERNAME` | Optional upstream Basic Auth username (upstream default `opencode`) | Service |
| Provider credentials, e.g. `OPENAI_API_KEY` | Supplied securely by Ansible or user authentication | Service/session |

Account home/UID/GID come from `getent passwd`; HOME is not a deployment input. Start sets `HOME`, `USER`, `LOGNAME`, XDG home directories, `OPENCODE_CONFIG_DIR=<account home>/.config/opencode`, `OPENCODE_DISABLE_AUTOUPDATE=1`, and PATH beginning with the runtime prefix. It removes `OPENCODE_BIN_PATH` so an inherited value cannot redirect the executable. Paths must be canonical absolute paths; native paths under `/opt` are rejected. Use a dedicated native account/home, not Docker-mounted config/state.

### Provisioning and installation pins

Supported bootstrap host: Debian/Ubuntu with Bash, apt, coreutils (`timeout`, `realpath`, `stat`), findutils, util-linux (`flock`, `runuser`), Git, getent, and systemd already available. Ansible creates the account/home, root-owned deployment directories/clone, workspace, and **inactive unit first**. Checkout/runtime and their ancestors must not be group/world-writable. The runtime account must have read/traverse access to the checkout and write access only to its home/workspace, not deployment files.

`OPENCODE_APT_PACKAGES` must include exact pins for each of:

```text
ca-certificates git nodejs npm ripgrep python3 python3-venv openssh-client
```

Use versions available in the selected distribution/snapshot repository (inspect `apt-cache policy PACKAGE` on the target); there are deliberately no invented cross-distribution version defaults. Additional apt tools may be included, but every entry needs an exact version. These pins constrain requested packages, not every transitive OS dependency. Node/npm compatibility is the operator's responsibility. Terraform, Ansible, browser bundles, CUDA, and other optional coding tools are not implicitly installed; provision them separately with approved pins if the workload needs them.

Provisioning performs bounded apt operations and installs `opencode-ai@$OPENCODE_VERSION` into the root-owned prefix using npm's public HTTPS registry, optional platform packages, and **`--ignore-scripts`**. It uses an empty installer environment/private cache and does not load account/workspace `.npmrc` files. It then initializes the home and verifies the requested CLI version via `runuser`, never by running OpenCode as root. Installer network operations are bounded at 600 seconds each; failed installs may leave partially changed dependencies. No unit is automatically started.

The package must support installation with scripts disabled and resolution of its optional platform binary without a postinstall hook. See the example version's [published package metadata](https://registry.npmjs.org/opencode-ai/1.2.15), [web command](https://github.com/anomalyco/opencode/blob/v1.2.15/packages/opencode/src/cli/cmd/web.ts), and [network option precedence](https://github.com/anomalyco/opencode/blob/v1.2.15/packages/opencode/src/cli/network.ts). Validate real installation, `--version`, and loopback binding on the concerned host for the approved version; mocked tests do not establish upstream runtime compatibility.

### Ansible-owned unit and login contract

Concrete default-path unit shape (Ansible must render overrides consistently):

```ini
[Unit]
Description=Native OpenCode web
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=opencode
Group=opencode
EnvironmentFile=/etc/opencode/service.env
ExecStart=/bin/bash /srv/opencode/repo/opencode/scripts/start.sh service
Restart=on-failure
RestartSec=5
KillMode=control-group
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/home/opencode /srv/workspaces/opencode
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Ansible-owned `/etc/opencode/service.env` (root:root `0600`, parent root-owned; values rendered directly, no variable expansion):

```ini
OPENCODE_USER=opencode
OPENCODE_ROOT=/srv/opencode
OPENCODE_REPO=/srv/opencode/repo
OPENCODE_PREFIX=/srv/opencode/runtime
OPENCODE_UNIT=opencode.service
OPENCODE_WORKSPACE=/srv/workspaces/opencode
OPENCODE_PORT=4096
# Ansible securely renders OPENCODE_SERVER_PASSWORD and provider credentials here.
```

The password comment is not a usable secret: the unit intentionally fails until a password is supplied. Keep secrets out of Git, shell history, command arguments, and provisioning logs; use Ansible `no_log` where it handles them. Journal access is controlled by the host and can expose application output. This unit is a baseline, not an agent sandbox: review workspace access and additional hardening for the workload. No passwordless sudo is required or granted.

The service changes to `OPENCODE_WORKSPACE` and foreground-execs:

```text
opencode web --hostname 127.0.0.1 --port <supplied port> --mdns false
```

No extra service CLI flags are accepted. Ansible owns TLS termination, WebSocket-capable proxying, authentication/access policy, and firewall rules. A proxy must reach the **host's** loopback (a bridge-networked container's `127.0.0.1` is not the host); do not solve that mismatch by exposing OpenCode publicly. Host-local users can reach this socket, hence the required upstream password as defense in depth.

Login hooks invoke `/bin/bash /srv/opencode/repo/opencode/scripts/start.sh session` **as the supplied account**, with its workspace/provider environment. There is no installation, privilege escalation, or implicit service attachment. CLI arguments are passed unchanged. An administrator can explicitly use `runuser -u opencode -- env OPENCODE_USER=opencode OPENCODE_WORKSPACE=/srv/workspaces/opencode /bin/bash /srv/opencode/repo/opencode/scripts/start.sh session`; provision credentials separately rather than adding secrets to that command line.

### Home resources, plugins, and updates

Native home initialization runs only during provisioning, as the account. It directly links `commands`, `skills`, `system`, and `gsd` to the checkout's `agent/` tree. It creates no `~/.agents` discovery links and removes only existing links that resolve to the identical shared target. Conflicting real directories or unrelated links are preserved and cause a clear failure; reconcile them deliberately. Redirected config roots are refused rather than modifying Docker config. Shared markdown agent definitions remain harness-specific.

The account must own its home. Workspace paths must also be canonical and outside `/opt`. Existing plugin-directory symlinks are never followed to seed missing files. If either `opencode.json` or `opencode.jsonc` exists, neither format is seeded, preventing defaults in the other format from overriding local settings. Existing credentials are not read, migrated, or rewritten.

Only missing, tracked `opencode.json[ c ]` (specifically `opencode.json` / `opencode.jsonc`), `tui.json`, package manifests/lockfile, and files under `plugin/` or `plugins/` are seeded. Existing config/plugin files are **never overwritten**, including their plugin lists. Ignored auth/state and `node_modules`/`.cache` trees are not copied. Existing local configs/plugins therefore do not automatically acquire later repository edits: review and merge defaults manually. OpenCode itself may resolve plugins and write user-owned caches during normal startup; the lifecycle does not promise offline or fully reproducible plugin dependencies. Restart services/sessions after config changes.

Management commands (supply the same non-secret contract environment):

```text
manage.sh start | stop | restart    root only, delegates to the named unit
manage.sh status                   systemctl status; preserves nonzero inactive status
manage.sh logs                     last 100 journal entries, no pager/follow
manage.sh version                  CLI version, always under the supplied non-root account
manage.sh update-check FULL_SHA     root; fetch/compare without checking out
manage.sh update FULL_SHA           root; clean checkout and stopped unit required
```

Service start/restart take the same nonblocking lifecycle lock as provisioning and updates. Emergency `stop` requires only root authorization and a valid `OPENCODE_UNIT` (default `opencode.service`): no account/home contract, recursive checkout/runtime audit or lifecycle lock. The lock prevents start/update races through these scripts, not direct systemctl calls or external deployment tools. Interactive sessions must be closed separately.

`update-check` and `update` require a full lowercase 40-character commit SHA and serialize with provisioning using a nonblocking lock. Fetch uses the administrator-managed `origin`, disables interactive Git credential prompts, and has a 120-second timeout; errors omit remote URLs. Checking updates may write Git objects/FETCH_HEAD. A commit already present locally may be satisfied by Git without contacting the remote; SHA selection is administrator approval, **not signature verification**.

Recommended sequence: `update-check SHA`, stop the unit and close interactive sessions, `update SHA`, run `entrypoint.sh provision` with approved pins, start, then verify the unit and authenticated proxy endpoint. Update refuses tracked/untracked changes, detaches at the exact commit, and uses `--no-overwrite-ignore` to protect ignored-file collisions. It does not copy the checkout or ignored state. It does not provision dependencies or restart automatically. **There is no automatic rollback**: apt/npm/plugin changes and OpenCode data migrations are not transactional. A failed provisioning leaves the unit stopped for operator recovery; Git checkout recovery alone does not restore runtime dependencies or state.

### Verification

Missing defaults are read into private temporary files before exclusive publication.
A failed Git read leaves no partial destination; content created concurrently at
the destination is preserved rather than overwritten.

```bash
bash -n opencode/scripts/{entrypoint,start,manage}.sh
python3 -B -m unittest discover -s opencode/tests -v
# If installed:
shellcheck -x -P opencode/scripts opencode/scripts/{entrypoint,start,manage}.sh
```

Run from the agents repository root as a non-root user. Tests mock host/system commands and account lookup, and use real temporary Git repositories/locks. They never install host packages, create accounts, or start services. Real systemd, apt provisioning, TLS/proxy, provider authentication, and plugin initialization require a separate targeted integration run on the concerned host before wider deployment.

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
  "model": "openai/gpt-5.6-sol",
  "small_model": "openai/gpt-5-mini",
  "permission": "allow",
  "provider": {
    "openai": {
      "options": { "apiKey": "{env:OPENAI_API_KEY}" }
    }
  }
}
```

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
