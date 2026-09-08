"""Rebuild public scratch fixture, test, and compare strict SDK type diagnostics."""
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

from fixture import fetch_fixture

HERE = pathlib.Path(__file__).resolve().parent


def verify():
    for invalid in ['/tmp/pi-remote-0.1.12-opencode', str(HERE), str(HERE / '.scratch/../README.md')]:
        rejected = subprocess.run([sys.executable, str(HERE / 'fixture.py')],
                                  env={**os.environ, 'PI_REMOTE_FIXTURE': invalid}, capture_output=True, text=True)
        assert rejected.returncode != 0 and 'PI_REMOTE_FIXTURE must be' in rejected.stderr
    root = fetch_fixture()
    versions = {'@earendil-works/pi-coding-agent': '0.85.1',
                '@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-agent-core': '0.85.1',
                '@earendil-works/pi-coding-agent/node_modules/typebox': '1.3.7',
                '@earendil-works/pi-ai': '0.85.1', '@earendil-works/pi-tui': '0.85.1', 'ssh2': '1.17.0',
                'typebox': '1.3.28', 'typescript': '5.9.3', '@types/ssh2': '1.15.5', '@types/node': '22.19.0'}
    for package, expected in versions.items():
        actual = json.loads((root / 'node_modules' / package / 'package.json').read_text())['version']
        assert actual == expected, f'{package}: expected {expected}, found {actual}'
        print(f'Test dependency: {package}@{actual}', flush=True)
    spec = importlib.util.spec_from_file_location('adaptation', HERE / 'apply-upstream.py')
    patch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patch)
    before = (root / 'index.ts').read_text()
    after = patch.patched(before)
    for invalid in [before + '\n', before.replace('\n', '\r\n'), after]:
        try:
            patch.patched(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('Patch must reject changed or already-patched input')
    assert hashlib.sha256((HERE / 'managed-projects.ts').read_bytes()).hexdigest() == patch.HELPER
    subprocess.run([sys.executable, str(HERE / 'apply-upstream.py'), str(root), '--check'], check=True, capture_output=True)
    assert (root / 'index.ts').read_text() == before, '--check changed the source'
    subprocess.run([sys.executable, str(HERE / 'apply-upstream.py'), str(root)], check=True, capture_output=True)
    assert (root / 'index.ts').read_text() == after
    assert (root / 'managed-projects.ts').read_bytes() == (HERE / 'managed-projects.ts').read_bytes()
    print('Post SHA256:', hashlib.sha256(after.encode()).hexdigest(), flush=True)
    diff = subprocess.run(['git', 'diff', '--no-index', '--stat', 'commit-index.ts', 'index.ts'], cwd=root, check=False)
    assert diff.returncode == 1
    test_env = {'PATH': os.environ['PATH'], 'HOME': str(root), 'TMPDIR': str(root),
                'JITI_FS_CACHE': 'false', 'PI_REMOTE_FIXTURE': str(root)}
    subprocess.run(['node', '--test', str(HERE / 'test-managed.mjs')], cwd=root, env=test_env, check=True)
    subprocess.run(['node', '--test', str(HERE / 'test-sdk-smoke.mjs')], cwd=root, env=test_env, check=True)
    flags = ['--noEmit', '--module', 'nodenext', '--moduleResolution', 'nodenext', '--target', 'es2022', '--skipLibCheck', '--strict']
    def diagnostics(file):
        result = subprocess.run([str(root / 'node_modules/.bin/tsc'), *flags, file], cwd=root, capture_output=True, text=True)
        print(result.stdout, end='')
        assert result.returncode in (0, 2), result.stderr
        return sorted(line.split('): ', 1)[1] for line in result.stdout.splitlines() if '): ' in line)
    baseline = diagnostics('commit-index.ts')
    actual = diagnostics('index.ts')
    assert actual == baseline, 'New TypeScript diagnostics introduced'
    print(f'PASS: strict pinned SDK diagnostics match upstream baseline ({len(baseline)} existing errors)')


if __name__ == '__main__':
    verify()
