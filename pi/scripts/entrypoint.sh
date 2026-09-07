#!/usr/bin/env bash
set -euo pipefail

# Reviewed together: pi-web embeds this exact Pi SDK version.
readonly PI_VERSION=0.85.1 PI_UI_VERSION=0.9.0

die() { printf 'pi: %s\n' "$*" >&2; exit 1; }
require_root() { [[ $EUID == 0 ]] || die 'administrator/root required; no automatic sudo'; }

load_contract() {
    export PI_ROOT="${PI_ROOT:-/srv/pi}" PI_UNIT="${PI_UNIT:-pi.service}"
    export PI_REPO="${PI_REPO:-$PI_ROOT/repo}" PI_PREFIX="${PI_PREFIX:-$PI_ROOT/runtime}"
    : "${PI_USER:?supply an existing named non-root account}"
    local record account password gecos shell path
    record=$(getent passwd "$PI_USER") || die 'account does not exist'
    IFS=: read -r account password PI_UID PI_GID gecos PI_HOME shell <<< "$record"
    [[ "$account" == "$PI_USER" && "$PI_UID" =~ ^[0-9]+$ && "$PI_UID" != 0 ]] || die 'named non-root account required'
    for path in "$PI_ROOT" "$PI_REPO" "$PI_PREFIX" "$PI_HOME"; do
        [[ "$path" == /* && "$path" != / && "$path" != /opt && "$path" != /opt/* && "$path" == "$(realpath -m -- "$path")" ]] || die 'paths must be canonical absolute paths outside /opt'
    done
    [[ "$PI_REPO/" == "$PI_ROOT/"* && "$PI_PREFIX/" == "$PI_ROOT/"* ]] || die 'checkout/runtime must be below PI_ROOT'
    [[ "$PI_PREFIX/" != "$PI_REPO/"* && "$PI_REPO/" != "$PI_PREFIX/"* ]] || die 'checkout/runtime must not overlap'
    [[ "$PI_HOME/" != "$PI_ROOT/"* && "$PI_ROOT/" != "$PI_HOME/"* ]] || die 'home and deployment must not overlap'
    [[ -d "$PI_HOME" && "$(stat -c %u -- "$PI_HOME")" == "$PI_UID" ]] || die 'account must own its existing home'
    [[ "$PI_UNIT" =~ ^[a-zA-Z0-9_-]+\.service$ ]] || die 'invalid unit name'
    export PI_HOME PI_CODING_AGENT_DIR="$PI_HOME/.pi/agent"
}

trusted_path() {
    local path="$1" owner mode
    while :; do
        [[ ! -L "$path" ]] || die "symlink in deployment path: $path"
        if [[ -e "$path" ]]; then
            read -r owner mode < <(stat -c '%u %a' -- "$path")
            [[ "$owner" == 0 ]] && (( (8#$mode & 8#022) == 0 )) || die "deployment path is not root-owned/non-writable: $path"
        fi
        [[ "$path" != / ]] || break
        path=$(dirname -- "$path")
    done
}

deployment_lock() {
    require_root
    local path unsafe
    for path in "$PI_ROOT" "$PI_REPO" "$PI_PREFIX" "$PI_ROOT/.lifecycle.lock"; do trusted_path "$path"; done
    [[ -d "$PI_REPO/.git" ]] || die 'supply a dedicated root-owned agents Git checkout (not the infrastructure repo)'
    for path in "$PI_REPO" "$PI_PREFIX"; do
        [[ -e "$path" ]] || continue
        unsafe=$(find "$path" -xdev \( ! -user root -o \( ! -type l -perm /022 \) \) -print -quit)
        [[ -z "$unsafe" ]] || die 'checkout/runtime contains untrusted ownership or writable entries'
    done
    exec 9>"$PI_ROOT/.lifecycle.lock"
    flock -n 9 || die 'another lifecycle operation is running'
}

require_stopped() {
    local state
    state=$(systemctl show --property=ActiveState --value "$PI_UNIT")
    [[ "$state" == inactive || "$state" == failed ]] || die 'stop the Ansible-managed unit before provisioning/updating'
}

require_clean_checkout() {
    local status
    status=$(git -C "$PI_REPO" status --porcelain --untracked-files=all --ignored) || die 'cannot inspect checkout status'
    [[ -z "$status" ]] || die 'checkout is dirty (including ignored state); preserve and reconcile first'
}

initialize_home() (
    [[ $EUID != 0 && $EUID == "$PI_UID" ]] || die 'initialize-home must run as PI_USER'
    export HOME="$PI_HOME"
    umask 077
    local name source destination tracked file relative parent pending=''
    for name in "$HOME/.pi" "$PI_CODING_AGENT_DIR"; do
        [[ ! -L "$name" ]] || die 'preserved redirected Pi state; reconcile manually'
    done
    mkdir -p -- "$PI_CODING_AGENT_DIR"
    for name in agents prompts skills; do
        source="$PI_REPO/agent/$name"
        [[ "$name" != agents ]] || source="$PI_REPO/agent"
        [[ -d "$source" ]] || die "missing shared resource: $source"
        destination="$PI_CODING_AGENT_DIR/$name"
        if [[ -e "$destination" || -L "$destination" ]]; then
            [[ -L "$destination" && "$(readlink -- "$destination")" == "$source" ]] || die "preserved conflicting resource: $destination"
        else
            ln -s -- "$source" "$destination"
        fi
    done
    # Seed only tracked presentation defaults. Never copy auth, sessions, OMP
    # databases/config, models with Docker endpoints, ignored files or npm state.
    tracked=$(mktemp)
    trap 'rm -f -- "$tracked" "$pending"' EXIT
    git -c safe.directory="$PI_REPO" -C "$PI_REPO" ls-files -z -- pi/.pi/agent > "$tracked"
    while IFS= read -r -d '' file; do
        relative=${file#pi/.pi/agent/}
        case "$relative" in settings.json|extensions/*.ts|extension-library/*.ts|themes/*.json) ;; *) continue ;; esac
        case "/$relative/" in */node_modules/*|*/.git/*) continue ;; esac
        destination="$PI_CODING_AGENT_DIR/$relative"
        [[ ! -e "$destination" && ! -L "$destination" ]] || continue
        parent=$(dirname -- "$destination")
        [[ "$parent" == "$(realpath -m -- "$parent")" ]] || die "preserved redirected defaults directory: $parent"
        mkdir -p -- "$parent"
        pending=$(mktemp "$parent/.pi-default.XXXXXXXX")
        git -c safe.directory="$PI_REPO" -C "$PI_REPO" show "HEAD:$file" > "$pending"
        mv -n -- "$pending" "$destination"
        rm -f -- "$pending"
    done < "$tracked"
)

verify_runtime() (
    local prefix="$1" version
    [[ -x "$prefix/bin/pi" && -x "$prefix/bin/pi-web" ]] || return 1
    cd -- "$prefix"
    runuser -u "$PI_USER" -- env -i HOME="$PI_HOME" PATH="$prefix/bin:/usr/bin:/bin" \
        /usr/bin/node -e '
        const {createRequire}=require("node:module");
        const root=process.argv[1]+"/lib/node_modules/";
        for(const [name,version] of [["@earendil-works/pi-coding-agent",process.argv[2]],["@agegr/pi-web",process.argv[3]]]) {
          if(require(root+name+"/package.json").version!==version) throw Error("installed version mismatch");
        }
        createRequire(root+"@agegr/pi-web/package.json")("node-pty");
        ' "$prefix" "$PI_VERSION" "$PI_UI_VERSION" || return 1
    version=$(runuser -u "$PI_USER" -- env -i HOME="$PI_HOME" PATH="$prefix/bin:/usr/bin:/bin" "$prefix/bin/pi" --version) || return 1
    [[ "$version" == "$PI_VERSION" ]] || return 1
    runuser -u "$PI_USER" -- env -i HOME="$PI_HOME" PATH="$prefix/bin:/usr/bin:/bin" "$prefix/bin/pi-web" --help >/dev/null
)

provision() (
    deployment_lock
    require_stopped
    require_clean_checkout
    umask 022
    : "${PI_APT_PACKAGES:?supply whitespace-separated package=version pins from inventory}"
    local -a packages
    local package required stage record account password build_uid build_gid rest npm_owner node_pin
    : "${PI_BUILD_USER:?supply a separate existing unprivileged build account without credentials}"
    record=$(getent passwd "$PI_BUILD_USER") || die 'build account does not exist'
    IFS=: read -r account password build_uid build_gid rest <<< "$record"
    [[ "$account" == "$PI_BUILD_USER" && "$build_uid" =~ ^[0-9]+$ && "$build_uid" != 0 && "$build_uid" != "$PI_UID" ]] || die 'build account must be non-root and distinct from PI_USER'
    [[ "$PI_APT_PACKAGES" != *$'\n'* ]] || die 'apt pins must be a single line'
    read -r -a packages <<< "$PI_APT_PACKAGES"
    for package in "${packages[@]}"; do
        [[ "$package" =~ ^[a-z0-9][a-z0-9+.-]*=[a-zA-Z0-9.+:~_-]+$ ]] || die 'every apt package needs an exact version'
    done
    for required in ca-certificates git nodejs ripgrep python3 openssh-client build-essential; do
        [[ " ${packages[*]} " == *" $required="* ]] || die "missing required apt pin: $required"
    done
    export DEBIAN_FRONTEND=noninteractive
    timeout 600 apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update
    timeout 600 apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends -- "${packages[@]}"
    env -i PATH=/usr/bin:/bin /usr/bin/node -e 'const [a,b]=process.versions.node.split(".").map(Number); if(a<22 || (a===22 && b<19)) process.exit(1)' || die 'pinned system Node must be >=22.19.0'
    if [[ " ${packages[*]} " != *" npm="* ]]; then
        # NodeSource bundles npm and conflicts with the separate distro package.
        npm_owner=$(dpkg-query -S /usr/bin/npm) || die 'bundled /usr/bin/npm must be owned by pinned nodejs'
        [[ "$npm_owner" =~ ^nodejs(:[a-z0-9-]+)?:\ /usr/bin/npm$ ]] || die 'bundled /usr/bin/npm must be owned by pinned nodejs'
        for package in "${packages[@]}"; do
            [[ "$package" != nodejs=* ]] || node_pin=${package#nodejs=}
        done
        record=$(dpkg-query -W -f='${Status} ${Version}' nodejs) || die 'cannot inspect installed nodejs package'
        [[ "$record" == "install ok installed $node_pin" ]] || die 'bundled npm requires the exact pinned nodejs version installed'
    fi
    env -i PATH=/usr/bin:/bin /usr/bin/npm --version >/dev/null || die 'system /usr/bin/npm must be usable'
    if ! verify_runtime "$PI_PREFIX" >/dev/null 2>&1; then
        stage=$(mktemp -d "$PI_ROOT/.build.XXXXXXXX")
        chmod 0711 "$stage"
        # Keep a failed stage (including previous runtime if promotion failed).
        # This is diagnostic evidence, not an automatic rollback mechanism.
        trap 'printf "Provision failed; inspect retained stage: %s\\n" "$stage" >&2' EXIT
        install -d -o "$build_uid" -g "$build_gid" -m 0700 "$stage/home"
        install -d -o "$build_uid" -g "$build_gid" -m 0755 "$stage/runtime"
        # npm rejects loading the same path as both user and global config.
        # Keep this empty global config outside build-writable directories.
        install -o root -g root -m 0644 /dev/null "$stage/npm-globalrc"
        (
            cd -- "$stage/home"
            # node-pty builds on Linux. All npm/dependency lifecycle code runs as
            # a separate non-root account, not a sandbox. Dependency code remains
            # trusted supply-chain input; runuser does not contain child processes.
            timeout 600 runuser -u "$PI_BUILD_USER" -- env -i HOME="$stage/home" PATH=/usr/bin:/bin \
                /usr/bin/npm install --global --prefix "$stage/runtime" --cache "$stage/home/cache" \
                --registry=https://registry.npmjs.org --userconfig=/dev/null --globalconfig="$stage/npm-globalrc" \
                --ignore-scripts=false --no-audit --no-fund --include=optional \
                --fetch-retries=2 --fetch-timeout=60000 \
                "@earendil-works/pi-coding-agent@$PI_VERSION" "@agegr/pi-web@$PI_UI_VERSION"
        )
        chown -hR root:root "$stage/runtime"
        chmod -R go-w "$stage/runtime"
        verify_runtime "$stage/runtime" || die 'staged runtime verification failed; runtime not promoted'
        [[ ! -e "$PI_PREFIX" ]] || mv -- "$PI_PREFIX" "$stage/previous"
        mv -- "$stage/runtime" "$PI_PREFIX"
        trap - EXIT
        rm -rf -- "$stage"
    fi
    runuser -u "$PI_USER" -- env -i HOME="$PI_HOME" PATH="$PI_PREFIX/bin:/usr/bin:/bin" \
        PI_USER="$PI_USER" PI_ROOT="$PI_ROOT" PI_REPO="$PI_REPO" PI_PREFIX="$PI_PREFIX" PI_UNIT="$PI_UNIT" \
        /bin/bash "$PI_REPO/pi/scripts/entrypoint.sh" initialize-home
    verify_runtime "$PI_PREFIX" || die 'runtime verification failed; unit stays stopped'
    printf 'Pi %s / pi-web %s provisioned. Unit remains stopped; native execution is LOCAL.\n' "$PI_VERSION" "$PI_UI_VERSION"
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    load_contract
    [[ $# == 1 ]] || die 'usage: entrypoint.sh provision | initialize-home'
    case "$1" in
        provision) provision ;;
        initialize-home) initialize_home ;;
        *) die 'usage: entrypoint.sh provision | initialize-home' ;;
    esac
fi
