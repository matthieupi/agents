#!/usr/bin/env python3
"""Apply only to byte-verified pinned public source in this lane's scratch."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from fetch import ROOT, PIN, SOURCE_SHA256, HELPER_SHA256

def apply(source: Path):
    source = source.resolve()
    helper = ROOT.parents[1] / ".pi/agent/extension-library/remote-project-mode.ts"
    if hashlib.sha256(helper.read_bytes()).hexdigest() != HELPER_SHA256:
        raise ValueError("Canonical helper changed: review and repin the build input")
    if os.geteuid() == 0 or ROOT / ".scratch" not in source.parents:
        raise ValueError("Apply requires a non-root user and an owned scratch destination")
    archive = ROOT / ".scratch/source.tgz"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Unexpected source archive")
    # Verify ALL original files, not just hunk context or package version.
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            relative = Path(member.name).relative_to(f"pi-web-{PIN}")
            target = source / relative
            if target.is_symlink() or target.read_bytes() != tar.extractfile(member).read():
                raise ValueError(f"Unexpected source/version: {relative}")
    files = json.loads((ROOT / "patch-files.json").read_text())
    for name, hashes in files.items():
        if hashes["before"] is None and (source / name).exists():
            raise ValueError(f"New patch file already exists: {name}")
    patch = ROOT / "pi-web.patch"
    command = ["patch", "-p1", "--batch", "--forward", "--fuzz=0", "-i", str(patch)]
    subprocess.run(command + ["--dry-run"], cwd=source, check=True)
    subprocess.run(command, cwd=source, check=True)
    for name, hashes in files.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != hashes["after"]:
            raise ValueError(f"Patched checksum mismatch: {name}")
    # Verbatim canonical input; never maintain a second copy of the protocol.
    shutil.copyfile(helper, source / "lib/remote-project-mode.ts")
    print("Canonical helper SHA256:", hashlib.sha256(helper.read_bytes()).hexdigest())

if __name__ == "__main__":
    apply(Path(sys.argv[1]))
