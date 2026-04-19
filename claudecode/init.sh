#!/bin/bash
set -euo pipefail

HOME_ROOT="/home/claude"
DEFAULTS_ROOT="/opt/agent"

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
    local shared_root="$HOME_ROOT/.agents"
    local claude_root="$HOME_ROOT/.claude"

    [[ -d "$HOME_ROOT" ]] || return 0

    ensure_shared_home_root "$shared_root"
    ensure_real_dir "$claude_root"

    [[ -d "$DEFAULTS_ROOT" ]] || return 0
    [[ -d "$DEFAULTS_ROOT/commands" ]] || return 0
    [[ -d "$DEFAULTS_ROOT/skills" ]] || return 0

    link_path "$claude_root/agents" "$DEFAULTS_ROOT"
    link_path "$claude_root/commands" "$DEFAULTS_ROOT/commands"
    link_path "$claude_root/skills" "$DEFAULTS_ROOT/skills"
    link_path "$shared_root/agents" "$DEFAULTS_ROOT"
    link_path "$shared_root/commands" "$DEFAULTS_ROOT/commands"
    link_path "$shared_root/skills" "$DEFAULTS_ROOT/skills"
}

init_home
