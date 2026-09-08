#!/bin/bash
set -euo pipefail
umask 077
[[ $# == 1 && $1 == container ]] || { printf '%s\n' 'Usage: start.sh container' >&2; exit 64; }
source /opt/t3/scripts/entrypoint.sh
validate_contract
initialize_home
# Hold a second, server-duration lock even if a caller bypasses the host
# wrappers. Never remove/replace this inode while any server is running.
exec 9>>/home/t3code/.server.lock
flock --exclusive --nonblock 9 || {
    printf '%s\n' 'This private home already has a server; refusing a second writer.' >&2; exit 75;
}
[[ -x /opt/t3/runtime/node_modules/.bin/t3 ]] || {
    printf '%s\n' 'Immutable T3 runtime is missing; an approved image build is required.' >&2; exit 69;
}
cd /workspace
# Upstream startup can print pairing credentials. Never forward its output to
# Docker logs. The operator owns private log retention and single-writer locking.
exec /opt/t3/runtime/node_modules/.bin/t3 serve --host 0.0.0.0 \
    --port "$T3CODE_PORT" --base-dir /home/t3code/base /workspace \
    >>/home/t3code/logs/server.log 2>&1
