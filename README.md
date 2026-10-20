# Agent products and shared resources

## Ordinary VM services

Pi, OpenCode, Paseo execution daemon, Paseo Hub and Paperclip services use the normal
service catalog and ordinary `docker-compose.j2` templates. Execution images use
native Docker builds. See [VM-SERVICES.md](VM-SERVICES.md) for exact
inputs, auth, account, state, Docker grants and ingress ownership.

> [!NOTE]
> The old managed VM controller and T3/OMP products have been retired from maintained
> source. No source-publication, privileged image activation, dynamic-default or SSH
> alias fallback remains. Ignored historical private data is preserved, not migrated
> or deleted. Source retirement does not remove anything from deployed machines.

## Preserved workstation interfaces

- [Pi](pi/README.md): run/mgr wrappers, static Compose, installer/init helper.
- [OpenCode V2](opencode/README.md): CPU/GPU dispatcher/menu/run/mgr, installer/init
  helper, native title/background plugins and retained volume/privilege/GPU flags.
  One `serve` backend, explicit `--server` clients; automatic recreation interrupts
  sessions. Optional dispatch/ssh-remote remain default-off and V1-targeted.
- `claudecode/`: existing workstation component.
- [Paseo daemon](paseo-deamon/README.md): VM templates and separately retained
  standalone component interface; embedded OpenCode belongs to Paseo.
- [Paseo Hub](paseo-hub/README.md): restricted UI service, not an execution host.
- [Paperclip base](paperclip/README.md): DevAI Hub-only private native-auth UI and
  PostgreSQL; native ownership established, signup closed and DevAI-admin-only
  ingress. Ordinary deployment seeds no agents or schedules; explicit acceptance
  created a paused native agent, documented in the parent deployment record.
- [Paperclip daemon](paperclip-daemon/README.md): ordinary native SSH execution
  container sharing agent HOME/workspace and explicit socket grants with Pi/OpenCode.
  This is the same trust boundary, not an isolated worker protocol.

## Shared defaults

`agent/` stays data-only: `system/` has persona Markdown, `commands/` has command
content, `prompts` is a symlink to commands, and `skills/` contains skill bundles.
Existing workstation harnesses own their HOME discovery links; no workspace-local
configuration tree is created proactively by this shared root.

Workstation shell initialization serializes the whole home update with Linux
`flock`: shared `agent/` directory inode first, home directory inode second.
The shared lock coordinates harnesses and containers using the same bind-mounted
resources; directory locks avoid root-owned lock files and do not change ownership
or writable-mount requirements. Keep these directories stable during initialization.
Resource links use exact destinations (`ln -sT`) and reuse already-correct links.
Container initialization also removes only the three exact legacy self-links
`{commands,skills,system}/<same-name> -> /opt/agent/<same-name>` under real,
non-redirected resource directories. Real content, custom links, and
`prompts -> commands` are preserved. This is not a general symlink-tree cleanup.

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

OpenCode V2 uses its own agent schema and resolves `@opencode/cli@latest` on all
maintained installation paths, with application auto-update disabled and no operator
version pin. Its public workstation source `.opencode/config` is mounted read-only;
selected assets link into private `.opencode/home-config`, not a full-source config
symlink. VM consumers share read-only `/opt/opencode-defaults` and `/opt/agent`
public mounts, preserving private HOME/auth/session state. The retained
`scripts/publish-plugins.mjs` is config-only and reconciles known managed content
while preserving unknown conflicts; KDCO package/install and GSD are retired.
The opt-in `runtime/` framework and its public-resource projection are retired.
Pi/OpenCode native start/manage scripts and OpenCode static Compose are also
retired; the product installers and ordinary VM Compose templates remain.

## Evidence boundary

⚠️ VM OpenCode requires a protected `opencode_backend_password` fact rendered as
`OPENCODE_PASSWORD`. External nginx must authenticate the client, then **replace**
upstream Authorization with Basic `opencode:<backend credential>`. The former
gateway-only anonymous-backend contract is incompatible; required infrastructure
changes are **outside this repository**, with no secret rotation authorized here.
Native readiness uses authenticated `/api/info`, not anonymous health or HTML.

Paseo requires >=0.12.0 with actual native V2 adapter packaging and required
`verify-paseo.mjs` build verification; published 0.12.0 source was checked.
Paperclip OpenCode V2 adapter/session/tool acceptance remains unverified: neither
old SSH callback evidence nor `latest` establishes compatibility or safe activation.
Prior disposable OpenCode latest install/server smoke passed at **2.1.1**, not a pin
or deployed-host acceptance.

> [!IMPORTANT]
> This reconciliation is documentation-only. Targeted credential-free workstation, backend and
> Pi installer/init tests exercise fixtures, not live containers. Retained wrapper
> coverage lives in `tests/test_workstation.py`. No image build, deployment or
> deployed-state cleanup is implied; the full test graph is not claimed clean.
