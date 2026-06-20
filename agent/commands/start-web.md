---
name: start-web
description: Start the OpenCode browser UI on the pre-published agent web port
---

<objective>
Start the OpenCode web server inside this container using the pre-published
Docker port provided by the wrapper.
</objective>

<requirements>
- Use `OPENCODE_AGENT_WEB_PORT`; if it is empty, explain that the container was
  not started with `--agent-web-port <port>` and do not guess a port.
- Bind the OpenCode server to `0.0.0.0` so Docker port publishing can expose it.
- Keep the process running in the background so the current agent session can
  continue.
- Write logs to `/tmp/opencode-web.log`.
- If a server is already listening on the requested port, report that instead
  of starting a duplicate process.
- If `OPENCODE_SERVER_PASSWORD` is empty, warn that the web server is exposed on
  the LAN without a password.
</requirements>

<command>
Run this exact shell flow:

```bash
if [[ -z "${OPENCODE_AGENT_WEB_PORT:-}" ]]; then
  printf 'No pre-published agent web port is configured. Restart the container with --agent-web-port <port>.\n' >&2
  exit 1
fi

if python3 - "${OPENCODE_AGENT_WEB_PORT}" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.2)
    raise SystemExit(0 if sock.connect_ex(("127.0.0.1", port)) == 0 else 1)
PY
then
  printf 'OpenCode web already appears to be listening on port %s.\n' "${OPENCODE_AGENT_WEB_PORT}"
else
  nohup opencode web --hostname 0.0.0.0 --port "${OPENCODE_AGENT_WEB_PORT}" > /tmp/opencode-web.log 2>&1 &
  printf 'Started OpenCode web on container port %s. Logs: /tmp/opencode-web.log\n' "${OPENCODE_AGENT_WEB_PORT}"
fi

if [[ -z "${OPENCODE_SERVER_PASSWORD:-}" ]]; then
  printf 'WARNING: OPENCODE_SERVER_PASSWORD is empty; this LAN-exposed server may be unprotected.\n' >&2
fi

printf 'Advertised URL: %s\n' "${OPENCODE_AGENT_WEB_URL:-http://localhost:${OPENCODE_AGENT_WEB_PORT}}"
```
</command>

<response>
Report:
- whether the server was started or was already running
- the port and advertised URL
- the log path
- any password warning
</response>
