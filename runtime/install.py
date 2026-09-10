#!/usr/bin/env python3
"""Explicit component lifecycle. Never imported/executed by protected root code.

Update performs network resolution and a non-root containerized lock generation;
build consumes that exact lock. Neither operation activates anything.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform as host_platform
import pwd
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
IMAGE = re.compile(r'sha256:[a-f0-9]{64}')
# Must match the protected launcher's fixed policy location; never forwarded in argv.
VM_POLICY = Path('/etc/venv-agents/policy.json')


def require(value, message):
    if not value:
        raise ValueError(message)


def ordinary():
    require(os.getuid() > 0 and os.geteuid() == os.getuid() and os.getegid() == os.getgid(),
            'Run as an ordinary user, never sudo/root')


def prerequisites(harness, platform):
    native = {'x86_64': 'linux/amd64', 'aarch64': 'linux/arm64'}.get(host_platform.machine())
    require(platform == native, 'Native host/platform match required; no implicit emulation')
    if harness == 'omp':
        require(native == 'linux/amd64', 'OMP is amd64-only')
        flags = [line.split(':', 1)[1].split() for line in Path('/proc/cpuinfo').read_text().splitlines()
                 if ':' in line and line.split(':', 1)[0].strip() == 'flags']
        require(flags and all('sse4_2' in cpu for cpu in flags), 'OMP/Bun requires SSE4.2 on every host CPU')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def private(path, *, directory=False):
    require(path.is_absolute() and path.resolve(strict=True) == path, 'Physical private path required')
    info = path.stat()
    require(info.st_uid == os.getuid() and not info.st_mode & 0o077,
            'Private path ownership/mode mismatch; no automatic repair')
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
            'Private regular file or directory required')
    return path


def state_root():
    path = Path.home() / '.local/state/agents-runtime'
    require(path.resolve() == path, 'Redirected runtime state refused')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return private(path, directory=True)


def atomic(path, value):
    private(path.parent, directory=True)
    if path.exists() or path.is_symlink():
        private(path)
    fd, temporary = tempfile.mkstemp(prefix='.receipt-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def bind_home(home, image):
    """No image change over unknown real state; explicit new slots stay independent."""
    private(home, directory=True)
    require(isinstance(image, str) and IMAGE.fullmatch(image), 'Exact HOME image binding required')
    binding = home / '.agents-runtime-image.json'
    if binding.exists() or binding.is_symlink():
        require(json.loads(private(binding).read_text()) == {'image': image},
                'Unknown real-state upgrade refused; select a new empty --state-slot, or retain the previous image')
    else:
        require(not list(home.iterdir()), 'Unbound existing HOME refused; no private-state adoption')
        atomic(binding, {'image': image})


def verify_image(receipt, inspected):
    require(receipt['schema'] == receipt['contract'] == 1 and receipt['harness'] in catalog()['harnesses']
            and receipt['resolution']['harness'] == receipt['harness']
            and receipt['platform'] == receipt['resolution']['platform'], 'Invalid selected receipt')
    require(IMAGE.fullmatch(receipt['image']) and inspected['Id'] == receipt['image']
            and inspected['Os'] + '/' + inspected['Architecture'] == receipt['platform'], 'Image identity/platform mismatch')
    labels = inspected['Config'].get('Labels', {})
    require(labels.get('io.agents-runtime.resolution') == digest(encoded(receipt['resolution']))
            and labels.get('io.agents-runtime.harness') == receipt['harness']
            and labels.get('io.agents-runtime.contract') == '1', 'Image/receipt contract mismatch')
    require(not inspected['Config'].get('Volumes'), 'Image-declared anonymous volumes refused')
    forbidden = {'DOCKER_HOST', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'BASH_ENV', 'ENV'}
    require(not any(item.split('=', 1)[0] in forbidden for item in inspected['Config'].get('Env') or []),
            'Image-inherited execution/authority override refused')


def catalog():
    return json.loads((ROOT / 'harnesses.json').read_text())


def version(value):
    require(isinstance(value, str) and re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value),
            'Stable three-part release required')
    return tuple(map(int, value.split('.')))


def select(versions, bounds):
    lower, upper = map(version, bounds)
    eligible = [v for v in versions if re.fullmatch(r'\d+\.\d+\.\d+', v)
                and lower <= version(v) < upper]
    require(eligible, 'No compatible stable release; review catalog, never widen automatically')
    return max(eligible, key=version)


def fetch(url, headers=None):
    require(url.startswith('https://'), 'TLS metadata required')
    with urlopen(Request(url, headers=headers or {}), timeout=30) as response:
        data = response.read(64 * 1024 * 1024 + 1)
        require(len(data) <= 64 * 1024 * 1024, 'Metadata too large')
        return data


def node_base(spec, platform):
    releases = json.loads(fetch('https://nodejs.org/dist/index.json'))
    selected = select([r['version'].removeprefix('v') for r in releases], spec['range'])
    repository = spec['repository']
    token = json.loads(fetch('https://auth.docker.io/token?service=registry.docker.io&scope=repository:'
                             + repository + ':pull'))['token']
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json'}
    data = fetch('https://registry-1.docker.io/v2/' + repository + '/manifests/' + selected + spec['suffix'], headers)
    manifest = json.loads(data)
    matches = [m['digest'] for m in manifest['manifests']
               if m.get('platform', {}).get('os', '') + '/' + m.get('platform', {}).get('architecture', '') == platform]
    require(len(matches) == 1 and IMAGE.fullmatch(matches[0]), 'Unique base platform manifest required')
    return {'version': selected, 'manifest': 'sha256:' + digest(data),
            'platform_digest': matches[0], 'image': 'node@' + matches[0]}


def debian_snapshot():
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT000000Z')
    records = {}
    for archive, suite in [('debian', 'bookworm'), ('debian', 'bookworm-updates'), ('debian-security', 'bookworm-security')]:
        url = f'https://snapshot.debian.org/archive/{archive}/{timestamp}/dists/{suite}/InRelease'
        records[suite] = {'url': url, 'sha256': digest(fetch(url))}
    return {'timestamp': timestamp, 'releases': records}


def apt_sources(snapshot):
    require(re.fullmatch(r'[0-9]{8}T[0-9]{6}Z', snapshot['timestamp']), 'Exact Debian snapshot required')
    return '\n'.join(f'Types: deb\nURIs: https://snapshot.debian.org/archive/{archive}/{snapshot["timestamp"]}/\n'
                     f'Suites: {suite}\nComponents: main\nSigned-By: /usr/share/keyrings/debian-archive-keyring.gpg\n'
                     'Check-Valid-Until: no\n' for archive, suite in
                     [('debian', 'bookworm'), ('debian', 'bookworm-updates'), ('debian-security', 'bookworm-security')])


def resolve(harness: str, catalog: dict, platform: str) -> dict:
    ordinary()
    require(harness in catalog['harnesses'], 'Unsupported harness')
    spec = catalog['harnesses'][harness]
    require(platform in spec['platforms'], 'Unsupported platform')
    prerequisites(harness, platform)
    packages = {}
    for name, bounds in spec['packages'].items():
        metadata = json.loads(fetch('https://registry.npmjs.org/' + quote(name, safe='')))
        selected = select(metadata['versions'], bounds)
        release = metadata['versions'][selected]
        integrity = release['dist'].get('integrity', '')
        require(re.fullmatch(r'sha512-[A-Za-z0-9+/]+={0,2}', integrity), 'Package SHA512 integrity required')
        require(len(base64.b64decode(integrity[7:], validate=True)) == 64, 'Invalid package integrity')
        require(release['dist']['tarball'].startswith('https://registry.npmjs.org/'), 'External package registry refused')
        packages[name] = {'version': selected, 'integrity': integrity}
    return {'schema': 1, 'contract': catalog['contract'], 'harness': harness, 'platform': platform,
            'catalog_sha256': digest(encoded(catalog)), 'base': node_base(catalog['node'], platform),
            'debian': debian_snapshot(), 'packages': packages, 'resolved_at': datetime.now(timezone.utc).isoformat()}


def docker(arguments, *, capture=True):
    # Explicit local endpoint; ambient contexts, remote builders and credentials
    # are not forwarded. Build-time rootful Docker remains host-root authority.
    return subprocess.run(['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', *arguments],
                          env={'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())},
                          text=True, capture_output=capture, check=True, timeout=1800)


def build_sources(harness, current, root=None):
    """One public allowlist for both resolution hashing and context publication."""
    recipe = 'images/' + harness + '/Dockerfile'
    require(current['harnesses'][harness]['dockerfile'] == recipe, 'Canonical harness recipe required')
    files = {'entry.py': 'entry.py', 'harnesses.json': 'harnesses.json',
             recipe: 'Dockerfile', recipe + '.dockerignore': 'Dockerfile.dockerignore'}
    if harness == 'opencode':
        base = '../opencode/.opencode/config/'
        provenance = (root or Path(__file__).resolve().parent) / base / 'kdco/upstream.json'
        upstream = json.loads(provenance.read_text())['files']
        for name in (*upstream, 'upstream.json', 'package.json', 'package-lock.json', 'README.md'):
            require(re.fullmatch(r'(?:kdco-primitives/|worktree/|notify/)?[A-Za-z0-9_.-]+', name)
                    and name not in ('.', '..'), 'Invalid public KDCO source path')
            files[base + 'kdco/' + name] = 'opencode-plugins/kdco/' + name
        for name in ('background-agents', 'worktree', 'notify'):
            relative = 'plugins/kdco-' + name + '.ts'
            files[base + relative] = 'opencode-plugins/' + relative
        files['../opencode/scripts/publish-plugins.mjs'] = 'publish-plugins.mjs'
    return files


def source_record(root, harness):
    files = build_sources(harness, json.loads((root / 'harnesses.json').read_text()), root)
    result = {}
    for relative in files:
        # Normalize the explicit sibling path, without accepting symlink redirects.
        path = Path(os.path.abspath(root / relative))
        require(path.resolve(strict=True) == path and path.is_file(), 'Physical public build source required')
        result[relative] = digest(path.read_bytes())
    revision = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True,
                              capture_output=True, check=True).stdout.strip()
    return {'revision': revision, 'public_files': result, 'public_sha256': digest(encoded(result))}


def lock_resolution(resolution):
    with tempfile.TemporaryDirectory(prefix='agents-resolution-') as temporary:
        root = Path(temporary)
        package = {'name': 'agents-runtime-selected', 'version': '1.0.0', 'private': True,
                   'dependencies': {name: item['version'] for name, item in resolution['packages'].items()}}
        (root / 'package.json').write_bytes(encoded(package))
        docker(['pull', '--platform', resolution['platform'], resolution['base']['image']])
        docker(['run', '--rm', '--pull=never', '--platform', resolution['platform'],
                '--user', f'{os.getuid()}:{os.getgid()}', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                '--memory', '1g', '--cpus', '2', '--pids-limit', '128', '--env', 'HOME=/tmp',
                '--mount', f'type=bind,src={root},dst=/resolution', '--workdir', '/resolution',
                '--entrypoint', 'npm', resolution['base']['image'], 'install', '--package-lock-only',
                '--ignore-scripts', '--include=optional', '--no-audit', '--no-fund', '--registry=https://registry.npmjs.org'])
        lock = json.loads((root / 'package-lock.json').read_text())
        validate_lock(resolution, lock)
        return dict(resolution, package=package, lock=lock, lock_sha256=digest(encoded(lock)))


def validate_lock(resolution, lock):
    require(lock.get('lockfileVersion') == 3, 'Complete npm v3 lock required')
    for name, item in resolution['packages'].items():
        locked = lock['packages']['node_modules/' + name]
        require(locked['version'] == item['version'] and locked['integrity'] == item['integrity'],
                'Direct package differs from resolved release')
    for name, item in lock['packages'].items():
        if not name:
            continue
        require(not item.get('link') and item.get('resolved', '').startswith('https://registry.npmjs.org/')
                and re.fullmatch(r'sha512-[A-Za-z0-9+/]+={0,2}', item.get('integrity', '')),
                'All transitive packages require registry URL and SHA512 integrity')


def validate_plugin_lock(root):
    """The vendored plugin package obeys the same registry/SRI policy."""
    package = json.loads((root / 'package.json').read_text())
    lock = json.loads((root / 'package-lock.json').read_text())
    dependencies = package['dependencies']
    require(dependencies and lock['packages']['']['dependencies'] == dependencies, 'Plugin package graph mismatch')
    packages = {}
    for name, pin in dependencies.items():
        version(pin)
        packages[name] = {'version': pin, 'integrity': lock['packages']['node_modules/' + name]['integrity']}
    validate_lock({'packages': packages}, lock)


def validate_resolution(harness, root, resolution):
    current = json.loads((root / 'harnesses.json').read_text())
    require(resolution['schema'] == 1 and resolution['harness'] == harness
            and resolution['contract'] == current['contract']
            and resolution['catalog_sha256'] == digest(encoded(current)), 'Resolution/catalog mismatch; run explicit update')
    require(resolution['platform'] in current['harnesses'][harness]['platforms'], 'Unsupported resolved platform')
    require(resolution['source'] == source_record(root, harness), 'Public source changed; run explicit update')
    require(IMAGE.fullmatch(resolution['base']['platform_digest'])
            and resolution['base']['image'] == 'node@' + resolution['base']['platform_digest'], 'Exact base required')
    require(resolution['lock_sha256'] == digest(encoded(resolution['lock'])), 'Lock digest mismatch')
    apt_sources(resolution['debian'])
    validate_lock(resolution, resolution['lock'])
    dependencies = {name: item['version'] for name, item in resolution['packages'].items()}
    require(set(dependencies) == set(current['harnesses'][harness]['packages'])
            and resolution['package']['dependencies'] == dependencies
            and resolution['lock']['packages']['']['dependencies'] == dependencies, 'Selected package graph mismatch')
    for name, selected in dependencies.items():
        lower, upper = map(version, current['harnesses'][harness]['packages'][name])
        require(lower <= version(selected) < upper, 'Resolved package outside reviewed range')
    return current


def build(harness: str, root: Path, resolution: dict, *, refresh: bool) -> dict:
    ordinary()
    prerequisites(harness, resolution['platform'])
    current = validate_resolution(harness, root, resolution)
    with tempfile.TemporaryDirectory(prefix='agents-build-') as temporary:
        context = Path(temporary)
        # Fresh allowlisted context: no checkout .git, hidden homes or credentials.
        for source, destination in build_sources(harness, current, root).items():
            path = Path(os.path.abspath(root / source))
            require(path.resolve(strict=True) == path and path.is_file(), 'Physical public build source required')
            data = path.read_bytes()
            require(digest(data) == resolution['source']['public_files'][source],
                    'Public source changed while copying; run explicit update')
            target = context / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if harness == 'opencode':
            validate_plugin_lock(context / 'opencode-plugins/kdco')
        (context / 'package.json').write_bytes(encoded(resolution['package']))
        (context / 'package-lock.json').write_bytes(encoded(resolution['lock']))
        (context / 'apt.sources').write_text(apt_sources(resolution['debian']))
        iid = context / 'image.id'
        args = ['build', '--pull=false', '--platform', resolution['platform'], '--iidfile', str(iid),
                '--build-arg', 'NODE_IMAGE=' + resolution['base']['image'],
                '--label', 'io.agents-runtime.resolution=' + digest(encoded(resolution))]
        if refresh:
            args.append('--no-cache')
        docker([*args, str(context)], capture=False)
        image = iid.read_text().strip()
        require(IMAGE.fullmatch(image), 'Build did not produce an exact local image ID')
        inspected = json.loads(docker(['image', 'inspect', image]).stdout)[0]
        require(inspected['Id'] == image and inspected['Os'] + '/' + inspected['Architecture'] == resolution['platform'],
                'Built image identity/platform mismatch')
        labels = inspected['Config'].get('Labels', {})
        require(labels.get('io.agents-runtime.harness') == harness and labels.get('io.agents-runtime.contract') == '1'
                and labels.get('io.agents-runtime.resolution') == digest(encoded(resolution)), 'Image contract mismatch')
        return {'schema': 1, 'harness': harness, 'image': image, 'platform': resolution['platform'],
                'resolution': resolution, 'built_at': datetime.now(timezone.utc).isoformat(), 'contract': 1}


def protected_path(value: str, *, executable: bool = False) -> Path:
    """Root custody through every ancestor; no guest-selected executable redirects."""
    require(isinstance(value, str) and re.fullmatch(r'/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', value)
            and all(part not in ('.', '..') for part in value.split('/')), 'Canonical protected path required')
    path = Path(value)
    require(path.resolve(strict=True) == path, 'Redirected protected path refused')
    for item in (path, *path.parents):
        info = item.lstat()
        require(info.st_uid == 0 and not info.st_mode & 0o6022, 'Root-owned non-writable protected path required')
        if item == path:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'Single-link protected regular file required')
            require(not executable or info.st_mode & 0o111, 'Executable protected launcher required')
        else:
            require(stat.S_ISDIR(info.st_mode), 'Protected directory ancestor required')
    return path


def vm_command(harness: str, receipt: dict, settings: dict) -> Path:
    """Ordinary-user preflight only. Root rechecks policy, seals, caller and image."""
    require(harness in ('pi', 'omp', 'opencode', 't3'), 'Claude is workstation-only; unsupported VM harness')
    require(isinstance(settings.get('target'), str)
            and re.fullmatch(r'[a-z0-9-]+:[a-z0-9-]+', settings['target']), 'Explicit VM target required')
    config = json.loads(protected_path(settings.get('vm_config')).read_text())
    command = protected_path(config['command'], executable=True)
    policy = json.loads(protected_path(str(VM_POLICY)).read_text())
    require(policy['schema'] == 2 and policy['scope'] == 'vm'
            and policy['target'] == settings['target'], 'VM target/policy mismatch')
    shared = policy.get('shared_runtime', {})
    require(shared.get('target') == policy['target'], 'Protected shared-runtime opt-in required')
    account = pwd.getpwuid(os.getuid())
    caller = policy.get('accounts', {}).get(account.pw_name, {})
    require(caller.get('uid') == os.getuid() and caller.get('gid') == os.getgid() == account.pw_gid,
            'Enrolled ordinary caller identity required')
    resolution = receipt['resolution']
    require(receipt['schema'] == receipt['contract'] == resolution['contract'] == 1
            and resolution['harness'] == harness
            and receipt['platform'] == resolution['platform'] == config['platform']
            and config['socket'] == '/var/run/docker.sock', 'VM receipt/platform/local endpoint mismatch')
    prerequisites(harness, receipt['platform'])
    projection = dict(harness=harness, platform=receipt['platform'], contract=receipt['contract'],
                      resolution_sha256=digest(encoded(resolution)),
                      source_sha256=resolution['source']['public_sha256'],
                      source_revision=resolution['source']['revision'])
    require(shared.get('images', {}).get(harness, {}).get(receipt['image']) == projection,
            'Build receipt is not reviewed in protected VM image policy')
    return command


def activate(harness: str, image: str, settings: dict) -> int:
    ordinary()
    require(settings.get('scope') in ('workstation', 'vm'), 'Explicit supported activation scope required')
    require(harness in catalog()['harnesses'] and isinstance(image, str) and IMAGE.fullmatch(image),
            'Explicit harness and local image ID required')
    require(settings['scope'] == 'vm' or not (settings.get('vm_config') or settings.get('target')),
            'VM selectors require VM activation scope')
    require(settings['scope'] != 'vm' or (settings.get('vm_config') and settings.get('target')),
            'VM activation requires explicit protected --vm-config and --target')
    root = private(Path(settings['state']), directory=True)
    receipt = json.loads(private(root / (harness + '-' + image[7:] + '.json')).read_text())
    require(receipt['image'] == image and receipt['harness'] == harness and receipt['contract'] == 1, 'Matching built receipt required')
    if settings['scope'] == 'vm':
        command = vm_command(harness, receipt, settings)
        # No receipt/path/target/env authorization reaches root; only the finite
        # existing sudoers operation. No timeout kills a transaction mid-recovery.
        return subprocess.run(['/usr/bin/sudo', '-n', '--', str(command), 'activate', harness, image],
                              env={'PATH': '/usr/bin:/bin', 'LANG': 'C'}, check=False).returncode
    inspected = json.loads(docker(['image', 'inspect', image]).stdout)[0]
    verify_image(receipt, inspected)
    atomic(root / (harness + '-selected.json'), receipt)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('action', choices=('update', 'build', 'activate'))
    parser.add_argument('harness', choices=tuple(catalog()['harnesses']))
    parser.add_argument('image', nargs='?')
    parser.add_argument('--scope', choices=('workstation', 'vm'), default='workstation')
    parser.add_argument('--vm-config', help='Explicit deployed root-owned build settings path (VM activation only)')
    parser.add_argument('--target', help='Exact environment:host from protected policy (VM activation only)')
    parser.add_argument('--platform', default='linux/' + {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(host_platform.machine(), 'unsupported'))
    args = parser.parse_args(argv)
    try:
        ordinary()
        require(args.action == 'activate' or args.image is None, 'Image is activation-only')
        require(args.action == 'activate' or (args.scope == 'workstation' and not args.vm_config and not args.target),
                'Scope/VM selectors are activation-only; update/build never activate')
        root = state_root()
        fd = os.open(root / '.install.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            private(root / '.install.lock')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == 'activate':
                return activate(args.harness, args.image or '', dict(scope=args.scope, state=str(root),
                                                                   vm_config=args.vm_config, target=args.target))
            path = root / (args.harness + '-resolution.json')
            if args.action == 'update':
                resolution = resolve(args.harness, catalog(), args.platform)
                resolution['source'] = source_record(ROOT, args.harness)
                resolution = lock_resolution(resolution)
                atomic(path, resolution)
            else:
                require(path.exists(), 'No exact resolution receipt; run update explicitly')
                resolution = json.loads(private(path).read_text())
                require(resolution['platform'] == args.platform, 'Requested platform differs from receipt')
            receipt = build(args.harness, ROOT, resolution, refresh=args.action == 'update')
            atomic(root / (args.harness + '-' + receipt['image'][7:] + '.json'), receipt)
            print(receipt['image'] + ' built; NOT activated')
            return 0
        finally:
            os.close(fd)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print('agents-runtime install: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
