#!/usr/bin/env python3
"""Public source -> verified patch -> native npm build -> pack. No installation."""
import os
import subprocess
import sys
from fetch import ROOT, PIN, extract
from apply import apply
from provenance import record

if os.geteuid() == 0:
    raise SystemExit("Refusing root build")
subprocess.run([sys.executable, str(ROOT / "fetch.py")], check=True)
destination = ROOT / ".scratch/rebuild"
if destination.exists():
    raise SystemExit(".scratch/rebuild already exists; retain it for review or choose a fresh workspace")
extract((ROOT / ".scratch/source.tgz").read_bytes(), destination)
source = destination / f"pi-web-{PIN}"
apply(source)
out = ROOT / ".scratch/out"
out.mkdir(exist_ok=True)

def run(*args):
    subprocess.run([sys.executable, str(ROOT / "run.py"), "--source", str(source), *args], check=True)

run("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund")
run("npm", "rebuild", "node-pty")
run("node", "--test", str(ROOT / "test.mjs"))
run("npm", "test")
run("npm", "run", "build")
run("npm", "pack", "--silent", "--ignore-scripts", "--pack-destination", str(out))
record(source)
