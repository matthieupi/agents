#!/usr/bin/python3 -I
"""Authenticated V2 backend readiness; no credential in argv or diagnostics."""
import base64
import json
import os
from pathlib import Path
import sys
import urllib.request


def request_info(home: Path, port: int) -> dict:
    # The image entry module owns the exact private-file validation contract.
    sys.path.insert(0, '/opt/venv')
    from entry import opencode_password
    password = opencode_password(home)
    authorization = base64.b64encode(('opencode:' + password).encode()).decode()
    request = urllib.request.Request(f'http://127.0.0.1:{port}/api/info',
                                     headers={'Authorization': 'Basic ' + authorization})
    with urllib.request.urlopen(request, timeout=3) as response:
        info = json.load(response)
    if not str(info.get('version', '')).startswith('2.') or type(info.get('pid')) is not int:
        raise ValueError('Not V2 readiness')
    return info


if __name__ == '__main__':
    try:
        request_info(Path(os.environ['HOME']), int(os.environ['VENV_AGENT_PORT']))
    except Exception:
        sys.exit('OpenCode authenticated V2 readiness failed')
