# Shared Config Defaults

Native, non-Docker lifecycle documentation: [OpenCode](opencode/README.md#native-lifecycle)
and [Pi](pi/README.md#native-lifecycle). Both execute locally as non-root
accounts, not in a sandbox. Remote-only DevAI activation must remain disabled in
Ansible until adapted and validated.

This workspace root hosts a shared default `agent/` tree consumed by the local
Claude Code, Pi, OpenCode, and [OMP](omp/README.md) containers. OMP is an independent
Docker CLI component in this same repository, not a Pi mode or native/web service.

- `agent/system/` contains shared persona/system-prompt Markdown
- `agent/commands/` contains shared command markdown files and prompt content
- `agent/prompts` is a symlink to `commands` (not a second content source)
- `agent/skills/` contains shared skill bundles

Each harness now initializes only its own home compatibility links at container startup.

- the shared root stays dumb data only; it does not contain harness-specific bootstrap logic
- the shared root is mounted read-write into each container at `/opt/agent`
- each harness uses its own supported discovery paths so edits write back to the single shared source of truth
- OMP references a persona through `SYSTEM.md`, registers commands once, and links individual grouped skill directories into its shallow skill-discovery layout; it does not load Pi extensions or pretend plain personas are task-agent definitions
- workspace-local `.agents`, `.claude`, `.pi`, and `.opencode` directories are no longer created proactively
- OMP also creates no workspace-local `.omp` tree; its private home is `omp/.omp`, separate from legacy Pi state retained pending migration preflight
