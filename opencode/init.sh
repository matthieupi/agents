#!/bin/bash
set -euo pipefail

HOME_ROOT="${HOME:-/home/opencode}"
DEFAULTS_ROOT="${OPENCODE_RESOURCES:-/opt/agent}"

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
    local opencode_root="${OPENCODE_CONFIG_DIR:-$HOME_ROOT/.config/opencode}"

    [[ -d "$HOME_ROOT" ]] || return 0

    if [[ -L "$HOME_ROOT/.config" || -L "$opencode_root" ]]; then
        echo 'Refusing redirected config root; preserved for operator review' >&2
        return 1
    fi

    ensure_real_dir "$HOME_ROOT/.config"
    ensure_real_dir "$opencode_root"

    # Never delete unknown/private plugins. Old auto-discovered loaders must be
    # reviewed before starting the new engine (including project ancestors).
    python3 - "$opencode_root" <<'PY'
from pathlib import Path
import sys

roots = [Path(sys.argv[1]), Path.home() / '.config/opencode']
roots += [root / '.opencode' for root in (Path.cwd(), *Path.cwd().parents)]
stale = sorted({str(path) for root in roots for folder in ('plugin', 'plugins')
                for path in (root / folder).glob('**/kdco-*')
                if path.suffix in ('.js', '.ts', '.mjs', '.cjs')})
if stale:
    sys.exit('Obsolete KDCO auto-discovered entrypoints found; no files changed. '
             'Review and remove/port these loaders explicitly before restarting:\n' + '\n'.join(stale))
PY

    for folder in commands skills system gsd; do
        if [[ ! -d "$DEFAULTS_ROOT/$folder" ]]; then
            echo "Missing shared resource directory: $DEFAULTS_ROOT/$folder; mount the complete agent tree" >&2
            return 1
        fi
    done

    link_path "$opencode_root/commands" "$DEFAULTS_ROOT/commands"
    link_path "$opencode_root/skills" "$DEFAULTS_ROOT/skills"
    link_path "$opencode_root/system" "$DEFAULTS_ROOT/system"
    link_path "$opencode_root/gsd" "$DEFAULTS_ROOT/gsd"

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
