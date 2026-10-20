#!/usr/bin/env bash
set -euo pipefail
umask 077
# Direct native servers must never generate an ephemeral credential that the
# gateway cannot know. Embedded consumers (Paseo/Paperclip) own their own launch.
if [[ ( "${1:-}" == opencode || "${1:-}" == */opencode ) && "${2:-}" == serve && -z "${OPENCODE_PASSWORD:-}" ]]; then
    printf '%s\n' 'opencode: OPENCODE_PASSWORD is required for native serve' >&2
    exit 1
fi
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
)
exec "$@"
