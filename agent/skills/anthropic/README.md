# Local skill bundles

These are editable, project-owned copies of 15 bundles originally published
in [Anthropic's skills collection](https://github.com/anthropics/skills/tree/main/skills).
The URL is attribution only. There is no submodule, upstream checkout, commit pin,
automatic updater, or network dependency for loading the local skills.

## Included skills

| Area | Skill IDs |
|---|---|
| Branding and design | `brand-guidelines`, `frontend-design`, `canvas-design`, `theme-factory`, `algorithmic-art` |
| Documents | `doc-coauthoring` |
| Development | `skill-creator`, `mcp-builder`, `web-artifacts-builder`, `webapp-testing`, `claude-api` |
| Communication and learning | `internal-comms`, `slack-gif-creator`, `academy-guide`, `discernment-nudge` |

## Local adaptations

- Execution instructions target **OpenCode V2**: native skills, available tools,
  subagents, and local output files instead of Claude Code commands or hosted
  artifact assumptions. Skill folders, not slash commands, are the integration.
- `skill-creator` includes an OpenCode CLI adapter for description evaluation and
  optimization. Its isolated runner currently supports Linux only. Model-backed
  evaluation is optional, requires configured provider
  access, and can incur costs. Get approval for the run and budget first.
- `brand-guidelines` applies **Neuralys** colors and semantic roles. It includes
  accessible color usage, typography fallback, and logo boundaries.
- Prose uses sentences, colons, commas, and parentheses rather than em dashes.
- `claude-api` still documents the **Anthropic API**. Product-specific SDK names,
  model IDs, and Managed Agents behavior are not OpenCode configuration. Likewise,
  `academy-guide` links to real Anthropic learning content, not an OpenCode course.

## Dependencies and verification boundary

Loading a skill reads Markdown. Running its scripts may additionally require
Python packages, Node packages, Playwright/browser binaries, fonts, LibreOffice,
or other utilities documented in the individual bundle. Copying these files
does **not** install those dependencies or grant tool permissions.

Read scripts before executing them. Preserve native permission boundaries and
existing project conventions. Use explicit, writable project output directories;
do not assume hosted `/mnt` paths or an interactive desktop are available.

One-time setup checks covered structure and mocked adapter behavior. Those checks
do not establish that every browser workflow, external service, or paid model
evaluation works in the deployment environment. No standing skill test suite or
branding evaluation fixtures are retained. Validate the relevant workflow when
setting it up, and review routine skill edits directly.

## Licenses and attribution

Keep each bundle's `LICENSE.txt`, font licenses, and
[third-party notices](THIRD_PARTY_NOTICES.md) with its resources. Other files may
have their own applicable notices. Local adaptation does not replace those terms
or imply Anthropic endorsement of Neuralys branding.

**Excluded after license review:** `docx`, `pdf`, `pptx`, and `xlsx`. Their supplied
terms expressly prohibit retained copies, derivative works, and redistribution.
They are not included in this local collection. References to those file formats
in other skills do not install or provide the excluded document skills.

The local modification record is [CHANGES.md](CHANGES.md). Maintain these copies
directly; any future upstream import is an explicit review, not an automatic sync.
