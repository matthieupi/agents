# Paperclip daemon — ordinary SSH execution container

`paperclip-daemon` is a normal selected VM Compose service, not a custom worker
protocol. Paperclip Hub uses upstream `opencode_local` / `pi_local` SSH adapters
and their authenticated per-run callback bridge. No worker-to-Hub inbound route
or persistent runnerd coordinator is required.

## Ownership and layout

| Surface | Owner / contract |
|---|---|
| Selection | `hosts.<host>.services: [..., paperclip-daemon]` |
| Deployment | Ordinary `deploy-services.yml --tags paperclip-daemon`; `/srv/paperclip-daemon` generated Compose/env/sshd config |
| Identity | Same canonical `agent` NSS UID/GID as Pi/OpenCode; root sshd bootstrap, only agent SSH sessions |
| HOME/workspace | Same `agent_home` and `agent_workspace` bind mounts at identical paths; no provider credential copies |
| Tools | Same pinned Node base and OpenCode installer/public KDCO inputs as OpenCode; separately pinned Pi CLI; existing shared plugin links resolve |
| SSH host identity | Dedicated `service_config['paperclip-daemon'].state_path/ssh`, root-only, read-only container mount; never the host sshd key |
| Authorization | Root-owned `/srv/paperclip-daemon/authorized_keys` mounted outside HOME; shared agent authorized_keys is untouched |
| Socket | Only `docker_access` emits bind mount, Compose group_add, and image NSS supplementary group; SSH initgroups therefore retains the grant |

No startup installer, recursive HOME chown, docker-exec dispatcher, generated
provider config or custom worker daemon is introduced. The foreground service is
native sshd. Model processes are separate from the existing OpenCode web service.
Paperclip stages per-run assets beneath `.paperclip-runtime`; it may inject skills
and write provider sessions in shared HOME. This is intentionally the **same trust
boundary**, not isolation between Pi, OpenCode and Paperclip tasks. Do not edit
shared configuration concurrently or assume agent tasks cannot affect siblings.

## Security boundary

- Exact configured LAN SSH port, no wildcard host publication. The existing native
  pre-Docker backend guard permits only the canonical Hub source to this port and
  denies other new forwarded connections. Hub app egress permits this port only.
- SSH requires the dedicated Hub client key and strict container host pin; root
  login, passwords, forwarding and user rc hooks are disabled. Public authorization
  additionally carries `restrict,from="<Hub IP>"`.
- sshd starts as root for privilege separation; sessions run as `agent`.
  Container-local passwordless sudo is explicitly approved. The capability set
  supports sshd/sudo and intentionally omits `SYS_ADMIN`; there is no
  `privileged: true` or `no-new-privileges` (the latter would break sudo).
- **Docker socket access is host-root-equivalent.** Container-local sudo alone is
  not the main boundary once that explicit socket grant exists. No host sudo or
  host Docker-group enrollment is added by this service.
  Container root can also modify shared host-backed HOME files; removing the socket
  grant alone would not establish sandbox isolation.
- The dedicated host keys and Hub app/DB/master key/SSH client key are sensitive
  persistent custody. Preserve them across recreation and include them in backups.

## Current acceptance and operation

COO's container deployed October 2, 2026: agent `1002:1003`, socket group `988`,
Node 24.20.0, OpenCode 1.18.29, Pi 0.85.1. Strict SSH, socket/sudo and upstream
authenticated callback acceptance passed. Existing `COO Paperclip SSH` was updated
in place, and the superseded host `paperclip` account and executor directories were
removed. Hub's real UI/database were not removed or recreated for this migration.

Shared OpenAI OAuth is present, but the two bounded Paperclip smoke attempts with
`openai/gpt-5.4-mini` and `openai/gpt-5.4` were rejected as unsupported for the ChatGPT
account (reported zero tokens/cost). `COO OpenCode` is paused; schedules and demand
wakeups are disabled. No successful provider-backed run is claimed. Pi's shared
auth was absent at inspection; authenticate Pi natively if it is needed.

On COO, use the normal deployed Compose context:

```sh
sudo docker compose --project-directory /srv/paperclip-daemon exec --user agent paperclip-daemon bash
```

This enters the shared `agent` HOME/workspace. `opencode auth login --provider openai`
changes the shared OpenCode login; do not run it merely to guess around a model
compatibility error. Pi uses `pi`, then `/login`. Never print provider tokens.
Review the native paused agent's instructions/model before enabling a manual task;
its current instructions are deliberately limited to infrastructure acceptance.

Parent evidence and commands: `.project/deployments/paperclip-daemon-20261002.md`.
