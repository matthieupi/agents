"""Parse the Bash installer's flags with real npm. No install or network access."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/entrypoint.sh'


@unittest.skipUnless(shutil.which('npm') and shutil.which('node') and os.geteuid() != 0,
                     'real npm/Node and a non-root runner required')
class NpmConfigTests(unittest.TestCase):
    def test_distinct_empty_configs_and_scripts_enabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            home = stage / 'home'
            home.mkdir()
            for name in ('npm-userrc', 'npm-globalrc'):
                (stage / name).touch()
            (home / '.npmrc').write_text('registry=https://invalid.example/\n')
            text = SCRIPT.read_text()
            flags = list(dict.fromkeys(shlex.split(match)[0].replace('$stage', temporary)
                         for match in re.findall(r'--(?:user|global)config=(?:"[^"]+"|\S+)', text)))
            self.assertEqual(len(flags), 2)
            self.assertNotEqual(flags[0].split('=', 1)[1], flags[1].split('=', 1)[1])
            script_flag, = re.findall(r'--ignore-scripts=\w+', text)
            env = {'HOME': str(home), 'PATH': str(Path(shutil.which('node')).parent) + ':/usr/bin:/bin'}
            for key, expected in [('registry', 'https://registry.npmjs.org/'), ('ignore-scripts', 'false')]:
                result = subprocess.run([shutil.which('npm'), 'config', 'get', key, '--global', *flags, script_flag],
                                        env=env, cwd=home, text=True, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)
