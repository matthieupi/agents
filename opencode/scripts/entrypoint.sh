#!/usr/bin/env bash
set -euo pipefail

die() { printf 'opencode: %s\n' "$*" >&2; exit 1; }

load_contract() {
    export OPENCODE_ROOT="${OPENCODE_ROOT:-/srv/opencode}"
    export OPENCODE_REPO="${OPENCODE_REPO:-$OPENCODE_ROOT/repo}"
    export OPENCODE_PREFIX="${OPENCODE_PREFIX:-$OPENCODE_ROOT/runtime}"
    : "${OPENCODE_USER:?supply an existing non-root account}"
    local record password gecos shell
    record=$(getent passwd "$OPENCODE_USER") || die 'account does not exist'
    IFS=: read -r OPENCODE_ACCOUNT password OPENCODE_UID OPENCODE_GID gecos OPENCODE_HOME shell <<< "$record"
    [[ "$OPENCODE_UID" != 0 && "$OPENCODE_ACCOUNT" == "$OPENCODE_USER" ]] || die 'named non-root account required'
    local path
    for path in "$OPENCODE_ROOT" "$OPENCODE_REPO" "$OPENCODE_PREFIX" "$OPENCODE_HOME"; do
        [[ "$path" == /* && "$path" != / && "$path" != /opt && "$path" != /opt/* && "$path" == "$(realpath -m -- "$path")" ]] || die 'paths must be canonical absolute paths outside /opt'
    done
    [[ "$OPENCODE_PREFIX/" != "$OPENCODE_REPO/"* && "$OPENCODE_REPO/" != "$OPENCODE_PREFIX/"* ]] || die 'checkout and runtime must not overlap'
    [[ -d "$OPENCODE_HOME" ]] || die 'account home must already exist'
    [[ "$(stat -c %u -- "$OPENCODE_HOME")" == "$OPENCODE_UID" ]] || die 'account must own its home'
    export OPENCODE_CONFIG_DIR="$OPENCODE_HOME/.config/opencode"
    export OPENCODE_DISABLE_AUTOUPDATE=1
    export OPENCODE_UNIT="${OPENCODE_UNIT:-opencode.service}"
    [[ "$OPENCODE_UNIT" =~ ^[a-zA-Z0-9_-]+\.service$ ]] || die 'invalid unit name'
}

require_root() { [[ $EUID == 0 ]] || die 'administrator/root execution required; no automatic sudo'; }

# Check ancestors too: an unprivileged user must not be able to replace a deployment.
trusted_path() {
    local path="$1" owner mode
    while :; do
        [[ ! -L "$path" ]] || die "symlink in deployment path: $path"
        if [[ -e "$path" ]]; then
            read -r owner mode < <(stat -c '%u %a' -- "$path")
            [[ "$owner" == 0 ]] && (( (8#$mode & 8#022) == 0 )) || die "deployment path is not root-owned/private: $path"
        fi
        [[ "$path" != / ]] || break
        path=$(dirname -- "$path")
    done
}

deployment_lock() {
    require_root
    trusted_path "$OPENCODE_ROOT"
    trusted_path "$OPENCODE_REPO"
    trusted_path "$OPENCODE_PREFIX"
    [[ -d "$OPENCODE_ROOT" && -d "$OPENCODE_REPO/.git" ]] || die 'provision a dedicated root-owned Git checkout first'
    local unsafe
    unsafe=$(find "$OPENCODE_REPO" -xdev \( ! -user root -o \( ! -type l -perm /022 \) \) -print -quit)
    [[ -z "$unsafe" ]] || die 'checkout contains non-root-owned or group/world-writable entries'
    if [[ -d "$OPENCODE_PREFIX" ]]; then
        unsafe=$(find "$OPENCODE_PREFIX" -xdev \( ! -user root -o \( ! -type l -perm /022 \) \) -print -quit)
        [[ -z "$unsafe" ]] || die 'runtime contains non-root-owned or group/world-writable entries'
    fi
    trusted_path "$OPENCODE_ROOT/.lifecycle.lock"
    exec 9>"$OPENCODE_ROOT/.lifecycle.lock"
    flock -n 9 || die 'another lifecycle operation is running'
}

initialize_home() (
    [[ $EUID == "$OPENCODE_UID" && $EUID != 0 ]] || die 'home initialization must run as the supplied account'
    export HOME="$OPENCODE_HOME"
    umask 077
    [[ ! -L "$HOME/.config" && ! -L "$OPENCODE_CONFIG_DIR" ]] || die 'native config must not redirect to Docker or another config tree'
    git -c safe.directory="$OPENCODE_REPO" -C "$OPENCODE_REPO" rev-parse --verify HEAD >/dev/null
    mkdir -p "$OPENCODE_CONFIG_DIR" "$HOME/.local/share/opencode" "$HOME/.cache/opencode"
    local name destination source legacy file relative parent tracked pending=''
    for name in commands skills system gsd; do
        source="$OPENCODE_REPO/agent/$name"
        destination="$OPENCODE_CONFIG_DIR/$name"
        [[ -d "$source" ]] || die "missing shared resource: $name"
        if [[ -e "$destination" || -L "$destination" ]]; then
            [[ -L "$destination" && "$(readlink -- "$destination")" == "$source" ]] || die "preserved conflicting resource; reconcile manually: $destination"
        else
            ln -s -- "$source" "$destination"
        fi
        legacy="$HOME/.agents/$name"
        if [[ -L "$legacy" && "$(realpath -m -- "$legacy")" == "$source" ]]; then
            rm -- "$legacy"
        elif [[ -e "$legacy" || -L "$legacy" ]]; then
            die "preserved external discovery tree; reconcile duplicate resources manually: $legacy"
        fi
    done
    # Capture first: process-substitution failures would otherwise be silently ignored.
    tracked=$(mktemp)
    trap 'rm -f -- "$tracked" "$pending"' EXIT
    git -c safe.directory="$OPENCODE_REPO" -C "$OPENCODE_REPO" ls-files -z -- opencode/.opencode/config > "$tracked" || die 'cannot list tracked defaults'
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
        git -c safe.directory="$OPENCODE_REPO" -C "$OPENCODE_REPO" show "HEAD:$file" > "$pending"
        # Publish a complete file exclusively; never replace concurrent user content.
        if ! ln -T -- "$pending" "$destination"; then
            [[ -e "$destination" || -L "$destination" ]] || die "cannot publish default: $destination"
        fi
        rm -f -- "$pending"
    done < "$tracked"
)

provision() (
    deployment_lock
    umask 022
    : "${OPENCODE_APT_PACKAGES:?supply whitespace-separated package=version pins}"
    : "${OPENCODE_VERSION:?supply an exact OpenCode version, e.g. 1.2.15}"
    [[ "$OPENCODE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die 'OpenCode version must be an exact stable version'
    local -a packages
    local package required state installed_version
    [[ "$OPENCODE_APT_PACKAGES" != *$'\n'* ]] || die 'apt pins must be a single line'
    read -r -a packages <<< "$OPENCODE_APT_PACKAGES"
    for package in "${packages[@]}"; do
        [[ "$package" =~ ^[a-z0-9][a-z0-9+.-]*=[a-zA-Z0-9.+:~_-]+$ ]] || die 'every apt package must have an exact version'
    done
    for required in ca-certificates git nodejs npm ripgrep python3 python3-venv openssh-client; do
        [[ " ${packages[*]} " == *" $required="* ]] || die "missing required apt pin: $required"
    done
    state=$(systemctl show --property=ActiveState --value "$OPENCODE_UNIT")
    [[ "$state" == inactive || "$state" == failed ]] || die 'unit must be inactive before provisioning (install the unit first)'
    export DEBIAN_FRONTEND=noninteractive
    timeout 600 apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update
    timeout 600 apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 \
        install -y --no-install-recommends -- "${packages[@]}"
    install -d -o root -g root -m 0755 "$OPENCODE_PREFIX"
    # Use a root-only npm environment; do not load a workspace or account .npmrc.
    local cache
    cache=$(mktemp -d "$OPENCODE_ROOT/.npm.XXXXXXXX")
    trap 'rm -rf -- "$cache"' EXIT
    (
        cd "$cache"
        timeout 600 env -i HOME="$cache" PATH=/usr/bin:/bin npm install --global \
            --prefix "$OPENCODE_PREFIX" --cache "$cache/cache" \
            --registry=https://registry.npmjs.org --userconfig=/dev/null --globalconfig=/dev/null \
            --ignore-scripts --no-audit --no-fund --include=optional \
            --fetch-retries=2 --fetch-timeout=60000 "opencode-ai@$OPENCODE_VERSION"
    )
    rm -rf -- "$cache"
    trap - EXIT
    runuser -u "$OPENCODE_USER" -- env -i HOME="$OPENCODE_HOME" USER="$OPENCODE_USER" \
        PATH="$OPENCODE_PREFIX/bin:/usr/bin:/bin" OPENCODE_USER="$OPENCODE_USER" \
        OPENCODE_ROOT="$OPENCODE_ROOT" OPENCODE_REPO="$OPENCODE_REPO" OPENCODE_PREFIX="$OPENCODE_PREFIX" \
        /bin/bash "$OPENCODE_REPO/opencode/scripts/entrypoint.sh" initialize-home
    installed_version=$(runuser -u "$OPENCODE_USER" -- env -i HOME="$OPENCODE_HOME" PATH="$OPENCODE_PREFIX/bin:/usr/bin:/bin" \
        OPENCODE_DISABLE_AUTOUPDATE=1 "$OPENCODE_PREFIX/bin/opencode" --version)
    [[ "$installed_version" == "$OPENCODE_VERSION" ]] || die 'installed CLI does not match the requested version'
    printf 'OpenCode %s provisioned; unit remains stopped.\n' "$installed_version"
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    load_contract
    case "${1:-}" in
        provision) [[ $# == 1 ]] || die 'usage: entrypoint.sh provision'; provision ;;
        initialize-home) [[ $# == 1 ]] || die 'unexpected arguments'; initialize_home ;;
        *) die 'usage: entrypoint.sh provision' ;;
    esac
fi
