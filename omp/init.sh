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

init_home() {
    [[ "$(id -u)" != 0 && "$HOME" == /home/omp ]] || {
        printf '[omp] init requires the non-root container account and HOME=/home/omp.\n' >&2; return 1;
    }
    [[ ! -L "$HOME/.omp" && ! -L "$HOME/.omp/agent" ]] || {
        printf '[omp] Refusing redirected state directories.\n' >&2; return 1;
    }
    mkdir -p "$HOME/.omp/agent"
    [[ -w "$HOME" && -w "$HOME/.omp" && -w "$HOME/.omp/agent" && -w /workspace && -w /opt/agent ]] || {
        printf '[omp] Home/state/workspace/resources must be writable by the configured UID/GID; fix only the concerned paths offline.\n' >&2
        return 1
    }
    local persona="${OMP_PERSONA:-build}"
    [[ "$persona" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || {
        printf '[omp] OMP_PERSONA must be a simple shared system Markdown basename.\n' >&2; return 1;
    }
    # SYSTEM.md reads plain Markdown; task agents require different frontmatter.
    link_resource "$HOME/.omp/agent/SYSTEM.md" "/opt/agent/system/$persona.md"
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
