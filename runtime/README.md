# Opt-in shared harness runtime

Explicit builds and foreground launches; no deployment, activation, state adoption,
automatic updates or pruning. Run the installer/adapter as an ordinary account,
never with sudo. Protected VM activation remains an explicit delegated operation.

## OpenCode V2 — hard clean migration

✅ OpenCode resolves **`@opencode/cli@latest`**, not `opencode-ai`, a V1 range, or
a user-configured version pin. `update` resolves the npm `latest` tag at that time.
The generated build manifest/lock and receipt record the **exact** resolved version,
registry URL and SHA512 integrity. This is immutable build evidence, not a public
configuration pin. `build` replays that resolution; run `update` to select latest
again. Other harnesses retain their existing reviewed ranges and recipes.

```sh
make -C runtime update HARNESS=opencode
make -C runtime build HARNESS=opencode
make -C runtime activate HARNESS=opencode IMAGE=sha256:<64-lowercase-hex>

python3 -B runtime/runtime.py run opencode --workspace /absolute/project -- --help
python3 -B runtime/runtime.py run opencode --workspace /absolute/project --web --port 4096
```

Workstation activation selects only future new-path launches. Existing images and
receipts are not rewritten. **OpenCode keeps its existing HOME and databases** when
switching selected images: the adapter first acquires the exclusive HOME writer
lock, rejects any remaining HOME-labelled container (including stopped/orphaned
containers), and verifies the selected image/receipt. Only then does it atomically
advance a valid existing image binding. It never stops, adopts or deletes an old
container to make the switch succeed. No new state slot or archived isolation root
is required for OpenCode. Other harnesses retain their original image binding and
require a new empty `--state-slot` when changing images. Unbound unknown state and
malformed bindings remain refused. Native OpenCode owns V1 config/database
normalization; the adapter does not rewrite private config or copy databases.
Before seeding defaults, a sole historical shared-runtime `config.json` is validated
as JSON/JSONC and moved to native `opencode.json` with exactly the same bytes and
mode, without converting settings or injecting canonical global defaults. Publication
is atomic and exclusive; the old name is retired only after the native name is
durable. Interrupted publication is recoverable only when both names identify that
same file. Other legacy/native filename conflicts require explicit reconciliation;
malformed or redirected legacy files fail closed without replacement. Existing native
`opencode.json` or `opencode.jsonc` remains private and suppresses global config seeding.
Rolling an image back does not reverse database writes or provide backup/restore.

### Public build closure

`install.build_sources()` is the single finite source-to-context map for hashing
and copying. OpenCode packages canonical public files from
`opencode/.opencode/config/`:

- `opencode.json`: native V2 `agents`, `providers`, `permissions` and public settings.
- `cli.json`.
- `plugins/first-prompt-title.js` and `plugins/background-subagents.js`.
- `tui-plugins/session-title.mjs` and the `session-title/tui.js` discovery shim.
- Exact `agent/system/*.md` and `agent/gsd/*.md` prompt files referenced by the
  canonical config, preserving their relative paths inside the public defaults.

No KDCO sources, deleted wrapper entrypoints, nested KDCO npm installs, config-root
dependency manifests, private credential trees or broad checkout copies are used.
Missing/symlinked inputs, stale resolutions and copy-time byte drift fail closed.
Source hashes, Git revision, lock and recipe remain bound into the image receipt.

Startup exclusively seeds public `opencode.json` and `cli.json` into
`~/.config/opencode/` and publishes individual required plugin files into physical
`plugins`/`tui-plugins` directories. Unrelated private plugin files are preserved;
required-name conflicts fail explicitly instead of silently hiding canonical plugins.
Known image-managed directory links are replaced with physical directories and
per-file links; unknown directory links are never followed or replaced. The exact
retired `kdco-background-agents.ts`, `kdco-worktree.ts` and `kdco-notify.ts` links
are removed only when their raw targets match the former public image/resource
paths. Unrecognized retired wrappers block startup without deletion. Existing V1
private config is preserved for native normalization, not copied into an archive.
Prompt directories remain managed links.
Physical config files ensure relative prompt references resolve from private config
HOME, not a symlink-resolved image path. With `--resources`,
reviewed shared `system`, `gsd`, `skills` and `commands` are linked instead of the
baked prompt fallback. Existing physical private files/directories are preserved;
redirected private config files are refused. Unknown conflicting symlinks fail
rather than being replaced. No V1 config isolation root
or V1 compatibility config is generated. Public provider settings reference
environment variables; private authentication remains in the isolated runtime HOME,
never copied from another account or baked into an image. The adapter does not
forward ambient host provider credentials.

### Server-first execution and credentials

```text
private image-bound HOME + canonical public config/prompt links
    -> protected per-HOME credential -> serve -> authenticated /api/info
                                                    |
                                      CLI client --server loopback URL
```

CLI startup runs a loopback server inside the container, waits for a V2 info
response with that server's PID, then attaches the CLI using `--server`. The
foreground supervisor forwards signals, returns the client's status and reaps its
children. Server output goes to a protected `.opencode-server.log` in that HOME.
The server endpoint is runtime-owned; caller `--server` overrides and unmanaged
`web`, `serve`, `upgrade` commands are refused.

`--web` runs `serve --hostname 0.0.0.0 --port <port>` with host publication restricted
to `127.0.0.1`. Readiness uses authenticated `/api/info` and requires V2 version/PID
fields, not V1 `/global/health` or an unauthenticated HTML page. It validates the
full Docker contract and exact running container ID before and after readiness.
This gate is not browser/provider acceptance or continuous health monitoring.

The runtime generates a random `.opencode-runtime-password` exclusively in the
private HOME, mode **0600**, and passes it only through `OPENCODE_PASSWORD` to
server/client processes. Basic-auth username is `opencode`. The host readiness
probe reads the same protected file, without importing executable startup code.
Symlinks, hardlinks, other ownership, broad permissions and malformed credentials
are refused. Credentials are not placed in Docker argv, URLs, contracts, receipts
or printed diagnostics. Environment credentials remain visible to the container's
account and Docker administrators; Docker access is host-root-equivalent.
OpenCode V2 refuses `--root-user`; other harnesses retain their disposable root mode.

### Dependency execution

Lock generation and `npm ci` disable lifecycle scripts. OpenCode's generated
package manifest approves only `allowScripts: {"@opencode/cli": true}`. Its image
rebuilds **only `@opencode/cli`**, as `node`, offline with BuildKit `--network=none`.
The optional platform package must already exist in the integrity-checked graph;
an unrecorded postinstall download fails. Other harness lifecycle behavior is
unchanged. Base image platform digest, Debian snapshot/signature verification and
`os-packages.tsv` evidence are retained.

## Isolation and caller contracts

The runtime contract remains schema/contract **1**; OpenCode V2 is the application
version, not a protected runtime receipt-schema migration. Pure contract builder
signatures and protected activation arguments are unchanged. Changes to startup,
catalog and public sources invalidate earlier build resolutions normally.

- Numeric caller UID/GID; dropped capabilities; no-new-privileges; read-only root;
  bounded tmpfs, memory/swap/CPU/PIDs; bridge network; no implicit Docker authority.
- Same absolute workspace path on host/container; separate private HOME per account,
  harness and state slot. Exclusive HOME writer lock; orphan containers block reuse.
- `--docker-socket`, `--cap-add NET_BIND_SERVICE`, `--root-user` (non-OpenCode),
  `--resources`, `--live-source`, `--checkout-write`, `--state-slot` are independent.
- Live startup is a reviewed two-file `entry.py`/`harnesses.json` bundle, not a broad
  checkout bind. Root never executes mutable startup/resources.
- No automatic adoption, killing, deletion, state repair or image pruning.

State is private under `~/.local/state/agents-runtime` (0700, receipts 0600).
Build receipts retain exact image ID, resolution, source digests and timestamps.
Ordinary-account receipts are **not** root authorization evidence.

Protected VM activation remains:

```sh
make -C runtime activate HARNESS=opencode IMAGE=sha256:<64-lowercase-hex> \
  SCOPE=vm VM_CONFIG=/etc/venv-agents/build.json TARGET=<environment>:<host>
```

It verifies protected config/launcher/policy custody, caller enrollment, exact target
and protected image projection, then delegates only finite harness/image arguments
via sudo. No mutable receipt/source/policy overrides cross that boundary. No Claude
VM enrollment. VM control promotion, gateway acceptance and lifecycle are owned by
the maintained VM launcher, not this workstation supervisor.

`make -C runtime resources RESOURCES=/absolute/reviewed/public/agent` reuses the VM
publisher to emit public V2 agent metadata; the tree must already contain physical
canonical prompts. No private providers/credentials are published. OpenCode runtime
startup uses its canonical baked config plus prompt links, not a V1 seed. The
`public_agents`/`seed_opencode` helper interfaces now consume **V2** metadata
(`agents`, `system`, `permissions`); callers must not send V1 manifests.

## Verification and acceptance boundaries

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s runtime/tests -v
git diff --check -- runtime
```

Offline tests stub Docker/network operations and exercise source closure, stale
evidence, exact receipts, credential protection, server/client sequencing, readiness,
activation and the other harness contracts. Legacy characterization additionally
needs PyYAML and a clean baseline; byte-identical-to-HEAD checks intentionally fail
against independently modified production trees.

⚠️ No image/runtime/provider acceptance is implied by offline tests. At migration
time the registry reported `@opencode/cli@latest = 2.0.32`; this is an observation,
not a pin. Docker is reachable through the environment's `docker` shim, but the
maintained adapter's fixed `/usr/bin/docker` executable is absent here, and local
npm execution is denied even for `npm --version`. No disposable install, image build
or online server/client acceptance was completed. Full legacy characterization
also requires PyYAML, absent from `/usr/bin/python3` here; no global dependency was
installed. No activation/deployment or actual user state was touched. Re-run latest
resolution and acceptance in an authorized builder with `/usr/bin/docker` available.
