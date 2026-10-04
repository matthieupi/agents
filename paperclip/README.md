# Paperclip — private Hub service and remote SSH execution

✅ **Admin access and native ownership completed September 29, 2026.**
Open **https://intellagent.network** through a DevAI **admin** WireGuard profile.
The owner is **sysadmin@xmist.dev** (display name `sysadmin`), using the existing
shared service password referenced from the Dev Vault. No password is stored here.
Signup is disabled; operators retain Paseo access but are not allowed into Paperclip.
Native login/admin authorization, TLS, signup/claim/Origin denials and app-only
recreation passed. Physical operator/mobile acceptance remains a separate handoff.
See the parent record `.project/deployments/paperclip-completion-20260929.md`.
The pinned image requires **x86-64-v2** CPU features (native `sharp` dependency);
Hub's canonical CPU model now supplies them. Do not revert to `qemu64` while
expecting this image to run.

DevAI Hub selects `paperclip` beside `paseo-hub`. The base serves
**https://intellagent.network** directly using native authenticated/private mode.
Normal service deployment seeds no company, agent, provider credential or schedule;
explicit native API configuration/acceptance is a separate operation.
The heartbeat scheduler is disabled. There is no cloud mode or custom execution guard.
Do not restore an execution-populated company database onto Hub as a base install.

An authenticated instance administrator can deliberately configure local adapters
and initiate runs. The base policy is operational, not tamper-proof admin isolation:
**do not configure or enable local execution on Hub**. Select the explicit remote
environment rather than the instance's existing Local environment.

**October 2 — containerized remote execution deployed.** The user
accepted sensitive Hub credential/checkpoint custody and selected OpenCode/Pi with
OpenAI. They explicitly approved upstream **direct SSH adapters** instead of native
runner WSS. `opencode_local` and `pi_local` both support remote SSH despite their
names; their authenticated, per-run callback bridge uses the existing SSH command
transport. No WSS listener/grant, provider pack, upstream patch or custom worker
protocol is needed. The ordinary `paperclip-daemon` service runs native sshd.
Pi is not available in the pinned native runner; the managed
AI-connection table maps OpenAI subscription to Codex, not OpenCode/Pi.

`COO Paperclip SSH` in **Neuralys Lab** now targets the ordinary
[`paperclip-daemon`](../paperclip-daemon/README.md) container at COO port 2222.
It shares the canonical `agent` UID/GID, HOME/workspace and explicit socket grant
with Pi/OpenCode; native SSH sessions run as agent and container-local sudo is
approved. Shared HOME and Docker access are deliberately the same trust boundary,
not isolation. The superseded host executor account/tools/state were removed.
Native SSH, socket/sudo, workspace and authenticated callback probes passed.
`COO OpenCode` is paused after two zero-token subscription-model rejections;
**no provider-backed remote run has passed**. See the parent's
`.project/deployments/paperclip-daemon-20261002.md` and `.project/TODO-MANUAL.md`.
Credentials are used through the shared mount, never copied into an image.
Hub's encrypted SSH secret, app state and any future
credential/checkpoint data must be treated as sensitive and backed up accordingly.

## Ownership and flow

```text
environments/devai/config.yml -> generated inventory + canonical admission
  -> existing account/engine prerequisites (no provider/workspace/socket grants)
  -> agent/paperclip: local directories + missing-only service secrets
  -> native nginx ACL: apply restrictions BEFORE app configuration changes
  -> common/docker_service: finite files, .env, native build/up
       +-> private PostgreSQL -> persistent local cluster
       +-> Paperclip preload -> native production server -> persistent assets
   -> verify reserved internal backend address -> native nginx + existing TLS issuer/DNS
       LAN/WireGuard -> https://intellagent.network -> Paperclip UI
```

| File / owner | Responsibility |
|---|---|
| `Dockerfile`, `Dockerfile.dockerignore` | Thin pinned-image composition; build-time NSS UID/GID mapping required by OpenSSH; only configuration script enters the build context; no upstream source build or CLI installation |
| `configure.mjs` | Runtime preload reads mounted service secrets, constructs `DATABASE_URL`, writes disposable native config, then upstream Node loader/server starts normally |
| `docker-compose.j2` | Non-root app + private PostgreSQL, local bind mounts, healthchecks, resource bounds; no exposed host ports |
| `env.j2` | Public canonical settings only; no secret interpolation from controller environment |
| Parent `agent/paperclip` role | Hub custody/client identity, exact egress guard, native API environment configuration and probes; the separate `agent/paperclip-daemon` role prepares container SSH identity/authorization |
| Parent `agent/gateway` role | Native nginx, pre-recreation access restriction, certificate transfer and exact-owned private DNS |

Canonical runtime metadata is `ansible_vars.service_config.paperclip` in DevAI
config. Delivery source is `services/agents/paperclip` in both workspace-copy and
Git modes; generated output is `service_base_path/paperclip` (currently
`/srv/paperclip`). Conventional `Dockerfile` plus explicitly listed
`Dockerfile.dockerignore` and `configure.mjs` are the entire public build input.
Existing common-role source/custody/convergence behavior is reused, not forked.

## Container and network boundary

- App and DB run under nonzero UID/GID from the existing `agent` account's NSS
  facts, with read-only root filesystems, `cap_drop: ALL`, `no-new-privileges`,
  bounded PIDs/memory and limited tmpfs. The app does not run the upstream root
  remap/chown entrypoint. Same UID is not an isolation boundary.
- No Docker socket, host-root/HOME/workspace or workstation-key mount, privileged
  mode, host network or shared `proxy_net` is supplied. The dedicated execution key
  is persisted through Paperclip's native encrypted-secret API, not an env/build input.
- Docker allocates `paperclip_private` dynamically as an internal IPv4 bridge.
  Compose references that external network; neither app nor DB publishes a port.
  Docker service discovery resolves `postgres`; external DNS forwarding is pointed
  at the container's own loopback, where no DNS server runs. The optional app-only
  `paperclip_ssh` bridge permits exactly the configured COO daemon SSH port (2222);
  the prior host TCP/22 allowance was removed. PostgreSQL stays internal-only.
  A table-local native nftables transaction blocks other forwarded egress and
  bridge-origin host access. A oneshot firewall unit plus Docker Requires/ExecStartPre
  loads the guard before container restoration; this is not an execution daemon.
  No Hub provider/SMTP internet access is granted.
- Paperclip reserves the last usable IPv4 address of its existing Docker-allocated
  internal bridge subnet. Compose and host nginx use that same derived address;
  container start order no longer changes nginx's upstream. Foreign attachments,
  occupied reservations and ambiguous allocation fail closed. The external bridge
  persists across app recreation and host restart; no subnet is hardcoded.
- Host nginx connects to the reserved app address on configured port 3100. The
  canonical host policy adds only this bridge-output TCP port. No worker-to-Hub
  permission, public A/AAAA record, public reverse proxy or resource resize is added.
  Docker's normal outbound NAT presents Hub's address to COO; the SSH authorized key
  is restricted to that source with forwarding/PTY disabled. Paseo is unchanged.
- Internal bridges are not complete host isolation. Existing Hub host policy,
  actual bridge/Docker packet behavior, LAN/WireGuard paths and denial paths need
  scoped live verification. Root/Docker operators can bypass host controls.

The app healthcheck calls `/api/health` with the canonical Host and requires
`status=ok`, `deploymentMode=authenticated`, and `deploymentExposure=private`.
Upstream probes PostgreSQL in this endpoint. `bootstrap_pending` is healthy before
first-admin setup; frontend access can intentionally remain 403. This does not
prove browser login, native claim, TLS or remote-agent functionality.

## Persistent custody

```text
/var/lib/paperclip/                   root:root 0700, configured local root
  app/                               NSS UID:GID 0700 -> /paperclip
    assets/                          uploaded application data
    logs/                            potentially sensitive app logs
  postgres/                          NSS UID:GID 0700 -> PostgreSQL PGDATA
  credentials/                       root:root 0700
    better-auth-secret               NSS UID:GID 0400
    tool-action-signing-secret        NSS UID:GID 0400
    postgres-password                NSS UID:GID 0400
    master-key                       NSS UID:GID 0400
```

All four secrets are independently generated with target-local
`openssl rand -hex 32`, only when missing, and persisted through native atomic
Ansible copy with `force: false`. Generation/copy is `no_log`, diffs suppressed,
and transient generation results cleared. Nothing is generated on the controller
or stored in Git or `.env`. Normal Ansible transfer has transient access to the
generated value; controller and target administration remain trusted.

The app mounts all four files read-only at `/run/secrets`; PostgreSQL receives
**only** its password file. The preload builds a URL-encoded database identity
using that same password and loads auth/signing values into the app process, not
Docker's configured environment. The encryption key is verified before startup
and supplied to the native encrypted-secret provider as a read-only file.
Runtime JSON contains no secrets and lives on a private `/run/paperclip` tmpfs.

Preparation rejects redirected ancestors, non-directory state, wrong existing
ownership/modes, nonregular/linked credential files and unapproved filesystems.
Only configured local ext4/XFS/Btrfs storage is accepted—not NFS/CIFS or a silent
fallback. Bind mounts use `create_host_path: false`. No recursive ownership repair
or destructive migration occurs. If app/DB data exists and any service credential
is missing, deployment fails rather than inventing replacement identities.

An interrupted first initialization can leave partial data; preserve it and restore
the matching credential set before retrying. Do not delete the DB or rotate a
guessed password. The official PostgreSQL initialization user owns this dedicated
cluster; it is not a separately constrained application DB role. PostgreSQL does
not rotate an existing DB password merely because its password file changes.

**Backup/restore is an operational follow-up:** automated DB backups are disabled
in the base. Take a consistent PostgreSQL backup plus assets and all four secrets,
encrypt off-host copies and validate restore. An ordinary copy of live PGDATA is
not a valid backup. Loss of `master-key` can make encrypted DB values unrecoverable.
Review free space on the unchanged 4-core / 6-GiB / 32-GiB Hub before rollout.

## Ingress and first-admin setup

Canonical settings are:

```yaml
auth_disable_sign_up: true
ingress_access_class: admin
ingress_allowed_cidrs: []       # no manually maintained peer allowlist
```

The native nginx ACL derives exact admin `/32`s from canonical DevAI policy.
`remote_access.preserve_https_sources_to: hub` preserves enrolled peer sources only
for Hub TCP/443. Gateway peer AllowedIPs and forwarding authorization remain the
identity boundary; all other traffic retains existing SNAT. Hub's compiler adds
only peer TCP/443 ingress, and networkd owns exact peer return routes via the
same-LAN gateway. Operators still reach Paseo on the shared HTTPS listener; the
Paperclip vhost denies them. Client-supplied forwarding headers grant no access.

Each service reconciliation reloads deny-all before app changes and opens the
derived admin ACL only after native owner readiness. Bootstrap keeps deny-all
through signup, claim, signup closure and verification. Do not allow the shared
gateway `/32` or use the explicitly unimplemented proxy-role-SNAT feature.
This assumes trusted gateway/Hub administration and does not provide isolation
against privileged same-L2 source spoofing; Proxmox anti-spoofing remains deferred.

TLS reuses Dev `docker-mgt`'s existing ACME owner and issuer directory. Its normal
apex-plus-wildcard certificate convention is retained; validation explicitly
requires `intellagent.network` SAN, matching key, validity and trusted chain.
A wildcard by itself does not cover the apex. Existing ACME DNS-01 challenge TXT
handling remains issuer-owned; this does not publish a public service address.

The exact `paperclip_apex` DNS section is reconciled on Dev and DevAI through the
existing ownership primitive, with foreign exact UCI domain/host conflicts refused.
Generic router service-name synthesis excludes Paperclip. Wildcard DNS, human-Hub
records and Paseo's existing exact records are not changed.

### Controlled native bootstrap and maintenance

The existing `deploy-services.yml --tags paperclip` entrypoint accepts explicit
`paperclip_bootstrap=true` **only for an unclaimed instance**. It uses native
`/api/auth/sign-up/email`, `/api/auth/get-session` and `/api/bootstrap/claim`.
Creation and claiming are separate; the first authenticated claim wins under a
native DB lock. An existing account conflict or existing owner stops the operation;
there is no reset, forced invite or raw database write.

Public config supplies `admin_email`, `admin_name`, `admin_password_vault` and
`admin_password_ref`. The approved reference is Dev's `vault_beszel_user_password`;
the value is loaded under a private namespace and is not duplicated into another
Vault, `.env`, command argument or log. Later shared-password rotations do not
automatically rotate this application account.

The temporary signup setting changes only the generated app environment behind
deny-all. An Ansible `always` block closes it and recreates only Paperclip on success
or failure. If the controller is killed/unreachable, deny-all remains in place;
rerun normal reconciliation to restore canonical signup closure before recovery.
Do not rerun bootstrap after a successful claim. Verification-only mode uses
`paperclip_verify_auth=true`; additionally set `paperclip_verify_external=true`
to verify canonical HTTPS from an already authorized controller admin path.
Passwords/cookies/responses use `no_log`; available operation sessions are signed out.

Use the existing **guarded host-firewall** workflow for host policy (ordinary site
does not activate it). Prepare Hub routes/firewall before the gateway NAT exception.
Use the existing native gateway playbook for enrolled policy, then the scoped
`make ansible ENV=devai HOST=hub` for normal convergence. Exact reviewed commands
and verification recaps are in the completion record. The bootstrap/owner-verification
tasks create no company, agent, provider credential or heartbeat schedule. Optional
SSH preparation and explicit environment configuration are separate operations above.

## Pinned source and verification

Reviewed Paperclip source: `6bc830b62bc96064aabe5c841cbdf97424bed73f`.
The full-SHA GHCR tag resolves to index digest
`sha256:5523c34a8b7086b3d935691512cd5b272e01ff985a36d4c274c5e7bcaad14947`;
AMD64 manifest `sha256:a7536141b69d7ce6352dccc9d676e8da260f7d63b5b61c20b3e19296b4e40c50`
reports the matching source revision and production command. The image includes
OpenCode/Claude/Codex tools; none are invoked or configured as agents by this base.

PostgreSQL `17-bookworm` resolves to index
`sha256:639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652`;
AMD64 metadata reports 17.11 and docker-library source
`2603e26e245e558218728ee14e0a42dcb020dc7f`, whose Dockerfile includes NSS-wrapper
support for arbitrary runtime UIDs. Artifact metadata is not attestation or layer
verification. The initial source review did not run the images; subsequent live
deployment and acceptance are recorded in the completion record above.

Pinned upstream references:
[Docker docs](https://github.com/paperclipai/paperclip/blob/6bc830b62bc96064aabe5c841cbdf97424bed73f/doc/DOCKER.md),
[Dockerfile](https://github.com/paperclipai/paperclip/blob/6bc830b62bc96064aabe5c841cbdf97424bed73f/Dockerfile),
[entrypoint](https://github.com/paperclipai/paperclip/blob/6bc830b62bc96064aabe5c841cbdf97424bed73f/scripts/docker-entrypoint.sh),
[config](https://github.com/paperclipai/paperclip/blob/6bc830b62bc96064aabe5c841cbdf97424bed73f/server/src/config.ts),
[schema](https://github.com/paperclipai/paperclip/blob/6bc830b62bc96064aabe5c841cbdf97424bed73f/packages/shared/src/config-schema.ts),
[health](https://github.com/paperclipai/paperclip/blob/6bc830b62bc96064aabe5c841cbdf97424bed73f/server/src/routes/health.ts),
[encryption key format](https://github.com/paperclipai/paperclip/blob/6bc830b62bc96064aabe5c841cbdf97424bed73f/server/src/secrets/local-encrypted-provider.ts).
Source uses external/embedded PostgreSQL, despite the Docker document's inconsistent
embedded-SQLite heading.

Historical source-only checks are recorded under the parent's
`.project/implementation/paperclip-base-2026-09-25.md`. September 29 completion adds
focused offline tests, scoped gateway/Hub convergence, native first-admin/login and
app-recreation evidence. Whole-host reboot, restore drills, mobile/operator device
acceptance and adversarial isolation remain unverified.
