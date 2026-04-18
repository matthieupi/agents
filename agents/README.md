# Shared Agent Defaults

This directory holds the shared default `agents/`, `prompts/`, and `skills/` trees used by the local Claude Code, Pi, and OpenCode containers.

- `agents/` contains shared agent definitions
- `prompts/` contains shared prompt templates and command markdown files
- `skills/` contains shared skill bundles
- `commands/` is a compatibility symlink to `prompts/` for harnesses that expect a `commands/` directory name

Runtime bootstrap does two things:

- seeds `~/.agents/{agents,prompts,skills}` as the shared global resource tree
- keeps each harness' normal home config directory real, while linking only the shared resource subdirectories back to `~/.agents`
- wires each project workspace so `.agents/` is the canonical shared folder while `.claude/`, `.pi/`, and `.opencode/` keep their harness-specific non-shared files
