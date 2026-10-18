#!/usr/bin/env bash
set -euo pipefail
# Only sshd needs root. Initialize shared OpenCode HOME as the execution account,
# using the same paths and product helper as the standalone service.
/usr/sbin/runuser -u "$USER" -- env OPENCODE_CONFIG_DIR="$HOME/.config/opencode" \
    /bin/bash /opt/opencode/service-entrypoint.sh /usr/bin/true
exec "$@"
