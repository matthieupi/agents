#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=entrypoint.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/entrypoint.sh"

update_checkout() {
    local action="$1" revision="$2" current target
    [[ "$revision" =~ ^[0-9a-f]{40}$ ]] || die 'supply an explicit full lowercase commit SHA, not a branch/tag'
    deployment_lock
    [[ -z "$(git -C "$OPENCODE_REPO" status --porcelain --untracked-files=all)" ]] || die 'checkout is dirty; preserve and reconcile changes first'
    current=$(git -C "$OPENCODE_REPO" rev-parse HEAD)
    # Never print a remote URL: it may contain credentials. No credential prompts in automation.
    GIT_TERMINAL_PROMPT=0 timeout 120 git -C "$OPENCODE_REPO" fetch --quiet --no-tags origin "$revision" >/dev/null 2>&1 || die 'fetch failed or timed out; check administrator-managed origin/access'
    target=$(git -C "$OPENCODE_REPO" rev-parse --verify 'FETCH_HEAD^{commit}')
    [[ "$target" == "$revision" ]] || die 'fetched revision mismatch'
    printf 'current=%s target=%s\n' "$current" "$target"
    [[ "$action" == update ]] || return 0
    [[ "$current" != "$target" ]] || return 0
    # Require a stopped unit; never unexpectedly interrupt sessions or restart after a partial failure.
    local state
    state=$(systemctl show --property=ActiveState --value "$OPENCODE_UNIT")
    [[ "$state" == inactive || "$state" == failed ]] || die 'stop the unit before updating'
    git -C "$OPENCODE_REPO" checkout --quiet --detach --no-overwrite-ignore "$target"
    printf '%s\n' 'Checkout updated. Run provision with approved dependency pins, then start the unit. No automatic rollback.'
}

manage_main() {
    local command=${1:-}
    # Emergency stop must work even with a broken deployment or busy installer.
    if [[ "$command" == stop ]]; then
        [[ $# == 1 ]] || die 'unexpected arguments'
        require_root
        local unit=${OPENCODE_UNIT:-opencode.service}
        [[ "$unit" =~ ^[a-zA-Z0-9_-]+\.service$ ]] || die 'invalid unit name'
        systemctl stop "$unit"
        return $?
    fi
    load_contract
    case "$command" in
    start|restart)
        [[ $# == 1 ]] || die 'unexpected arguments'
        require_root
        # Keep the lock in this shell while systemctl waits for completion.
        # A concurrent start/restart must not race an installer or checkout.
        deployment_lock
        systemctl "$command" "$OPENCODE_UNIT" ;;
    status)
        [[ $# == 1 ]] || die 'unexpected arguments'
        exec systemctl --no-pager --full status "$OPENCODE_UNIT" ;;
    logs)
        [[ $# == 1 ]] || die 'unexpected arguments'
        exec journalctl --no-pager -u "$OPENCODE_UNIT" -n 100 ;;
    version)
        [[ $# == 1 ]] || die 'unexpected arguments'
        if [[ $EUID == 0 ]]; then
            exec runuser -u "$OPENCODE_USER" -- env -i HOME="$OPENCODE_HOME" PATH="$OPENCODE_PREFIX/bin:/usr/bin:/bin" \
                OPENCODE_DISABLE_AUTOUPDATE=1 "$OPENCODE_PREFIX/bin/opencode" --version
        fi
        [[ $EUID == "$OPENCODE_UID" ]] || die 'run as the supplied account or administrator'
        exec env -i HOME="$OPENCODE_HOME" PATH="$OPENCODE_PREFIX/bin:/usr/bin:/bin" \
            OPENCODE_DISABLE_AUTOUPDATE=1 "$OPENCODE_PREFIX/bin/opencode" --version ;;
    update|update-check)
        [[ $# == 2 ]] || die 'usage: manage.sh update|update-check FULL_COMMIT_SHA'
        update_checkout "$command" "$2" ;;
    *) die 'usage: manage.sh start|stop|restart|status|logs|version|update-check SHA|update SHA' ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    manage_main "$@"
fi
