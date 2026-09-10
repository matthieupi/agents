# Shared Config Defaults

An additive, explicit [runtime interface](runtime/README.md) has offline implementation.
It does not replace any workstation command, image, manager, native path or default.
Workstation installation/startup readiness, finite installer-to-protected-VM
activation, protected control upgrades and gateway image replacement/recovery exist.
No target is enabled by this work and no new-path image is runtime-accepted. Full
legacy characterization, resource parity and online acceptance remain incomplete;
read the runtime status and protected VM contract before attempting use.

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
- OMP references a persona through `SYSTEM.md`, registers commands once, and links individual grouped skill directories into its shallow skill-discovery layout; it does not load Pi extensions
- workspace-local `.agents`, `.claude`, `.pi`, and `.opencode` directories are no longer created proactively
- OMP also creates no workspace-local `.omp` tree; its private home is `omp/.omp`, with tracked starter YAML and fresh credentials/state by default. Legacy private Pi/OMP files remain protected and untouched; the old tracked OMP YAML defaults in Pi were removed with user authorization. Historical recovery is optional operator work, not a migration deliverable or acceptance blocker.

## Shared system-agent import

The eight `agent/system/*.md` files carry portable `name`/`description` YAML
frontmatter only. Prompt bodies are unchanged; no tool/model/permission metadata
is added. Names are `system-build`, `system-coo`, `system-devops`, `system-explore`,
`system-plan`, `system-plan-inline`, `system-reviewer`, and `system-secops`.

```text
agent/system/<role>.md
  +-- individual symlink -> ~/.omp/agent/agents/system-<role>.md -> OMP task agents
  +-- individual symlink -> ~/.pi/agent/agents/system-<role>.md  -> Pi /system
```

OMP Docker init and Pi Docker/native home init scan only top-level system Markdown,
validate simple basenames and canonical targets inside the system root, reuse exact
links and fail while preserving conflicts. No GSD import, copied prompt bodies,
model-mediated file-reading instructions, or stale-link cleanup. Pi converts only
its recognized legacy whole-root `agents` symlink to a real directory; unrelated
files and unknown links are not replaced. See [Pi's consumer matrix](pi/README.md#automatic-system-agent-import-docker-and-native)
for preset limitations: vanilla Pi is not being given a new subagent framework.

Use the exact `system-*` names to select shared definitions. Existing prompt/skill
instructions referring to `explore`, `plan`, etc. are **not automatically aliased**;
OMP may resolve an unprefixed name to a bundled agent instead. Those delegation
instructions still require harness-aware selection, not an assumption of equivalent
behavior. Roles are instructions, not permission sandboxes. Plain Markdown consumers
(including OMP `SYSTEM.md`) see the small metadata header as part of the prompt;
frontmatter-aware consumers strip it. Primary `OMP_PERSONA` and skill wiring are unchanged.

Source implementation and diff review are complete; manual discovery, conflict,
repeat-init and native extension compatibility validation are pending. No tests,
syntax/build checks, Docker or deployment operations were performed for this import.

OMP's source MVP and follow-ups are complete: explicit non-root image-home ownership,
per-path init diagnostics, and leading `omp -r` for **image-only rebuild** (no container
refresh). Native resume uses `omp --resume`, `omp session -r`, `omp -- -r`, or `-r`
after a workspace. The [remote reuse failure remains unresolved](omp/README.md#known-runtime-follow-ups);
no warnings-only validation or startup-readiness change is delivered.
Automated test creation/execution is waived by the
user; final manual verification/validation remains user-owned and pending, not
passed. See [OMP's validation handoff](omp/README.md#user-validation-handoff).
