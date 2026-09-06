#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=entrypoint.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/entrypoint.sh"
load_contract
[[ $EUID != 0 && $EUID == "$OPENCODE_UID" ]] || die 'run explicitly as OPENCODE_USER (systemd User= or runuser); never root'
export HOME="$OPENCODE_HOME" USER="$OPENCODE_USER" LOGNAME="$OPENCODE_USER"
export XDG_CONFIG_HOME="$HOME/.config" XDG_DATA_HOME="$HOME/.local/share" XDG_CACHE_HOME="$HOME/.cache"
export PATH="$OPENCODE_PREFIX/bin:/usr/local/bin:/usr/bin:/bin"
unset OPENCODE_BIN_PATH
umask 077
[[ -x "$OPENCODE_PREFIX/bin/opencode" ]] || die 'runtime missing; administrator must provision first'
: "${OPENCODE_WORKSPACE:?supply an existing absolute workspace}"
[[ "$OPENCODE_WORKSPACE" == /* && -d "$OPENCODE_WORKSPACE" ]] || die 'workspace must be an existing absolute directory'
[[ "$OPENCODE_WORKSPACE" != /opt && "$OPENCODE_WORKSPACE" != /opt/* && "$OPENCODE_WORKSPACE" == "$(realpath -m -- "$OPENCODE_WORKSPACE")" ]] || die 'workspace must be canonical and outside /opt'
cd -- "$OPENCODE_WORKSPACE"
mode=${1:-}
[[ $# -gt 0 ]] && shift
case "$mode" in
    service)
        [[ $# == 0 ]] || die 'service accepts no extra CLI flags'
        : "${OPENCODE_PORT:?supply loopback web port}"
        [[ "$OPENCODE_PORT" =~ ^[1-9][0-9]{0,4}$ ]] && (( OPENCODE_PORT >= 1024 && OPENCODE_PORT <= 65535 )) || die 'port must be 1024..65535'
        : "${OPENCODE_SERVER_PASSWORD:?web service requires a secret supplied by the service manager}"
        exec "$OPENCODE_PREFIX/bin/opencode" web --hostname 127.0.0.1 --port "$OPENCODE_PORT" --mdns false
        ;;
    session) exec "$OPENCODE_PREFIX/bin/opencode" "$@" ;;
    *) die 'usage: start.sh service | session [OpenCode CLI arguments...]' ;;
esac
