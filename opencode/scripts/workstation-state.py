"""Local wrapper preflight; stdout is a private pipe to the invoking shell.

No Docker, Vault, ownership repair, or application-state migration belongs here.
"""
import fcntl
import os
from pathlib import Path
import secrets
import stat
import sys


def directory(path: Path, *, private: bool = False) -> None:
    if path.is_symlink() or path.resolve() != path:
        raise ValueError(f"Redirected directory: {path}")
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or not os.access(path, os.R_OK | os.W_OK | os.X_OK)
            or info.st_mode & 0o022
            or (private and stat.S_IMODE(info.st_mode) != 0o700)):
        raise ValueError(f"Unsafe ownership/permissions: {path}; preserved, not repaired")


def prepare(root: Path) -> str:
    directory(root)
    state = root / '.opencode'
    directory(state)
    for name in ('home-config', 'data', 'cache', 'state', 'locks'):
        directory(state / name)
    # No dedicated backend mount; excluded from image inputs. A workspace bind of
    # the checkout still exposes its files to the same UID, as with provider state.
    private = state / 'workstation-private'
    directory(private, private=True)
    # Lock the stable directory inode: no partially-created lock/password race.
    fd = os.open(private, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        override = os.environ.get('OPENCODE_PASSWORD') or os.environ.get('OPENCODE_SERVER_PASSWORD')
        if override:
            return override
        password = private / 'backend-password'
        if not password.exists() and not password.is_symlink():
            temporary = private / ('.password-' + secrets.token_hex(16))
            try:
                with open(temporary, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
                    stream.write(secrets.token_hex(32) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, password)
                os.fsync(fd)
            finally:
                temporary.unlink(missing_ok=True)
        secret_fd = os.open(password, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(secret_fd) as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise ValueError('Unsafe backend-password file; preserved, not repaired')
            value = stream.read(66)
        if len(value) != 65 or value[-1] != '\n' or any(c not in '0123456789abcdef' for c in value[:-1]):
            raise ValueError('Invalid backend-password file; preserved, not reset')
        return value[:-1]
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        print(prepare(Path(sys.argv[1])))
    except (OSError, ValueError) as error:
        sys.exit(f'Workstation state preflight failed: {error}')
