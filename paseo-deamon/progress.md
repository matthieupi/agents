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
