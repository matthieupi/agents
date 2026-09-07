"""Exercise the installer's config flags with real npm, without installing/network."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/entrypoint.sh'


@unittest.skipUnless(shutil.which('npm'), 'real npm required')
class NpmConfigTests(unittest.TestCase):
    def probe(self, poisoned_home=False):
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            (stage / 'npm-globalrc').touch(mode=0o644)
            if poisoned_home:
                (stage / '.npmrc').write_text('registry=https://example.invalid/\n')
            text = SCRIPT.read_text()
            flags = [shlex.split(match)[0].replace('$stage', temporary)
                     for match in re.findall(r'--(?:user|global)config=(?:"[^"]+"|\S+)', text)]
            self.assertEqual(len(flags), 2)
            return subprocess.run([shutil.which('npm'), 'config', 'get', 'registry', '--global', *flags],
                                  env={'HOME': temporary, 'PATH': os.environ['PATH']},
                                  cwd=temporary, text=True, capture_output=True, timeout=15)

    def test_distinct_config_sources_are_accepted_by_real_npm(self):
        result = self.probe()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_configs_preserve_public_registry_default(self):
        result = self.probe()
        self.assertEqual(result.stdout.strip(), 'https://registry.npmjs.org/', result.stderr)

    def test_home_npmrc_cannot_redirect_installer(self):
        result = self.probe(poisoned_home=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'https://registry.npmjs.org/')
