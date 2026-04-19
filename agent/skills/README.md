# Skill Taxonomy

The project skills are grouped by **purpose** in the filesystem.

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
