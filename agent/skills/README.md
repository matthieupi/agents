# Skill Taxonomy

The project skills are grouped by **purpose** in the filesystem. The `anthropic/`
group contains locally maintained bundles adapted from Anthropic's examples;
it is a source grouping rather than a runtime dependency.

## OpenCode V2

OpenCode discovers nested `SKILL.md` bundles through the shared skills directory
already exposed by the workstation harness. The immediate skill-directory name
is its ID, irrespective of grouping: `anthropic/brand-guidelines/SKILL.md` loads
as `brand-guidelines`. Mention `@brand-guidelines` or ask for Neuralys branding;
the agent loads it with the native `skill` tool using `{"id":"brand-guidelines"}`.

For standalone installations, copy a complete bundle into
`.opencode/skills/<id>/` (project) or `~/.config/opencode/skills/<id>/` (global).
Do not copy only `SKILL.md`: supporting scripts, references, assets, and licenses
belong to the bundle. A `.skill` archive is transport, not an OpenCode installer.

See [the local bundle guide](anthropic/README.md) for scope and dependencies.

## Pi skill layout constraint

Pi discovers skills recursively, but a skill must still live in its own
folder with a `SKILL.md` file.

Valid:

```text
skills/planning/write-a-prd/SKILL.md
skills/dev/build-feature/SKILL.md
```

Not valid as a skill:

```text
skills/planning/write-a-prd.md
```

## Important behavior

Grouping by folder is purely for organization.

- `planning/write-a-prd/SKILL.md` still loads as `/skill:write-a-prd`
- `git/git-smart/SKILL.md` still loads as `/skill:git-smart`
- the folder path does **not** become part of the skill command name

## Groups

### Git

- `git-status`
- `git-smart`

### Development

- `bugfix`
- `build-feature`
- `n3tx-init`: read-only N3TX session orientation; `/n3tx-init [feature/system context and/or N3TX path]` invokes the shared skill through a thin command.
- `tdd`

### Architecture

- `deep-audit`
- `distill`
- `distill-deep`
- `improve-codebase-architecture`
- `refactor-plan`

### Design

- `grill-me`
- `interface-design`

### Planning

- `prd-to-issue`
- `write-a-prd`

### Research

- `ideation-skill`

### Performance

- `perf-analysis-skill`

## Filesystem layout

```text
skills/
├── anthropic/
├── architecture/
├── design/
├── dev/
├── git/
├── performance/
├── planning/
└── research/
```

Skill discovery remains recursive, so this grouped layout preserves the same
underlying skill behavior while making the repository easier to navigate.
