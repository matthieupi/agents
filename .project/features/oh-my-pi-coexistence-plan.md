# Oh My Pi Coexistence Plan

## ✅ Recommendation

Install a pinned Oh My Pi (OMP) release alongside upstream Pi, preserve `./pi` as the existing Pi launcher, and make `./pi --oh [args...]` select the `omp` executable. Keep the image/container naming and detached keep-alive lifecycle unchanged; select the actual agent only at the existing `docker exec` boundary.

Reuse the mounted `pi/.pi` root as requested by setting `PI_CONFIG_DIR=.pi` and retaining `PI_CODING_AGENT_DIR=/home/pi/.pi/agent`. Add an OMP-native `config.yml` before first launch so OMP does not rename Pi's existing `settings.json` during legacy migration. Keep extension presets Pi-only initially; OMP already has native subagents, and the checked-in extensions spawn `pi` and use Pi-specific tool names.

## 🔎 Web Research Findings

Authoritative sources checked on 2026-08-24:

- Canonical project: [`can1357/oh-my-pi`](https://github.com/can1357/oh-my-pi), a fork/distribution of Pi—not a Pi extension or wrapper.
- Package: [`@oh-my-pi/pi-coding-agent`](https://www.npmjs.com/package/@oh-my-pi/pi-coding-agent); executable: `omp`.
- Current stable version: `18.0.4`; package requires Bun `>=1.3.14` and publishes provenance metadata.
- Upstream recommends `bun install -g @oh-my-pi/pi-coding-agent`; its Dockerfile pins Bun `1.4.0` and launches `omp` through `tini`.
- OMP supports the required Pi-like launch surface: interactive `omp`, `-p`, `--mode json`, `-e`, `--no-extensions`, `--session`, and provider API-key environment variables.
- OMP defaults to `~/.omp`, but `PI_CONFIG_DIR` changes its user root and `PI_CODING_AGENT_DIR` changes its default-profile agent directory. Project-native config remains `<workspace>/.omp`.
- If `config.yml` is absent, OMP migrates `settings.json` to YAML and renames the JSON file to `.bak`; coexistence therefore requires creating OMP YAML first.

Primary references:

- https://github.com/can1357/oh-my-pi/blob/main/README.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/cli-reference.md
- https://github.com/can1357/oh-my-pi/blob/main/docs/config-usage.md
- https://github.com/can1357/oh-my-pi/blob/main/Dockerfile
- https://github.com/can1357/oh-my-pi/blob/main/scripts/install.sh
- https://registry.npmjs.org/@oh-my-pi%2Fpi-coding-agent/latest

## 📍 Current State

- `pi/Dockerfile` installs an unpinned `@mariozechner/pi-coding-agent`, health-checks `pi --version`, and defaults to `CMD ["pi"]`.
- Both Compose and the host wrapper start `init.sh && tail -f /dev/null`; normal agent startup happens later through `docker exec ... pi`.
- `pi/pi` is a command-first router. `pi/pi-run` owns workspace resolution, container lifecycle, extension presets, and the two final `docker exec` calls.
- The whole `pi/.pi` tree is mounted at `/home/pi/.pi`, with `PI_CODING_AGENT_DIR=/home/pi/.pi/agent`.
- Existing Pi extensions import legacy `@mariozechner/*` APIs. OMP has compatibility loading, but five orchestration extensions explicitly spawn `pi`, and some pass tool names that do not match OMP's native tool set.
- Neighboring OpenCode follows the same keep-alive-container pattern and reruns `init.sh` at every attach. Pi currently runs initialization only when creating a container.
- The direct Pi wrapper incorrectly mounts the repository root at `/opt/agents`, while `init.sh` expects the shared agent tree at `/opt/agent`.
- No automated harness integration tests exist; validation is currently shell/Compose/image smoke testing.

## 🗺️ Target Flow

```text
./pi [existing command/path/args]
  -> pi/pi-run --agent-cli pi
  -> detached lab/pi:latest container
  -> init.sh
  -> docker exec ... pi

./pi --oh [path] [omp args]
  -> pi/pi-run --agent-cli omp
  -> same detached lab/pi:latest container
  -> init.sh rerun on attach
  -> docker exec ... omp

                         +------------------------------+
Pi --------------------> | /home/pi/.pi/agent           |
OMP (PI_CONFIG_DIR=.pi)->| settings.json  (Pi)          |
                         | config.yml    (OMP)          |
                         | auth.json      (Pi)          |
                         | agent.db       (OMP)         |
                         | extensions/, skills/, themes |
                         +------------------------------+
```

## 📊 Decisions and Boundaries

| Decision | Plan | Reason |
|---|---|---|
| Runtime model | Side-by-side | User selected `./pi --oh`; upstream Pi remains the default and rollback path. |
| OMP install | Pinned Bun + pinned package | Matches upstream recommendation and this repository's global-package image pattern. |
| Versions | `BUN_VERSION=1.4.0`, `OMP_VERSION=18.0.4` build args | Reproducible builds; easy explicit upgrades. |
| Container lifecycle | Keep detached `tail -f /dev/null` | Matches all current harnesses; changing Dockerfile `CMD` alone would not affect normal use. |
| Persistence | Reuse `/home/pi/.pi` | User decision; `PI_CONFIG_DIR=.pi` makes OMP root-level state durable. |
| Settings | Separate files in shared root | `settings.json` remains Pi-owned; `config.yml` is OMP-owned and prevents destructive auto-migration. |
| Extension presets | Pi-only in first pass | Presets explicitly spawn `pi`; silently changing nested runtime would be unsafe. |
| Shared mount defect | Fix in this pass | OMP should not inherit a known direct-wrapper integration break. |
| OMP self-update | Do not use in containers | Rebuild from pinned image versions instead of mutating running containers. |

## 💻 Method Signature Surface

```text
pi/pi
  / usage() -> void                         # document --oh launch mode

pi/pi-run
  + validate_agent_cli(value: string) -> void
  + exec_agent(container_name: string, args: string[]) -> never
  / docker_run_pi(args: string[]) -> void   # add shared OMP environment

pi/init.sh
  / init_home() -> void                     # remain idempotent for attach-time execution

No TypeScript extension callable signatures change in the first pass.
```

## 💻 Intended Code Shape

### 1. Install both CLIs reproducibly

Update `pi/Dockerfile` without removing Pi:

```dockerfile
ARG BUN_VERSION=1.4.0
ARG OMP_VERSION=18.0.4

ENV BUN_INSTALL=/opt/bun
ENV PATH=/opt/bun/bin:/home/pi/.local/bin:/usr/local/bin:/usr/bin:/bin

RUN curl -fsSL https://bun.sh/install | bash -s "bun-v${BUN_VERSION}" \
    && bun install -g "@oh-my-pi/pi-coding-agent@${OMP_VERSION}" \
    && bun --version \
    && omp --version

HEALTHCHECK ... CMD pi --version && omp --version || exit 1
CMD ["pi"]
```

Keep `CMD ["pi"]` because Pi remains the image default; wrapper/Compose workflows override it with the keep-alive command anyway. Do not use the mutable `curl https://omp.sh/install | sh` path in the image.

### 2. Add an explicit runtime selector

Route the public flag before normal command dispatch:

```diff
 case "$CMD" in
+    --oh)
+        shift
+        OMP_HARNESS_ARGS=(--agent-cli omp)
+        # Consume an immediate harness-owned --login, then stop option parsing.
+        exec "${SCRIPT_DIR}/pi-run" "${OMP_HARNESS_ARGS[@]}" -- "$@"
+        ;;
```

In `pi-run`, consume the internal selector before workspace/agent arguments, validate it against the closed set `pi|omp`, and centralize attach behavior:

```bash
AGENT_CLI="pi"

exec_agent() {
    local container_name="$1"
    shift
    exec docker exec -it \
        "$container_name" \
        bash -lc '/opt/harness/init.sh && exec "$0" "$@"' \
        "$AGENT_CLI" "$@"
}
```

Use this helper for both existing-container and new-container attaches. This removes duplicate literal `pi` invocations and adopts OpenCode's safer attach-time `init.sh` pattern.

Expected UX:

```bash
./pi                         # unchanged: upstream Pi
./pi /workspace             # unchanged: upstream Pi
./pi --oh                    # OMP TUI
./pi --oh /workspace         # OMP in selected workspace
./pi --oh -p "Review this"  # OMP one-shot mode
./pi --oh --login            # OMP with existing OAuth callback ports published
docker exec -it pi omp       # manual Compose attach
```

Named `ext-*` commands continue to launch Pi. Do not reinterpret `./pi --oh ext-agent-team`; OMP's native `task`/Agent Hub is the supported OMP orchestration path in this pass.

### 3. Reuse `.pi` without breaking Pi

Add the same variables in Compose and direct-wrapper container creation:

```text
PI_CONFIG_DIR=.pi
PI_CODING_AGENT_DIR=/home/pi/.pi/agent
```

Create `pi/.pi/agent/config.yml` as an OMP-owned, valid YAML mapping before OMP's first launch. Seed only settings that are intentionally shared or needed for a usable first run; do not mechanically translate every Pi setting. Create `models.yml` only if the current Ollama/custom-provider entry is required, using OMP's documented provider schema. Leave Pi's `settings.json`, `models.json`, `auth.json`, and existing sessions untouched.

Add comments to the README—not machine config files—clarifying ownership:

```text
settings.json / models.json  -> upstream Pi
config.yml / models.yml      -> OMP
auth.json                    -> upstream Pi
agent.db                     -> OMP credentials/settings
```

⚠️ Both agents will see the shared `extensions/` directory. Validate OMP's legacy import compatibility before declaring extensions supported. Do not rewrite extension subprocesses in this first pass: `/sub` and the `ext-*` bundles continue spawning upstream Pi by design. OMP users should prefer OMP's built-in `task` tool until a dedicated extension-porting pass is requested.

### 4. Fix the shared-agent mount while touching startup

In `pi/pi-run`, replace:

```text
${SCRIPT_DIR}/.. -> /opt/agents
```

with the same contract Compose/OpenCode use:

```text
${SCRIPT_DIR}/../agent -> /opt/agent
```

Rename `AGENTS_DIR` to singular `AGENT_DIR` to match what it contains. This makes `init.sh` actually link shared commands/prompts/skills for per-workspace containers.

### 5. Documentation and operating model

Update `pi/README.md`, `pi/pi` help, and `pi/.env.example` to cover:

- OMP identity and `./pi --oh` examples.
- Direct Compose attach with `omp`.
- Pinned image upgrade flow (`OMP_VERSION` build argument, rebuild, recreate containers).
- Shared `.pi` file ownership and the one-time migration hazard.
- OMP credentials in `agent.db`; do not commit live credentials.
- OMP's project-local native config remains `.omp/`, despite the user root being `.pi`.
- Extension compatibility boundary and Pi-only named presets.
- `omp setup` is interactive and should run only after container startup, never during image build.

## 🧩 Implementation Slices

| Slice | Files | Deliverable |
|---|---|---|
| 1. Image capability | `pi/Dockerfile` | Both `pi` and pinned `omp` are installed and health-checked. |
| 2. Runtime selection | `pi/pi`, `pi/pi-run` | `./pi --oh` forwards all remaining arguments to `omp`; existing Pi routes are unchanged. |
| 3. Durable shared state | `pi/docker-compose.yml`, `pi/pi-run`, `pi/.pi/agent/config.yml` | OMP uses the mounted `.pi` root without migrating/removing Pi JSON settings. |
| 4. Harness consistency | `pi/pi-run`, `pi/init.sh` | Shared agent mount is corrected and initialization reruns safely before every attach. |
| 5. Operator docs | `pi/README.md`, `pi/.env.example`, wrapper help | Installation, launch, state ownership, upgrade, and compatibility behavior are explicit. |

## 🧪 Verification

### Static checks

```bash
bash -n pi/pi pi/pi-run pi/pi-mgr pi/init.sh
docker compose -f pi/docker-compose.yml config
```

Confirm no unrelated files change and the existing untracked `opencode/.opencode/config/gsd` remains untouched.

### Image checks

```bash
docker build --build-arg BUN_VERSION=1.4.0 --build-arg OMP_VERSION=18.0.4 -t lab/pi:latest pi
docker run --rm lab/pi:latest pi --version
docker run --rm lab/pi:latest omp --version
docker inspect --format '{{json .Config.Healthcheck.Test}}' lab/pi:latest
```

### Runtime smoke matrix

| Case | Expected result |
|---|---|
| `./pi -p "reply ok"` | Existing Pi one-shot flow remains functional. |
| `./pi --oh -p --no-session "reply ok"` | OMP runs in the same workspace container and exits successfully. |
| Re-run `./pi --oh` | Existing container is reused; `init.sh` remains idempotent. |
| `./pi --oh /tmp/test-workspace` | Workspace parsing remains correct after selector removal. |
| `./pi --oh --login` | Container is recreated with callback ports when needed. |
| `docker exec pi omp --version` | Compose container exposes OMP directly. |
| Inspect `/home/pi/.pi/agent/settings.json` | File still exists and was not renamed to `.bak`. |
| Inspect `/home/pi/.pi/agent/config.yml` | OMP loads the intended YAML config. |
| Inspect shared links | `~/.pi/agent/{agents,prompts,skills}` point into `/opt/agent`. |

### Compatibility checks

1. Start OMP with extensions enabled and confirm legacy `@mariozechner/*` imports load without startup errors.
2. Verify one shared skill and one shared prompt are discoverable.
3. Verify OMP can discover the configured API provider or run `omp models`.
4. Confirm Pi still reads `settings.json` and its existing theme/provider configuration.
5. Invoke one existing `/sub` flow under each runtime and document that it launches upstream Pi until the extensions are deliberately ported.

## ⚠️ Risks and Mitigations

| Risk | Mitigation |
|---|---|
| OMP auto-renames Pi's `settings.json` | Check in a valid OMP `config.yml` before first launch and assert JSON remains in smoke tests. |
| Rapid upstream OMP releases alter behavior | Pin Bun and OMP build args; upgrade only through reviewed image rebuilds. |
| OMP extension compatibility is incomplete | Keep Pi as default/rollback; test ambient extensions; keep named presets Pi-only. |
| Shared sessions/config files have different formats | Treat file ownership explicitly; do not import or rename old sessions automatically. |
| Nested custom agents unexpectedly use Pi | Document current behavior; do not set a misleading runtime-propagation contract until tool/flag compatibility is ported. |
| Existing workspace containers hide a rebuilt image | Existing rebuild command already removes `pi-*` containers; document Compose recreation separately. |
| OMP writes credentials into tracked `.pi` | Verify `.gitignore` covers `agent.db` and other OMP state before authentication; extend ignores if required. |
| Direct wrapper currently misses shared resources | Correct mount source/target and rerun idempotent init on attach. |

## ✨ Follow-up (Not in This Pass)

- Port custom extensions to OMP-native package imports and tool names.
- Add runtime propagation for nested agents only after Pi/OMP argument compatibility is tested.
- Decide whether OMP should eventually become the default `./pi` runtime.
- Add executable shell integration tests for all agent harnesses rather than relying only on manual smoke checks.

### Critical Files for Implementation

- `pi/Dockerfile`
- `pi/pi`
- `pi/pi-run`
- `pi/docker-compose.yml`
- `pi/.pi/agent/config.yml`

### Saved Plan

- `.project/features/oh-my-pi-coexistence-plan.md`
