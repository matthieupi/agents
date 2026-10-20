#!/usr/bin/env python3
"""Authenticated V2 readiness, without credentials in argv or diagnostics."""
import base64
import json
import os
import sys
import time
import urllib.request


def request_info() -> dict:
    password = os.environ.get("OPENCODE_PASSWORD") or os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    if not password:
        raise RuntimeError("Missing password")
    auth = base64.b64encode(("opencode:" + password).encode()).decode()
    port = int(os.environ.get("OPENCODE_DOCKER_PORT", "4096"))
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/info",
                                     headers={"Authorization": "Basic " + auth})
    with urllib.request.urlopen(request, timeout=2) as response:
        info = json.load(response)
    if not info.get("version", "").startswith("2.") or not isinstance(info.get("pid"), int):
        raise RuntimeError("Not a V2 readiness response")
    return info


if __name__ == "__main__":
    deadline = time.monotonic() + (90 if "--wait" in sys.argv else 0)
    while True:
        try:
            request_info()
            break
        except Exception:
            if time.monotonic() >= deadline:
                sys.exit("OpenCode V2 authenticated readiness failed; inspect container logs/config/password")
            time.sleep(1)
