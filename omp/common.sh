#!/bin/bash
# OMP-local lifecycle contract, sourced only by the two host entrypoints.
# No .env sourcing: exported inputs only. Docker Compose has its own .env loader.
set -euo pipefail

log_error() { printf '[omp] %s\n' "$*" >&2; }
die() { log_error "$@"; exit 1; }

export OMP_COMPONENT_DIR="$SCRIPT_DIR"
export OMP_IMAGE="${OMP_IMAGE:-lab/omp:latest}"
export OMP_UID="${OMP_UID:-1000}" OMP_GID="${OMP_GID:-1000}"
export OMP_NETWORK="${OMP_NETWORK:-devai-xmist}"
export OMP_MEMORY="${OMP_MEMORY:-2g}" OMP_CPUS="${OMP_CPUS:-2.0}"
export OMP_PERSONA="${OMP_PERSONA:-build}"
export OMP_STATE_DIR="${OMP_STATE_DIR:-$SCRIPT_DIR/.omp}"
export OMP_AGENT_DIR="${OMP_AGENT_DIR:-$SCRIPT_DIR/../agent}"
export SSH_DIR_PATH="${SSH_DIR_PATH:-$SCRIPT_DIR/ssh}"
export GITCONFIG_PATH="${GITCONFIG_PATH:-/dev/null}"

require_host() {
    [[ "$EUID" != 0 ]] || die 'Run wrappers as the intended developer account, not root.'
    local command
    for command in docker python3 realpath sha256sum; do
        command -v "$command" >/dev/null || die "Required command not found: $command"
    done
    [[ "$OMP_UID" =~ ^[1-9][0-9]*$ && "$OMP_GID" =~ ^[1-9][0-9]*$ ]] || die 'OMP_UID and OMP_GID must be positive decimal IDs.'
    [[ "$SCRIPT_DIR" != *,* && "$SCRIPT_DIR" != *$'\n'* ]] || die 'Unsupported comma/newline in component path.'
    [[ "$OMP_MEMORY" =~ ^[1-9][0-9]*[bBkKmMgG]?$ ]] || die 'OMP_MEMORY requires a positive integer with optional b/k/m/g suffix.'
    [[ "$OMP_CPUS" =~ ^([1-9][0-9]*(\.[0-9]+)?|0\.[0-9]*[1-9][0-9]*)$ ]] || die 'OMP_CPUS requires a positive decimal value.'
    [[ "$OMP_NETWORK" != host && "$OMP_NETWORK" != none && "$OMP_NETWORK" != container:* ]] || die 'OMP_NETWORK must be a named Docker network, not host/none/container mode.'
}

resolve_mounts() {
    local key value
    for key in OMP_STATE_DIR OMP_AGENT_DIR SSH_DIR_PATH GITCONFIG_PATH; do
        value="${!key}"
        [[ -e "$value" ]] || die "Missing $key path: $value. Prepare it explicitly; see README."
        value="$(realpath -e -- "$value")"
        # --mount uses comma-separated fields. Reject rather than misbind.
        [[ "$value" != *,* && "$value" != *$'\n'* ]] || die "Unsupported comma/newline in $key path."
        printf -v "$key" '%s' "$value"
        export "$key"
    done
    [[ -d "$OMP_STATE_DIR/agent" && -d "$OMP_AGENT_DIR" && -d "$SSH_DIR_PATH" ]] || die 'State/agent, shared resources and SSH source must be existing directories.'
    [[ -f "$GITCONFIG_PATH" || "$GITCONFIG_PATH" == /dev/null ]] || die 'GITCONFIG_PATH must be a file or /dev/null.'
    [[ -f "$SCRIPT_DIR/init.sh" ]] || die 'Missing init.sh.'
    local legacy
    legacy="$(realpath -m -- "$SCRIPT_DIR/../pi/.pi")"
    [[ "$OMP_STATE_DIR" != "$legacy" && "$OMP_STATE_DIR" != "$legacy/"* && "$legacy" != "$OMP_STATE_DIR/"* ]] || die 'OMP state must not overlap legacy Pi state.'
    [[ "$OMP_STATE_DIR" != / && "$OMP_STATE_DIR" != "$OMP_AGENT_DIR" && "$OMP_STATE_DIR" != "$OMP_AGENT_DIR/"* && "$OMP_AGENT_DIR" != "$OMP_STATE_DIR/"* ]] || die 'OMP private state must not overlap shared resources.'
}

workspace_container_name() {
    local basename hash
    basename="${1##*/}"
    basename="${basename//[^a-zA-Z0-9_.-]/-}"
    hash="$(printf '%s' "$1" | sha256sum)"
    printf 'omp-%s-%s\n' "${basename:0:40}" "${hash:0:16}"
}

owned_container_ids() {
    docker container ls -aq \
        --filter label=dev.xmist.agents.component=omp \
        --filter "label=dev.xmist.agents.owner=$SCRIPT_DIR" "$@"
}

require_owned_container() {
    [[ "${1:-}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || die 'Expected one container name or ID, not options.'
    # Return an immutable ID, never operate on a name after inspecting it.
    docker container inspect "$1" | python3 "$SCRIPT_DIR/container-contract.py" owned
}

validate_existing_container() {
    local id="$1"
    export OMP_EXPECTED_IMAGE_ID
    OMP_EXPECTED_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$OMP_IMAGE")" || die "Build the image first: $SCRIPT_DIR/omp build"
    if ! docker container inspect "$id" | python3 "$SCRIPT_DIR/container-contract.py" reuse; then
        log_error "Refusing reuse. After draining sessions: $SCRIPT_DIR/omp stop $id; $SCRIPT_DIR/omp remove $id; then relaunch the workspace. Bind state is retained."
        return 1
    fi
}

exec_agent() {
    local id="$1"
    shift
    local -a terminal=(-i)
    [[ ! -t 0 || ! -t 1 ]] || terminal+=(-t)
    exec docker exec "${terminal[@]}" --workdir /workspace "$id" \
        bash -c '/opt/harness/init.sh && exec /usr/local/bin/omp "$@"' omp "$@"
}
