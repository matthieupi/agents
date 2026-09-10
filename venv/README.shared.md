# Protected shared-runtime VM integration

✅ Plan-12 infrastructure/VM implementation; **offline verified, not deployed**.
No environment is opted in by this change. Workstation wrappers, existing image
recipes, `venv/Makefile`, `build.py`, native scripts and defaults are untouched.
The original resource-rollout hold remains binding.

## Ownership and explicit commands

`shared.py` is a protected VM adapter, not another image builder. Enrollment
promotes controller-reviewed copies of it, `runtime/runtime.py`, and
`runtime/harnesses.json` into the configured protected library. The deployed
launcher checks their hash bindings before importing them. It never imports a
guest checkout as root.

Build/update still belong to the component's explicit `runtime/` installer and
never activate an image automatically. The VM activation endpoint is the existing
finite sudo form (substitute the configured `paths.command`, never a guest script):

```text
sudo -n <paths.command> activate <pi|omp|opencode|t3> sha256:<64 lowercase hex>
```

The component installer now delegates explicitly selected VM activation to that
protected endpoint. Its VM selector requires the protected build configuration
and exact target; there is no automatic machine detection or legacy redirect:

```text
make -C runtime activate HARNESS=<harness> IMAGE=sha256:<image-id> \
  SCOPE=vm VM_CONFIG=<paths.build_settings> TARGET=<environment>:<host>
```

This hookup was implemented in the runtime workstream and verified here by
read-only source inspection. No runtime files were edited for these VM fixes.

After explicit activation, ordinary enrolled launcher calls use the shared
contract for the selected reviewed image. Other installed legacy images keep
their legacy command and socket behavior. A control upgrade alone cannot select,
reinterpret or redefine an installed image receipt.

Explicit CLI-only source/capability requests use:

```text
<paths.command> shared-run opencode -- <app arguments>
<paths.command> shared-run pi --live-source -- <app arguments>
<paths.command> shared-run omp --docker-socket -- <app arguments>
```

`--docker-socket`, repeatable `--cap-add`, `--root-user` and `--checkout-write`
must each be permitted by the protected target allowance. Allowances alone grant
nothing. Only `NET_BIND_SERVICE` is currently supported. There is no catch-all
privileged option or Claude VM enrollment. Root-user requests use baked startup,
read-only workspace and disposable HOME; root plus live checkout execution is
refused. Managed web always uses baked startup and the zero-grant default profile.

The ordinary host Docker client remains host-root-equivalent on a rootful daemon.
Socket-off **inside** the container is not a sandbox against other Docker admins
and is not an approved unprivileged Paseo daemon path.

## Canonical optional policy

Configuration lives only under
`ansible_vars.venv_agents.shared_runtime.targets.<literal-host>` in `config.yml`:

```yaml
# Shape only; no runnable target or real image authorization is supplied here.
enabled: true
policy:
  version: 1                         # strictly increasing control version
  target: <environment>:<host>
  enrollment_marker: <paths.marker>
  controls:
    adapter: {path: <paths.library>/shared.py, sha256: <reviewed-file-sha256>}
    runtime: {path: <paths.library>/runtime.py, sha256: <reviewed-file-sha256>}
    catalog: {path: <paths.library>/harnesses.json, sha256: <reviewed-file-sha256>}
  checkout:
    path: <ordinary-owned-editable-checkout>
    owner: <enrolled-account>
    origin: <credential-free-repository-url>
    revision: <reviewed-full-git-commit>
    public_paths: [runtime/entry.py, runtime/harnesses.json]
  grants: {docker_socket: false, root_user: false, checkout_write: false, cap_add: []}
  images:
    opencode:
      sha256:<local-image-id>:
        harness: opencode
        platform: linux/amd64
        contract: 1
        resolution_sha256: <image-label-io.agents-runtime.resolution>
        source_sha256: <build-receipt-resolution-source-public_sha256>
        source_revision: <build-receipt-resolution-source-revision>
  transitions:
    - harness: opencode
      from: sha256:<previous-exact-id> # null only for reviewed first installation
      to: sha256:<candidate-exact-id>
      state: backward-compatible
      evidence: <reviewed-state-compatibility-document-reference>
  staging_ports: {opencode: <distinct-configured-loopback-port>}
  staging_limits: {memory_mb: 512, cpus: 1, pids: 64}
```

The image map is a **reviewed receipt projection**, not a guest-supplied activation
receipt or a tag. Node/manifest/platform/lock provenance remains in the component
build receipt; `resolution_sha256` binds that resolution to the immutable local
image. The root activation endpoint independently checks local ID, platform,
harness/contract/resolution labels and a bounded mountless version probe. OMP
remains amd64-only with SSE4.2 required on every CPU.

No default compatibility entry is manufactured. The only supported real-state
transition policy is an explicit reviewed `backward-compatible` assertion for an
exact `(harness, from-ID, to-ID)` pair, with a document reference. Unknown,
irreversible and backup-only migrations are refused. This is operator-reviewed
evidence, not an automated proof that application migrations are reversible.
Image rollback never reverses HOME/session/database/provider writes.

**Native and legacy-layout admission restrictions:** a new transition from a
`native-pi` default is refused before image execution. Pi homes retaining the
`native_pi_home` binding are also refused. An image compatibility assertion does
not prove native writer quiescence; a complete native cutover transaction is not
supported by this opt-in path. Legacy enrollment itself is unchanged.

For an image not already on the shared startup contract, every affected account's
managed harness root must be absent or empty, physically owned and unredirected.
Populated legacy Pi, OMP, OpenCode and T3 roots are refused, not rewritten. The old
initializer stores absolute resource links; Pi also uses a whole-root `agents`
symlink. Those layouts cannot be assumed compatible with `/opt/agent` and the new
physical agents directory. This check runs before journaling/cutover and again
after old writers are quiesced, including CLI-only OMP. An explicit HOME-layout
migration remains unsupported; do not delete state or links merely to pass the gate.

First complete ordinary enrollment, then promote opt-in on a completed host using
the existing `make agents-check` / `make agents` flow with explicit environment,
literal host and normal transport inputs. Fresh bootstrap with opt-in already
enabled is refused before initial mutations; it cannot invent original seals.
No deployment command was executed in this workstream.

## Checkout custody and source behavior

Enrollment checks physical path, UID/GID, origin, Git dirtiness/untracked files,
known hidden runtime directories and declared native-service references. Existing
checkouts are never pulled, reset, cleaned, recursively chowned or replaced.
For an absent checkout, the maintained enrollment module records creation intent
in private `shared-checkout.json`, creates a token-named sibling staging directory,
and records its device/inode and ordinary ownership. Ansible Git clones there as
that owner; ordinary-user Git probes verify physical root, exact revision, origin
and clean status. Only then is the stage published at the final path using Linux
`renameat2(RENAME_NOREPLACE)`. Even an empty existing destination is never replaced.

A failed clone does not leave a directory at the final path. On explicit retry,
the exact failed stage and its work remain untouched in recorded history; a fresh
stage is used. A crash between mkdir and inode publication retains the unverified
remnant without adopting it. A crash after publication rename is completed only
when the destination has the journaled inode and custody. Unknown inode/path/
intent changes refuse recovery. Completed reapply does not reclone or pull.

The configured destination parent must already be root-controlled. Existing
checkouts—including empty directories left by older, unjournaled attempts—are
not adopted as creation attempts. They remain subject to normal custody/origin
inspection and explicit manual resolution if not a repository. Retained failed
stages consume disk until separately reviewed cleanup; this flow never resets,
cleans or deletes their contents.

The checkout cannot overlap the workspace mount or protected controls. The
default runtime uses the baked startup and mounts no checkout. Explicit live CLI
mode exposes only the two reviewed public files at identical host/container
paths—not their parent checkout, `.git`, private runtime state or provider homes.
`--checkout-write` permits writes only to those file binds. Launch records retain
source revision, public-content digest and effective grants, not app argv/secrets.
Host edits affect subsequent interpretation, not already-loaded processes or image
dependencies. Rollback retains the previous image's own startup bundle.

## Control promotion and recovery

```text
reapply validates original enrollment
  -> activation lock + exclusive maintenance admission
  -> reject pending activation/resource/workspace transitions
  -> verify old seals, target, entrypoint locations and metadata
  -> journal exact before/after bytes, UID/GID/modes
  -> gated reviewed entrypoints; drain already-loaded old launchers
  -> publish reviewed controls and optional policy
  -> validate candidate launcher and current gateway ownership
  -> publish versioned overlay seal  [CONTROL COMMIT POINT]
  -> verify and archive exact transition
```

Original `files`, `bootstrap_policy` and publication provenance are retained.
`shared_runtime_seal` is the active hash/metadata/policy overlay; history and private
archives retain earlier transitions. No hash rewrite blesses unknown source drift.

Completed-host install-mode reapply recovers a matching interrupted control
transition before validation; check mode reports it without changing files.
Before overlay-seal publication recovery restores exact prior records; afterward it
finishes the exact committed transition. Unknown bytes/modes/owners, failed
restoration or failed gateway ownership checks retain the admission journal.

Independent legacy HTTP-redirect rewriting is skipped after shared promotion;
resource mutation remains explicitly held rather than rewriting versioned controls
through the old resource reconciler. Unchanged workspace reapply still validates;
a pending shared transaction defers that pre-reapply step to exact recovery.

## Image replacement and recovery

```text
existing finite activation + caller/target/seal checks
  -> recover any exact recorded transaction before new admission
  -> reject unsupported native cutover and legacy HOME layouts
  -> exact reviewed state transition + immutable image checks
  -> maintenance admission, selected writer scan and staging headroom check
  -> private replacement journal closes launch admission
  -> disposable tmpfs HOME / no host binds / finite loopback staging health
  -> capture gateway bytes/metadata and selected oneshot unit state
  -> stop only selected container; retain exact ID under rollback name
  -> canonical candidate on real HOME; backend and authenticated gateway checks
  -> atomic selected policy publication  [IMAGE COMMIT POINT]
  -> finalize matching gateway journal; archive runtime journal
```

Staging uses its own configured bounded limits. The capacity check accounts for
the full memory limits of existing workloads in the shared cgroup; insufficient
headroom refuses staging rather than risking an OOM kill of retained services.
Active CLI or foreign containers mounting selected private state are refused, not
killed. Shared CLI and web creation use the same per-account writer lock; an
existing web container also prevents a second CLI writer. Managed candidate
lifecycle requires an inherited protected activation-lock descriptor.

The service contract must be the existing sealed `Type=oneshot`/
`RemainAfterExit=yes` unit. Its marker state is retained while Docker owns the
actual worker; no native retirement or unknown service-worker stop is performed
for replacement. New shared-native cutovers are blocked. The unchanged legacy
enrollment path retains its own first-install flow.

For recovery of an older shared first-install transaction interrupted after native
profile removal, admission checks the exact private replacement journal, both
policies, target, immutable delta/signature and transaction-derived identities.
Only the declared retired native profile may be temporarily missing, and only if
the sealed gateway configuration names that path and its private first-install
journal contains profile bytes matching the original enrollment seal. All other
controls remain mandatory. Recovery restores that recorded transition before
normal seal validation and new-admission checks. A missing profile without those
proofs, a forged snapshot, another missing control or a redirected path is refused.

On pre-publication failure, remove only the token-bound candidate, restore the old
container name and original running/stopped state, restore unit enablement and
route/marker bytes/metadata, and verify recovery. A stopped backend is checked as
authenticated unavailable, not started merely to satisfy health checks. After
matching policy publication, recovery finishes that commit; it never resurrects
the previous image over potentially newer state. Failed/unknown recovery retains
journals and blocks launch/reapply. Successful finalization permits the next update.

Previous exact containers/images and private transition archives remain until an
explicit later acceptance/cleanup decision. There is no global prune or automatic
HOME restoration. Recovery uses the same finite activation command; do not delete
markers/journals, reset the checkout or invoke mutable scripts with sudo.

## Verification boundary

New tests cover exact control publication/recovery, legacy absence, receipt and
privilege narrowing, first shared install, pristine-state legacy image conversion, OMP CLI-only
updates, repeat updates, stopped-state rollback, wrong target/caller, foreign writers,
staging capacity and process-death boundaries through journal finalization.
Security regressions exercise actual legacy initializer footprints, real seal
validation through native-profile recovery, and inode-bound checkout retry and
no-replace publication. Native cutover and populated legacy HOME conversion are
tested as explicit refusals, not described as completed migration capabilities.
Docker/systemd/gateway health boundaries are modeled offline; existing gateway
HTTP/API/WS contract tests remain separate. No real image, provider, browser,
deployment, rootless-daemon or plan13 acceptance is implied.
