#!/bin/bash
# Container-only reference wiring. Never migrate, copy, chown or replace user data.
set -euo pipefail
umask 077

link_resource() {
    local current="$1" shared="$2"
    [[ -e "$shared" ]] || { printf '[omp] Missing resource: %s\n' "$shared" >&2; return 1; }
    if [[ -L "$current" && "$(readlink -- "$current")" == "$shared" ]]; then
        return
    fi
    if [[ -e "$current" || -L "$current" ]]; then
        printf '[omp] Preserved conflicting %s; move it aside explicitly to use %s.\n' "$current" "$shared" >&2
        return 1
    fi
    ln -sT -- "$shared" "$current"
}

import_system_agents() (
    local root agents="$HOME/.omp/agent/agents" file name target
    root="$(realpath -e -- /opt/agent/system)"
    [[ -d "$root" && ! -L "$agents" ]] || {
        printf '[omp] Missing system root or conflicting agents directory: %s\n' "$agents" >&2; return 1;
    }
    mkdir -p -- "$agents"
    shopt -s nullglob
    for file in "$root"/*.md; do
        name="${file##*/}"
        [[ "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*\.md$ ]] || {
            printf '[omp] Invalid system agent basename: %s\n' "$name" >&2; return 1;
        }
        target="$(realpath -e -- "$file")"
        [[ -f "$target" && "${target%/*}" == "$root" && "${target##*/}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*\.md$ ]] || {
            printf '[omp] Refusing system agent outside shared system root: %s\n' "$file" >&2; return 1;
        }
        link_resource "$agents/system-$name" "$target"
    done
)

init_home() {
    local runtime_uid runtime_gid account account_name account_password account_uid account_gid account_rest
    runtime_uid="$(id -u)"
    runtime_gid="$(id -g)"
    printf '[omp] Runtime UID=%s GID=%s (primary).\n' "$runtime_uid" "$runtime_gid" >&2
    account="$(getent passwd omp)" || {
        printf '[omp] Missing passwd account omp; rebuild the OMP image.\n' >&2; return 1;
    }
    IFS=: read -r account_name account_password account_uid account_gid account_rest <<< "$account"
    [[ "$runtime_uid" != 0 && "$runtime_uid" == "$account_uid" && "$runtime_gid" == "$account_gid" ]] || {
        printf '[omp] Account mismatch: runtime UID=%s GID=%s; passwd omp UID=%s primary GID=%s. Rebuild with matching OMP_UID/OMP_GID and recreate only the concerned container.\n' \
            "$runtime_uid" "$runtime_gid" "$account_uid" "$account_gid" >&2
        return 1
    }
    [[ "${HOME:-}" == /home/omp ]] || {
        printf '[omp] init requires HOME=/home/omp.\n' >&2; return 1;
    }
    [[ ! -L "$HOME/.omp" && ! -L "$HOME/.omp/agent" ]] || {
        printf '[omp] Refusing redirected state directories.\n' >&2; return 1;
    }
    local path failed=0
    if ! mkdir -p "$HOME/.omp/agent"; then
        printf '[omp] Cannot prepare /home/omp/.omp/agent.\n' >&2
        failed=1
    fi
    for path in "$HOME" "$HOME/.omp" "$HOME/.omp/agent" /workspace /opt/agent; do
        if [[ ! -d "$path" || ! -w "$path" || ! -x "$path" ]]; then
            printf '[omp] Required directory is missing, unwritable or unsearchable: %s (runtime UID=%s GID=%s).\n' \
                "$path" "$runtime_uid" "$runtime_gid" >&2
            stat -L --printf='[omp] Path metadata: type=%F uid=%u gid=%g mode=%a\n' -- "$path" >&2 || \
                printf '[omp] Metadata unavailable for: %s\n' "$path" >&2
            failed=1
        fi
    done
    if (( failed )); then
        printf '[omp] Rebuild/recreate for image-home ownership; review only concerned bind paths offline. Init never changes host ownership or permissions.\n' >&2
        return 1
    fi
    local persona="${OMP_PERSONA:-build}"
    [[ "$persona" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || {
        printf '[omp] OMP_PERSONA must be a simple shared system Markdown basename.\n' >&2; return 1;
    }
    # SYSTEM.md reads plain Markdown, including the portable agent metadata.
    link_resource "$HOME/.omp/agent/SYSTEM.md" "/opt/agent/system/$persona.md"
    import_system_agents
    # prompts is an alias of commands in the shared repository: expose once.
    link_resource "$HOME/.omp/agent/commands" /opt/agent/commands
    # Native OMP scans only skills/<name>/SKILL.md. Shared skills are grouped
    # one extra level deep, so use directory references, not copied skill bodies.
    local skills="$HOME/.omp/agent/skills" file directory name target
    [[ ! -L "$skills" ]] || {
        printf '[omp] Preserved conflicting skills link; move it aside explicitly.\n' >&2; return 1;
    }
    mkdir -p "$skills"
    shopt -s nullglob
    local -a files=(/opt/agent/skills/*/SKILL.md /opt/agent/skills/*/*/SKILL.md)
    for file in "${files[@]}"; do
        directory="${file%/*}"
        name="${directory##*/}"
        target="$(realpath -e -- "$directory")"
        [[ "$target" == /opt/agent/skills/* ]] || {
            printf '[omp] Refusing skill reference outside shared skills: %s\n' "$directory" >&2; return 1;
        }
        link_resource "$skills/$name" "$target"
    done
}

init_home
