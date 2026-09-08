#!/bin/bash
set -euo pipefail

import_system_agents() (
    local shared="$1" agents="$2" previous="${3:-}"
    local root file name target current old
    root="$(realpath -e -- "$shared/system")"
    [[ -d "$root" && "${agents%/*}" == "$(realpath -m -- "${agents%/*}")" ]] || {
        printf '[pi] Missing system root or redirected agent state: %s\n' "$agents" >&2; return 1;
    }
    # Convert only the literal root link created by older Pi initialization.
    # Never write individual imports through that link into the shared checkout.
    if [[ -L "$agents" ]]; then
        old="$(readlink -- "$agents")"
        if [[ "$old" == "$shared" || ( -n "$previous" && "$old" == "$previous" ) ]]; then
            unlink -- "$agents"
        else
            printf '[pi] Preserved conflicting agents link: %s\n' "$agents" >&2; return 1
        fi
    fi
    mkdir -p -- "$agents"
    shopt -s nullglob
    for file in "$root"/*.md; do
        name="${file##*/}"
        [[ "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*\.md$ ]] || {
            printf '[pi] Invalid system agent basename: %s\n' "$name" >&2; return 1;
        }
        target="$(realpath -e -- "$file")"
        [[ -f "$target" && "${target%/*}" == "$root" && "${target##*/}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*\.md$ ]] || {
            printf '[pi] Refusing system agent outside shared system root: %s\n' "$file" >&2; return 1;
        }
        current="$agents/system-$name"
        if [[ -L "$current" && "$(readlink -- "$current")" == "$target" ]]; then
            continue
        fi
        if [[ -e "$current" || -L "$current" ]]; then
            printf '[pi] Preserved conflicting %s; reconcile explicitly to use %s.\n' "$current" "$target" >&2; return 1
        fi
        ln -sT -- "$target" "$current"
    done
)

dir_empty() {
    local path="$1"
    [[ -d "$path" && -z "$(ls -A "$path" 2>/dev/null)" ]]
}

next_backup_path() {
    local path="$1"
    local candidate="${path}.local"
    local index=1

    while [[ -e "$candidate" || -L "$candidate" ]]; do
        candidate="${path}.local.${index}"
        index=$((index + 1))
    done

    printf '%s\n' "$candidate"
}

ensure_real_dir() {
    local path="$1"

    if [[ -L "$path" ]]; then
        rm -f "$path"
    elif [[ -e "$path" && ! -d "$path" ]]; then
        rm -f "$path"
    fi

    mkdir -p "$path"
}

link_path() {
    local current_path="$1"
    local shared_path="$2"

    if [[ -L "$current_path" ]]; then
        rm -f "$current_path"
    elif [[ -e "$current_path" ]]; then
        if [[ -d "$current_path" && -d "$shared_path" ]] && dir_empty "$shared_path"; then
            rmdir "$shared_path"
            mv "$current_path" "$shared_path"
        else
            local backup
            backup="$(next_backup_path "$current_path")"
            mv "$current_path" "$backup"

            if [[ -d "$backup" && -d "$shared_path" ]]; then
                cp -a -n "$backup/." "$shared_path/" 2>/dev/null || true
            elif [[ -f "$backup" && ! -e "$shared_path" ]]; then
                cp -a "$backup" "$shared_path"
            fi
        fi
    fi

    ln -s "$shared_path" "$current_path"
}

ensure_shared_home_root() {
    local shared_root="$1"
    mkdir -p "$shared_root"
    if [[ ! -e "$shared_root/prompts" && ! -L "$shared_root/prompts" ]]; then
        ln -s commands "$shared_root/prompts"
    fi
}

init_home() {
    local HOME_ROOT="/home/pi" DEFAULTS_ROOT="/opt/agent"
    local shared_root="$HOME_ROOT/.agents"
    local pi_root="$HOME_ROOT/.pi/agent"

    [[ -d "$HOME_ROOT" ]] || return 0

    import_system_agents "$DEFAULTS_ROOT" "$pi_root/agents"
    ensure_shared_home_root "$shared_root"
    ensure_real_dir "$HOME_ROOT/.pi"
    ensure_real_dir "$pi_root"

    [[ -d "$DEFAULTS_ROOT" ]] || return 0
    [[ -d "$DEFAULTS_ROOT/commands" ]] || return 0
    [[ -d "$DEFAULTS_ROOT/skills" ]] || return 0

    link_path "$pi_root/prompts" "$DEFAULTS_ROOT/prompts"
    link_path "$pi_root/skills" "$DEFAULTS_ROOT/skills"
    link_path "$shared_root/agents" "$DEFAULTS_ROOT"
    link_path "$shared_root/commands" "$DEFAULTS_ROOT/commands"
    link_path "$shared_root/skills" "$DEFAULTS_ROOT/skills"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    init_home
fi
