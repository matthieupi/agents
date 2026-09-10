# KDCO plugins (enabled)

Vendored from <https://github.com/kdcokenny/ocx>, revision
`636dc2dbd10a780ef9f4b7a0bbf175aacd742e8c`, directory
`workers/kdco-registry/files/plugins`. `upstream.json` retains the original
SHA-256 values of all 20 TypeScript files and the repository MIT `LICENSE`.
It is provenance, not an installation receipt or a source downloader.

## Local patch

`background-agents.ts` differs from upstream only in artifact access hardening:
delegation/session IDs must be 1–128 ASCII letters/digits/underscore/hyphen,
starting with a letter or digit; reads enforce storage containment, reject
symlinked paths, open the leaf with `O_NOFOLLOW`, and require a regular file.
New delegation directories must also be physical. Only missing files become a
cache miss; access/security failures propagate. This blocks traversal into other
sessions and symlinked artifacts. It is not a sandbox against a process with the
same account actively replacing ancestor directories during filesystem calls.

## Discovery and dependencies

Only `../plugins/kdco-{background-agents,worktree,notify}.ts` are entrypoints.
These are static default re-exports, not a custom loader. Helpers and npm modules
stay outside both `plugin/` and `plugins/`, even for recursive discovery versions.
OpenCode 1.18.29 uses the non-recursive `{plugin,plugins}/*.{ts,js}` scan and supports
these legacy default factories. Its binary embeds Bun (needed by `bun:sqlite`).
The seven exact dependency pins and npm v3 lock retain upstream's reviewed
1.3.13 plugin/SDK development baseline; that is not the OpenCode application pin.
The nested package prevents OpenCode's config-root dependency maintenance from
changing this graph or overwriting private root package manifests.

Fresh builds run ordinary `npm ci --ignore-scripts --no-audit --no-fund` in this
package. Mutable workstation/native/VM install paths use the existing publication
helper under a shared package-local `flock`: unchanged manifest/lock and installed
tree fingerprints skip npm entirely, without network. Actual file bytes, paths
and symlink targets are checked; missing dependencies cannot be hidden by a stamp.
An absent/invalid stamp triggers one conservative install. This is not a signed
attestation against a same-account attacker who can rewrite both code and stamp.
Only successful installs with stable inputs publish a new stamp atomically.
Changed graphs still require idle sessions: an in-place npm failure can leave a
partial tree, not a preserved old runtime. Retry the normal install while idle.
Dependencies have no required lifecycle scripts. No plugin is imported by
installation. Actual OpenCode startup **does invoke factories and hooks**:
background-agents creates delegation storage, worktree opens SQLite, and notify
inspects terminal/config state. No OCX registry config, agents, permissions, or
native-task denial is copied. Native task remains available for write-capable agents.
Upstream `delegate` requires explicit edit/write/bash denial on the chosen agent;
existing private or inherited policy may make an agent ineligible. Installation
does not rewrite that policy to make the tool accept it.

⚠️ Worktree deletion schedules `git add -A`, an automatic snapshot commit, and
`git worktree remove --force` on idle, even if the commit fails. Worktree config can
run project-defined shell hooks and copy/symlink files. Native execution has the
account's filesystem access. Review `.opencode/worktree.jsonc` before using it.
Headless containers/VMs generally cannot open a desktop terminal or display host
notifications. No host desktop socket, terminal utility, permission or capability
is added. Notify may attempt local desktop/cmux commands when available.

The lock includes `node-notifier@10.0.1` and `uuid@8.3.2`; the latter is deprecated
and affected by GHSA-w5hq-g745-h8pq. Do not silently apply npm's breaking force-fix.
Audit rerun on 2026-09-10 reports two moderate findings. The reviewed notifier's
Windows toaster calls UUID v4 without a buffer; it does not call the affected
v3/v5/v6 buffer APIs. This limits the observed exposure, not the advisory itself.
See verification results in the component README/progress log. Enabling hooks is
not a claim that desktop notifications or every provider/platform is accepted.

Restart only the selected idle OpenCode session after installation to load changes.
Source edits do not update running deployments or already-loaded sessions.
