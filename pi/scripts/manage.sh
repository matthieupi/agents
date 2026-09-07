#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=entrypoint.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/entrypoint.sh"

update_checkout() {
    local action="$1" revision="$2" branch status current target
    [[ "$revision" =~ ^[0-9a-f]{40}$ ]] || die 'supply a full lowercase commit SHA'
    : "${PI_BRANCH:?supply the assigned local branch}"
    pi_git check-ref-format --branch "$PI_BRANCH" >/dev/null 2>&1 || die 'invalid PI_BRANCH'
    deployment_lock
    branch=$(pi_git symbolic-ref --short HEAD) || die 'detached checkout; preserve and reconcile first'
    [[ "$branch" == "$PI_BRANCH" ]] || die 'checkout is not on assigned PI_BRANCH; preserved'
    status=$(pi_git status --porcelain --untracked-files=all) || die 'cannot inspect checkout status'
    [[ -z "$status" ]] || die 'checkout is dirty; preserve and reconcile edits before explicit update'
    current=$(pi_git rev-parse HEAD)
    pi_git fetch --quiet --no-tags origin "$PI_BRANCH" >/dev/null 2>&1 || die 'fetch failed or timed out; check origin/access'
    target=$(pi_git rev-parse --verify "$revision^{commit}") || die 'requested commit unavailable'
    [[ "$target" == "$revision" ]] || die 'revision mismatch'
    pi_git merge-base --is-ancestor "$target" FETCH_HEAD || die 'target is not on the fetched assigned branch'
    pi_git merge-base --is-ancestor HEAD "$target" || die 'update is not a fast-forward; local commits preserved'
    printf 'current=%s target=%s\n' "$current" "$target"
    [[ "$action" == update ]] || return 0
    pi_git merge --ff-only --no-overwrite-ignore "$target"
    printf '%s\n' 'Checkout fast-forwarded on assigned branch. No install, service action, commit or push.'
}

manage_main() {
    load_contract
    require_pi_user
    case "${1:-}" in
        status)
            [[ $# == 1 ]] || die 'unexpected arguments'
            exec env -i PATH=/usr/bin:/bin /usr/bin/systemctl --no-pager show \
                --property=Id,LoadState,ActiveState,SubState "$PI_UNIT" ;;
        version)
            [[ $# == 1 ]] || die 'unexpected arguments'
            env -i HOME="$PI_HOME" PATH="$PI_PREFIX/bin:/usr/bin:/bin" \
                timeout --kill-after=10 30 "$PI_PREFIX/bin/pi" --version ;;
        update|update-check)
            [[ $# == 2 ]] || die 'usage: manage.sh update|update-check FULL_COMMIT_SHA'
            update_checkout "$1" "$2" ;;
        *) die 'usage: manage.sh status|version|update-check SHA|update SHA; administrators use systemctl directly' ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then manage_main "$@"; fi
