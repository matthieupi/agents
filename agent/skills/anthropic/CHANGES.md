# Local modifications

## 2026-10-23

This directory is a locally maintained adaptation of Anthropic's skill examples,
not an unmodified upstream distribution. Original license and attribution files
are retained. No source commit is pinned and no repository synchronization is
configured.

### Execution and integration

- Adapted skill instructions, supporting guides, examples, and review UI to
  OpenCode V2, available native tools, local files, and headless environments.
- Reworked the skill-creator runtime helpers for OpenCode rather than Claude
  subprocesses; retained offline validation, packaging, aggregation, and review
  resources. Archives are optional transport, not an OpenCode installation API.
- Added batch cancellation that prevents queued launches and terminates active
  local process groups on interruption or failure. The isolated runner is
  Linux-only; requests already submitted remotely may still incur charges.
- Adapted Claude API workflow routing, tool names, provenance handling, and eval
  output defaults while retaining actual Anthropic product contracts.
- Adapted browser examples to create project-local output directories and made
  HTML artifact delivery usable without a hosted artifact interface.
- Corrected web-artifact initialization for nested project paths and escaped
  generated title text.

### Branding and prose

- Replaced Anthropic identity in `brand-guidelines` with Neuralys palette,
  semantic roles, accessibility checks, and typography guidance.
- Made the algorithmic-art template's original palette optional; branded work
  follows the local branding skill rather than mandatory Anthropic identity.
- Reformulated em-dash prose throughout the included bundles. Third-party legal
  texts are preserved verbatim.

### Exclusions

- Excluded `docx`, `pdf`, `pptx`, and `xlsx` with the user's approval because their
  supplied licenses prohibit retained copies, derivative works, and redistribution.
  No local implementation of those four skills is included.
- References to document formats and genuine Anthropic-hosted capabilities in
  other skills are not a claim that the excluded bundles are installed.

### Verification

Setup-time checks covered inventory, YAML metadata, unique IDs, local-file layout,
license preservation, punctuation, syntax, and the OpenCode adapter using mock
events and local fake subprocesses. All 33 focused checks passed before the user
requested removal of the setup tests and branding fixtures. Those temporary test
files are no longer retained; the skill-creator's evaluation tools remain available
as functionality, not a standing maintenance suite.

No live-provider, browser, document-rendering, or deployment acceptance is implied.
Validate the intended workflow when setting it up, with permission where required.
