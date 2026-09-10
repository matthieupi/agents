"""Static image recipe contracts; never build images or access the network."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('image_installer', ROOT / 'install.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)
CATALOG = json.loads((ROOT / 'harnesses.json').read_text())
RECIPES = {name: (ROOT / spec['dockerfile']).read_text()
           for name, spec in CATALOG['harnesses'].items()}


class ImageRecipeTests(unittest.TestCase):
    def test_ca_bootstrap_precedes_https_install(self):
        for name, recipe in RECIPES.items():
            with self.subTest(harness=name):
                flat = recipe.replace('\\\n', ' ')
                steps = [step.strip() for step in flat.split('&&')]
                bootstrap = steps.index('apt-get install -y --no-install-recommends ca-certificates')
                restore = steps.index('cp /tmp/apt.sources /etc/apt/sources.list.d/debian.sources')
                updates = [i for i, step in enumerate(steps) if step == 'apt-get update']
                self.assertEqual(len(updates), 2)
                self.assertLess(updates[0], bootstrap)
                self.assertLess(bootstrap, restore)
                self.assertLess(restore, updates[1])
                self.assertIn('rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*', flat)
                self.assertLess(flat.index('rm -f /etc/apt/sources.list'), flat.index('apt-get update'))
                self.assertIn('COPY apt.sources /tmp/apt.sources', recipe)
                self.assertIn('rm -f /tmp/apt.sources', flat)

    def test_bootstrap_preserves_selected_signed_snapshots(self):
        for name, recipe in RECIPES.items():
            with self.subTest(harness=name):
                match = re.search(r"sed '([^']+)' /tmp/apt.sources > /etc/apt/sources.list.d/debian.sources", recipe)
                self.assertIsNotNone(match, 'Bootstrap must transform the generated sources, not select new archives')
                for timestamp in ('20260910T000000Z', '20250102T030405Z'):
                    sources = installer.apt_sources({'timestamp': timestamp})
                    # Execute only the extracted sed expression, not Dockerfile shell.
                    bootstrap = subprocess.run(['sed', '-e', match[1]], input=sources,
                                               text=True, capture_output=True, check=True).stdout
                    self.assertEqual(bootstrap, sources.replace('https://snapshot.debian.org/',
                                                                'http://snapshot.debian.org/'))
                    self.assertEqual(bootstrap.count(timestamp), 3)
                    self.assertEqual(bootstrap.count('Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg'), 3)
                    self.assertEqual(bootstrap.count('Check-Valid-Until: no'), 3)
                    self.assertNotIn('https://', bootstrap)

    def test_no_insecure_verification_overrides(self):
        forbidden = r'(?i)trusted\s*[:=]\s*(?:yes|true)|allow-unauthenticated|allow-insecure|allowdowngradetoinsecure|verify-(?:peer|host)|check-certificate|curl\s+.*(?:--insecure| -k\b)'
        for name, recipe in RECIPES.items():
            with self.subTest(harness=name):
                self.assertNotRegex(recipe, forbidden)
                self.assertNotRegex(installer.apt_sources({'timestamp': '20260910T000000Z'}), forbidden)

    def test_package_hooks_are_nonroot_offline_with_bundled_headers(self):
        for name, recipe in RECIPES.items():
            with self.subTest(harness=name):
                user = None
                hooks = []
                for line in recipe.splitlines():
                    if line.startswith('USER '):
                        user = line.split()[1]
                    if 'npm ci ' in line:
                        self.assertEqual(user, 'node')
                        self.assertIn('--ignore-scripts', line)
                        self.assertIn('--no-audit --no-fund', line)
                        if '/opt/opencode-defaults/kdco' not in line:
                            self.assertIn('--include=optional', line)
                    if 'npm rebuild ' in line:
                        hooks.append(line)
                        self.assertEqual(user, 'node')
                        self.assertTrue(line.startswith('RUN --network=none '))
                        self.assertIn('npm_config_nodedir=/usr/local npm rebuild --offline', line)
                self.assertEqual(len(hooks), 1)
                self.assertLess(recipe.index('npm ci '), recipe.index('npm rebuild '))

    def test_startup_and_package_receipts(self):
        for name, recipe in RECIPES.items():
            with self.subTest(harness=name):
                self.assertIn('ARG NODE_IMAGE\nFROM ${NODE_IMAGE}', recipe)
                self.assertIn(f'io.agents-runtime.harness="{name}" io.agents-runtime.contract="1"', recipe)
                self.assertIn('COPY entry.py harnesses.json /opt/agents-runtime/', recipe)
                self.assertIn('package.json package-lock.json /opt/agents-runtime/packages/', recipe)
                self.assertIn('dpkg-query -W > /opt/agents-runtime/os-packages.tsv', recipe)
                self.assertIn('chmod -R a+rX,a-w /opt/agents-runtime', recipe)
                self.assertIn('python3 libnss-wrapper', recipe)
                entrypoint = next(line for line in recipe.splitlines() if line.startswith('ENTRYPOINT '))
                self.assertEqual(json.loads(entrypoint.removeprefix('ENTRYPOINT ')),
                                 ['/usr/bin/python3', '-I', '/opt/agents-runtime/entry.py', name])
                self.assertEqual(re.findall(r'^USER (.+)$', recipe, re.M)[-1], 'node')
                if name == 'omp':
                    self.assertIn('test "$(dpkg --print-architecture)" = amd64', recipe)


if __name__ == '__main__':
    unittest.main()
