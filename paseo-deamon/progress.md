## 2026-09-12 — Isolated Paseo/OpenCode component
- Added build, Compose, native-auth startup, config example, tests and mapping/build documentation.
- Reused maintained OpenCode native installer; official Paseo base owns Paseo packaging.
- Scope is only paseo-deamon; preserved pre-existing agent/venv edits. No deployment or remote operations.
- Docker executable unavailable; no image built, live discovery, native authentication or provider session verified.
- Registry observations: OpenCode 1.18.30, Paseo CLI 0.8.0; not installed-version evidence.
- Parent submodule enumeration encounters unrelated missing .gitmodules mapping; agents Git status inspected directly.
- Verification: 4 unittest tests passed; real Compose rendering test skipped because Docker is absent. No mocks presented as live evidence.
- Initial test run exposed unwritable /tmp/opencode and extensionless TypeScript imports; fixtures now use temporary directories within this component and resolve .ts imports.
- Added explicit official-image digest format guard and aligned UID-1000 passwd HOME with identity discovery mounts.

## 2026-09-12 — Runtime Paseo account and home
- Renamed the UID 1000 passwd account to `paseo` when necessary and set its actual home to `/home/paseo`; numeric UID/GID runtime behavior is unchanged.
- Rehomed managed OpenCode, SSH, and Git mount destinations and environment values from `/home/runner` to `/home/paseo`.
- Preserved upstream HOME-volume suppression and restored the baked KDCO asset into its private tmpfs layer so the suppression does not hide required image content.
- No build, deployment, or remote operation was run.
- Corrected a YAML indentation regression found by the component test suite before final validation.
- Verification: 5 component tests passed; Compose rendering remains skipped because Docker is unavailable.

## 2026-09-12 — KDCO tmpfs correction
- Replaced startup KDCO tree copying with an exact, idempotent symlink to the immutable image asset; foreign links and directories are rejected.
- Made HOME and ephemeral OpenCode config tmpfs ownership follow `PASEO_UID`/`PASEO_GID`, retaining read-only managed descendant mounts.
- Verification: 6 component tests passed; Compose rendering remains skipped because Docker is unavailable.

## 2026-10-20 — Repo-owned OpenCode V2 dependency migration
- Removed the deleted plugin publication helper and vendored KDCO build inputs, startup constant/link function and link test. KDCO package removal itself is owned by another task.
- Kept the official exact-version/digest Paseo base and package checks unchanged. Reused native `install_runtime()` for scoped local `@opencode/cli@latest`; removed the ignored OpenCode version build input.
- Build checks scoped package metadata, native latest receipt and prefixed CLI output using build-only HOME. Records normalized `/opt/opencode-version.txt` and `/opt/opencode-install.json`; these are build outputs, not versions observed in this workstream.
- Replaced deleted tui.json with cli.json and explicitly mounted canonical title/background server plugins and both session-title TUI assets read-only. No whole plugin-directory mount or KDCO publication remains. Private-state mounts/auth/locks and identity boundaries are unchanged.
- Historical review (superseded by the 0.12.0 review below): official Paseo v0.8.0 commit b8e24677e12b226c7c38c1c3a40649daa9f1152f uses legacy `serve --port`, HTTP/SSE and `@opencode-ai/sdk/v2/client`, NOT ACP. That older SDK's /v2 name does not establish new CLI V2 compatibility. Reviewed the same revision's official docker/base/Dockerfile supervisor/HOME contract.
- External caller handoff: remove OPENCODE_VERSION, replace OPENCODE_TUI_CONFIG_PATH with OPENCODE_CLI_CONFIG_PATH, add OPENCODE_TUI_PLUGINS_PATH, retain canonical OPENCODE_PLUGINS_PATH and all private state selectors. External infrastructure/control files were not edited.
- Verification: existing canonical title/background Node tests passed 23/23. Python source, Dockerfile Node validator and native build shell syntax checks passed; `git diff --check -- paseo-deamon` passed.
- Component unittest discovery was attempted with system Python and the existing /workspace/.venv-agents interpreter; both blocked at missing PyYAML (no dependency installed). Docker CLI exists but Compose plugin is absent; its render test now detects that accurately. Component assertions, real Compose render, actual native installation/image build, fresh-cache plugin discovery and live provider/API/auth/state/signal behavior are NOT passed evidence.
- No deployment, commit, remote execution, or actual runtime HOME or /state access. Pre-existing file mode changes were preserved.

## 2026-10-20 — Verified Paseo 0.12.0 native V2 provider
- Reviewed published release gitHead cafe4b01c8522ff39560241c5deb01427dc8dc5b: provider-registry selects OpenCodeRuntimeClient; runtime-client detects V2 >=2.0.10 and imports v2/agent; v2/runtime starts localhost port-0 serve, generates OPENCODE_PASSWORD and uses authenticated @opencode/client. The server declares exact @opencode/client 2.0.10 alongside the legacy SDK. No adapter rewrite is required; README's historical 0.8.0 blocker is replaced with current verified source support.
- Added build-only verify-paseo.mjs: exact stable Paseo >=0.12.0, exact matching CLI/server package names/versions, declared exact V2 client >=2.0.10 <3, and compiled provider registry/runtime-client/V2 agent/runtime existence. Layout is grounded in the reviewed server package files and tsconfig rootDir src/outDir dist/server. This is a fail-closed packaging prerequisite, not complete installed dependency resolution or live provider acceptance.
- Retained exact PASEO_VERSION and official version/digest base guard. Only OpenCode resolves latest; its recorded build version must now be major 2 and >=2.0.10, matching upstream selection support. Updated Compose fixture to 0.12.0 and a synthetic digest-shaped pin.
- Verification: 10/10 new disposable-fixture Node tests passed, including older-release rejection, exact-version mismatch, missing/old/ranged client dependency and missing runtime modules. Scoped diff whitespace check passed. Component unittest retried with /workspace/.venv-agents/bin/python: still blocked by missing PyYAML. Caller can rerun with its prepared isolated environment; no Python dependency was installed here.
- Selected pinned image build, compiled layout inside that image and live provider/session/tool/security acceptance remain pending. No selected digest was supplied, no image was built/deployed, and no actual runtime HOME/state was accessed. No production KDCO references remain; historical notes and negative tests retain the name.
