# Paperclip — private Hub base service

✅ **Base deployed on DevAI Hub September 26, 2026; first-admin setup pending.**
Paperclip/PostgreSQL health and non-root/no-socket runtime controls were verified.
The apex currently returns the intended **403 deny-all** with valid TLS; browser
access is not enabled yet. See the parent deployment record
`.project/deployments/paperclip-hub-20260926.md` for scope and remaining checks.
The pinned image requires **x86-64-v2** CPU features (native `sharp` dependency);
Hub's canonical CPU model now supplies them. Do not revert to `qemu64` while
expecting this image to run.

DevAI Hub selects `paperclip` beside `paseo-hub`. The base serves
**https://intellagent.network** directly using native authenticated/private mode.
No company, agent, provider credentials, execution workspace or schedules are seeded.
The heartbeat scheduler is disabled. There is no cloud mode or custom execution guard.
Do not restore an execution-populated company database onto Hub as a base install.

An authenticated instance administrator can deliberately configure local adapters
and initiate runs. The base policy is operational, not tamper-proof admin isolation:
**do not configure or enable agents on Hub**. Agent integration remains deferred
pending reviewed remote-only setup and a separate worker return-route decision.

## Ownership and flow

```text
environments/devai/config.yml -> generated inventory + canonical admission
  -> existing account/engine prerequisites (no provider/workspace/socket grants)
  -> services/paperclip: local directories + missing-only service secrets
  -> native nginx ACL: apply restrictions BEFORE app configuration changes
  -> common/docker_service: finite files, .env, native build/up
       +-> private PostgreSQL -> persistent local cluster
       +-> Paperclip preload -> native production server -> persistent assets
  -> observe healthy backend address -> native nginx + existing TLS issuer/DNS
       LAN/WireGuard -> https://intellagent.network -> Paperclip UI
```

| File / owner | Responsibility |
|---|---|
| `Dockerfile`, `Dockerfile.dockerignore` | Thin pinned-image composition; only configuration script enters the build context; no upstream source build or CLI installation |
| `configure.mjs` | Runtime preload reads mounted service secrets, constructs `DATABASE_URL`, writes disposable native config, then upstream Node loader/server starts normally |
| `docker-compose.j2` | Non-root app + private PostgreSQL, local bind mounts, healthchecks, resource bounds; no exposed host ports |
| `env.j2` | Public canonical settings only; no secret interpolation from controller environment |
| Parent `services/paperclip` role | Local filesystem/type/ownership checks, missing-only target secret generation, private network and healthy endpoint observation |
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
- No Docker socket, host-root mount, host HOME, workspace, SSH keys, provider
  secrets, privileged mode, host network or shared `proxy_net` is supplied.
- Docker allocates `paperclip_private` dynamically as an internal IPv4 bridge.
  Compose references that external network; neither app nor DB publishes a port.
  Docker service discovery resolves `postgres`; external DNS forwarding is pointed
  at the container's own loopback, where no DNS server runs. External providers,
  SMTP, integrations and remote agents are not enabled by this base.
- Host nginx connects to the observed app address on configured port 3100. The
  canonical host policy adds only this bridge-output TCP port. No worker-to-Hub
  permission, public A/AAAA record, public reverse proxy, NAT or resource resize is
  added. Existing `paseo.intellagent.network` behavior is unchanged.
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

Initial canonical settings are:

```yaml
auth_disable_sign_up: true
ingress_allowed_cidrs: []       # native nginx deny-all, NOT allow-all
```

Admission accepts unique explicit RFC1918 IPv4 CIDRs. Enabling signup requires
**exactly one private `/32`**. The native nginx access include is reloaded
synchronously **before** Compose can change signup settings. A failed validation
or reload prevents app recreation. On first install, the include exists before
the frontend is published. No secondary login proxy is added; Paperclip owns auth.

TLS reuses Dev `docker-mgt`'s existing ACME owner and issuer directory. Its normal
apex-plus-wildcard certificate convention is retained; validation explicitly
requires `intellagent.network` SAN, matching key, validity and trusted chain.
A wildcard by itself does not cover the apex. Existing ACME DNS-01 challenge TXT
handling remains issuer-owned; this does not publish a public service address.

The exact `paperclip_apex` DNS section is reconciled on Dev and DevAI through the
existing ownership primitive, with foreign exact UCI domain/host conflicts refused.
Generic router service-name synthesis excludes Paperclip. Wildcard DNS, human-Hub
records and Paseo's existing exact records are not changed.

### Controlled bootstrap (only after separately authorized host rollout)

1. Keep deny-all and signup disabled for first deployment. Review the current
   source/diff, inventory regeneration, disk headroom, issuer/exact-record custody,
   host-policy dependency and backup plan. Use the established **Hub-scoped** site
   workflow first so the new host-output port rule precedes service startup. Never
   treat service-only deployment as host firewall reconciliation.
2. Confirm native Compose health, app private/authenticated posture, exact TLS SAN,
   and deny-all/no-public/no-worker paths. No bootstrap company/agent is needed.
3. Determine the chosen operator's **actual source address seen by Hub nginx**.
   Select that one private `/32` and set `auth_disable_sign_up: false` in canonical
   config. If multiple clients share that source through NAT, do not open the
   window until access is restricted to the intended operator. Do not whitelist a
   whole subnet for an unclaimed instance.
4. Regenerate inventory through the normal reviewed flow and reconcile only Hub.
   Visit **https://intellagent.network**, create the intended account, and choose
   **Claim this instance**. Native private bootstrap is first-authenticated-user-wins.
   Stop before company/agent onboarding; do not import a company or supply model keys.
5. Verify the intended instance owner. Restore `auth_disable_sign_up: true` and
   reconcile Hub before considering any broader **private-only** ingress list.
   Verify signup and a second-client claim fail. Record the exact scoped commands,
   source identity and results without passwords, cookies or signup tokens.
6. If interrupted, restore deny-all and signup-disabled canonical settings and
   reconcile Hub. Inspect ownership via the restricted operator path; never reset
   an unknown account or delete data to make setup convenient.

The existing `make ansible ENV=devai HOST=hub` is the scoped site entrypoint after
reviewed inventory/host dependencies. No Make target is added. These are future
operator instructions, not commands executed by this implementation pass.

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
verification. Neither image has been pulled, built or run in this pass.

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

Focused syntax/render checks are recorded under the parent's
`.project/implementation/paperclip-base-2026-09-25.md`. No tests were added or run,
no Make commands or live operations executed, no credentials generated, and no
further delegation performed during completion. Native Compose/image, first-admin,
packet-path, reboot and restore acceptance remain unverified, not artificial gates.
