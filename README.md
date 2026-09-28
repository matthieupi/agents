# Agent products and shared resources

## Ordinary VM services

Pi, OpenCode, Paseo execution daemon and Paseo Hub use the normal service catalog,
native Docker builds and Compose. See [VM-SERVICES.md](VM-SERVICES.md) for exact
inputs, auth, account, state, Docker grants and ingress ownership.

> [!NOTE]
> The old managed VM controller and T3/OMP products have been retired from maintained
> source. No source-publication, privileged image activation, dynamic-default or SSH
> alias fallback remains. Ignored historical private data is preserved, not migrated
> or deleted. Source retirement does not remove anything from deployed machines.

## Preserved workstation interfaces

- [Pi](pi/README.md): existing run/mgr wrappers, static Compose, native scripts.
- [OpenCode](opencode/README.md): existing CPU/GPU wrappers, Compose, native scripts,
  KDCO plugins and explicit optional tools.
- `claudecode/`: existing workstation component.
- [Opt-in runtime](runtime/README.md): separate Pi/OpenCode/Claude workstation
  build/select/run interface. It does not delegate to a VM controller or replace
  existing workstation defaults. Its local build receipts are not VM authorization.
- [Paseo daemon](paseo-deamon/README.md): VM templates and separately retained
  standalone component interface; embedded OpenCode belongs to Paseo.
- [Paseo Hub](paseo-hub/README.md): restricted UI service, not an execution host.
- [Paperclip base](paperclip/README.md): DevAI Hub-only private native-auth UI and
  PostgreSQL; no configured agents or scheduler, frontend deny-all pending bootstrap.

## Shared defaults

`agent/` stays data-only: `system/` has persona Markdown, `commands/` has command
content, `prompts` is a symlink to commands, and `skills/` contains skill bundles.
Existing workstation harnesses own their HOME discovery links; no workspace-local
configuration tree is created proactively by this shared root.

Pi Docker/native initialization imports top-level system Markdown as individual
`~/.pi/agent/agents/system-*.md` links. Exact links are reused; unknown links and
conflicts are preserved and fail rather than being overwritten.

> [!IMPORTANT]
> The two-field `name`/`description` frontmatter is portable metadata, not
> model/tool permissions.

Use the exact names (`system-build`, `system-coo`, `system-devops`, `system-explore`,
`system-plan`, `system-plan-inline`, `system-reviewer`, `system-secops`); no aliases
to unprefixed names or new delegation framework are supplied. See
[Pi's consumer matrix](pi/README.md#automatic-system-agent-import-docker-and-native).

OpenCode workstation config uses its own agent schema. The opt-in runtime's
`resources` target calls the product-owned public config publisher; ordinary VM
services do not register agents from that manifest.

## Evidence boundary

> [!IMPORTANT]
> This cleanup is source-only. No tests were authored or executed, and no validation,
> build or deployment was run. Mixed workstation test files retain obsolete cases
> for separate maintenance; their presence is not a claim of a passing test graph.
