#!/usr/bin/env python3
"""Fake Docker executable for subprocess argv/Compose environment regression only."""
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args[:1] == ["--host"]:
    args = args[2:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as stream:
    stream.write(json.dumps({"args": args, "env": {k: v for k, v in os.environ.items() if k.startswith(("T3CODE_", "COMPOSE_"))}}) + "\n")
image = "sha256:" + "c" * 64
if args[:2] == ["context", "inspect"]:
    print(json.dumps([{"Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock"}}}]))
elif args[:1] == ["build"]:
    if os.environ.get("FAKE_BUILD_FAIL"):
        sys.exit(1)
    Path(args[args.index("--iidfile") + 1]).write_text(image)
elif args[:2] == ["image", "inspect"]:
    print(json.dumps([{"Id": image}]))
elif args[:2] == ["container", "ls"] or "compose" in args:
    pass
else:
    raise SystemExit(f"Unexpected fixture command: {args}")
