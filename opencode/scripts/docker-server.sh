#!/bin/bash
set -euo pipefail
[[ "$EUID" != 0 ]] || { echo 'Docker V2 must run as a non-root account' >&2; exit 1; }
[[ $# == 0 ]] || { echo 'Docker server takes no arguments; use OPENCODE_DOCKER_PORT' >&2; exit 1; }
[[ "${OPENCODE_SERVER_USERNAME:-opencode}" == opencode ]] || { echo 'V2 requires username opencode' >&2; exit 1; }
export OPENCODE_PASSWORD="${OPENCODE_PASSWORD:-${OPENCODE_SERVER_PASSWORD:-}}"
[[ -n "$OPENCODE_PASSWORD" ]] || { echo 'Set OPENCODE_PASSWORD (or OPENCODE_SERVER_PASSWORD) before starting Docker V2' >&2; exit 1; }
bash /opt/harness/init.sh
exec opencode serve --hostname 0.0.0.0 --port "${OPENCODE_DOCKER_PORT:-4096}"
