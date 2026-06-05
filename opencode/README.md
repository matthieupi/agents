# OpenCode - Containerized AI Coding Assistant

Dockerized [OpenCode](https://opencode.ai/) for local and remote development workflows.

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
- OpenCode links `~/.config/opencode/{commands,skills}` and `~/.agents/*` back to that shared source
- Existing real home directories are preserved by moving them aside to `.local*` backups if they conflict during startup

### Arbitrary config directory

Yes: OpenCode supports an arbitrary config directory through `OPENCODE_CONFIG_DIR`, but this service now keeps the default home path so behavior stays aligned with Claude-style home + project discovery.

This service sets:

```bash
OPENCODE_CONFIG_DIR=/home/opencode/.config/opencode
```

This service keeps `~/.config/opencode` as the active config directory and links shared resources from `~/.agents` into it during startup via `init.sh`.

Project-shared resources come directly from `/opt/agent`, so you do not need a separate project `.opencode/` for shared commands/skills.

OpenCode does not share markdown `agents/` definitions with Claude/Pi. Its agent schema is different, so this bootstrap only shares `commands/` and `skills/` with OpenCode and leaves `.opencode/agents/` harness-specific.

### Shared home defaults

Shared default agents, commands, and skills live under the shared workspace `agent/` tree, mounted in the container as `/opt/agent`, and OpenCode links them into its home config during startup via `init.sh`.

- `../agent/commands/` -> `~/.agents/commands` -> `~/.config/opencode/commands`
- `../agent/skills/` -> `~/.agents/skills` -> `~/.config/opencode/skills`

Only the `prompts/commands` and `skills/` defaults are applied to OpenCode. Shared `agents/` stay Claude/Pi-only unless they are converted to OpenCode's native schema.

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
  "model": "anthropic/claude-sonnet-4-5",
  "small_model": "anthropic/claude-haiku-4-5",
  "permission": "allow",
  "provider": {
    "anthropic": {
      "options": { "apiKey": "{env:ANTHROPIC_API_KEY}" }
    }
  }
}
```

### Supported Providers

OpenCode supports 75+ providers. Common ones pre-configured:
- **Anthropic** (Claude) - via `ANTHROPIC_API_KEY`
- **OpenAI** (GPT-4) - via `OPENAI_API_KEY`
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
