#!/usr/bin/python3
"""Maintained component build flow. Runs as SSH user; root only activates an ID."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import uuid


SETTINGS = Path('/etc/venv-agents/build.json')
HARNESSES = ('pi', 'omp', 'opencode', 't3')


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative(value: object) -> Path:
    if not isinstance(value, str) or not value or value.startswith('/'):
        raise ValueError('Invalid build manifest path')
    path = Path(value)
    if '..' in path.parts or any(part in ('', '.') for part in path.parts):
        raise ValueError('Invalid build manifest path')
    return path


def _protected_directory(path: Path) -> None:
    for item in (path, *path.parents):
        info = item.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('Root-controlled maintained source path required')


def _read_settings() -> tuple[dict, bytes]:
    _protected_directory(SETTINGS.parent)
    info = SETTINGS.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o644):
        raise ValueError('Unsafe maintained build settings')
    data = SETTINGS.read_bytes()
    return json.loads(data), data


def _verify_source(root: Path, record: dict) -> None:
    if set(record) != {'schema', 'canonical_root', 'lock', 'source_sha256', 'files'} or record['schema'] != 1:
        raise ValueError('Invalid maintained source manifest')
    if not re.fullmatch(r'[a-f0-9]{64}', record['source_sha256']):
        raise ValueError('Invalid maintained source identity')
    files = record['files']
    if not isinstance(files, list) or not files:
        raise ValueError('Empty maintained source manifest')
    seen = set()
    for entry in files:
        if set(entry) != {'path', 'mode', 'sha256'}:
            raise ValueError('Invalid maintained source entry')
        relative = _safe_relative(entry['path'])
        if str(relative) in seen or not re.fullmatch(r'[a-f0-9]{64}', entry['sha256']):
            raise ValueError('Duplicate or invalid maintained source entry')
        seen.add(str(relative))
        path = root / relative
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != int(entry['mode'], 8)
                or _digest(path) != entry['sha256']):
            raise ValueError(f'Maintained source drift: {relative}')


@contextmanager
def source_snapshot(root: Path):
    """Hold the public source lock and prove source/settings before release."""
    record_path = root / 'build-record.json'
    record_info = record_path.lstat()
    if (not stat.S_ISREG(record_info.st_mode) or record_info.st_uid != 0 or record_info.st_gid != 0
            or record_info.st_nlink != 1 or stat.S_IMODE(record_info.st_mode) != 0o644):
        raise ValueError('Unsafe maintained source manifest')
    record = json.loads(record_path.read_text())
    lock_path = Path(record['lock'])
    canonical = Path(record['canonical_root'])
    if (not lock_path.is_absolute() or '..' in lock_path.parts or not canonical.is_absolute()
            or '..' in canonical.parts or lock_path.parent != canonical.parent):
        raise ValueError('Invalid maintained source lock binding')
    _protected_directory(canonical)
    _protected_directory(root)
    generations = canonical.parent / ('.' + canonical.name + '.build-generations')
    if root != canonical and (root.parent != generations or root.name != record.get('source_sha256')):
        raise ValueError('Build script is outside its maintained source generation')
    fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o644):
            raise ValueError('Unsafe maintained source lock')
        fcntl.flock(fd, fcntl.LOCK_SH)
        _verify_source(root, record)
        settings, settings_bytes = _read_settings()
        yield settings
        _verify_source(root, record)
        if _read_settings()[1] != settings_bytes:
            raise ValueError('Maintained build settings changed during build')
    finally:
        os.close(fd)


def prerequisites(harness: str, machine: str, cpuinfo: str) -> None:
    if harness not in HARNESSES:
        raise ValueError('Unknown harness')
    if machine not in ('x86_64', 'aarch64'):
        raise ValueError('Supported native amd64/arm64 CPU required')
    if harness == 'omp' and machine != 'x86_64':
        raise ValueError('OMP component supports amd64 only')
    # OMP installs Bun; OpenCode ships a Bun-based executable. Baseline Bun still
    # requires SSE4.2. Check every advertised processor before any Docker work.
    if harness in ('omp', 'opencode') and machine == 'x86_64':
        flags = [line.split(':', 1)[1].split() for line in cpuinfo.splitlines()
                 if line.split(':', 1)[0].strip() == 'flags' and ':' in line]
        if not flags or not all('sse4_2' in values for values in flags):
            raise ValueError('Bun requires SSE4.2; ask the coordinator to fix VM CPU configuration')


def build(harness: str, root: Path, settings: dict) -> str:
    if os.getuid() == 0 or os.geteuid() == 0:
        raise ValueError('Run make as the enrolled SSH account, never root/sudo')
    machine = platform.machine()
    prerequisites(harness, machine, Path('/proc/cpuinfo').read_text())
    expected = 'linux/amd64' if machine == 'x86_64' else 'linux/arm64'
    if settings['platform'] != expected:
        raise ValueError('Native platform required; emulation is not CPU acceptance')
    if not re.fullmatch(r'[a-z0-9./:-]+@sha256:[a-f0-9]{64}', settings['docker_cli_image']):
        raise ValueError('Pinned Docker CLI manifest required')
    if harness == 'opencode' and not re.fullmatch(r'\d+\.\d+\.\d+', settings['opencode_version']):
        raise ValueError('Exact OpenCode version required')
    socket = settings['socket']
    if not isinstance(socket, str) or not socket.startswith('/') or '..' in Path(socket).parts:
        raise ValueError('Absolute local Docker socket required')
    docker = ['/usr/bin/docker', '--host', 'unix://' + socket]
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'DOCKER_BUILDKIT': '1'}
    prefix = 'venv-build:' + uuid.uuid4().hex + '-'

    def call(arguments: list[str], capture: bool = False) -> str:
        result = subprocess.run(docker + arguments, cwd=root, env=environment,
                                check=True, text=True, stdout=subprocess.PIPE if capture else None,
                                timeout=3600 if arguments[0] == 'build' else 60)
        return (result.stdout or '').strip()

    def inspect(tag: str) -> str:
        image = call(['image', 'inspect', '--format', '{{.Id}}', tag], True)
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
            raise ValueError('Invalid local image ID')
        return image

    def image(name: str, dockerfile: str, context: str, args: dict,
              dependencies: dict | None = None, target: str | None = None) -> tuple[str, str]:
        ignore = root / (dockerfile + '.dockerignore' if name not in ('node', 'omp-component', 't3-component')
                         else context + '/.dockerignore')
        if not ignore.is_file():
            raise ValueError(f'Missing maintained context allowlist: {ignore.relative_to(root)}')
        dependencies = dependencies or {}
        for tag, identity in dependencies.items():
            if inspect(tag) != identity:
                raise ValueError('Intermediate image drift before build')
        tag = prefix + name
        command = ['build', '--pull=false', '--platform', expected, '-f', dockerfile, '-t', tag]
        if target:
            command += ['--target', target]
        for key, value in sorted(args.items()):
            command += ['--build-arg', key + '=' + value]
        call(command + [context])
        for dependency, identity in dependencies.items():
            if inspect(dependency) != identity:
                raise ValueError('Intermediate image drift during build')
        return tag, inspect(tag)

    if harness in ('pi', 'opencode', 't3'):
        pins = json.loads((root / 't3code/runtime/pins.json').read_text())['build_args']
    if harness in ('pi', 'opencode'):
        base, base_id = image('node', 't3code/Dockerfile', 't3code', pins, target='base')
        prepared, prepared_id = image('prepared', 'venv/Dockerfile.base', 'venv',
                                     {'COMPONENT_BASE': base}, {base: base_id})
    if harness == 'pi':
        component, component_id = image('pi-component', 'pi/Dockerfile.vm', 'pi',
                                       {'PI_VM_BASE': prepared}, {prepared: prepared_id})
    elif harness == 'opencode':
        component, component_id = image('opencode-component', 'venv/Dockerfile.opencode', '.',
                                       {'OPENCODE_VM_BASE': prepared,
                                        'OPENCODE_VERSION': settings['opencode_version']},
                                       {prepared: prepared_id})
    else:
        context = 'omp' if harness == 'omp' else 't3code'
        component, component_id = image(harness + '-component', context + '/Dockerfile', context,
                                       {} if harness == 'omp' else pins)
    _, identity = image(harness, 'venv/Dockerfile.vm', 'venv',
                        {'COMPONENT_IMAGE': component, 'DOCKER_CLI_IMAGE': settings['docker_cli_image']},
                        {component: component_id})
    return identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('harness', choices=HARNESSES)
    args = parser.parse_args(argv)
    try:
        root = Path(__file__).resolve().parents[1]
        # Activation takes its private lock only after this shared lock is released.
        with source_snapshot(root) as settings:
            identity = build(args.harness, root, settings)
        # Root executes its protected deployed launcher, never this checkout.
        command = settings['command']
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+', command) or '..' in Path(command).parts:
            raise ValueError('Absolute deployed launcher required')
        subprocess.run(['/usr/bin/sudo', '--', command, 'activate', args.harness, identity],
                       check=True, timeout=1200)
        print(f'{args.harness} installed: {identity}')
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f'venv build: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
