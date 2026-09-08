#!/usr/bin/env bash
set -euo pipefail

die() { printf 'opencode: %s\n' "$*" >&2; exit 1; }

require_opencode_user() {
    [[ $EUID != 0 && $UID != 0 ]] || die 'never root; run explicitly as OPENCODE_USER'
    [[ $EUID == "${OPENCODE_UID:-}" && $UID == "$EUID" ]] || die 'run explicitly as OPENCODE_USER (exact account UID required)'
}

load_contract() {
    [[ $EUID != 0 && $UID != 0 ]] || die 'never root; run explicitly as OPENCODE_USER'
    export OPENCODE_REPO="${OPENCODE_REPO:-/srv/agents}"
    export OPENCODE_ROOT="${OPENCODE_ROOT:-$OPENCODE_REPO/opencode}"
    export OPENCODE_PREFIX="${OPENCODE_PREFIX:-$OPENCODE_ROOT/.runtime}"
    : "${OPENCODE_USER:?supply an existing non-root account}"
    local record password gecos shell
    record=$(getent passwd "$OPENCODE_USER") || die 'account does not exist'
    IFS=: read -r OPENCODE_ACCOUNT password OPENCODE_UID OPENCODE_GID gecos OPENCODE_HOME shell <<< "$record"
    [[ "$OPENCODE_UID" =~ ^[0-9]+$ && "$OPENCODE_UID" != 0 && "$OPENCODE_ACCOUNT" == "$OPENCODE_USER" ]] || die 'named non-root account required'
    require_opencode_user
    local path
    for path in "$OPENCODE_ROOT" "$OPENCODE_REPO" "$OPENCODE_PREFIX" "$OPENCODE_HOME"; do
        [[ "$path" == /* && "$path" != / && "$path" != /opt && "$path" != /opt/* && "$path" == "$(realpath -m -- "$path")" ]] || die 'paths must be canonical absolute paths outside /opt'
    done
    [[ "$OPENCODE_ROOT" == "$OPENCODE_REPO/opencode" && "$OPENCODE_PREFIX" == "$OPENCODE_ROOT/.runtime" ]] || die 'require OPENCODE_ROOT=OPENCODE_REPO/opencode and OPENCODE_PREFIX=OPENCODE_ROOT/.runtime'
    [[ "$OPENCODE_HOME/" != "$OPENCODE_REPO/"* && "$OPENCODE_REPO/" != "$OPENCODE_HOME/"* ]] || die 'private home and checkout must not overlap'
    for path in "$OPENCODE_HOME" "$OPENCODE_REPO" "$OPENCODE_ROOT"; do
        [[ -d "$path" && "$(stat -c %u -- "$path")" == "$OPENCODE_UID" ]] || die 'OPENCODE_USER must own its existing home, checkout and component'
    done
    export OPENCODE_CONFIG_DIR="$OPENCODE_HOME/.config/opencode"
    export OPENCODE_DISABLE_AUTOUPDATE=1
    export OPENCODE_UNIT="${OPENCODE_UNIT:-opencode.service}"
    [[ "$OPENCODE_UNIT" =~ ^[a-zA-Z0-9_-]+\.service$ ]] || die 'invalid unit name'
    [[ -d "$OPENCODE_REPO/.git" && ! -L "$OPENCODE_REPO/.git" && "$(opencode_git rev-parse --show-toplevel)" == "$OPENCODE_REPO" ]] || die 'OPENCODE_REPO must be the whole agents Git checkout'
}

opencode_git() {
    require_opencode_user
    env -i HOME="$OPENCODE_HOME" PATH=/usr/bin:/bin GIT_TERMINAL_PROMPT=0 \
        timeout --kill-after=10 120 /usr/bin/git -C "$OPENCODE_REPO" "$@"
}

deployment_lock() {
    require_opencode_user
    [[ ! -L "$OPENCODE_ROOT/.lifecycle.lock" ]] || die 'preserved redirected lifecycle lock'
    exec 9>"$OPENCODE_ROOT/.lifecycle.lock"
    flock -n 9 || die 'another lifecycle operation is running'
}

initialize_home() (
    require_opencode_user
    export HOME="$OPENCODE_HOME"
    umask 077
    local name destination source legacy file relative parent tracked pending='' path old
    for path in "$OPENCODE_CONFIG_DIR" "$HOME/.local/share/opencode" "$HOME/.cache/opencode" "$HOME/.local/state/opencode" "$HOME/.agents"; do
        [[ "$path" == "$(realpath -m -- "$path")" ]] || die 'preserved redirected private state; reconcile manually'
    done
    if [[ -n ${OPENCODE_PREVIOUS_REPO:-} ]]; then
        [[ "$OPENCODE_PREVIOUS_REPO" == /* && "$OPENCODE_PREVIOUS_REPO" != / && "$OPENCODE_PREVIOUS_REPO" == "$(realpath -m -- "$OPENCODE_PREVIOUS_REPO")" ]] || die 'invalid OPENCODE_PREVIOUS_REPO'
    fi
    mkdir -p "$OPENCODE_CONFIG_DIR" "$HOME/.local/share/opencode" "$HOME/.cache/opencode" "$HOME/.local/state/opencode"
    for name in commands skills system gsd; do
        source="$OPENCODE_REPO/agent/$name"
        destination="$OPENCODE_CONFIG_DIR/$name"
        old="${OPENCODE_PREVIOUS_REPO:-$OPENCODE_REPO}/agent/$name"
        [[ -d "$source" ]] || die "missing shared resource: $name"
        if [[ -e "$destination" || -L "$destination" ]]; then
            [[ -L "$destination" && ( "$(readlink -- "$destination")" == "$source" || "$(readlink -- "$destination")" == "$old" ) ]] || die "preserved conflicting resource; reconcile manually: $destination"
            [[ "$(readlink -- "$destination")" == "$source" ]] || ln -sfnT -- "$source" "$destination"
        else
            ln -s -- "$source" "$destination"
        fi
        legacy="$HOME/.agents/$name"
        if [[ -L "$legacy" && ( "$(readlink -- "$legacy")" == "$source" || "$(readlink -- "$legacy")" == "$old" ) ]]; then
            rm -- "$legacy"
        elif [[ -e "$legacy" || -L "$legacy" ]]; then
            die "preserved external discovery tree; reconcile duplicate resources manually: $legacy"
        fi
    done
    # Capture first: process-substitution failures would otherwise be silently ignored.
    tracked=$(mktemp)
    trap 'rm -f -- "$tracked" "$pending"' EXIT
    opencode_git ls-files -z -- opencode/.opencode/config > "$tracked" || die 'cannot list tracked defaults'
    # Only tracked, explicitly allowed config files; never state, auth, caches or node_modules.
    while IFS= read -r -d '' file; do
        relative=${file#opencode/.opencode/config/}
        case "$relative" in
            opencode.json|opencode.jsonc|tui.json|package.json|package-lock.json|plugins/*|plugin/*) ;;
            *) continue ;;
        esac
        case "/$relative/" in */node_modules/*|*/.cache/*) continue ;; esac
        # A second config format could override an existing user's settings.
        case "$relative" in
            opencode.json|opencode.jsonc)
                if [[ -e "$OPENCODE_CONFIG_DIR/opencode.json" || -L "$OPENCODE_CONFIG_DIR/opencode.json" ||
                      -e "$OPENCODE_CONFIG_DIR/opencode.jsonc" || -L "$OPENCODE_CONFIG_DIR/opencode.jsonc" ]]; then
                    continue
                fi ;;
        esac
        destination="$OPENCODE_CONFIG_DIR/$relative"
        [[ ! -e "$destination" && ! -L "$destination" ]] || continue
        parent=$(dirname -- "$destination")
        [[ "$(realpath -m -- "$parent")" == "$parent" ]] || die "preserved redirected plugin directory: $parent"
        mkdir -p -- "$(dirname -- "$destination")"
        pending=$(mktemp "$parent/.opencode-default.XXXXXXXX")
        opencode_git show "HEAD:$file" > "$pending"
        # Publish a complete file exclusively; never replace concurrent user content.
        if ! ln -T -- "$pending" "$destination"; then
            [[ -e "$destination" || -L "$destination" ]] || die "cannot publish default: $destination"
        fi
        rm -f -- "$pending"
    done < "$tracked"
)

isolated_runtime() (
    require_opencode_user
    local prefix="$1" home="$2"
    shift 2
    cd -- "$home"
    env -i HOME="$home" USER="$OPENCODE_USER" LOGNAME="$OPENCODE_USER" \
        PATH="$prefix/bin:/usr/bin:/bin" XDG_CONFIG_HOME="$home/.config" \
        XDG_DATA_HOME="$home/.local/share" XDG_CACHE_HOME="$home/.cache" XDG_STATE_HOME="$home/.local/state" \
        OPENCODE_CONFIG_DIR="$home/.config/opencode" OPENCODE_DISABLE_AUTOUPDATE=1 \
        timeout --kill-after=10 30 "$prefix/bin/opencode" "$@"
)

verify_runtime() (
    require_opencode_user
    local prefix="$1" home="$2" version
    [[ -x "$prefix/bin/opencode" ]] || return 1
    env -i HOME="$home" PATH=/usr/bin:/bin timeout --kill-after=10 30 /usr/bin/node -e '
        const p=require(process.argv[1]+"/node_modules/opencode-ai/package.json");
        if(p.name!=="opencode-ai" || p.version!==process.argv[2]) process.exit(1);
        ' "$prefix" "$OPENCODE_VERSION" || return 1
    version=$(isolated_runtime "$prefix" "$home" --version) || return 1
    [[ "$version" == "$OPENCODE_VERSION" ]]
)

install_runtime() (
    : "${OPENCODE_VERSION:?supply an exact stable OpenCode X.Y.Z version}"
    [[ "$OPENCODE_VERSION" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || die 'OpenCode version must be an exact stable version'
    deployment_lock
    umask 077
    local stage
    stage=$(mktemp -d "$OPENCODE_ROOT/.build.XXXXXXXX")
    trap 'printf "Install failed; inspect retained stage: %s\n" "$stage" >&2' EXIT
    mkdir -- "$stage/home"
    : > "$stage/npm-userrc"
    : > "$stage/npm-globalrc"
    if ! verify_runtime "$OPENCODE_PREFIX" "$stage/home" > "$stage/reuse.log" 2>&1; then
        mkdir -- "$stage/runtime"
        (
            cd -- "$stage/home"
            # Standard lifecycle is required by recent compiled-binary packages.
            # This isolates configuration/secrets, not the user's filesystem access.
            env -i HOME="$stage/home" PATH=/usr/bin:/bin TMPDIR="$stage/home" \
                XDG_CONFIG_HOME="$stage/home/.config" XDG_DATA_HOME="$stage/home/.local/share" \
                XDG_CACHE_HOME="$stage/home/.cache" XDG_STATE_HOME="$stage/home/.local/state" \
                OPENCODE_CONFIG_DIR="$stage/home/.config/opencode" OPENCODE_DISABLE_AUTOUPDATE=1 \
                NPM_CONFIG_USERCONFIG="$stage/npm-userrc" NPM_CONFIG_GLOBALCONFIG="$stage/npm-globalrc" \
                NPM_CONFIG_REGISTRY=https://registry.npmjs.org NPM_CONFIG_CACHE="$stage/home/.cache/npm" \
                timeout --kill-after=10 600 /usr/bin/npm install --no-save --package-lock=false --prefix "$stage/runtime" \
                --cache "$stage/home/.cache/npm" --registry=https://registry.npmjs.org \
                --userconfig="$stage/npm-userrc" --globalconfig="$stage/npm-globalrc" \
                --ignore-scripts=false --no-audit --no-fund --include=optional \
                --fetch-retries=2 --fetch-timeout=60000 "opencode-ai@$OPENCODE_VERSION" \
                > "$stage/npm.log" 2>&1
        ) || die 'npm install failed or timed out; existing runtime preserved'
        # Local npm mode keeps vendor fallback children local too. Preserve the
        # public bin path with a relative link that survives runtime promotion.
        mkdir -- "$stage/runtime/bin"
        ln -s -- ../node_modules/.bin/opencode "$stage/runtime/bin/opencode"
        verify_runtime "$stage/runtime" "$stage/home" > "$stage/verify.log" 2>&1 || die 'staged runtime verification failed; existing runtime preserved'
        [[ ! -e "$OPENCODE_PREFIX" ]] || mv -- "$OPENCODE_PREFIX" "$stage/previous"
        if ! mv -- "$stage/runtime" "$OPENCODE_PREFIX"; then
            [[ ! -e "$stage/previous" ]] || mv -- "$stage/previous" "$OPENCODE_PREFIX"
            die 'runtime promotion failed; inspect stage before retry'
        fi
        if ! verify_runtime "$OPENCODE_PREFIX" "$stage/home" >> "$stage/verify.log" 2>&1; then
            mv -- "$OPENCODE_PREFIX" "$stage/failed-runtime"
            [[ ! -e "$stage/previous" ]] || mv -- "$stage/previous" "$OPENCODE_PREFIX"
            die 'promoted runtime verification failed; previous runtime restored if present'
        fi
    fi
    trap - EXIT
    rm -rf -- "$stage" || printf 'Installed; staging cleanup incomplete: %s\n' "$stage" >&2
    printf 'OpenCode %s installed or reused; run initialize-home separately. No service action.\n' "$OPENCODE_VERSION"
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    load_contract
    case "${1:-}" in
        install) [[ $# == 1 ]] || die 'unexpected arguments'; install_runtime ;;
        initialize-home) [[ $# == 1 ]] || die 'unexpected arguments'; deployment_lock; initialize_home ;;
        *) die 'usage: entrypoint.sh install | initialize-home' ;;
    esac
fi
