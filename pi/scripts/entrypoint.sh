#!/usr/bin/env bash
set -euo pipefail

# Reviewed together: pi-web embeds this exact Pi SDK version.
readonly PI_VERSION=0.85.1 PI_UI_VERSION=0.9.0

die() { printf 'pi: %s\n' "$*" >&2; exit 1; }
require_pi_user() {
    [[ $EUID != 0 && $UID != 0 ]] || die 'never root; run explicitly as PI_USER'
    [[ $EUID == "${PI_UID:-}" && $UID == "$EUID" ]] || die 'run explicitly as PI_USER (exact account UID required)'
}

load_contract() {
    [[ $EUID != 0 && $UID != 0 ]] || die 'never root; run explicitly as PI_USER'
    export PI_REPO="${PI_REPO:-/srv/agents}"
    export PI_ROOT="${PI_ROOT:-$PI_REPO/pi}" PI_UNIT="${PI_UNIT:-pi.service}"
    export PI_PREFIX="${PI_PREFIX:-$PI_ROOT/.runtime}"
    : "${PI_USER:?supply an existing named non-root account}"
    local record account password gecos shell path
    record=$(getent passwd "$PI_USER") || die 'account does not exist'
    IFS=: read -r account password PI_UID PI_GID gecos PI_HOME shell <<< "$record"
    [[ "$account" == "$PI_USER" && "$PI_UID" =~ ^[0-9]+$ && "$PI_UID" != 0 ]] || die 'named non-root account required'
    require_pi_user
    for path in "$PI_ROOT" "$PI_REPO" "$PI_PREFIX" "$PI_HOME"; do
        [[ "$path" == /* && "$path" != / && "$path" != /opt && "$path" != /opt/* && "$path" == "$(realpath -m -- "$path")" ]] || die 'paths must be canonical absolute paths outside /opt'
    done
    [[ "$PI_ROOT" == "$PI_REPO/pi" && "$PI_PREFIX" == "$PI_ROOT/.runtime" ]] || die 'require PI_ROOT=PI_REPO/pi and PI_PREFIX=PI_ROOT/.runtime'
    [[ "$PI_HOME/" != "$PI_REPO/"* && "$PI_REPO/" != "$PI_HOME/"* ]] || die 'private home and checkout must not overlap'
    for path in "$PI_HOME" "$PI_REPO" "$PI_ROOT"; do
        [[ -d "$path" && "$(stat -c %u -- "$path")" == "$PI_UID" ]] || die 'PI_USER must own its existing home, checkout and component'
    done
    [[ "$PI_UNIT" =~ ^[a-zA-Z0-9_-]+\.service$ ]] || die 'invalid unit name'
    export PI_HOME PI_CODING_AGENT_DIR="$PI_HOME/.pi/agent"
    [[ "$(pi_git rev-parse --show-toplevel)" == "$PI_REPO" ]] || die 'PI_REPO must be the whole agents Git checkout'
}

deployment_lock() {
    require_pi_user
    [[ ! -L "$PI_ROOT/.lifecycle.lock" ]] || die 'preserved redirected lifecycle lock'
    exec 9>"$PI_ROOT/.lifecycle.lock"
    flock -n 9 || die 'another lifecycle operation is running'
}

pi_git() {
    require_pi_user
    env -i HOME="$PI_HOME" PATH=/usr/bin:/bin GIT_TERMINAL_PROMPT=0 \
        timeout --kill-after=10 120 /usr/bin/git -C "$PI_REPO" "$@"
}

initialize_home() (
    require_pi_user
    export HOME="$PI_HOME"
    umask 077
    local name source destination tracked file relative parent pending=''
    [[ "$PI_CODING_AGENT_DIR" == "$(realpath -m -- "$PI_CODING_AGENT_DIR")" ]] || die 'preserved redirected Pi state; reconcile manually'
    if [[ -n ${PI_PREVIOUS_REPO:-} ]]; then
        [[ "$PI_PREVIOUS_REPO" == /* && "$PI_PREVIOUS_REPO" != / && "$PI_PREVIOUS_REPO" == "$(realpath -m -- "$PI_PREVIOUS_REPO")" ]] || die 'invalid PI_PREVIOUS_REPO'
    fi
    mkdir -p -- "$PI_CODING_AGENT_DIR"
    # Reuse the container's resource importer, not its home/lifecycle setup.
    source "$PI_ROOT/init.sh"
    import_system_agents "$PI_REPO/agent" "$PI_CODING_AGENT_DIR/agents" "${PI_PREVIOUS_REPO:+$PI_PREVIOUS_REPO/agent}"
    for name in prompts skills; do
        source="$PI_REPO/agent/$name"
        [[ -d "$source" ]] || die "missing shared resource: $source"
        destination="$PI_CODING_AGENT_DIR/$name"
        if [[ -e "$destination" || -L "$destination" ]]; then
            if [[ -L "$destination" && "$(readlink -- "$destination")" == "$source" ]]; then
                continue
            elif [[ -n ${PI_PREVIOUS_REPO:-} && -L "$destination" && "$(readlink -- "$destination")" == "$PI_PREVIOUS_REPO${source#"$PI_REPO"}" ]]; then
                ln -sfnT -- "$source" "$destination"
            else
                printf 'Preserved existing resource: %s\n' "$destination" >&2
            fi
        else
            ln -s -- "$source" "$destination"
        fi
    done
    # Keep the original allowlist and copy-once defaults. No auth, sessions,
    # OMP databases/config, Docker models or ignored package state are copied.
    tracked=$(mktemp)
    trap 'rm -f -- "$tracked" "$pending"' EXIT
    pi_git ls-files -z -- pi/.pi/agent > "$tracked"
    while IFS= read -r -d '' file; do
        relative=${file#pi/.pi/agent/}
        case "$relative" in settings.json|extensions/*.ts|extension-library/*.ts|themes/*.json) ;; *) continue ;; esac
        case "/$relative/" in */node_modules/*|*/.git/*|*/../*) continue ;; esac
        destination="$PI_CODING_AGENT_DIR/$relative"
        [[ ! -e "$destination" && ! -L "$destination" ]] || continue
        parent=$(dirname -- "$destination")
        [[ "$parent" == "$(realpath -m -- "$parent")" ]] || die "preserved redirected defaults directory: $parent"
        mkdir -p -- "$parent"
        pending=$(mktemp "$parent/.pi-default.XXXXXXXX")
        pi_git show "HEAD:$file" > "$pending"
        # Publish the complete file exclusively; concurrent user files win.
        if ! ln -T -- "$pending" "$destination"; then
            [[ -e "$destination" || -L "$destination" ]] || die "cannot publish default: $destination"
        fi
        rm -f -- "$pending"
    done < "$tracked"
)

verify_runtime() (
    require_pi_user
    local prefix="$1" home="$2" version
    [[ -x "$prefix/bin/pi" && -x "$prefix/bin/pi-web" ]] || return 1
    cd -- "$home" || return 1
    env -i HOME="$home" PATH="$prefix/bin:/usr/bin:/bin" \
        timeout --kill-after=10 30 /usr/bin/node -e '
        const {createRequire}=require("node:module");
        const root=process.argv[1]+"/lib/node_modules/";
        for(const [name,version] of [["@earendil-works/pi-coding-agent",process.argv[2]],["@agegr/pi-web",process.argv[3]]]) {
          if(require(root+name+"/package.json").version!==version) throw Error("installed version mismatch");
        }
        createRequire(root+"@agegr/pi-web/package.json")("node-pty");
        ' "$prefix" "$PI_VERSION" "$PI_UI_VERSION" || return 1
    version=$(env -i HOME="$home" PATH="$prefix/bin:/usr/bin:/bin" \
        timeout --kill-after=10 30 "$prefix/bin/pi" --version) || return 1
    [[ "$version" == "$PI_VERSION" ]] || return 1
    env -i HOME="$home" PATH="$prefix/bin:/usr/bin:/bin" \
        timeout --kill-after=10 30 "$prefix/bin/pi-web" --help >/dev/null
)

install_runtime() (
    deployment_lock
    umask 077
    local stage
    stage=$(mktemp -d "$PI_ROOT/.build.XXXXXXXX")
    trap 'printf "Install failed; inspect retained stage: %s\n" "$stage" >&2' EXIT
    mkdir -- "$stage/home"
    : > "$stage/npm-userrc"
    : > "$stage/npm-globalrc"
    env -i HOME="$stage/home" PATH=/usr/bin:/bin timeout --kill-after=10 30 /usr/bin/node -e \
        'const [a,b]=process.versions.node.split(".").map(Number); if(a<22 || (a===22 && b<19)) process.exit(1)' || die 'Ansible must supply system Node >=22.19.0'
    env -i HOME="$stage/home" PATH=/usr/bin:/bin timeout --kill-after=10 30 /usr/bin/npm \
        --userconfig="$stage/npm-userrc" --globalconfig="$stage/npm-globalrc" --version >/dev/null || die 'Ansible must supply usable system npm'
    if ! verify_runtime "$PI_PREFIX" "$stage/home" >/dev/null 2>&1; then
        mkdir -- "$stage/runtime"
        (
            cd -- "$stage/home"
            # Dependency scripts run as PI_USER, never root. Empty HOME/config
            # and env exclude provider/web secrets; this is not a UID sandbox.
            env -i HOME="$stage/home" PATH=/usr/bin:/bin TMPDIR="$stage/home" \
                NPM_CONFIG_USERCONFIG="$stage/npm-userrc" NPM_CONFIG_GLOBALCONFIG="$stage/npm-globalrc" \
                timeout --kill-after=10 600 /usr/bin/npm install --global --prefix "$stage/runtime" --cache "$stage/home/cache" \
                --registry=https://registry.npmjs.org --userconfig="$stage/npm-userrc" --globalconfig="$stage/npm-globalrc" \
                --ignore-scripts=false --no-audit --no-fund --include=optional \
                --fetch-retries=2 --fetch-timeout=60000 \
                "@earendil-works/pi-coding-agent@$PI_VERSION" "@agegr/pi-web@$PI_UI_VERSION" \
                > "$stage/npm.log" 2>&1
        ) || die 'npm install failed or timed out; existing runtime preserved'
        verify_runtime "$stage/runtime" "$stage/home" > "$stage/verify.log" 2>&1 || die 'staged runtime verification failed; existing runtime preserved'
        [[ ! -e "$PI_PREFIX" ]] || mv -- "$PI_PREFIX" "$stage/previous"
        if ! mv -- "$stage/runtime" "$PI_PREFIX"; then
            [[ ! -e "$stage/previous" ]] || mv -- "$stage/previous" "$PI_PREFIX"
            die 'runtime promotion failed; inspect stage before retry'
        fi
        if ! verify_runtime "$PI_PREFIX" "$stage/home" >> "$stage/verify.log" 2>&1; then
            mv -- "$PI_PREFIX" "$stage/failed-runtime"
            [[ ! -e "$stage/previous" ]] || mv -- "$stage/previous" "$PI_PREFIX"
            die 'promoted runtime verification failed; previous runtime restored if present'
        fi
    fi
    trap - EXIT
    rm -rf -- "$stage" || printf 'Installed; staging cleanup incomplete: %s\n' "$stage" >&2
    initialize_home
    printf 'Pi %s / pi-web %s installed or reused; no service action.\n' "$PI_VERSION" "$PI_UI_VERSION"
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    load_contract
    [[ $# == 1 ]] || die 'usage: entrypoint.sh install | initialize-home'
    case "$1" in
        install) install_runtime ;;
        initialize-home) deployment_lock; initialize_home ;;
        *) die 'usage: entrypoint.sh install | initialize-home' ;;
    esac
fi
