#!/bin/bash
# Publish maintained V2 inputs without copying or overwriting private HOME state.
set -euo pipefail

cleanup_legacy_self_links() {
    local root="$1" name parent path
    root="$(realpath -e -- "$root")"
    for name in commands skills system; do
        parent="$root/$name"
        path="$parent/$name"
        [[ -d "$parent" && "$(realpath -e -- "$parent")" == "$parent" ]] || continue
        if [[ -L "$path" && "$(readlink -- "$path")" == "/opt/agent/$name" ]]; then
            unlink -- "$path"
        fi
    done
}

init_home() (
    local home_root="${HOME:-/home/opencode}"
    local resources="${OPENCODE_RESOURCES:-/opt/agent}"
    local source="${OPENCODE_DEFAULTS:-/opt/opencode-defaults}"
    local config="${OPENCODE_CONFIG_DIR:-$home_root/.config/opencode}"
    local publisher="${OPENCODE_PUBLISHER:-/opt/opencode/publish-plugins.mjs}"

    [[ -d "$home_root" ]] || { echo 'Missing private HOME' >&2; return 1; }
    [[ -d "$resources" ]] || {
        echo "Missing shared resources: $resources; mount the complete agent tree" >&2
        return 1
    }
    # Coordinate shared source publication before locking private HOME. No
    # root-owned lock files, no deletion of unknown config or redirected roots.
    exec 8<"$resources"
    flock -x 8
    exec 7<"$home_root"
    flock -x 7
    cleanup_legacy_self_links "$resources"

    # Project-local obsolete loaders are outside the publisher's ownership.
    # Preserve them and stop rather than silently starting a mixed V1/V2 engine.
    python3 - <<'PY'
from pathlib import Path
import sys

roots = [root / '.opencode' for root in (Path.cwd(), *Path.cwd().parents)]
stale = sorted({str(path) for root in roots for folder in ('plugin', 'plugins')
                for path in (root / folder).glob('**/kdco-*')
                if path.suffix in ('.js', '.ts', '.mjs', '.cjs')})
if stale:
    sys.exit('Preserved obsolete project loaders; review and remove/port explicitly:\n' + '\n'.join(stale))
PY
    node "$publisher" config "$source" "$resources" "$config"
)

init_home
