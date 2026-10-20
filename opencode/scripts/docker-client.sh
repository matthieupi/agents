#!/bin/bash
set -euo pipefail
export OPENCODE_PASSWORD="${OPENCODE_PASSWORD:-${OPENCODE_SERVER_PASSWORD:-}}"
python3 /opt/harness/docker-health.py --wait
exec opencode --server "http://127.0.0.1:${OPENCODE_DOCKER_PORT:-4096}" "$@"
