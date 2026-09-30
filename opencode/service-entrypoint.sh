#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${HOME:?}" "${OPENCODE_CONFIG_DIR:?}"
# Product initialization only: no registration, provider copy, installer or policy.
node /opt/opencode/component/scripts/publish-plugins.mjs \
    /opt/opencode/component/.opencode/config "$OPENCODE_CONFIG_DIR"
exec "$@"
