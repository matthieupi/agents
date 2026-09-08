# OMP — standalone Docker CLI

✅ Source-only MVP extracted from Pi, in the existing agents repository.
Own image `lab/omp:latest`, component `omp`, non-root account `/home/omp`, and
private `.omp` state. No native installer, web frontend, Ansible activation,
Docker socket, published ports, or automatic migration. Pi/COO remain vanilla Pi.

**Implementation status (2026-09-08):** pinned source and local diffs reviewed.
By explicit request, no tests were added/run, no syntax checks or runtime probes
were run, and no images were built or containers/deployments changed. Source
compatibility findings below are not a claim of successful runtime validation.

## Commands and prerequisites

Run host wrappers as the intended non-root developer, never with sudo. Requires
Linux, Bash, GNU coreutils (`realpath`, `sha256sum`), Python 3, Docker CLI/daemon
access and, for the optional static service, modern Docker Compose v2 supporting
long bind syntax with `create_host_path: false`. The image currently supports
**Linux amd64 only** (Bun baseline asset and retained Terraform amd64 package).
No macOS/ARM/native support is claimed.

Before launch, prepare **only the concerned** state, workspace and SSH directories
under your account. State must contain `agent/` and be writable by the image's
configured UID/GID. Do not run recursive ownership fixes on Pi state or the shared
resource repository. An empty SSH directory is fine when no SSH credentials are
needed. Existing Git configuration is optional (`/dev/null` by default).

```bash
# From services/agents/omp, as the intended developer:
mkdir -p ssh                 # empty read-only SSH bind is supported
chmod 700 .omp .omp/agent ssh
export SSH_DIR_PATH="$(realpath ssh)"
export OMP_NETWORK=devai-xmist   # must already exist on the selected daemon
./omp build                    # later operator action; not run in this pass
./omp /absolute/project
./omp -r                       # upstream resume picker, NOT rebuild
./omp session /absolute/project --resume SESSION_ID
./omp session -- --help         # upstream help, not wrapper help
./omp session -- build          # prompt named build
./omp -- -- -r                  # pass an upstream -- and literal -r
./omp list
./omp stop omp-project-HASH
./omp remove omp-project-HASH   # stopped container only; state retained
```

`omp session` escapes management-word dispatch, not upstream subcommand parsing.
For an upstream-reserved word as literal prompt, pass another `--`, e.g.
`omp session -- -- setup`. `omp session -- setup` invokes upstream setup.
The installed container executable is always `/usr/local/bin/omp`, never this
repository's host wrapper, even with the checkout as workspace.

### Argument contract

`omp-run [existing-directory] [--] [OMP_ARGS...]` consumes at most one leading
existing directory and one harness delimiter. A leading `--` skips workspace
detection. All remaining arguments, including spaces, empty strings, `-r`,
`--resume`, `--login`, `--rebuild`, and later `--`, pass as an unchanged Bash array.
**Forwarding does not mean upstream accepts a flag**: 18.0.4's built-in launch
parser does not define `--login` or `--rebuild`. Use OMP's interactive `/login` or
setup flow; no provider callback ports are published. Provider-specific browser
callbacks that need inbound ports are not implemented in this MVP.

Interactive exec requests a TTY only when both stdin/stdout are terminals; stdin
remains attached for pipes. Wrappers resolve their own canonical path through
symlinks, so an optional user-owned PATH symlink can point at `omp/omp`.

### Lifecycle ownership

```text
omp -> omp-run -> inspect/create owned workspace container -> init -> /usr/local/bin/omp
    -> omp-mgr -> inspect owned immutable ID -> scoped lifecycle operation
```

- Names include a sanitized basename and first 16 hex digits of the canonical
  workspace SHA-256. Same-basename directories are distinct; full workspace labels
  make even a hash/name collision fail closed rather than attach to another mount.
- Containers carry `dev.xmist.agents.component=omp`,
  `dev.xmist.agents.owner=<canonical component checkout>`, and
  `dev.xmist.agents.workspace=<canonical host workspace>`.
- `list`/`all`/`clean` are scoped to **this checkout's labels**, not a name prefix.
  Explicit names/IDs are checked too. Operations use inspected immutable IDs.
  Copying/moving the checkout changes ownership: operate from its original path
  or use deliberate administrator-owned Docker operations after metadata review.
- Reuse/start/shell check current image reference **and image ID**, exact six
  mount sources/access, workspace, UID/GID, home/persona, network, CPU/memory,
  startup command and basic no-host-control constraints. Unknown extra mounts,
  published ports or privilege changes fail. Stop/remove/logs still work for
  stale configurations, but require ownership labels.
- `build`, `rebuild`, `update` only build the image. They never fetch Git, update
  an installation in place, or remove/refresh containers. A successful rebuild
  requires explicit recreation when image IDs differ. A failed build leaves
  containers alone. Do not use upstream `omp update` in a durable image.
- `remove`/`rm` never force removal; first drain sessions and `stop` the selected
  container. `clean` removes only stopped/created/dead owned containers;
  `clean -f`/`fclean` explicitly stop all containers owned by this checkout before
  removal. No volume-delete flags, bind-data deletion, pruning or stack restart.
- Creation failures are retained for diagnosis, not automatically deleted by name.
  An init conflict is fatal and preserved; use `omp logs NAME` and resolve it.
  Concurrent launches can cause a name-conflict error; retry after the winning
  creator completes. There is no claim of transactional coordination with other
  Docker administrators or host filesystem edits.

### Method Signature Surface

```text
omp
  + usage()
omp-run
  + docker_run_agent()
omp-mgr
  + rebuild_image()
  + prepare_existing_container(CONTAINER_ID)
common.sh (OMP-local only)
  + log_error(MESSAGE...)
  + die(MESSAGE...)
  + require_host()
  + resolve_mounts()
  + workspace_container_name(CANONICAL_WORKSPACE)
  + owned_container_ids(DOCKER_FILTER_ARGS...)
  + require_owned_container(NAME_OR_ID)
  + validate_existing_container(CONTAINER_ID)
  + exec_agent(CONTAINER_ID, OMP_ARGS...)
container-contract.py
  + require(condition: bool, reason: str) -> None
  + main() -> None
init.sh
  + link_resource(CURRENT_PATH, SHARED_PATH)
  + init_home()
Pi removed interfaces
  - pi --oh [workspace] [OMP_ARGS...]
  - pi-run --agent-cli {pi|omp} [ARGS...]
  - validate_agent_cli(AGENT_CLI)
Pi existing call signatures unchanged (implementation now Pi-only)
  exec_agent(CONTAINER_NAME, PI_ARGS...)
  docker_run_agent(DOCKER_ARGS...)
  usage()
```

## Configuration

**Wrappers read exported environment only. They do not read/source `.env`.**
Compose reads `.env` under its normal rules. Export the same chosen values when
switching between the two interfaces; neither wrapper executes shell dotenv data.
Relative override paths in wrappers resolve against the caller's cwd. Prefer
absolute paths everywhere; comma/newline mount paths are rejected by the runner.

| Input | Default / contract |
|---|---|
| `OMP_IMAGE` | `lab/omp:latest` |
| `OMP_UID`, `OMP_GID` | `1000`, `1000`; positive IDs used for image build and runtime |
| `OMP_NETWORK` | existing external `devai-xmist`; same default in runner/Compose |
| `OMP_MEMORY`, `OMP_CPUS` | `2g`, `2.0`; memory integer with optional b/k/m/g suffix, positive CPUs |
| `OMP_STATE_DIR` | component `.omp`; existing directory with `agent/` |
| `OMP_AGENT_DIR` | sibling `agent`; shared editable resources |
| `SSH_DIR_PATH` | component `ssh`; existing directory, mounted read-only |
| `GITCONFIG_PATH` | `/dev/null`, or existing read-only file |
| `OMP_PERSONA` | `build`; existing `agent/system/<basename>.md`, no path traversal |
| `WORKSPACE_PATH` | Compose requires canonical absolute directory; runner uses argv or cwd, not this env input |
| `OMP_COMPONENT_DIR` | wrapper forces real component path; Compose operator must supply it |
| Provider variables | exported allowlist in `.env.example`; values not passed as build arguments |

The image's passwd account must match runtime IDs; changing Compose `user` alone
is not a substitute for rebuilding with matching `OMP_UID/GID`. Init refuses root
and checks writable home/state/workspace/resources. It never chowns host mounts.
Provider environment changes require recreation; reuse intentionally does not
compare or print secret values. For Git identity, use the read-only gitconfig.
Model defaults are `providers: {}`; OMP's bundled provider catalog remains in use.
Configure endpoint/model entries deliberately in OMP's own `models.yml`, never
Pi's legacy YAML. These two starter YAML files are **tracked**: do not put keys
in them. Use provider environment or OMP's private credential DB instead.

### Optional static Compose container

Compose creates `omp`; per-workspace wrappers use hashed names and **do not attach
to that static container automatically**. Do not casually run both against one
state root; concurrency/database behavior still needs validation.

```bash
# From the canonical omp component directory; after preparing paths:
export OMP_COMPONENT_DIR="$(pwd -P)"
export WORKSPACE_PATH="$(realpath /absolute/project)"
# Supply the same OMP_* and SSH/Git inputs chosen for the wrappers.
docker compose up -d --build omp
docker compose exec omp bash -c '/opt/harness/init.sh && exec /usr/local/bin/omp'
./omp list
./omp stop omp
./omp remove omp
```

`OMP_COMPONENT_DIR` is required for Compose ownership labels. Network provisioning
is external; this component does not create a network or join `proxy_net`. No proxy
route, OAuth ports or Docker socket is needed for ordinary outbound API access.
Compose refuses missing bind sources instead of creating root-owned directories.

## Shared resources and discovery evidence

Read-only public package-source review used **18.0.4**, not latest docs:

- [npm metadata](https://registry.npmjs.org/@oh-my-pi/pi-coding-agent/18.0.4):
  bin `omp -> dist/cli.js`, engine Bun `>=1.3.14`, no shrinkwrap. Tarball integrity:
  `sha512-vi2vZGsZ/OigD3f8M+Qixreuk7afU5P6Qe2JlcW6nTWOC48zYXeY4QZGPsM3R0Ata4xPGNWDtCKCgKjx6KO00A==`.
  Registry advertises signatures/provenance; their cryptographic attestations were
  not independently verified here. Installation remains package-manager based.
- [Bun 1.4.0 release metadata](https://api.github.com/repos/oven-sh/bun/releases/tags/bun-v1.4.0):
  `bun-linux-x64-baseline.zip` SHA-256
  `184fb4595f0d401a217cf7c78c1bc430ba83314dab7a8b94805babbf7fa7097f`.
  Dockerfile verifies this digest instead of executing the mutable bun.sh installer.
  Changing the Bun pin requires a separately reviewed matching asset checksum.
- [CLI entry](https://unpkg.com/@oh-my-pi/pi-coding-agent@18.0.4/src/cli.ts):
  Bun shebang and minimum-version guard; `--version` uses the lightweight runner
  rather than launch/setup. This does not prove distribution worker/native-module
  behavior. Healthcheck also uses a disposable HOME, not private state.
- [Root helpers](https://unpkg.com/@oh-my-pi/pi-utils@18.0.4/src/dirs.ts):
  native `.omp/agent` defaults; `PI_CONFIG_DIR`/`PI_CODING_AGENT_DIR` are supported
  compatibility overrides but **not set here**. XDG/profile redirects are not
  inherited from the host. CLI-selected profiles are upstream functionality, but
  this MVP wires shared references only in the default profile.
- [Settings](https://unpkg.com/@oh-my-pi/pi-coding-agent@18.0.4/src/config/settings.ts)
  and [schema](https://unpkg.com/@oh-my-pi/pi-coding-agent@18.0.4/src/config/settings-schema.ts):
  YAML mapping is loaded before legacy migration; existing `config.yml` prevents
  fallback migration. Schema defines numeric `setupVersion`; setup scenes compare
  it against scene versions ([wizard](https://unpkg.com/@oh-my-pi/pi-coding-agent@18.0.4/src/modes/setup-wizard/index.ts)).
  [Current setup version](https://unpkg.com/@oh-my-pi/pi-coding-agent@18.0.4/src/modes/setup-version.ts)
  is exactly 2. Starter retains `setupVersion: 2`; interactive setup can be requested explicitly.
  No setup or migration runs during image construction.
- [Models](https://unpkg.com/@oh-my-pi/pi-coding-agent@18.0.4/src/config/model-registry.ts):
  default file is `models.yml`; empty providers leave bundled models available.
  Upstream may also probe optional local model endpoints; no working LAN model
  connection is implied by these minimal defaults.
- [Native discovery](https://unpkg.com/@oh-my-pi/pi-coding-agent@18.0.4/src/discovery/builtin.ts)
  and [helpers](https://unpkg.com/@oh-my-pi/pi-coding-agent@18.0.4/src/discovery/helpers.ts):
  `SYSTEM.md` is read as plain Markdown; native project config is considered
  separately from user config. Commands/prompts use nonrecursive Markdown scans
  (native glob, Git ignores enabled). Skill scanning reads immediate child
  directories or symlinks containing `SKILL.md`, requires description frontmatter,
  and skips `enabled: false`. It does not recursively traverse grouped skill trees.
- [Task discovery](https://unpkg.com/@oh-my-pi/pi-coding-agent@18.0.4/src/task/discovery.ts):
  nearest project `.omp/agents` > user agents > extension/plugin agents > bundled.
  Top-level Markdown files/symlinks only; parser requires `name` and `description`.
  Bundled task agents remain available independently of this harness.
- [Argument parser](https://unpkg.com/@oh-my-pi/pi-coding-agent@18.0.4/src/cli/args.ts)
  and [flag table](https://unpkg.com/@oh-my-pi/pi-coding-agent@18.0.4/src/cli/flag-tables.ts):
  `-r`/`--resume`/`--session` take an optional nonempty, non-flag next value;
  without it they select the picker. The wrapper does not reinterpret this arity.

```text
/opt/agent/system/build.md --------> ~/.omp/agent/SYSTEM.md (reference)
/opt/agent/commands ---------------> ~/.omp/agent/commands (one reference)
/opt/agent/skills/<group>/<skill> --> ~/.omp/agent/skills/<skill> (directory links)
```

Plain `agent/system/*.md` personas lack OMP agent frontmatter. They are consumed
as a selected system prompt, **not falsely registered as task agents**. The
default is `build`; choosing another persona requires explicit removal of only
the old recognized `SYSTEM.md` link while OMP is stopped, then recreation with
the new `OMP_PERSONA`. Unknown links/files/directories always survive conflicts;
init fails with a notice rather than silently using a different resource.

`agent/prompts -> commands` is the same source, so no second prompt link is
created. Top-level `fix-test.md` and `start-web.md` are the supported command
candidates. Nested `commands/gsd`, `commands/infra`, `agent/gsd` and other resources
remain readable at `/opt/agent`, **not promised as registered slash commands**.
Command discovery is not proof that the workflow body/tool vocabulary is OMP
compatible. Workspace-native `.omp` and cross-tool discovery may override or
collide with global resources under upstream precedence; the harness does not
disable project discovery or manufacture a `.agents` tree.

Skill wiring is the only layout adapter: a bounded scan of direct and one-group
skill directories creates individual references. No recursive shared-root link,
no copied bodies, no Pi themes/settings/extensions. Duplicate directory basenames
with different targets fail as conflicts. Stale links are not silently removed:
after renaming/removing shared skills, review and retire only the corresponding
old links explicitly. Editing through references edits the shared repository.

## Security and state ownership

- No passwordless container sudo; no privileged/host-namespace flags, extra devices,
  Docker group grants, socket mount or `DOCKER_HOST` forwarding. Docker daemon
  access on a rootful host is nevertheless host-root-equivalent; labels prevent
  accidental lifecycle cross-talk, not malicious Docker administrators.
- Workspace and shared resources are read-write by design. SSH/init/gitconfig are
  read-only, but SSH credentials remain readable to the agent. This is not
  zero-trust confinement: executable tools, shared prompts and project configs
  are trusted inputs, and outbound network access is not restricted here.
- API values are not build arguments and runner passes only environment names on
  argv. Docker administrators can inspect container environment. Treat logs,
  transcripts, DBs, blobs, and crash reports as potentially secret too.
- `.omp` defaults deny all new runtime paths. `agent.db`, `history.db`, `models.db`,
  their WAL/SHM/journal sidecars, sessions, blobs, caches, plugins, profiles,
  install identity and backups must never be committed. Ignore rules do not protect
  secrets manually inserted in tracked YAML or force-added files.
- Each component state root is private, but all workspaces using its default root
  share OMP auth/history. Every workspace is mounted as `/workspace`: upstream
  cwd-based history can therefore group distinct host projects together. Select
  sessions carefully; use separate `OMP_STATE_DIR` roots for history separation.
  The workspace label isolates container reuse, not upstream session indexing.
- Base image, apt repositories, pip tooling, Playwright and transitive OMP
  dependencies are not hermetically locked. Terraform download retains the prior
  unchecked-archive pattern. These are residual supply-chain risks.

## Offline migration and rollback

**Not performed, automated, or approved by launching this component.** Old tracked
Pi `config.yml`/`models.yml` and their exceptions remain until preflight. All old
ignored state remains operator-owned. Rebuilding source does not migrate data.

1. Obtain a separate migration approval/maintenance window. Inventory local YAML
   modifications and record old image IDs/configuration privately. Save customized
   YAML and especially the rollback `config.yml` sentinel outside Git; do not reset
   or clean the checkout. Only then consider future tracked-default removal.
2. Stop all old OMP processes **and every writer sharing old Pi state**, not the
   whole infrastructure stack. Confirm no writers remain. Take a private, mode-0700
   backup with restricted files; it may contain Pi secrets and must never be
   committed, logged, or mounted into the new OMP container.
3. Establish nonoverlapping canonical source, stage and destination directories.
   Refuse symlink escapes or existing credentials/nonempty target state. Only
   pristine starter YAML is replaceable after explicit confirmation; customized
   target YAML is a conflict. Do not merge trees or overwrite credentials.
4. Use an explicit OMP-only copy allowlist. Pinned `dirs.ts` identifies
   `agent/config.yml`, `agent/models.yml`, `agent/agent.db` (auth/settings),
   `agent/history.db` (session history), `agent/models.db` (model cache),
   `agent/blobs` and `agent/sessions`. **Path existence does not prove old provenance**:
   sessions in the former shared root require separate classification before copy.
   Exclude Pi `auth.json`, JSON settings/models/keybindings, Pi sessions, extensions,
   plugins, themes, ambiguous caches and installation identity. The pinned source
   also identifies `secret-placeholder.key`; determine whether selected history
   depends on it before enabling secret-placeholder history migration. Do not
   blindly transfer or regenerate it for an existing archive.
5. Copy, never move. For SQLite use an offline SQLite backup API or a proven
   consistent snapshot accounting for WAL/SHM. Copying only a live main DB is not
   safe. Run integrity checks without printing secret rows. Validate a private
   staged copy and promote it without overwriting existing state. Restrict new
   directories to 0700 and auth DB to 0600; adjust only destination ownership for
   the configured UID/GID. Verify source checksums unchanged, privately.
6. Before launching with real history, classify its format and saved absolute
   paths for that source version. This pass verified path helpers and resume
   argument arity, **not legacy session-format compatibility or path rewriting**.
   Old `/home/pi` paths may need explicit mapping; both old and new Docker runs
   use `/workspace`, which alone cannot identify the original host project.
   Keep ambiguous history archived rather than attempting wholesale conversion.
7. Validate only the new OMP container first: authentication without logging keys,
   selected conversation/resume, resource discovery and persistence. Then validate
   vanilla Pi independently. Do not use `fclean` as a migration shortcut.
8. Rollback: stop only new OMP writers; preserve new state separately; restore old
   image/config and YAML sentinel if needed; use untouched old state. Never merge
   databases backward or overwrite newer Pi credentials. Post-cutover histories
   diverge; rollback returns to the prior snapshot, not synchronized state.

## User validation handoff

These are **suggested operator commands, not commands executed by the agent**.
Start with source-only checks from `services/agents`:

```bash
bash -n omp/omp omp/omp-run omp/omp-mgr omp/common.sh omp/init.sh pi/pi pi/pi-run
git diff --check -- omp pi/Dockerfile pi/pi pi/pi-run pi/docker-compose.yml pi/.env.example pi/README.md README.md .gitignore
git check-ignore --no-index omp/.omp/agent/agent.db-wal omp/.omp/agent/auth.json omp/.omp/profiles/private/config.yml
# The two defaults below should NOT be ignored (exit status 1 is expected):
git check-ignore --no-index omp/.omp/agent/config.yml omp/.omp/agent/models.yml
```

After you choose to validate runtime, use disposable paths/defaults and dummy
credentials first; do not point these commands at legacy Pi state:

```bash
docker build -t lab/omp:extraction-test omp
docker build -t lab/pi:extraction-test pi
docker run --rm --network none --entrypoint /usr/local/bin/omp lab/omp:extraction-test --version
docker run --rm --network none --entrypoint /usr/local/bin/pi lab/pi:extraction-test --version
# Prepare private synthetic OMP state (agent/config.yml, agent/models.yml),
# disposable workspace, and a COPY of shared resources for mutation checks.
export OMP_IMAGE=lab/omp:extraction-test
export OMP_STATE_DIR=/absolute/disposable/omp-state
export OMP_AGENT_DIR=/absolute/disposable/agent-resources
export SSH_DIR_PATH=/absolute/disposable/empty-ssh
omp/omp /absolute/disposable/workspace
```

Separately render Compose with an explicit non-secret env file and canonical
`OMP_COMPONENT_DIR`/`WORKSPACE_PATH` (do not print real provider secrets). Check
static-container ownership and mount equivalence before using its lifecycle.

Remaining acceptance work: shell/Python/Compose syntax; fake-Docker argv and
ownership/failure/race checks; image install/bin/native workers; default-home
healthcheck side effects; non-root permissions; TTY/stdin/exit/signal behavior;
actual SYSTEM/command/skill discovery and precedence (including native glob on
the linked commands root with ignores); conflicts, same-basename workspaces,
static/per-workspace lifecycle, and resource limit normalization; provider login,
model reachability, DB concurrency/persistence, resumed cwd/history separation,
offline snapshot/rollback and secret exclusions. No automated test coverage was
added in this pass. No live migration or deployment should be inferred from the
source implementation.
