#!/usr/bin/env python3
"""Record build inputs and artifact hashes; does not infer test success."""
import hashlib
import json
from pathlib import Path
from fetch import ROOT, PIN, SOURCE_SHA256, HELPER_SHA256, ARTIFACTS

def record(source: Path):
    files = json.loads((ROOT / "patch-files.json").read_text())
    for name, hashes in files.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != hashes["after"]:
            raise ValueError(f"Built source differs from patch: {name}")
    helper_hash = hashlib.sha256((source / "lib/remote-project-mode.ts").read_bytes()).hexdigest()
    if helper_hash != HELPER_SHA256:
        raise ValueError("Built helper differs from pinned canonical input")
    artifact = ROOT / ".scratch/out/agegr-pi-web-0.9.0-remote.1.tgz"
    patch = (ROOT / "pi-web.patch").read_bytes()
    lines = patch.decode().splitlines()
    report = {
        "source": PIN, "sourceArchiveSha256": SOURCE_SHA256,
        "publicArtifacts": {name: {"url": url, "sri": "sha512-" + sri} for name, (url, sri) in ARTIFACTS.items()},
        "sourceManifestVersion": "0.8.11", "replacementFor": "0.9.0", "version": "0.9.0-remote.1",
        "patchSha256": hashlib.sha256(patch).hexdigest(), "patchBytes": len(patch), "patchFiles": len(files),
        "addedLines": sum(line.startswith("+") and not line.startswith("+++") for line in lines),
        "removedLines": sum(line.startswith("-") and not line.startswith("---") for line in lines),
        "helperSource": "../../.pi/agent/extension-library/remote-project-mode.ts", "helperSha256": helper_hash,
        "artifact": artifact.name, "artifactSha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "artifactBytes": artifact.stat().st_size,
    }
    (ROOT / ".scratch/out/build-provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return report

if __name__ == "__main__":
    import sys
    record(Path(sys.argv[1]))
