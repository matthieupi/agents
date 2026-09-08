"""Canonical build-input validation; shared by host wrapper and image builder."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def validate(runtime):
    pins = json.loads((runtime / "pins.json").read_text())
    if pins["schema"] != 1 or set(pins["build_args"]) != {"NODE_IMAGE", "DEBIAN_SNAPSHOT"}:
        raise RuntimeError("Unknown pin schema/build arguments")
    node = pins["node_version"]
    if not re.fullmatch(r"24\.\d+\.\d+", node) or int(node.split(".")[1]) < 10:
        raise RuntimeError("An exact supported Node 24 patch is required")
    if not re.fullmatch(r"node:" + re.escape(node) + r"-bookworm-slim@sha256:[a-f0-9]{64}", pins["build_args"]["NODE_IMAGE"]):
        raise RuntimeError("Exact Node patch/tag/digest mismatch")
    if not re.fullmatch(r"\d{8}T\d{6}Z", pins["build_args"]["DEBIAN_SNAPSHOT"]):
        raise RuntimeError("Invalid Debian snapshot")
    if not pins["platforms"] or set(pins["platforms"]) - {"linux/amd64", "linux/arm64"}:
        raise RuntimeError("Unsupported build platforms")
    version = pins["t3_version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError("Exact T3 version required")
    raw = (runtime / "package-lock.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != pins["package_lock_sha256"]:
        raise RuntimeError("Reviewed lock SHA-256 mismatch")
    manifest = json.loads((runtime / "package.json").read_text())
    lock = json.loads(raw)
    deps = {"t3": version}
    if manifest.get("dependencies") != deps or any(k in manifest for k in (
            "scripts", "devDependencies", "optionalDependencies", "overrides", "workspaces")):
        raise RuntimeError("Runtime manifest must contain only the exact T3 dependency")
    if lock["lockfileVersion"] != 3 or lock["packages"][""]["dependencies"] != deps:
        raise RuntimeError("Lock root mismatch")
    t3 = lock["packages"]["node_modules/t3"]
    if (t3["version"] != version or t3["integrity"] != pins["t3_integrity"] or
            t3["resolved"] != f"https://registry.npmjs.org/t3/-/t3-{version}.tgz" or
            t3["bin"] != {"t3": "dist/bin.mjs"}):
        raise RuntimeError("T3 identity/bin/SRI mismatch")
    for path, pkg in lock["packages"].items():
        if not path:
            continue
        if (not path.startswith("node_modules/") or ".." in path.split("/") or pkg.get("link") or
                not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", pkg.get("version", "")) or
                not re.fullmatch(r"https://registry\.npmjs\.org/[^?#\s]+\.tgz", pkg.get("resolved", "")) or
                not re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", pkg.get("integrity", ""))):
            raise RuntimeError("Every locked artifact requires exact registry identity and SHA-512")
        if bool(pkg.get("hasInstallScript")) != (path in pins["install_hooks"]):
            raise RuntimeError("Unreviewed lock lifecycle hook")
    return pins


def installed(runtime, pins):
    if subprocess.check_output(["node", "-p", "process.versions.node"], text=True).strip() != pins["node_version"]:
        raise RuntimeError("Installed Node patch mismatch")
    found = {}
    lock = json.loads((runtime / "package-lock.json").read_text())
    for path in (runtime / "node_modules").rglob("package.json"):
        # Nested bundled source manifests can have developer scripts; only npm
        # installed package roots from the lock are lifecycle targets.
        relative = str(path.parent.relative_to(runtime))
        if relative not in lock["packages"]:
            continue
        pkg = json.loads(path.read_text())
        hooks = {k: v for k, v in pkg.get("scripts", {}).items() if k in ("preinstall", "install", "postinstall")}
        if hooks:
            found[relative] = hooks
    if found != pins["install_hooks"]:
        raise RuntimeError("Installed lifecycle hooks differ from audited scripts")


if __name__ == "__main__":
    runtime = Path(sys.argv[1])
    pins = validate(runtime)
    if "--installed" in sys.argv:
        installed(runtime, pins)
    print("Build artifact contract verified")
