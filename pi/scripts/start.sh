#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=entrypoint.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/entrypoint.sh"

start_main() {
    load_contract
    [[ $EUID != 0 && $EUID == "$PI_UID" ]] || die 'run explicitly as PI_USER; never root'
    export HOME="$PI_HOME" USER="$PI_USER" LOGNAME="$PI_USER"
    export PATH="$PI_PREFIX/bin:/usr/bin:/bin" PI_WEB_SKIP_VERSION_CHECK=1
    unset NODE_OPTIONS NODE_PATH
    umask 077
    local mode=${1:-}
    [[ $# -gt 0 ]] && shift
    case "$mode" in
        service)
            [[ $# == 0 ]] || die 'service accepts no extra flags'
            : "${PI_PORT:?supply an explicit loopback web port}"
            [[ "$PI_PORT" =~ ^[1-9][0-9]{0,4}$ ]] && (( PI_PORT >= 1024 && PI_PORT <= 65535 )) || die 'port must be 1024..65535'
            : "${PI_WEB_PASSWORD:?supply web password via the service manager}"
            [[ -x "$PI_PREFIX/bin/pi-web" ]] || die 'provision the runtime first'
            ;;
        session) [[ -x "$PI_PREFIX/bin/pi" ]] || die 'provision the runtime first' ;;
        *) die 'usage: start.sh service | session [Pi arguments...]' ;;
    esac
    : "${PI_WORKSPACE:?supply an existing canonical absolute workspace}"
    [[ "$PI_WORKSPACE" == /* && -d "$PI_WORKSPACE" && "$PI_WORKSPACE" != / && "$PI_WORKSPACE" != /opt && "$PI_WORKSPACE" != /opt/* && "$PI_WORKSPACE" == "$(realpath -m -- "$PI_WORKSPACE")" ]] || die 'invalid workspace'
    [[ "$PI_WORKSPACE/" != "$PI_ROOT/"* ]] || die 'workspace must not be inside the deployment'
    cd -- "$PI_WORKSPACE"
    case "$mode" in
        service) exec "$PI_PREFIX/bin/pi-web" --hostname 127.0.0.1 --port "$PI_PORT" --no-open ;;
        session) exec "$PI_PREFIX/bin/pi" "$@" ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then start_main "$@"; fi
