#!/usr/bin/env python3
"""Fetch public pinned inputs only; no git credentials or lifecycle scripts."""
import base64
import hashlib
import io
import pathlib
import tarfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
PIN = "8463025a321b8a660e9c27b1fa9e1938e1e84c1f"
SOURCE_SHA256 = "f47707b9dbc2e29ef76b7b5909867cae951c6c520a9cc0fa02f690a57e8ad649"
HELPER_SHA256 = "01f211cd703a3150fbd723fcaad0df965e0e1922d05c8e9df6026bea616324da"
ARTIFACTS = {
    "pi-web": ("https://registry.npmjs.org/@agegr/pi-web/-/pi-web-0.9.0.tgz", "Z8E9NfdeMvhuNRLLd8Ck+ZqaGViF40M8UGmKtF1mSlPHkLb6bGJWQ0atlz8jwsGCdcmJIFKhmpEGL6ZoyWK4CQ=="),
    "sdk": ("https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-0.85.1.tgz", "FGRN+OHbWaefBPGaTggAdLjrIHW+s2PzLyglz/5dfLzb9of7uuXMXYC0fJIeZTw+shS32o2cuQ9jF7YSDuL/oQ=="),
}

def extract(data, dest):
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            path = pathlib.PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError(f"Unsafe archive member: {member.name}")
        archive.extractall(dest)

if __name__ == "__main__":
    scratch = ROOT / ".scratch"
    scratch.mkdir(exist_ok=True)
    for name, (url, sri) in ARTIFACTS.items():
        data = urllib.request.urlopen(url).read()
        if base64.b64encode(hashlib.sha512(data).digest()).decode() != sri:
            raise ValueError(f"Unexpected npm SRI: {name}")
        (scratch / f"{name}.tgz").write_bytes(data)
        if not (scratch / name / "package").exists():
            extract(data, scratch / name)
        print(name, "SRI verified")
    data = urllib.request.urlopen(f"https://codeload.github.com/agegr/pi-web/tar.gz/{PIN}").read()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("Unexpected source checksum")
    (scratch / "source.tgz").write_bytes(data)
    print("source sha256", hashlib.sha256(data).hexdigest())
    if not (scratch / "upstream").exists():
        extract(data, scratch / "upstream")
