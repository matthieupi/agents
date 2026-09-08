#!/bin/bash
set -euo pipefail
umask 077
[[ ${T3CODE_PROVIDER:-} == none ]] || {
    printf '%s\n' 'T3CODE_PROVIDER must explicitly be none; selected providers are not implemented.' >&2
    exit 64
}
[[ $# == 1 ]] || { printf '%s\n' 'Usage: provider.sh status|initialize-home|login' >&2; exit 64; }
case "$1" in
    status) printf '%s\n' 'unconfigured' ;;
    initialize-home) : ;; # No generic resource links or provider state.
    login) printf '%s\n' 'Provider login is unavailable: no provider is configured.' >&2; exit 69 ;;
    *) printf '%s\n' 'Unsupported provider action.' >&2; exit 64 ;;
esac
