"""Exercise maintained publication through Make into the real common startup."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('publication_startup', ROOT / 'runtime/entry.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class Publication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.resources = self.base / 'reviewed public'
        self.resources.mkdir()
        for name in ('system', 'gsd', 'commands', 'skills'):
            (self.resources / name).mkdir()
        self.home = self.base / 'home'
        self.home.mkdir(mode=0o700)
        self.config = self.home / '.config/opencode'
        entry.directory(self.config)
        self.canonical = json.loads((ROOT / 'opencode/.opencode/config/opencode.json').read_text())
        for agent in self.canonical['agent'].values():
            relative = agent['prompt'][8:-1]
            shutil.copyfile(ROOT / 'agent' / relative, self.resources / relative)

    def publish(self):
        return subprocess.run(['make', '-C', str(ROOT / 'runtime'), 'resources',
                               'RESOURCES=' + str(self.resources)], capture_output=True, text=True)

    def test_generated_manifest_registers_real_agents_end_to_end(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.resources / 'opencode-agents.json'
        self.assertEqual(json.loads(manifest.read_text()), {'agent': self.canonical['agent']})
        self.assertEqual(manifest.stat().st_mode & 0o777, 0o644)
        entry.initialize('opencode', self.home, self.resources)
        seeded = json.loads((self.config / 'config.json').read_text())
        self.assertEqual(seeded, entry.public_agents(self.canonical, self.resources))
        for agent in seeded['agent'].values():
            self.assertTrue(Path(agent['prompt'][6:-1]).is_file())
        inode = manifest.stat().st_ino
        self.assertEqual(self.publish().returncode, 0)
        self.assertEqual(manifest.stat().st_ino, inode)

    def test_generated_resources_preserve_private_provider_plugin_and_policy(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        private = {'provider': {'private': {'options': {'apiKey': 'fixture-only'}}},
                   'plugin': ['private-plugin'], 'agent': {'explore': {'disable': True}}}
        path = self.config / 'opencode.json'
        original = json.dumps(private)
        path.write_text(original)
        entry.initialize('opencode', self.home, self.resources)
        seeded = json.loads((self.config / 'config.json').read_text())
        self.assertEqual(set(seeded), {'$schema', 'agent'})
        self.assertNotIn('explore', seeded['agent'])
        self.assertEqual(path.read_text(), original)
        (self.config / 'config.json').unlink()
        private['permission'] = {'edit': 'deny'}
        original = json.dumps(private)
        path.write_text(original)
        entry.initialize('opencode', self.home, self.resources)
        self.assertFalse((self.config / 'config.json').exists())
        self.assertEqual(path.read_text(), original)

    def test_publication_collision_is_preserved(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.resources / 'opencode-agents.json'
        manifest.write_text('operator-owned conflict')
        self.assertNotEqual(self.publish().returncode, 0)
        self.assertEqual(manifest.read_text(), 'operator-owned conflict')

    def test_publication_requires_explicit_destination_and_physical_prompts(self):
        result = subprocess.run(['make', '-C', str(ROOT / 'runtime'), 'resources', 'RESOURCES='],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        prompt = self.resources / 'system/explore.md'
        prompt.unlink()
        self.assertNotEqual(self.publish().returncode, 0)
        prompt.symlink_to(ROOT / 'agent/system/explore.md')
        self.assertNotEqual(self.publish().returncode, 0)
