#!/bin/bash
set -euo pipefail
[[ "${OPENCODE_SERVER_USERNAME:-opencode}" == opencode ]] || { echo 'V2 requires username opencode' >&2; exit 1; }
export OPENCODE_PASSWORD="${OPENCODE_PASSWORD:-${OPENCODE_SERVER_PASSWORD:-}}"
[[ -n "$OPENCODE_PASSWORD" ]] || { echo 'Set OPENCODE_PASSWORD before attaching Docker V2' >&2; exit 1; }
for arg in "$@"; do
    case "$arg" in
        --server|--server=*|serve)
            echo 'Docker client uses the existing local server; server overrides are not allowed' >&2
            exit 1
            ;;
    esac
done
python3 /opt/harness/docker-health.py --wait
exec opencode --server "http://127.0.0.1:${OPENCODE_DOCKER_PORT:-4096}" "$@"
