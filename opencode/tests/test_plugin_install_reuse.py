"""Hermetic workstation initialization regression: real Bash/Node, fixture npm."""
import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


COMPONENT = Path(__file__).resolve().parents[1]


class InstallFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='kdco-install-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'home'
        self.config = self.home / '.config/opencode'
        self.package = self.config / 'kdco'
        self.package.mkdir(parents=True)
        (self.config / 'plugins').mkdir()
        for name in ('background-agents', 'worktree', 'notify'):
            (self.config / f'plugins/kdco-{name}.ts').write_text('export default async () => ({})\n')
        (self.package / 'package.json').write_text('{"name":"fixture","version":"1.0.0","private":true}')
        (self.package / 'package-lock.json').write_text(
            '{"name":"fixture","lockfileVersion":3,"packages":{"":{"name":"fixture","version":"1.0.0"}}}')
        binary = self.root / 'bin'
        binary.mkdir()
        self.calls = self.root / 'npm-calls'
        npm = binary / 'npm'
        npm.write_text('''#!/bin/bash
set -eu
printf 'ci\n' >> "$CALLS"
root="$PWD"
if [[ ${2:-} == --prefix ]]; then root="$3"; fi
sleep 0.1
rm -rf -- "$root/node_modules"
mkdir -p "$root/node_modules"
if [[ ${FAIL_INSTALL:-} == 1 ]]; then
    printf partial > "$root/node_modules/fixture"
    exit 42
fi
printf fixture > "$root/node_modules/fixture"
''')
        npm.chmod(0o755)
        self.env = dict(os.environ, PATH=str(binary) + ':' + os.environ['PATH'], CALLS=str(self.calls))
        script = (COMPONENT / 'init.sh').read_text()
        self.script = script.replace('HOME_ROOT="/home/opencode"', f'HOME_ROOT="{self.home}"')
        self.script = self.script.replace('DEFAULTS_ROOT="/opt/agent"', f'DEFAULTS_ROOT="{self.root / "absent-resources"}"')
        self.script = self.script.replace('/opt/opencode-publish-plugins.mjs', str(COMPONENT / 'scripts/publish-plugins.mjs'))

    def initialize(self):
        return subprocess.run(['/bin/bash', '-c', self.script], env=self.env, text=True, capture_output=True, timeout=120)

    def successful(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def installs(self):
        return len(self.calls.read_text().splitlines()) if self.calls.exists() else 0


class Reuse(InstallFixture):
    def test_unchanged_repeated_init_does_not_run_npm_again(self):
        self.successful(self.initialize())
        self.successful(self.initialize())
        self.assertEqual(self.installs(), 1, 'unchanged initialization must be offline and non-destructive')


@unittest.skipUnless(os.environ.get('KDCO_REAL_NPM_TEST') == '1', 'opt-in public npm installation in disposable directory')
class RealNpm(InstallFixture):
    def test_real_locked_install_then_no_npm_reuse_then_corruption_repair(self):
        for name in ('package.json', 'package-lock.json'):
            (self.package / name).write_bytes((COMPONENT / '.opencode/config/kdco' / name).read_bytes())
        for name in ('userrc', 'globalrc'):
            (self.root / name).touch()
        fixture_path = self.env['PATH']
        self.env.update(PATH=os.environ['PATH'], HOME=str(self.home),
                        NPM_CONFIG_USERCONFIG=str(self.root / 'userrc'),
                        NPM_CONFIG_GLOBALCONFIG=str(self.root / 'globalrc'),
                        NPM_CONFIG_CACHE=str(self.root / 'npm-cache'),
                        NPM_CONFIG_FETCH_TIMEOUT='30000', NPM_CONFIG_FETCH_RETRIES='0')
        first = self.initialize()
        self.successful(first)
        self.assertEqual(json.loads(first.stdout), {'changed': True})
        # An unchanged launch must not invoke npm at all, even when it would fail.
        (self.root / 'bin/npm').write_text('#!/bin/bash\nexit 99\n')
        self.env['PATH'] = fixture_path
        repeated = self.initialize()
        self.successful(repeated)
        self.assertEqual(json.loads(repeated.stdout), {'changed': False})
        artifact = self.package / 'node_modules/unique-names-generator/package.json'
        original = artifact.read_bytes()
        artifact.write_bytes(original + b'\n')
        self.env['PATH'] = os.environ['PATH']
        repaired = self.initialize()
        self.successful(repaired)
        self.assertEqual(json.loads(repaired.stdout), {'changed': True})
        self.assertEqual(artifact.read_bytes(), original)
