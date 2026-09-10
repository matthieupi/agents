#!/bin/bash
# VM-only invocation of the existing pinned T3 runtime and private initializer.
set -euo pipefail
umask 077
[[ $# == 0 && $UID != 0 ]] || exit 64
workspace=$PWD
[[ $workspace == /* && $workspace != / && -d $workspace && ! -L $workspace ]] || exit 64
source /opt/t3/scripts/entrypoint.sh
validate_contract
initialize_home
exec 9>>/home/t3code/.server.lock
flock --exclusive --nonblock 9 || { printf '%s\n' 'T3 private home already has a server.' >&2; exit 75; }
[[ -x /opt/t3/runtime/node_modules/.bin/t3 ]] || exit 69
# Native pairing/session logs are private, not exposed through Docker logs.
exec /opt/t3/runtime/node_modules/.bin/t3 serve --host 0.0.0.0 \
    --port "$T3CODE_PORT" --base-dir /home/t3code/base "$workspace" \
    >>/home/t3code/logs/server.log 2>&1
