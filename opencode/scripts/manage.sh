#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=entrypoint.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/entrypoint.sh"

update_checkout() {
    local action="$1" revision="$2" branch status current target
    [[ "$revision" =~ ^[0-9a-f]{40}$ ]] || die 'supply a full lowercase commit SHA'
    : "${OPENCODE_BRANCH:?supply the assigned local branch}"
    opencode_git check-ref-format --branch "$OPENCODE_BRANCH" >/dev/null 2>&1 || die 'invalid OPENCODE_BRANCH'
    deployment_lock
    branch=$(opencode_git symbolic-ref --short HEAD) || die 'detached checkout; preserve and reconcile first'
    [[ "$branch" == "$OPENCODE_BRANCH" ]] || die 'checkout is not on assigned OPENCODE_BRANCH; preserved'
    status=$(opencode_git status --porcelain --untracked-files=all) || die 'cannot inspect checkout status'
    [[ -z "$status" ]] || die 'checkout is dirty; preserve and reconcile edits before explicit update'
    current=$(opencode_git rev-parse HEAD)
    opencode_git fetch --quiet --no-tags origin "$OPENCODE_BRANCH" >/dev/null 2>&1 || die 'fetch failed or timed out; check origin/access'
    target=$(opencode_git rev-parse --verify "$revision^{commit}") || die 'requested commit unavailable'
    [[ "$target" == "$revision" ]] || die 'revision mismatch'
    opencode_git merge-base --is-ancestor "$target" FETCH_HEAD || die 'target is not on the fetched assigned branch'
    opencode_git merge-base --is-ancestor HEAD "$target" || die 'update is not a fast-forward; local commits preserved'
    printf 'current=%s target=%s\n' "$current" "$target"
    [[ "$action" == update ]] || return 0
    opencode_git merge --ff-only --no-overwrite-ignore "$target"
    printf '%s\n' 'Checkout fast-forwarded on assigned branch. No install, service action, commit or push.'
}

manage_main() {
    load_contract
    case "${1:-}" in
        status)
            [[ $# == 1 ]] || die 'unexpected arguments'
            exec env -i PATH=/usr/bin:/bin /usr/bin/systemctl --no-pager show \
                --property=Id,LoadState,ActiveState,SubState "$OPENCODE_UNIT" ;;
        version)
            [[ $# == 1 ]] || die 'unexpected arguments'
            (
                umask 077
                home=$(mktemp -d)
                trap 'rm -rf -- "$home"' EXIT
                isolated_runtime "$OPENCODE_PREFIX" "$home" --version
            ) ;;
        update|update-check)
            [[ $# == 2 ]] || die 'usage: manage.sh update|update-check FULL_COMMIT_SHA'
            update_checkout "$1" "$2" ;;
        *) die 'usage: manage.sh status|version|update-check SHA|update SHA; administrators use systemctl directly' ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then manage_main "$@"; fi
