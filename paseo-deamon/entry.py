"""Constrained foreground startup, not a package installer or provider adapter."""
import fcntl
import json
import os
from pathlib import Path
import re
import stat


KDCO_SOURCE = Path("/opt/opencode/component/.opencode/config/kdco")


def validate_config(path: Path) -> dict:
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077
            or metadata.st_uid != os.getuid()):
        raise ValueError("Paseo config must be a regular owner-only file owned by the runtime UID")
    config = json.loads(path.read_text())
    password = config.get("daemon", {}).get("auth", {}).get("password", "")
    if not isinstance(password, str) or not re.fullmatch(r"\$2[aby]\$(?:1[0-6])\$[./A-Za-z0-9]{53}", password):
        raise ValueError("Paseo requires a native bcrypt hash (cost 10..16), not plaintext or the example marker")
    if config.get("version") != 1:
        raise ValueError("Paseo config version must be 1")
    return config


def ensure_kdco_link(config_home: Path, source: Path = KDCO_SOURCE) -> None:
    """Expose the baked KDCO tree through the private ephemeral config root."""
    target = config_home / "opencode" / "kdco"
    if not source.is_dir() or source.is_symlink():
        raise ValueError("Unexpected KDCO source asset path")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("Unexpected KDCO config root")
    try:
        existing = target.readlink()
    except FileNotFoundError:
        target.symlink_to(source, target_is_directory=True)
    except OSError as error:
        raise ValueError("Unexpected KDCO runtime asset path") from error
    else:
        if existing != source:
            raise ValueError("Unexpected KDCO runtime asset path")


def main() -> None:
    if os.getuid() == 0 or os.getgid() == 0:
        raise ValueError("Numeric non-root UID and GID required")
    if "PASEO_PASSWORD" in os.environ:
        raise ValueError("Plaintext password environment overrides are forbidden")
    os.umask(0o077)
    # The private ephemeral config root keeps the baked KDCO dependency outside
    # the suppressed upstream HOME volume; host-provided descendants stay RO.
    ensure_kdco_link(Path(os.environ["XDG_CONFIG_HOME"]))
    home = Path(os.environ["PASEO_HOME"])
    validate_config(home / "config.json")
    # Locks survive exec and prevent concurrent component writers, without a broker.
    for root in (home, Path("/state/provider")):
        metadata = root.stat()
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise ValueError("Dedicated state directories must be UID-owned mode 0700")
        fd = os.open(root / ".component.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.set_inheritable(fd, True)
    for key in ("XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        Path(os.environ[key]).mkdir(parents=True, exist_ok=True, mode=0o700)
    entry = Path("/etc/paseo-server-entry").read_text().strip()
    expected = "/usr/local/lib/node_modules/@getpaseo/server/dist/scripts/supervisor-entrypoint.js"
    if entry != expected or not Path(entry).is_file():
        raise ValueError("Unexpected upstream foreground supervisor contract; review the base image")
    os.execvp("node", ["node", entry])


if __name__ == "__main__":
    main()
