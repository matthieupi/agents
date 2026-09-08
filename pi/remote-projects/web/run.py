#!/usr/bin/env python3
"""Run build/test commands as the current non-root user with no inherited secrets."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
from fetch import ROOT, PIN

if os.geteuid() == 0:
    raise SystemExit("Refusing root build")
source = ROOT / ".scratch" / "upstream" / f"pi-web-{PIN}"
args = sys.argv[1:]
if args[:1] == ["--source"]:
    source = Path(args[1]).resolve()
    args = args[2:]
if ROOT / ".scratch" not in source.parents:
    raise SystemExit("Source must be inside owned scratch")
home = ROOT / ".scratch" / "home"
home.mkdir(parents=True, exist_ok=True)
helper = ROOT.parents[1] / ".pi/agent/extension-library/remote-project-mode.ts"
if not (source / "lib/remote-project-mode.ts").exists():
    shutil.copyfile(helper, source / "lib/remote-project-mode.ts")
env = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": str(home), "TMPDIR": str(home),
    "XDG_CONFIG_HOME": str(home / ".config"),
    "XDG_CACHE_HOME": str(home / ".cache"),
    "PI_CODING_AGENT_DIR": str(home / ".pi/agent"),
    "npm_config_cache": str(home / "npm-cache"),
    "npm_config_userconfig": str(home / "user.npmrc"), "npm_config_globalconfig": str(home / "global.npmrc"),
    "npm_config_registry": "https://registry.npmjs.org/",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0", "NEXT_TELEMETRY_DISABLED": "1", "CI": "1",
}
raise SystemExit(subprocess.call(args, cwd=source, env=env))
