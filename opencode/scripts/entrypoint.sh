#!/usr/bin/env bash
# Installer helper shared by native Compose image builds. No native service lifecycle.
set -euo pipefail

die() { printf 'opencode: %s\n' "$*" >&2; exit 1; }

require_opencode_user() {
    [[ $EUID != 0 && $UID != 0 ]] || die 'never root; run explicitly as OPENCODE_USER'
    [[ $EUID == "${OPENCODE_UID:-}" && $UID == "$EUID" ]] || die 'run explicitly as OPENCODE_USER (exact account UID required)'
}

load_contract() {
    : "${OPENCODE_USER:?supply an existing non-root account}"
    local record password gecos shell
    record=$(getent passwd "$OPENCODE_USER") || die 'account does not exist'
    IFS=: read -r OPENCODE_ACCOUNT password OPENCODE_UID OPENCODE_GID gecos OPENCODE_HOME shell <<< "$record"
    [[ "$OPENCODE_UID" =~ ^[0-9]+$ && "$OPENCODE_ACCOUNT" == "$OPENCODE_USER" ]] || die 'named non-root account required'
    require_opencode_user
    export OPENCODE_REPO="${OPENCODE_REPO:-/srv/agents}"
    export OPENCODE_ROOT="${OPENCODE_ROOT:-$OPENCODE_REPO/opencode}"
    export OPENCODE_PREFIX="${OPENCODE_PREFIX:-$OPENCODE_ROOT/.runtime}"
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
    exec 8<"$OPENCODE_REPO/agent"
    flock -x 8
    exec 7<"$HOME"
    flock -x 7
    node "$OPENCODE_ROOT/scripts/publish-plugins.mjs" config \
        "$OPENCODE_ROOT/.opencode/config" "$OPENCODE_REPO/agent" "$OPENCODE_CONFIG_DIR"
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
    local prefix="$1" home="$2" expected="${3:-}" version metadata
    [[ -x "$prefix/bin/opencode" ]] || return 1
    metadata=$(env -i HOME="$home" PATH=/usr/bin:/bin timeout --kill-after=10 30 /usr/bin/node -e '
        const p=require(process.argv[1]+"/node_modules/@opencode/cli/package.json");
        if(p.name!=="@opencode/cli" || !/^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.test(p.version) || Number(p.version.split(".")[0])<2) process.exit(1);
        console.log(p.version);
        ' "$prefix") || return 1
    [[ -z "$expected" || "$metadata" == "$expected" ]] || return 1
    version=$(isolated_runtime "$prefix" "$home" --version) || return 1
    version=${version#opencode v}
    [[ "$version" == "$metadata" ]]
)

install_runtime() (
    deployment_lock
    [[ "$OPENCODE_PREFIX" == "$OPENCODE_ROOT/.runtime" && "$OPENCODE_PREFIX" == "$(realpath -m -- "$OPENCODE_PREFIX")" ]] || die 'preserved redirected runtime prefix; reconcile manually'
    umask 077
    local stage resolved
    stage=$(mktemp -d "$OPENCODE_ROOT/.build.XXXXXXXX")
    trap 'printf "Install failed; inspect retained stage: %s\n" "$stage" >&2' EXIT
    mkdir -- "$stage/home"
    : > "$stage/npm-userrc"
    : > "$stage/npm-globalrc"
    # Explicit install resolves latest, never reuses an unverified/obsolete tag.
    mkdir -- "$stage/runtime"
    # npm 11+ requires project-scoped lifecycle approval.
    printf '%s\n' '{"private":true,"allowScripts":{"@opencode/cli":true}}' > "$stage/runtime/package.json"
    (
        cd -- "$stage/home"
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
            --fetch-retries=2 --fetch-timeout=60000 "@opencode/cli@latest" \
            > "$stage/npm.log" 2>&1
    ) || die 'npm install failed or timed out; existing runtime preserved'
    mkdir -- "$stage/runtime/bin"
    ln -s -- ../node_modules/.bin/opencode "$stage/runtime/bin/opencode"
    verify_runtime "$stage/runtime" "$stage/home" > "$stage/verify.log" 2>&1 || die 'staged runtime verification failed; existing runtime preserved'
    resolved=$(isolated_runtime "$stage/runtime" "$stage/home" --version)
    resolved=${resolved#opencode v}
    printf '{"package":"@opencode/cli","requested":"latest","version":"%s"}\n' "$resolved" > "$stage/runtime/.native-install.json"
    [[ ! -e "$OPENCODE_PREFIX" ]] || mv -- "$OPENCODE_PREFIX" "$stage/previous"
    if ! mv -- "$stage/runtime" "$OPENCODE_PREFIX"; then
        [[ ! -e "$stage/previous" ]] || mv -- "$stage/previous" "$OPENCODE_PREFIX"
        die 'runtime promotion failed; inspect stage before retry'
    fi
    if ! verify_runtime "$OPENCODE_PREFIX" "$stage/home" "$resolved" >> "$stage/verify.log" 2>&1; then
        mv -- "$OPENCODE_PREFIX" "$stage/failed-runtime"
        [[ ! -e "$stage/previous" ]] || mv -- "$stage/previous" "$OPENCODE_PREFIX"
        die 'promoted runtime verification failed; previous runtime restored if present'
    fi
    trap - EXIT
    rm -rf -- "$stage" || printf 'Installed; staging cleanup incomplete: %s\n' "$stage" >&2
    printf 'OpenCode %s installed from @opencode/cli@latest; run initialize-home separately. No service action.\n' "$resolved"
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    load_contract
    case "${1:-}" in
        install) [[ $# == 1 ]] || die 'unexpected arguments'; install_runtime ;;
        initialize-home) [[ $# == 1 ]] || die 'unexpected arguments'; deployment_lock; initialize_home ;;
        *) die 'usage: entrypoint.sh install | initialize-home' ;;
    esac
fi
