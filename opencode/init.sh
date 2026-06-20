#!/bin/bash
set -euo pipefail

HOME_ROOT="/home/opencode"
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

remove_legacy_link() {
    local current_path="$1"
    local shared_path="$2"

    if [[ -L "$current_path" && "$(readlink "$current_path")" == "$shared_path" ]]; then
        rm -f "$current_path"
    fi
}

init_home() {
    local shared_root="$HOME_ROOT/.agents"
    local opencode_root="$HOME_ROOT/.config/opencode"

    [[ -d "$HOME_ROOT" ]] || return 0

    ensure_real_dir "$HOME_ROOT/.config"
    ensure_real_dir "$opencode_root"

    [[ -d "$DEFAULTS_ROOT/commands" ]] || return 0
    [[ -d "$DEFAULTS_ROOT/skills" ]] || return 0
    [[ -d "$DEFAULTS_ROOT/system" ]] || return 0

    link_path "$opencode_root/commands" "$DEFAULTS_ROOT/commands"
    link_path "$opencode_root/skills" "$DEFAULTS_ROOT/skills"
    link_path "$opencode_root/system" "$DEFAULTS_ROOT/system"
    if [[ -d "$DEFAULTS_ROOT/gsd" ]]; then
        link_path "$opencode_root/gsd" "$DEFAULTS_ROOT/gsd"
    fi

    # opencode already discovers project commands and skills from
    # ~/.config/opencode. Exposing the same mounted trees through ~/.agents as
    # well makes opencode scan duplicate roots and can amplify symlink loops
    # into paths like skills/skills/skills/... and commands/commands/commands/...
    remove_legacy_link "$shared_root/commands" "$DEFAULTS_ROOT/commands"
    remove_legacy_link "$shared_root/skills" "$DEFAULTS_ROOT/skills"
    remove_legacy_link "$shared_root/system" "$DEFAULTS_ROOT/system"
    remove_legacy_link "$shared_root/gsd" "$DEFAULTS_ROOT/gsd"
    remove_legacy_link "$shared_root/prompts" "commands"
}

init_home
