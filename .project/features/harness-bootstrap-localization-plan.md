# Harness Bootstrap Localization Plan

## Goal

Remove the shared `/workspace/bootstrap.sh` bootstrap entrypoint and move startup wiring into each harness repository.

After this change:
- `/workspace/{agents,commands,prompts,skills}` remains shared data only
- each harness owns its own home initialization and workspace compatibility wiring
- startup behavior is readable and maintainable from the harness that actually consumes it

## Current State

Today all three harnesses call the same shared bootstrap script:

- `claudecode/docker-compose.yml`
- `claudecode/claude-run`
- `pi/docker-compose.yml`
- `pi/pi-run`
- `opencode/docker-compose.yml`
- `opencode/opencode-run`

That script currently does two jobs:

1. Home bootstrap
   - creates harness-specific config directories
   - seeds shared defaults from `/opt/agents/{agents,commands,skills}`
   - links `~/.agents/*` into the harness home config

2. Workspace bootstrap
   - creates `/workspace/.agents/{agents,commands,skills}`
   - creates `/workspace/.agents/prompts -> commands`
   - links each harness's project-local compatibility directories back into `/workspace/.agents`

This centralizes behavior, but it also mixes three different harness models into one cross-harness script.

## Target Design

Delete the shared bootstrap script and replace it with harness-local init scripts:

- `claudecode/init.sh`
- `pi/init.sh`
- `opencode/init.sh`

Each init script should:
- contain only the logic relevant to that harness
- initialize both home state and workspace compatibility paths
- preserve non-destructive migration behavior via `.local*` backups
- treat `commands` as canonical and `prompts` as compatibility-only

The shared root at `/workspace` becomes a dumb resource bundle only:

- `agents/`
- `commands/`
- `prompts -> commands`
- `skills/`

## Shared Invariants

These rules should remain true after the refactor:

- `commands` is the canonical shared command/prompt directory
- `prompts` exists only as a compatibility symlink to `commands`
- `/workspace/.agents` is the project-local shared source of truth
- existing real directories are never overwritten destructively; they are moved aside to `.local*`
- OpenCode continues to share `commands` and `skills`, but not markdown `agents`

## Per-Harness Responsibilities

### Claude

Own only Claude-specific initialization.

Home responsibilities:
- ensure `/home/claude/.claude`
- ensure `/home/claude/.claude/{agents,commands,skills}`
- seed from `/opt/agents/{agents,commands,skills}`
- ensure `/home/claude/.agents`
- link:
  - `/home/claude/.agents/agents` -> `/home/claude/.claude/agents`
  - `/home/claude/.agents/commands` -> `/home/claude/.claude/commands`
  - `/home/claude/.agents/skills` -> `/home/claude/.claude/skills`
  - `/home/claude/.agents/prompts` -> `commands`

Workspace responsibilities:
- ensure `/workspace/.agents/{agents,commands,skills}`
- ensure `/workspace/.agents/prompts -> commands`
- ensure `/workspace/.claude`
- link:
  - `/workspace/.claude/agents` -> `/workspace/.agents/agents`
  - `/workspace/.claude/commands` -> `/workspace/.agents/commands`
  - `/workspace/.claude/skills` -> `/workspace/.agents/skills`

### Pi

Own only Pi-specific initialization.

Home responsibilities:
- ensure `/home/pi/.pi/agent`
- ensure `/home/pi/.pi/agent/{agents,prompts,skills}`
- seed:
  - `agents` from `/opt/agents/agents`
  - `prompts` from `/opt/agents/commands`
  - `skills` from `/opt/agents/skills`
- ensure `/home/pi/.agents`
- link:
  - `/home/pi/.agents/agents` -> `/home/pi/.pi/agent/agents`
  - `/home/pi/.agents/commands` -> `/home/pi/.pi/agent/prompts`
  - `/home/pi/.agents/skills` -> `/home/pi/.pi/agent/skills`
  - `/home/pi/.agents/prompts` -> `commands`

Workspace responsibilities:
- ensure `/workspace/.agents/{agents,commands,skills}`
- ensure `/workspace/.agents/prompts -> commands`
- ensure `/workspace/.pi`
- link:
  - `/workspace/.pi/agents` -> `/workspace/.agents/agents`
  - `/workspace/.pi/prompts` -> `/workspace/.agents/prompts`
  - `/workspace/.pi/skills` -> `/workspace/.agents/skills`

### OpenCode

Own only OpenCode-specific initialization.

Home responsibilities:
- ensure `/home/opencode/.config/opencode`
- ensure `/home/opencode/.config/opencode/{commands,skills}`
- seed:
  - `commands` from `/opt/agents/commands`
  - `skills` from `/opt/agents/skills`
- ensure `/home/opencode/.agents`
- link:
  - `/home/opencode/.agents/commands` -> `/home/opencode/.config/opencode/commands`
  - `/home/opencode/.agents/skills` -> `/home/opencode/.config/opencode/skills`
  - `/home/opencode/.agents/prompts` -> `commands`
- do not create or link shared markdown `agents`

Workspace responsibilities:
- ensure `/workspace/.agents/{agents,commands,skills}`
- ensure `/workspace/.agents/prompts -> commands`
- ensure `/workspace/.opencode`
- link:
  - `/workspace/.opencode/commands` -> `/workspace/.agents/commands`
  - `/workspace/.opencode/skills` -> `/workspace/.agents/skills`
- do not link `/workspace/.opencode/agents`

## Init Script Structure

Each harness-local init script should include:

- `dir_empty`
- `next_backup_path`
- `ensure_real_dir`
- `link_path`
- `ensure_shared_home_root`
- `ensure_shared_workspace_tree`
- `init_home`
- `init_workspace`

Recommended structure:

```bash
#!/bin/bash
set -euo pipefail

dir_empty() { ... }
next_backup_path() { ... }
ensure_real_dir() { ... }
link_path() { ... }
ensure_shared_home_root() { ... }
ensure_shared_workspace_tree() { ... }
init_home() { ... }
init_workspace() { ... }

init_home
init_workspace
```

Do not put `tail -f /dev/null` inside these scripts. The caller should remain responsible for container lifetime behavior.

## File-By-File Changes

### Add

- `claudecode/init.sh`
- `pi/init.sh`
- `opencode/init.sh`

### Edit

- `claudecode/docker-compose.yml`
  - mount `./init.sh:/opt/harness/init.sh:ro`
  - replace `/opt/agents/bootstrap.sh ...` entrypoint with `/opt/harness/init.sh && tail -f /dev/null`

- `claudecode/claude-run`
  - mount `init.sh` into the container
  - replace `/opt/agents/bootstrap.sh ...` invocation with `/opt/harness/init.sh`

- `pi/docker-compose.yml`
  - mount `./init.sh:/opt/harness/init.sh:ro`
  - replace `/opt/agents/bootstrap.sh ...` entrypoint with `/opt/harness/init.sh && tail -f /dev/null`

- `pi/pi-run`
  - mount `init.sh` into the container
  - replace `/opt/agents/bootstrap.sh ...` invocation with `/opt/harness/init.sh`

- `opencode/docker-compose.yml`
  - mount `./init.sh:/opt/harness/init.sh:ro`
  - replace `/opt/agents/bootstrap.sh ...` entrypoint with `/opt/harness/init.sh && tail -f /dev/null`

- `opencode/opencode-run`
  - mount `init.sh` into the container
  - replace `/opt/agents/bootstrap.sh ...` invocation with `/opt/harness/init.sh`

- `README.md`
  - remove mention of shared bootstrap behavior
  - describe root as shared data only

- `claudecode/README.md`
  - explain Claude-local startup initialization

- `pi/README.md`
  - explain Pi-local startup initialization and `prompts` compatibility

- `opencode/README.md`
  - explain OpenCode-local startup initialization and the lack of shared markdown `agents`

### Delete

- `bootstrap.sh`

Delete `bootstrap.sh` only after every runtime call site has been rewired.

## Recommended Mount Pattern

Mount the harness-local init script into the container rather than embedding it inline in entrypoints:

- Claude: `./init.sh:/opt/harness/init.sh:ro`
- Pi: `./init.sh:/opt/harness/init.sh:ro`
- OpenCode: `./init.sh:/opt/harness/init.sh:ro`

Why:
- keeps startup behavior versioned with the harness repo
- works for both Compose and direct `docker run`
- avoids rebuilding images for init-only changes
- keeps entrypoints and run commands readable

## Migration Order

1. Add `claudecode/init.sh`, `pi/init.sh`, and `opencode/init.sh`
2. Rewire `claudecode/claude-run`, `pi/pi-run`, and `opencode/opencode-run`
3. Rewire `claudecode/docker-compose.yml`, `pi/docker-compose.yml`, and `opencode/docker-compose.yml`
4. Update shared and harness README files
5. Syntax-check all shell scripts
6. Validate compose files
7. Run smoke tests for all three harnesses
8. Delete `/workspace/bootstrap.sh`

## Verification Checklist

### Shell syntax

- `bash -n /workspace/claudecode/init.sh`
- `bash -n /workspace/pi/init.sh`
- `bash -n /workspace/opencode/init.sh`
- `bash -n /workspace/claudecode/claude-run`
- `bash -n /workspace/pi/pi-run`
- `bash -n /workspace/opencode/opencode-run`

### Compose validation

- `docker compose config` in `claudecode/`
- `docker compose config` in `pi/`
- `docker compose config` in `opencode/`

### Runtime smoke tests

Claude:
- `~/.claude/{agents,commands,skills}` seeded and linked correctly
- `/workspace/.claude/*` linked into `/workspace/.agents/*`

Pi:
- `~/.pi/agent/prompts` seeded from shared `commands`
- `/workspace/.pi/prompts` links to `/workspace/.agents/prompts`

OpenCode:
- no shared markdown `agents` linked into home or workspace config
- `commands` and `skills` linked correctly

### Migration safety

- existing real directories are moved to `.local*` backups
- no harness rewrites sibling harness workspace directories

## Risks And Constraints

### Main risk

The existing shared script initializes all workspace harness directories in one pass. After localization, startup order matters more:

- the first harness to start creates `/workspace/.agents`
- later harnesses should only attach their own compatibility directories

This is acceptable, but each init script must avoid modifying workspace paths owned by other harnesses.

### Intended duplication

Some helper logic will exist in three repos. This is acceptable because:

- each harness becomes self-contained
- behavior is easier to audit locally
- harness-specific differences stop being hidden behind a generic switch statement

### Constraint

Do not reintroduce a shared sourced shell library during this refactor. That would recreate the same cross-harness coupling under a different name.

## Definition Of Done

The refactor is complete when:

- each harness starts successfully without calling `/workspace/bootstrap.sh`
- each harness initializes only its own home and workspace compatibility paths
- `/workspace` contains only shared data resources
- `prompts` remains compatibility-only
- OpenCode still avoids shared markdown `agents`
- `/workspace/bootstrap.sh` has been removed
