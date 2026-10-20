# Sourced only by local workstation wrappers, never by managed services.
WORKSTATION_UID="$(id -u)"
WORKSTATION_GID="$(id -g)"
WORKSTATION_OWNER="$(printf '%s\0%s' "$SCRIPT_DIR" "$WORKSTATION_UID" | sha256sum | cut -d' ' -f1)"

workstation_owned() {
    local labels
    # Reject Compose label presence, even if a label's value is empty.
    labels="$(docker inspect --format '{{ index .Config.Labels "dev.xmist.opencode.workstation" }}|{{range $key, $value := .Config.Labels}}{{if or (eq $key "com.docker.compose.project") (eq $key "com.docker.compose.service")}}compose{{end}}{{end}}' "$1")" || return 1
    [[ "$labels" == "$WORKSTATION_OWNER|" ]]
}

workstation_ids() {
    local ids container
    ids="$(docker ps "$@" --filter "label=dev.xmist.opencode.workstation=$WORKSTATION_OWNER")" || return 1
    for container in $ids; do
        if workstation_owned "$container"; then
            printf '%s\n' "$container"
        fi
    done
}

workstation_local() {
    [[ "$WORKSTATION_UID" != 0 ]] || { log_error 'Run as the local non-root user, not sudo/root'; return 1; }
    local endpoint
    if [[ -n "${DOCKER_CONTEXT:-}" || -z "${DOCKER_HOST:-}" ]]; then
        endpoint="$(docker context inspect --format '{{.Endpoints.docker.Host}}' "${DOCKER_CONTEXT:-$(docker context show)}")" || return 1
    else
        endpoint="$DOCKER_HOST"
    fi
    [[ "$endpoint" == unix:///* ]] || { log_error 'Workstation binds require a local Unix-socket Docker daemon'; return 1; }
}
