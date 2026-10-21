"""Fetch only the exact public fixture into isolated scratch; never install it."""
import base64
import hashlib
import io
import os
import pathlib
import tarfile
import urllib.request

SRI = "OAJarFnnGnzVDsHKmKwITYhOb//pOWhbp9DXA6Nfd2nnkyt/8e/5D1bmakqimO+IGVpTzVRfXEkM77pAZ9mz2Q=="
COMMIT = "7c9b1f61b74e20e59ad7e9307ad3bb365c24774c"
DEFAULT_ROOT = pathlib.Path(__file__).resolve().parent / '.scratch'
ROOT = pathlib.Path(os.environ.get('PI_REMOTE_FIXTURE', str(DEFAULT_ROOT)))
if ROOT not in (DEFAULT_ROOT, pathlib.Path('/tmp/opencode/pi-remote-projects')):
    raise ValueError('PI_REMOTE_FIXTURE must be the owned .scratch or /tmp/opencode/pi-remote-projects')


def prepare_scratch():
    if ROOT.parent.resolve() != ROOT.parent:
        raise ValueError('Scratch ancestry must not use symlinks')
    created = False
    try:
        ROOT.mkdir(mode=0o700)
        created = True
    except FileExistsError:
        pass
    if ROOT.is_symlink() or not ROOT.is_dir() or ROOT.stat().st_uid != os.getuid() or ROOT.stat().st_mode & 0o022:
        raise ValueError('Scratch directory must be owned by the invoking user and not group/world writable')
    marker = ROOT / '.fixture-owner'
    if created:
        marker.write_text('pi-remote-projects-public-test-fixture-v1\n')
    if marker.is_symlink() or not marker.is_file() or marker.read_text() != 'pi-remote-projects-public-test-fixture-v1\n':
        raise ValueError('Refusing an existing directory not initialized by this fixture helper')
    # Reject aliased/foreign outputs before fetch_fixture or the exact patch writes.
    for name in ['upstream.tgz', 'managed-projects.ts', 'index.ts', 'package.json', 'README.md', 'README.zh-CN.md', 'CHANGELOG.md', 'LICENSE',
                 *['commit-' + name for name in ['index.ts', 'package.json', 'README.md', 'README.zh-CN.md', 'CHANGELOG.md', 'LICENSE']]]:
        target = ROOT / name
        if target.is_symlink() or (target.exists() and (not target.is_file() or target.stat().st_nlink != 1 or target.stat().st_uid != os.getuid())):
            raise ValueError(f'Refusing unsafe scratch output: {name}')


def fetch_fixture():
    prepare_scratch()
    cache = ROOT / 'upstream.tgz'
    data = cache.read_bytes() if cache.exists() else urllib.request.urlopen(
        'https://registry.npmjs.org/pi-ssh-remote/-/pi-ssh-remote-0.1.12.tgz', timeout=60).read()
    if base64.b64encode(hashlib.sha512(data).digest()).decode() != SRI:
        raise ValueError('Published artifact SRI mismatch')
    cache.write_bytes(data)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for name in ['index.ts', 'package.json', 'README.md', 'README.zh-CN.md', 'CHANGELOG.md', 'LICENSE']:
            member = archive.getmember('package/' + name)
            if not member.isfile():
                raise ValueError('Unexpected archive member')
            content = archive.extractfile(member).read()
            pinned = ROOT / ('commit-' + name)
            source = pinned.read_bytes() if pinned.exists() else urllib.request.urlopen(
                f'https://raw.githubusercontent.com/petrichor20211/pi-ssh-remote/{COMMIT}/{name}', timeout=60).read()
            if content != source:
                raise ValueError(f'Published file differs from pinned commit: {name}')
            pinned.write_bytes(source)
            (ROOT / name).write_bytes(content)
            print(hashlib.sha256(content).hexdigest(), name)
    return ROOT


if __name__ == '__main__':
    fetch_fixture()
