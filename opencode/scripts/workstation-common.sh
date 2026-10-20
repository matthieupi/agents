# Sourced only by local workstation wrappers, never by managed services.
WORKSTATION_UID="$(id -u)"
WORKSTATION_GID="$(id -g)"

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
