#!/bin/bash
set -euo pipefail
umask 077
[[ $# == 0 ]] || { printf '%s\n' 'Usage: init.sh' >&2; exit 64; }
exec /bin/bash /opt/t3/scripts/start.sh container
