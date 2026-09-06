#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=entrypoint.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/entrypoint.sh"

update_checkout() {
    local action="$1" revision="$2" current target
    [[ "$revision" =~ ^[0-9a-f]{40}$ ]] || die 'supply an explicit full lowercase commit SHA, not a tag/branch'
    deployment_lock
    require_clean_checkout
    current=$(git -C "$PI_REPO" rev-parse HEAD)
    # Do not log credential-bearing URLs or allow prompts in automation.
    GIT_TERMINAL_PROMPT=0 timeout 120 git -C "$PI_REPO" fetch --quiet --no-tags origin "$revision" >/dev/null 2>&1 || die 'fetch failed/timed out; check administrator-managed origin/access'
    target=$(git -C "$PI_REPO" rev-parse --verify 'FETCH_HEAD^{commit}')
    [[ "$target" == "$revision" ]] || die 'fetched revision mismatch'
    printf 'current=%s target=%s\n' "$current" "$target"
    [[ "$action" == update && "$current" != "$target" ]] || return 0
    require_stopped
    git -C "$PI_REPO" checkout --quiet --detach --no-overwrite-ignore "$target"
    printf '%s\n' 'Checkout updated. Review pins, run provision, then start for local execution. No automatic restart or rollback.'
}

manage_main() {
    local command=${1:-}
    # Emergency stop must work even with a broken deployment or busy installer.
    if [[ "$command" == stop ]]; then
        [[ $# == 1 ]] || die 'unexpected arguments'
        require_root
        local unit=${PI_UNIT:-pi.service}
        [[ "$unit" =~ ^[a-zA-Z0-9_-]+\.service$ ]] || die 'invalid unit name'
        systemctl stop "$unit"
        return $?
    fi
    load_contract
    case "$command" in
        start|restart)
            [[ $# == 1 ]] || die 'unexpected arguments'
            deployment_lock
            systemctl "$command" "$PI_UNIT" ;;
        status)
            [[ $# == 1 ]] || die 'unexpected arguments'
            exec systemctl --no-pager --full status "$PI_UNIT" ;;
        logs)
            [[ $# == 1 ]] || die 'unexpected arguments'
            exec journalctl --no-pager -u "$PI_UNIT" -n 100 ;;
        version)
            [[ $# == 1 ]] || die 'unexpected arguments'
            printf 'pinned Pi=%s pi-web=%s\n' "$PI_VERSION" "$PI_UI_VERSION"
            # Read package metadata, not agent code, as administrator.
            env -i PATH=/usr/bin:/bin /usr/bin/node -e 'for(const name of ["@earendil-works/pi-coding-agent","@agegr/pi-web"]) {const p=process.argv[1]+"/lib/node_modules/"+name+"/package.json"; console.log(name+" installed="+JSON.parse(require("node:fs").readFileSync(p,"utf8")).version)}' "$PI_PREFIX" ;;
        update|update-check)
            [[ $# == 2 ]] || die 'usage: manage.sh update|update-check FULL_COMMIT_SHA'
            update_checkout "$command" "$2" ;;
        *) die 'usage: manage.sh status|start|stop|restart|logs|version|update-check SHA|update SHA' ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then manage_main "$@"; fi
