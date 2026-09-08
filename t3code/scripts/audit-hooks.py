#!/usr/bin/env python3
"""Read verified npm tarballs in memory, inventory lifecycle hooks (never execute)."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import urllib.request


def inspect(item):
    path, pkg = item
    if not path:
        return None
    data = urllib.request.urlopen(pkg["resolved"], timeout=90).read()
    if "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode() != pkg["integrity"]:
        raise ValueError(f"Tarball SHA-512 mismatch: {path}")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        manifests = [m for m in archive.getmembers() if m.name.endswith("/package.json") and m.name.count("/") == 1]
        if len(manifests) != 1:
            raise ValueError(f"Unexpected tarball package root: {path}")
        manifest = json.load(archive.extractfile(manifests[0]))
        if manifest.get("name") != path.split("node_modules/")[-1] or manifest.get("version") != pkg["version"]:
            raise ValueError(f"Tarball identity differs from lock: {path}")
        hooks = {k: v for k, v in manifest.get("scripts", {}).items() if k in ("preinstall", "install", "postinstall")}
        if hooks or manifest["name"] in ("@ff-labs/fff-node", "node-gyp-build", "node-gyp-build-optional-packages"):
            result = {"path": path, "version": pkg["version"], "hooks": hooks}
            if "--source" in sys.argv:
                result["source"] = {m.name: archive.extractfile(m).read().decode(errors="replace") for m in archive.getmembers()
                                    if m.isfile() and m.size < 60000 and (m.name.endswith((".js", ".json")))
                                    and (m.name.startswith("package/scripts/") or m.name in (
                                        "package/bin.js", "package/index.js", "package/build-test.js",
                                        "package/optional.js", "package/dist/src/binary.js"))}
            return result
    return None


if __name__ == "__main__":
    lock = json.loads((Path(__file__).resolve().parents[1] / "runtime/package-lock.json").read_text())
    with ThreadPoolExecutor(max_workers=8) as pool:
        for result in pool.map(inspect, lock["packages"].items()):
            if result:
                print(json.dumps(result, indent=2))
    print(f"Verified SHA-512 for all {len(lock['packages']) - 1} locked tarballs; no extraction or hooks executed.")
