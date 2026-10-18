#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${HOME:?}" "${OPENCODE_CONFIG_DIR:?}"
# Same resource-before-HOME lock order as workstation initialization. Subshell
# releases locks before the long-lived backend (or embedded consumer) starts.
(
    exec 8</opt/agent
    flock -x 8
    exec 7<"$HOME"
    flock -x 7
    node /opt/opencode/component/scripts/publish-plugins.mjs config \
        /opt/opencode-defaults /opt/agent "$OPENCODE_CONFIG_DIR"
    node /opt/opencode/component/scripts/publish-plugins.mjs \
        /opt/opencode/component/.opencode/config "$OPENCODE_CONFIG_DIR"
)
exec "$@"
