# Shared Config Defaults

This workspace root hosts a shared default `agent/` tree consumed by the local Claude Code, Pi, and OpenCode containers.

- `agent/` contains shared agent definitions at its root
- `agent/commands/` contains shared command markdown files and prompt content
- `agent/prompts/` mirrors prompt-oriented shared content
- `agent/skills/` contains shared skill bundles

Each harness now initializes only its own home compatibility links at container startup.

- the shared root stays dumb data only; it does not contain harness-specific bootstrap logic
- the shared root is mounted read-write into each container at `/opt/agent`
- each harness links its home config directly to `/opt/agent` plus `/opt/agent/{commands,skills}` so edits write back to the single shared source of truth
- workspace-local `.agents`, `.claude`, `.pi`, and `.opencode` directories are no longer created proactively
