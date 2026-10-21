# DevOps handoff: deploy the clean OpenCode V2 migration

## ✅ Task and completion boundary

**Objective:** publish the merged source, update the host-owned deployment and ingress, then rebuild/recreate OpenCode using `@opencode/cli@latest`. Preserve the existing server-first architecture, persistent user state, shared configuration, and access boundaries.

**Current status:** source migration and conflict resolution are complete. The finalized merge is being published with this handoff; verify that the deployment branch contains it before proceeding. **Production is still V1.** No production restart, credential rotation, database migration, or proxy change was performed.

**Owner:** DevOps, with access to the host deployment checkout, secret management, and external ingress configuration. Perform the cutover from an independent host SSH/management session—not from the OpenCode container being replaced.

Do not close this task after an image build alone. Completion requires authenticated end-to-end access, effective config/plugin checks, representative background-agent behavior, and a recorded recovery path.

## 📍 Intent and scope

The user explicitly approved:

- Install **`@opencode/cli@latest`**, not `opencode-ai@latest` and not a pinned OpenCode version.
- Make a hard, clean V2 switch. Do not retain a V1/V2 compatibility deployment, `config/v2/` tree, or separate V2 state roots.
- Retain one server that clients connect to. Exiting a TUI must not stop that server.
- Automatically replace workstation containers when their image/configuration changes; the user rejected the earlier refusal guard. Replacement interrupts active work, so schedule this production cutover deliberately.
- Retain the homebrew session-title prompt footer. The earlier port of custom
  first-prompt title generation is superseded: use native V2's built-in `title`
  agent with `openai/gpt-5-mini`; do not load `plugins/first-prompt-title.js`.
- Default native `subagent` calls to `background: true` when omitted. Preserve explicit `background: false` and native permission/depth checks.
- Preserve remote's subsequent architecture changes, including its agent roster/model choices and retirement of obsolete paths.

The initial motivation was slowest-worker wave barriers and missed work while the orchestrator waited. This implementation uses native background agents and completion notifications. **It does not implement a new durable dispatch queue, distributed workers, or automatic worktree integration/merge orchestration.** Do not promise those capabilities as deployment acceptance.

### Remote changes that must stay retired

Do not resurrect `runtime/`, `venv/`, GSD workflows, OMP/T3 products, native OpenCode start/manage scripts, or `opencode/docker-compose.yml`. The retained VM deployment is the ordinary service-template path documented in `VM-SERVICES.md`. Installer/init helpers remain build dependencies, not a restored native service framework.

## Git state and source publication

The table below records the snapshot immediately before publishing this handoff and the finalized merge. It is not the expected post-publication remote state.

Repository: `https://github.com/matthieupi/agents`

| Reference at handoff | State |
|---|---|
| Local `master` | `4d8764a3a61d9c10d9d5a0fc0653677170c4dfd4` |
| Merge commit | `merge(opencode): Reconcile V2 with service architecture` |
| Merge parents | `8a6ba61` — V2 migration; `c19d250` — remote service/config restructuring |
| Last fetched `origin/master` | `c19d250`; local `master` is ahead by two commits |
| Previously pushed `opencode/v2-migration` | Contains `8a6ba61`; **not the finalized merge** |
| Commit identity used | `COO <coo@intellagent.network>` |

Refresh remote references and confirm the deployment branch contains `4d8764a` and this handoff. Publish only if they are still missing; these values are a snapshot, not a guarantee that remote remains unchanged. If using `master`, a normal fast-forward push is expected only while remote has not diverged. Never force-push or overwrite newer remote work.

There is unrelated local work in `/workspace/agents`:

- Modified `agent/skills/README.md`.
- Untracked `agent/commands/n3tx-init.md` and `agent/skills/dev/n3tx-init/`.
- Widespread pre-existing permission-bit differences visible to ordinary `git status`.

These were excluded from the migration and preserved during integration. **Do not `git add .`, reset/clean the checkout, or blanket-stash/commit that work.** `git -c core.fileMode=false status --short` helps distinguish content changes from permission noise. The temporary merge worktree was removed; the merge is already applied to the primary checkout.

## Live environment observed

| Item | Observation |
|---|---|
| Running server container | `opencode-opencode-1` |
| Running image name | `opencode-opencode` |
| Last inspected running CLI | **1.18.29**; recheck before cutover |
| Published backend | `127.0.0.1:4096 -> container 4096` |
| Compose labels | Host deployment comes from `/srv/opencode/docker-compose.yml` |
| Current assistant environment | Inside the running OpenCode container; replacing it disconnects this conversation and terminates its tools |
| Host deployment files | `/srv/opencode` and the external proxy configuration are not available inside this container |
| Other running consumers | Paperclip daemon, Paseo daemon, Pi, and an unrelated application container; do not restart them indiscriminately |

The live deployment is **not** interchangeable with the workstation wrapper. It has host-owned service configuration, ingress, public-source mounts, and a custom entrypoint. Do not substitute the workstation launcher as a shortcut.

## 🗺️ Required architecture and authentication change

```text
External client
    |
    v
Existing TLS/Host/Origin enforcement + gateway authentication
    |
    | REPLACE upstream Authorization with backend Basic auth
    v
Loopback/controlled-network OpenCode V2 backend
    |   username: opencode
    |   password: protected OPENCODE_PASSWORD
    v
One server -> sessions, native background agents, completion notifications
```

### Critical incompatibility with the old deployment

The old contract authenticated at nginx and stripped `Authorization`, leaving the native upstream anonymous. **That does not work with V2.** Disposable checks against 2.0.32 and 2.1.1 returned 401 when the native password was absent/empty; clearing auth variables is not a bypass.

Required parent-owned changes:

1. Create/manage a protected, stable **`opencode_backend_password`** fact through the existing secret-management workflow.
2. Render it as `OPENCODE_PASSWORD` through `opencode/env.j2`. The template expects a single-line value; use a dotenv-safe generated secret, such as random hex, and protect the rendered `.env` file.
3. Keep the existing external gateway authentication. After successful client authentication, **replace** upstream `Authorization` with Basic authentication for `opencode:<backend password>`.
4. Do not forward the client's gateway credentials as native credentials, and do not simply strip the header. Both fail when credentials differ.
5. Preserve loopback publication, controlled backend-network access, exact allowed origins, streaming, TLS, Host/Origin checks, and any existing CORS preflight handling. Validate the actual V2 browser/client flow through ingress.
6. Preserve existing gateway/provider secret references. No rotation of those credentials is part of this task.

The source entrypoint deliberately fails early for direct `opencode serve` without `OPENCODE_PASSWORD`. Embedded Paseo/Paperclip launch commands are separate and are not forced through this standalone-server password requirement.

**Secret handling:** do not print full container environments, rendered Compose/env files, proxy Authorization values, provider auth files, or secret-bearing logs into task comments. Do not put passwords in shell arguments/history. Store only redacted evidence and protected recovery material.

## Source and deployment contracts to apply

| Area | Relevant source / required behavior |
|---|---|
| VM image | `opencode/Dockerfile.service` and its Dockerfile-specific ignore file |
| Native installer helper | `opencode/scripts/entrypoint.sh`; installs scoped package `@opencode/cli@latest` and verifies it; no `OPENCODE_VERSION` build argument |
| Shared public publisher | `opencode/scripts/publish-plugins.mjs`; V2 config-only publication, no KDCO package/install mode |
| Runtime startup | `opencode/service-entrypoint.sh`; publish resources/config before exec, retain locks and non-root execution |
| Service templates | `opencode/docker-compose.j2`, `opencode/env.j2` |
| Backend readiness | `opencode/backend-health.mjs`; authenticated `/api/info`, V2 version validation |
| Public resources | Read-only `/opt/agent` and `/opt/opencode-defaults`; private user config/state remain in HOME |
| Config delivery | Parent ordinary service flow enumerates tracked public resources and removes retired **delivered public files**, not arbitrary private HOME content |

Shared publication call:

```text
node /opt/opencode/component/scripts/publish-plugins.mjs config \
  /opt/opencode-defaults /opt/agent "$OPENCODE_CONFIG_DIR"
```

Keep this exact installed publisher path consistent in OpenCode, Paseo daemon, and Paperclip daemon images. A mismatch was found and fixed during review.

### Parent build-input catalog updates

- OpenCode finite inputs: `Dockerfile.service`, `Dockerfile.service.dockerignore`, `service-entrypoint.sh`, `backend-health.mjs`, `scripts/entrypoint.sh`, and `scripts/publish-plugins.mjs`.
- Remove retired KDCO package files, entrypoints, dependency-install steps, and OpenCode version selectors from delivery/build catalogs.
- Paseo/Paperclip named OpenCode build contexts need the installer, publisher, and shared wrapper used by their Dockerfiles—not the deleted KDCO package. Follow the current Dockerfile COPY closure.
- Deliver `paseo-deamon/verify-paseo.mjs` for Paseo builds. Select a reviewed Paseo image with its native V2 adapter; the repository's compatibility floor is **0.12.0**. Do not assume the existing selected image supports V2.
- Keep maintained config/resources as read-only runtime mounts; do not bake private HOME/provider credentials or copy the whole checkout into an image.
- Parent catalog/ingress integration lives outside this repo. `VM-SERVICES.md` describes its expected ordinary service flow; locate the actual owners rather than inventing a parallel deployment framework.

### CLI/API changes to avoid carrying forward

```text
Install:   @opencode/cli@latest, not opencode-ai@latest
Server:    opencode serve --hostname 0.0.0.0 --port <configured-port>
Client:    opencode --server <server-url>
Health:    GET /api/info, authenticated as opencode
Remove:    --mdns false, old web startup, /global/health, old package paths
Dangerous: client --auto, not a V1 server-wide permission flag
```

Preserve configured CORS arguments, resource limits, NSS UID/GID, HOME/workspace paths, non-root execution, and explicit socket grants. Do not add privileges/socket access to make startup pass.

## Execution sequence

| Phase | Work | Exit condition |
|---|---|---|
| 1. Verify source | Verify commit/remote state and this handoff; publish the finalized merge only if still missing, without unrelated local work | Deployment source contains `4d8764a` or a reviewed descendant |
| 2. Prepare | Locate host Compose/proxy owners; update parent inputs, protected backend secret, and upstream auth; render/validate templates | No stale KDCO/version/mDNS/health references; no secrets in public outputs |
| 3. Recovery | Record current image **ID/digest**, resolved Compose inputs, mounts and ownership; preserve the old image; back up application-consistent state before V2 touches it | Documented old-image/config/state restore route |
| 4. Build | From an independent host session, build the service image with deliberately refreshed npm installation | Build succeeds; record resolved OpenCode version and resulting image ID/digest |
| 5. Cut over | Drain active tasks/tools, coordinate shared-HOME writers, recreate only the intended service and reload the coordinated proxy config | Container remains running/healthy; no private state was reset |
| 6. Accept | Run the bounded checks below through direct backend and real external entrypoint | All must-pass criteria recorded |
| 7. Close | Record deployed source/version/image, acceptance results, known limits and rollback custody | Task owner explicitly accepts deployment |

**`latest` and caching:** `latest` is the approved source selector, not evidence that a cached Docker layer fetched npm today. Use an uncached build when deliberately refreshing it, then record the exact resolved version. 2.1.1 is the latest disposable-build evidence from this work—not a required pin or a guarantee of current npm resolution.

Avoid broad `compose down`, volume deletion, recursive chown, database resets, and restarts of unrelated services. Public config changes can also affect other consumers sharing the maintained source; coordinate their convergence separately. Do not treat this as an approval to upgrade every running daemon at once.

## 🧪 Bounded acceptance checklist

### Must pass for the OpenCode cutover

- [ ] Deployed source includes the finalized merge; image reports native OpenCode **major version 2**; resolved package/version and image identity are recorded.
- [ ] Container runs as the configured non-root account, with intended limits, mounts, network and socket grant; server is the foreground lifecycle process.
- [ ] Direct `/api/info` succeeds with the protected native credential and reports V2. Missing/incorrect credentials fail; health uses the configured port.
- [ ] External unauthenticated access is rejected. Authorized browser/client access succeeds through the real gateway, including streaming. Native backend auth does not replace gateway protection.
- [ ] TUI connects with `--server`; disconnect/reconnect preserves the session and does not create/replace a separate managed server or stop the backend.
- [ ] Effective agents, models, providers and prompt references resolve. Remote's updated roster/default model is preserved; GSD is absent. Confirm the configured provider/model is actually available; do not silently substitute another model to hide a failure.
- [ ] The native `title` agent retains `openai/gpt-5-mini`; no custom `first-prompt-title` generator is loaded. The background-default plugin is active and CLI footer registration loads. No obsolete KDCO loader runs.
- [ ] A fresh real user prompt obtains a sensible title; title display renders in the supported **prompt footer**. A later prompt does not overwrite a deliberate custom title.
- [ ] A native subagent call omitting `background` returns control while the child runs. Its result reaches the caller. With two different-duration children, the first completion is usable without waiting for the unrelated slower child. Explicit `background: false` still behaves as foreground execution.
- [ ] Background defaults do not bypass agent permissions/depth limits. No polling/sleep loop is needed to consume completion notifications.
- [ ] Existing credentials/private settings remain intact and representative session access is checked. Any V1 persisted-state incompatibility is reported explicitly; it is not fixed by deleting state.
- [ ] Logs show no startup/restart loop, missing public-resource links, plugin failures, or credential disclosure.

### Additional acceptance only if those consumers are updated

- Paseo: selected image passes the V2 verifier, daemon starts through the real wrapper, native auth works, and a real provider session completes. Static COPY/adapter checks alone are insufficient.
- Paperclip daemon: SSH identity/custody and existing grants remain unchanged; test its actual OpenCode V2 adapter/session flow. This was **not** established by the source migration.
- GPU: perform an actual GPU build/run if selected. CPU evidence does not establish GPU compatibility.

## Recovery / stop conditions

Stop the rollout for failed auth/streaming, missing config/plugins, permission escalation, unexpected HOME mutation, unavailable required models, incompatible persisted state, or repeated crashes. Do not bypass security or erase state to make acceptance green.

Recovery is the old **image plus matched deployment/proxy configuration and compatible state**, not another build of `latest`:

1. Stop the failed V2 writer and retain protected diagnostic evidence.
2. Restore the prior image and matched ingress/env configuration.
3. If V2 changed persistent data incompatibly, restore the application-consistent pre-cutover snapshot while all relevant writers are stopped. V1 compatibility after V2 writes has not been established.
4. Verify old-version access and session/credential integrity before resuming work. Record any acknowledged post-snapshot data loss.

## Evidence already available / verification limits

- The merge preserves both parents, remote retirements and agent defaults; unrelated N3TX files were hash-checked and preserved. No unresolved merge entries remain.
- Disposable OpenCode service image built with **2.1.1**; authenticated health, complete tracked public-source publication, then-current server title/background plugin activation, and CLI footer loading were checked. That title-generator evidence predates its retirement and does not establish native title generation; recheck native titles and the retained footer during acceptance.
- Backend, startup/config, title/background, workstation, provider-verifier and service-template/wrapper checks ran during implementation. Review caught and fixed a daemon publisher COPY-path mismatch and stale agent-roster assertions.
- Final merge checks were deliberately lightweight at the user's request: conflict/whitespace, JSON/config intent, shell syntax, and ancestry/local-work preservation. **A fresh exhaustive post-merge suite was not run.**
- Real deployed providers, browser ingress, production V1 database compatibility, GPU, and live Paseo/Paperclip adapter flows are not established. Standalone Compose validation was used where this environment's Docker wrapper could not execute Compose correctly.
- Optional `opencode/dispatch` and `opencode/ssh-remote` integrations remain V1-targeted and default-off. Do not enable them as part of V2 acceptance.
- No production cutover or acceptance is claimed by this document.

## Deliverables for the task report

Provide deployed commit/branch, resolved CLI version, image ID/digest, deployment timestamp/operator, services actually changed, redacted acceptance results, unresolved limitations, and protected backup/rollback references. Identify the owner of the parent secret/proxy changes. Do not attach raw secrets, rendered environment files, auth databases, or unredacted inspect output.

**Primary references:** `opencode/README.md`, `VM-SERVICES.md`, current service Dockerfiles/templates, `paseo-deamon/README.md`, and `paperclip-daemon/README.md`.
