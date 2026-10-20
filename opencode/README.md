# OpenCode V2 — server-first workflows

OpenCode installation paths in this repository resolve **`@opencode/cli@latest`**.
There is no operator-supplied OpenCode version pin. A resolved version, image ID or
install receipt records what was built; it does not make `latest` reproducible.
Application auto-update is disabled; use the owning installation/build lifecycle.

The workstation, native service and shared-runtime client workflows are server-first:

```text
canonical config + private persistent state
    -> opencode serve -> authenticated GET /api/info
           ^
           +-- opencode --server http://127.0.0.1:<port>
           +-- optional published browser/API endpoint
```

Docker runs the server as PID 1; exiting its TUI client leaves the server running.
There is no idle `tail`, separate `web` process, V1 `attach`, or `/start-web` step.
Use the client helper inside workstation containers, not a bare `opencode` that
could start an independent local runtime.

## 📍 Choose the owning lifecycle

| Path | Owner and boundary |
| --- | --- |
| CPU/GPU workstation Docker | This README; writable canonical checkout config and shared resources |
| Native account/service | [Native lifecycle](#native-lifecycle); local execution as the selected account, not a sandbox |
| Protected VM images/gateway | [VM runtime](../venv/README.md#vm-image-adapters-and-auth-boundary); separate enrollment, secrets and activation contract |
| Opt-in shared runtime | [Runtime README](../runtime/README.md#opencode-v2--hard-clean-migration); explicit resolution/build/activation and exclusive HOME ownership |
| Paseo-managed child | [Paseo README](../paseo-deamon/README.md); dedicated state, upstream provider owns the server |

Source implementation or disposable tests do not establish deployed-host, provider,
browser, GPU or old-session acceptance. In particular, VM external-gateway/backend
credential integration remains infrastructure-owned and unresolved by this component.

## Workstation installation

Prerequisites: Docker Engine, Compose v2 for Compose usage, Bash, Python 3 and
`realpath` for the wrapper. Optional guided menus require [`gum`](https://github.com/charmbracelet/gum).
Commands here run from `agents/opencode/` unless stated otherwise.

```sh
cp .env.example .env
# Edit .env: set a strong server password and your chosen provider configuration.
mkdir -p workspace ssh .opencode/data .opencode/cache .opencode/state
docker network create devai-xmist    # once, only if the external network is absent
docker compose config --quiet
docker compose up -d --build
docker exec -it opencode bash /opt/harness/docker-client.sh
```

Compose reads `.env`; **the wrapper does not source it**. For wrapper launches,
supply secrets through an exported environment or your protected environment loader.
Provider authentication may also be completed through OpenCode; an API key is not
mandatory for every supported provider/authentication method.

```sh
# Supply OPENCODE_PASSWORD securely in the environment first.
docker build -t lab/opencode:latest .
./opencode /absolute/path/to/project
```

Mounts must be accessible to the container account: wrapper launches use UID/GID
**1000:1000**, regardless of the host caller. Compose permits `UID`/`GID` overrides;
its image passwd account is still UID 1000. Review ownership of the selected paths
rather than recursively chowning an unrelated checkout or HOME.

Both workstation launchers use the external `devai-xmist` network. For a standalone
Compose deployment, deliberately replace its external-network declaration with a
local bridge; the wrapper still requires the named network.

## CLI reference

```sh
./opencode                         # TUI in current directory
./opencode /path/to/project        # TUI in selected workspace
./opencode menu                    # guided command builder (alias: tui)
./opencode -w                      # browser/API on 127.0.0.1:4096
./opencode --web 5000 .            # host 5000 -> existing server port 4096
./opencode --web --port 5000 .     # equivalent explicit port form
./opencode --wlan 4096 .           # publish on 0.0.0.0 (LAN opt-in)
./opencode -d .                    # --dangerous: client --auto, denies still apply
```

Every server requires `OPENCODE_PASSWORD`, including TUI-only and loopback use.
`OPENCODE_SERVER_PASSWORD` is accepted as fallback when the preferred value is
empty/unset. Basic-auth username is fixed to **`opencode`**; custom usernames fail.
Passwords are inherited by clients, not placed in client argv or URLs. Docker
administrators can inspect container environments; this is not a secret vault.
LAN use requires your own firewall/TLS/access policy; Basic auth over plain HTTP
does not encrypt credentials.

`--agent-web-port 4096` publishes the already-running server on the LAN while
attaching the TUI. Only **4096** is supported in this legacy mode; use `--web PORT`
for remapping. It cannot combine with `--web`/`--wlan`. It exposes
`OPENCODE_AGENT_WEB_PORT`, `OPENCODE_AGENT_WEB_BIND_HOST` and
`OPENCODE_AGENT_WEB_URL`; optional `OPENCODE_AGENT_WEB_HOST` changes the advertised
host (default `localhost`), not the bind address. Do not start a second listener.

### Resources, GPU and extra ports

```sh
./opencode --cpus 4 --memory 8g .
./opencode --web 4096 --cpus 2 --mem 4g .
./opencode --gpu .                 # alias: -gpu; all GPUs
./opencode --gpu 0 .
./opencode --gpu 0,1 --cpus 8 --memory 32g .
./opencode --web 4096 --gpu .
./opencode --publish 3000 .
./opencode -p 5173:5173 -p 127.0.0.1:8080:80 .
./opencode -p 0.0.0.0:8080:80 .     # explicit LAN publication
```

Wrapper defaults: **8.0 CPUs / 16g memory**. Compose separately limits its service
to **2.0 CPUs / 2G memory**. Resource, GPU and publishing choices are container
creation settings; relaunching with different settings triggers replacement.

GPU uses `lab/opencode:gpu`, based on CUDA 12.4.1 **devel** with toolkit/compiler,
Python 3.11 development headers and native build tools. It requires NVIDIA Container
Toolkit and compatible host drivers. Validate host support independently:

```sh
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

GPU access grants agent commands real compute/VRAM/power capacity. `--publish`/`-p`
is repeatable and accepts `PORT`, `HOST:CONTAINER`, or
`127.0.0.1|0.0.0.0:HOST:CONTAINER`. Unqualified mappings normally expose all host
interfaces. Dev servers must listen on `0.0.0.0` inside the container. Container
port **4096** is reserved for OpenCode; use the dedicated web options for it.

### Rebuilds and container management

```sh
./opencode -r .                    # build CPU AND GPU images only; then exit
./opencode rebuild                 # CPU build + refresh workspace containers
./opencode rebuild gpu             # GPU build + refresh workspace containers
./opencode rebuild all             # both builds + refresh workspace containers
./opencode list                    # alias: ls
./opencode stop <name|all>
./opencode start <name>
./opencode remove <name|all>        # alias: rm
./opencode clean                   # remove stopped containers
./opencode clean -f                # stop first; also available as fclean
./opencode logs <name>
./opencode shell <name>
```

⚠️ Ordinary wrapper launches **automatically stop/remove/recreate** the selected
container when its immutable image ID, lifecycle/config fingerprint, resources,
GPU selector or published ports differ. Fingerprinting covers canonical root/CLI
config, plugin assets, init script, workspace/source paths and selected credential/
provider environment values. **Active sessions are interrupted.** This also applies
to password rotation and a same-tag image rebuild. Plan an idle window; replacement
is not a live migration. Matching running containers are reused after readiness;
stopped containers are removed and recreated on the next normal launch.

Names are `opencode-<workspace-basename>` and `opencode-<basename>-gpu`; equal
basenames collide even for different paths. CPU/GPU profiles have separate names
but share canonical state. Manager `rebuild` (alias `update`) force-removes matching
workspace containers across profiles, not just the rebuilt profile. `start` merely
starts an existing container; it does not reconcile it to current launch settings.

Docker build caches can reuse the npm `latest` layer; even manager `--pull` does
not force npm re-resolution. Deliberately refresh latest with:

```sh
docker build --no-cache -t lab/opencode:latest .
docker build --no-cache -f Dockerfile.gpu -t lab/opencode:gpu .
# Compose alternative: docker compose build --no-cache opencode
```

Repeat disposable acceptance after refreshing. Compose owns its own replacement
behavior (`docker compose up -d --build`); the wrapper fingerprint is not a Compose
controller. Do not mix the two managers for the same container.

## Canonical configuration and persistence

There is one public V2 source tree, **`.opencode/config/`**, not a parallel V2
configuration/state tree. Docker mounts it directly, read-write, at
`/home/opencode/.config/opencode`; init does not project or rewrite its JSON.

| Workstation host path | Container use |
| --- | --- |
| `.opencode/config` | `~/.config/opencode`: canonical server config, CLI config, plugins |
| `.opencode/data` | `~/.local/share/opencode`: sessions and provider authentication |
| `.opencode/cache` | `~/.cache/opencode`: caches |
| `.opencode/state` | `~/.local/state/opencode`: CLI state |
| `../agent` | `/opt/agent`, writable shared commands/skills/system/GSD resources |
| selected workspace | `/workspace`, writable project |
| `SSH_DIR_PATH` (default `./ssh`) | `~/.ssh`, read-only identity/config/known_hosts |

Compose additionally supports `GITCONFIG_PATH` as a read-only Git config mount.
Keep private state out of Git and retain these directories across container
replacement. The scripts do not delete old session/auth databases; **actual V1
database conversion and recovery of real old sessions remain unverified**. Upstream
V2 owns database/legacy syntax normalization. Existing bytes being retained is not
proof of compatibility, a backup, or a clean rollback guarantee.

### Public defaults and plugin behavior

- `opencode.json` uses native V2 `agents`, `providers`, ordered `permissions`,
  `system` prompt references and `request` settings. Default model is
  `openai/gpt-6`; the native `title` agent uses `openai/gpt-5-mini`.
- Canonical permissions globally allow actions, with selected per-agent overrides.
  Read-only role descriptions are not filesystem sandboxes (some allow shell).
- Automatic compaction is **disabled**: `compaction: {auto: false, buffer: 50000}`.
  `gpt-6-astra` and `gpt-6.1-sol` declare **320,000 input**, 1,050,000 context and
  128,000 output tokens. The buffer is not an enabled 270,000-token trigger, hard
  byte cap, or verified fix for upstream long-session request-size failures.
- Server plugins `plugins/first-prompt-title.js` and `plugins/background-subagents.js`
  use native V2 hooks. Background execution defaults to `true` only when a native
  `subagent` call omits it; **explicit `background: false` is allowed for every
  agent**, read-only or write-capable. Native permissions/depth checks still apply.
  Policy guidance favors completion notifications and dependency-driven work, not
  polling, sleeps, global wave barriers or legacy read/write tool routing.
- The first-prompt plugin owns only initial title generation through the native
  title hook. It preserves custom titles; the host owns persistence/concurrent
  rename protection. Optional bounded OpenAI title generation uses
  `OPENCODE_TITLE_API_KEY` (fallback `OPENAI_API_KEY`), `OPENCODE_TITLE_BASE_URL`
  (full chat-completions URL) and `OPENCODE_TITLE_MODEL` (default `gpt-4.1-mini`).
  Missing credentials/failure falls back to a first-prompt-derived title.
- `cli.json` selects the `opencode` theme and `./tui-plugins/session-title` package.
  Its `tui.js` shim loads the display-only `.mjs` plugin: a sanitized, colored,
  up-to-35-grapheme title appended at **`prompt.footer.status`**, not a replacement
  for the built-in footer or a title generator. See [title details and tests](.opencode/config/tui-plugins/README.md).

The title-specific environment overrides are plugin inputs, not automatically
forwarded by the workstation wrapper/Compose template; wire them deliberately in
the owning deployment if needed. Provider environment variables alone likewise do
not register every possible provider: configure the native provider schema.

Init links `commands`, `skills`, `system`, `gsd` directly from `/opt/agent` into
config and removes exact duplicate legacy `~/.agents` resource links. Docker's
resource-link helper can move conflicting local content to `.local*` and merge
missing files into the writable shared tree; review private conflicts first.
Shared Markdown `agents/` for other harnesses is not OpenCode's agent registry.
Redirected config roots and discovered `kdco-*` loaders fail with review guidance;
unknown plugin files are not silently deleted. Review project-local discovery too,
including later worktrees. No KDCO package/install/publication remains.

## Environment reference

| Input | Scope |
| --- | --- |
| `OPENCODE_PASSWORD` / `OPENCODE_SERVER_PASSWORD` | Required workstation/native server and client secret; preferred value wins |
| `OPENCODE_SERVER_USERNAME` | Only `opencode` accepted |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | Canonical provider environment references |
| `GEMINI_API_KEY`, `OPENROUTER_API_KEY` | Forwarded workstation inputs; configure provider/auth as appropriate |
| `OLLAMA_HOST` | Canonical Ollama base URL before `/v1`; default `http://ollama.xmist.dev:11434` |
| `OPENAI_COMPAT_BASE_URL`, `OPENAI_COMPAT_API_KEY` | Forwarded inputs for explicitly configured compatible providers |
| `WORKSPACE_PATH` | Compose workspace selector; wrapper uses positional path |
| `UID`, `GID` | Compose identity, defaults 1000; wrapper is fixed 1000:1000 |
| `OPENCODE_WEB_BIND_HOST`, `OPENCODE_WEB_PORT` | Compose publication, defaults `127.0.0.1:4096`; wrapper uses flags |
| `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL` | Workstation author/committer identity |
| `SSH_DIR_PATH`, `GITCONFIG_PATH` | Dedicated SSH directory; optional Git config (Compose only) |

SSH keys grant the agent the target account's rights. Provision dedicated keys,
least-privilege remote accounts and verified `known_hosts` before launch; the
read-only mount does not permit host-key enrollment. Workstation images run
non-root but include **passwordless sudo**, writable shared resources and execution
egress. They are trusted development environments, not per-agent isolation.

## Native lifecycle

Native scripts execute locally as an existing named non-root `OPENCODE_USER`.
Both UID and EUID must match its passwd UID. Root must not execute editable checkout
scripts or Git; infrastructure-owned wrappers must reject root before loading them.
Infrastructure owns accounts, tools, protected units/secrets, TLS/proxying and service
control. These scripts never create accounts, escalate privileges or control units.

| Input | Contract |
| --- | --- |
| `OPENCODE_REPO` | Default `/srv/agents`; full account-owned Git checkout, not worktree/submodule |
| `OPENCODE_ROOT` / `OPENCODE_PREFIX` | Must equal `$OPENCODE_REPO/opencode` / `$OPENCODE_ROOT/.runtime` |
| HOME and paths | Passwd HOME; existing account-owned home/checkout/component, canonical absolute paths outside `/opt`; home/checkout cannot overlap |
| `OPENCODE_WORKSPACE` | Existing canonical absolute launch directory outside `/opt` |
| `OPENCODE_PORT` | **Service and session**: decimal 1024..65535, no leading zeroes |
| Password/username | **Service and session**: same aliases and fixed username as Docker |
| `OPENCODE_PREVIOUS_REPO` | Optional explicit known old checkout for home-link migration |
| `OPENCODE_BRANCH` | Assigned local branch, required for explicit source update/check |
| `OPENCODE_UNIT` | Default `opencode.service`; read-only status only |

As that account, with the required inputs supplied securely:

```sh
bash "$OPENCODE_REPO/opencode/scripts/entrypoint.sh" install
bash "$OPENCODE_REPO/opencode/scripts/entrypoint.sh" initialize-home
bash "$OPENCODE_REPO/opencode/scripts/start.sh" service
# In another terminal, same account/port/password/workspace contract:
bash "$OPENCODE_REPO/opencode/scripts/start.sh" session
```

Install always resolves latest with a bounded local npm install in ignored staging,
sanitized HOME/XDG/npm configuration, approved CLI lifecycle and optional platform
packages. It verifies package metadata and actual `--version` before/after promotion;
public binary is `.runtime/bin/opencode`. No provider or session is launched for
verification. Sanitization is not a filesystem sandbox. Failed stages/logs remain
for inspection; promotion attempts to restore an old runtime on failure, but its
renames are not crash-atomic and provide no application-state rollback.

**Install does not initialize HOME.** Run `initialize-home` separately while sessions
are stopped; lifecycle locking serializes installers, not live state writers.
It seeds missing root config, links shared resources and canonical plugin/CLI assets.
Only the exact known public V1 root default (SHA256
`0a1dec62e5d116dbd684482dfb00ce0746200d536b0ec8cda49aaba4d88d3316`) is promoted
in place. Other custom root configs are preserved for upstream compatibility.
Known canonical/historical title bytes and exact current/previous managed links
may become canonical asset links. Exact public legacy KDCO re-export wrappers or
known current/previous wrapper links are unlinked, not their package targets.
Unknown/modified wrappers, title assets, CLI config or resource conflicts are
preserved and fail with actionable reconciliation guidance; do not force-delete
them. No migration backup/archive or clean rollback is created. Private CLI
preferences require explicit review; publishing canonical `cli.json` skips upstream
legacy TUI/KV preference migration. HOME auth/data/cache/state are not copied away.

Service execs `serve --hostname 127.0.0.1 --port <port>` with no extra flags;
session execs `--server http://127.0.0.1:<port>` and rejects server overrides.
Launch resets HOME/USER/LOGNAME and XDG paths to passwd HOME, fixes config/PATH,
disables auto-update and clears executable/test-home/Node overrides. It does not
source an environment file. The infrastructure proxy must reach loopback and
preserve the independent backend-auth boundary.

`manage.sh status` and `version` are read-only. `update-check FULL_SHA` and
`update FULL_SHA` require a clean assigned branch and a full lowercase commit SHA
on its fetched origin branch, descending from HEAD. Update is fast-forward-only
with ignored-file collision protection; no reset/clean/commit/push or implicit
install/restart. Drain sessions before installing or activating updated assets.

## Related integrations and limits

- **VM:** [backend secret/gateway handoff](../venv/README.md#opencode-v2-backend-secret-and-gateway-handoff)
  and [existing HOME migration](../venv/README.md#existing-opencode-home-migration)
  are distinct from native scripts. The VM requires a protected backend password
  file and external gateway Authorization translation/API/WS checks. Do not infer
  acceptance from a root-page `200`, V1 `/global/health` or an enrollment flag.
- **Shared runtime:** explicit `update` resolves latest, `build` replays its recorded
  resolution. OpenCode alone supports selected-image advancement in the **same HOME**
  under an exclusive writer lock, after rejecting remaining HOME-labelled containers
  and validating image/receipt/binding. It never kills/adopts containers to do so.
  Other harnesses remain image-bound and need a new empty state slot for image changes.
- **Paseo:** upstream **0.12.0** supports the native V2 provider (CLI minimum 2.0.10),
  including per-child password and authenticated client. Packaging checks are not
  actual image/provider/session/tool acceptance; do not attach it to workstation state.
- **Optional V1 packages:** [dispatch](dispatch/README.md) and
  [ssh-remote](ssh-remote/README.md) remain **default-off, V1-targeted and not ported
  or established compatible with V2**. Their retained instructions/tests are not a
  full optional-integration migration claim. Do not enable them in V2 on this basis.

## 🧪 Verification and troubleshooting

Run from the **agents repository root**:

```sh
bash -n opencode/opencode-run opencode/init.sh opencode/scripts/docker-{server,client}.sh
bash -n opencode/scripts/{entrypoint,start,manage}.sh
python3 -B -m unittest discover -s opencode/tests -p 'test_*.py' -v
node --test opencode/tests/*.test.mjs
node opencode/.opencode/config/tui-plugins/run-tests.mjs
# Optional isolated network import/setup contract smoke, not live rendering:
node opencode/.opencode/config/tui-plugins/run-tests.mjs --runtime
# Optional native smoke with an already-installed, reviewed V2 binary:
OPENCODE_NATIVE_TEST_BINARY=/absolute/path/to/opencode \
  python3 -B -m unittest discover -s opencode/tests -p 'test_native_lifecycle.py' -v
# Optional real Docker smoke with fresh disposable state and no host mounts:
docker build -t opencode-v2-check:disposable opencode
OPENCODE_DOCKER_SMOKE_IMAGE=opencode-v2-check:disposable \
  python3 -B -m unittest discover -s opencode/tests -p 'test_docker_v2.py' -v
```

Python tests cover native lifecycle/account guards with fixtures and Docker launcher/
readiness contracts; live Docker smoke is opt-in. Node tests cover server plugin
hooks; the title runner isolates HOME/XDG and mocks rendering. These commands do not
prove real provider calls, live footer rendering, GPU, native worktrees, V1 database
conversion or production gateway acceptance. No aggregate test totals are implied.

For startup failures, inspect `./opencode logs <name>` or `docker compose logs
opencode`, then check mounted-path ownership, required resource directories, stale
project plugins and password inputs. Health uses authenticated `/api/info` with V2
version/PID fields, not an unauthenticated HTML page. For repeated provider login,
check that the same persistent data path is mounted; do not delete it to troubleshoot.
If old state/config conflicts, stop affected writers and reconcile only the named
paths; retain unknown custom content for operator review.

## License

MIT
