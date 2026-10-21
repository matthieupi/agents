# Claude Code - Containerized AI Coding Assistant

Dockerized [Claude Code](https://docs.anthropic.com/en/docs/claude-code) for local and remote development workflows.

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY

# 2. Create workspace
mkdir -p workspace

# 3. Build & start
docker compose up -d --build

# 4. Attach to Claude Code
docker exec -it claude-code claude
```

## Usage Patterns

### Interactive TUI (default)

```bash
docker exec -it claude-code claude
```

### One-shot command

```bash
docker exec claude-code claude "explain this codebase"
```

### With specific project

```bash
docker exec -it claude-code claude /workspace/my-project
```

### Resume session

```bash
docker exec -it claude-code claude --continue
```

## Directory Structure

```
claude-code/
├── Dockerfile              # Container definition
├── docker-compose.yml      # Service orchestration
├── .env.example            # Environment template
├── .env                    # Your config (git-ignored)
├── .claude/                # Claude auth state and runtime config
├── ssh/                    # SSH keys for remote access
│   ├── id_ed25519          # Agent private key
│   ├── id_ed25519.pub      # Agent public key
│   ├── config              # SSH client config
│   └── known_hosts         # Known host keys
└── workspace/              # Your projects (mounted)
```

## Configuration

### Shared project agent folder

On startup, this service bootstraps a shared project folder at `/workspace/.agents` and keeps it as the source of truth for shared project-local agents, prompts, and skills.

- Shared resources live in `.agents/agents`, `.agents/commands`, and `.agents/skills`
- `.agents/prompts` is created as a compatibility symlink to `.agents/commands`
- `/workspace/.claude` stays as a real harness-specific directory, but `/workspace/.claude/agents`, `/workspace/.claude/commands`, and `/workspace/.claude/skills` are linked into `.agents`
- Existing real resource directories are preserved by moving them aside to `.local*` backups if they conflict during the first bootstrap

### Shared home defaults

Claude keeps `~/.claude` as its normal config directory, and links shared resources from `~/.agents` into it.

Shared default agents, commands, and skills come from the shared workspace root `../agent`, and Claude links its home config directly to that shared source during startup via `init.sh`.

- `../agent/` -> `~/.agents/agents` -> `~/.claude/agents`
- `../agent/commands/` -> `~/.agents/commands` -> `~/.claude/commands`
- `../agent/prompts/` -> `~/.agents/prompts`
- `../agent/skills/` -> `~/.agents/skills` -> `~/.claude/skills`

The shared root is mounted at `/opt/agent`, and Claude's `~/.claude/{agents,commands,skills}` paths point back to that shared source.

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | API key from console.anthropic.com |
| `WORKSPACE_PATH` | No | Project directory (default: `./workspace`) |
| `GIT_AUTHOR_NAME` | No | Git commit author name |
| `GIT_AUTHOR_EMAIL` | No | Git commit author email |
| `SSH_DIR_PATH` | No | SSH directory for remote access (default: `./ssh`) |
| `GITCONFIG_PATH` | No | Path to .gitconfig |

### Settings (`.claude/settings.json`)

```json
{
  "permissions": {
    "allow_file_read": true,
    "allow_file_write": true,
    "allow_bash": true,
    "trust_mode": "prompt"
  },
  "model": {
    "default": "claude-sonnet-4-20250514"
  }
}
```

## SSH Access to Remote Machines

The agent has a dedicated SSH key for accessing test/remote machines with limited permissions.

### SSH Directory Structure

```
ssh/
├── id_ed25519          # Private key (claude-agent@xmist.dev)
├── id_ed25519.pub      # Public key (add to target machines)
├── config              # SSH client configuration
├── known_hosts         # Known host keys
└── authorized_keys     # Keys allowed to access this agent
```

### Granting Access to a Remote Machine

1. Copy the agent's public key:
```bash
cat ssh/id_ed25519.pub
```

2. Add it to the target machine's authorized_keys:
```bash
# On target machine
echo "ssh-ed25519 AAAA... claude-agent@xmist.dev" >> ~/.ssh/authorized_keys
```

3. Configure host aliases in `ssh/config`:
```
Host test-server
    HostName 192.168.1.100
    User deploy
    IdentityFile ~/.ssh/id_ed25519
```

4. The agent can now SSH:
```bash
ssh test-server
```

## Security Notes

- Container runs as non-root user (`claude:1000`)
- `no-new-privileges` and `cap_drop: ALL` applied
- API key never baked into image
- SSH keys mounted read-only
- Workspace is the only writable mount (besides config)
- Agent SSH key is separate from personal keys for isolation

## Network

Default: joins `devai-xmist` external network. For standalone:

```yaml
networks:
  devai-xmist:
    driver: bridge
```

## Troubleshooting

### "ANTHROPIC_API_KEY required"
```bash
cp .env.example .env
# Add your key to .env
```

### Permission denied on workspace
```bash
sudo chown -R 1000:1000 workspace/
```

### Container won't start
```bash
docker compose logs claude-code
```

## License

MIT
