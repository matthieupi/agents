# Manual handoff

## Global progress tracking

- `/progress.txt` was absent; the unprivileged source workstream could not create
  it (`PermissionDenied`). A controller administrator should create it if this
  project still requires a global log, then append the dated entry from
  `services/agents/.project/progress.txt`. Do not grant guest agents root access
  or change live VM permissions to resolve a controller logging issue.

## Source publication / target integration (not authorized in this workstream)

1. Review the Pi-only Bash source diff and Pi README. The prior shared native
   framework/manifest and new OMP component were removed; OpenCode was restored
   exactly to b15a790 and is not ported in this pass. Obtain explicit
   Git authorization before committing/pushing the agents branch or updating
   the parent indexed gitlink; no publication was performed here.
2. After publication passes the infrastructure source gate, inventory existing
   Pi auth/sessions/resources and preserve `/srv/pi/repo`, `/srv/pi/runtime`,
   unit/service environment and passwd home for protected-SHA rollback.
3. Run the selected non-root install and initialization on the concerned host
   only, then validate package loading, CLI, loopback auth and proxy transport.
   Drain/restart only the concerned unit, using administrator-owned systemctl.
4. Before provisioning a writer, verify server-enforced branch/tag/privileged-CI
   restrictions. A local assigned branch alone is not authorization.
