#!/bin/bash
set -euo pipefail

mode="${1:-}"
harness="${2:-}"
root="${3:-}"

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

ensure_shared_tree() {
    local shared_root="$1"
    ensure_real_dir "$shared_root"
    ensure_real_dir "$shared_root/agents"
    ensure_real_dir "$shared_root/prompts"
    ensure_real_dir "$shared_root/skills"
    if [[ ! -e "$shared_root/commands" && ! -L "$shared_root/commands" ]]; then
        ln -s prompts "$shared_root/commands"
    fi
}

ensure_shared_root() {
    local shared_root="$1"
    mkdir -p "$shared_root"
    if [[ ! -e "$shared_root/commands" && ! -L "$shared_root/commands" ]]; then
        ln -s prompts "$shared_root/commands"
    fi
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

bootstrap_workspace() {
    local workspace_root="$1"
    local shared_root="$workspace_root/.agents"

    [[ -d "$workspace_root" ]] || exit 0

    ensure_shared_tree "$shared_root"

    ensure_real_dir "$workspace_root/.claude"
    ensure_real_dir "$workspace_root/.pi"
    ensure_real_dir "$workspace_root/.opencode"

    link_path "$workspace_root/.claude/agents" "$shared_root/agents"
    link_path "$workspace_root/.claude/commands" "$shared_root/commands"
    link_path "$workspace_root/.claude/skills" "$shared_root/skills"

    link_path "$workspace_root/.pi/agents" "$shared_root/agents"
    link_path "$workspace_root/.pi/prompts" "$shared_root/prompts"
    link_path "$workspace_root/.pi/skills" "$shared_root/skills"

    link_path "$workspace_root/.opencode/commands" "$shared_root/commands"
    link_path "$workspace_root/.opencode/skills" "$shared_root/skills"
}

bootstrap_home() {
    local home_root="$1"
    local shared_root="$home_root/.agents"
    local defaults_root="/opt/agents"
    local source_agents=""
    local source_prompts=""
    local source_skills=""

    [[ -d "$home_root" ]] || exit 0

    ensure_shared_root "$shared_root"

    case "$harness" in
        claude)
            ensure_real_dir "$home_root/.claude"
            source_agents="$home_root/.claude/agents"
            source_prompts="$home_root/.claude/commands"
            source_skills="$home_root/.claude/skills"
            ;;
        pi)
            ensure_real_dir "$home_root/.pi"
            ensure_real_dir "$home_root/.pi/agent"
            source_agents="$home_root/.pi/agent/agents"
            source_prompts="$home_root/.pi/agent/prompts"
            source_skills="$home_root/.pi/agent/skills"
            ;;
        opencode)
            ensure_real_dir "$home_root/.config"
            ensure_real_dir "$home_root/.config/opencode"
            source_prompts="$home_root/.config/opencode/commands"
            source_skills="$home_root/.config/opencode/skills"
            ;;
        *)
            echo "Unsupported harness: $harness" >&2
            exit 1
            ;;
    esac

    if [[ -n "$source_agents" ]]; then
        ensure_real_dir "$source_agents"
    fi
    ensure_real_dir "$source_prompts"
    ensure_real_dir "$source_skills"

    if [[ -d "$defaults_root" ]]; then
        if [[ -n "$source_agents" ]]; then
            cp -a -n "$defaults_root/agents/." "$source_agents/" 2>/dev/null || true
        fi
        cp -a -n "$defaults_root/prompts/." "$source_prompts/" 2>/dev/null || true
        cp -a -n "$defaults_root/skills/." "$source_skills/" 2>/dev/null || true
    fi

    if [[ -n "$source_agents" ]]; then
        link_path "$shared_root/agents" "$source_agents"
    fi
    link_path "$shared_root/prompts" "$source_prompts"
    link_path "$shared_root/skills" "$source_skills"

    if [[ ! -e "$shared_root/commands" && ! -L "$shared_root/commands" ]]; then
        ln -s prompts "$shared_root/commands"
    fi
}

case "$mode" in
    home)
        bootstrap_home "$root"
        ;;
    workspace)
        bootstrap_workspace "$root"
        ;;
    *)
        echo "Usage: $0 <home|workspace> <claude|pi|opencode> <path>" >&2
        exit 1
        ;;
esac
