"""Prior-release HOME migration: real public historical bytes, never user state."""
import base64
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from previous_opencode import COMMIT, historical, previous_home
from test_opencode_v2 import CANONICAL, canonical_prompts, load

entry = load('entry')


class ExistingHomeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        self.home, self.resources = self.parent / 'home', self.parent / 'resources'
        self.home.mkdir(mode=0o700)
        for name in ('system', 'gsd', 'commands', 'skills'):
            (self.resources / name).mkdir(parents=True)
        for relative, text in canonical_prompts().items():
            (self.resources / relative).write_text(text)
        self.public = json.loads((CANONICAL / 'opencode.json').read_text())
        (self.resources / 'opencode-agents.json').write_text(json.dumps(self.public))
        for name in ('cli.json', 'plugins/first-prompt-title.js', 'plugins/background-subagents.js',
                     'tui-plugins/session-title.mjs', 'tui-plugins/session-title/tui.js'):
            destination = self.resources / 'opencode-config' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((CANONICAL / name).read_bytes())
        self.root = self.home / '.config/opencode'
        self.root.mkdir(mode=0o700, parents=True)
        self.previous = previous_home(self.resources)
        (self.root / 'config.json').write_text(self.previous['config'])
        for name, encoded in self.previous['assets'].items():
            destination = self.root / name
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination.write_bytes(base64.b64decode(encoded))
        (self.root / 'kdco').symlink_to(self.resources / 'opencode-plugins/kdco')
        (self.root / 'auth.json').write_bytes(b'private-credential-fixture')
        self.database = self.home / '.local/share/opencode/private-existing.db'
        self.database.parent.mkdir(parents=True)
        with sqlite3.connect(self.database) as connection:
            connection.execute('create table private_state(value text)')
            connection.execute('insert into private_state values (?)', ('private fixture',))

    def test_actual_previous_projection_and_assets_migrate_without_private_state_loss(self):
        self.assertEqual(self.previous['commit'], COMMIT)
        self.assertTrue(entry.managed_legacy_agents(json.loads(self.previous['config']), self.resources))
        private = {'model': 'openai/private-model', 'agent': {'build': {'permission': {'edit': 'deny'}}},
                   'provider': {'openai': {'options': {'apiKey': 'private-key-fixture'}}},
                   'plugin': ['./plugins/kdco-worktree.ts', ['unrelated-plugin', {'preference': True}]]}
        (self.root / 'opencode.json').write_text(json.dumps(private))
        cli = {'theme': {'name': 'private-theme'}, 'keybinds': {'leader': 'ctrl+x'}, 'plugins': ['unrelated-tui']}
        (self.root / 'cli.json').write_text(json.dumps(cli))
        database = self.database.read_bytes()
        first = entry.seed_opencode(self.home, self.resources)
        self.assertTrue(first['changed'])
        self.assertFalse((self.root / 'config.json').exists())
        managed = json.loads((self.root / 'opencode.json').read_text())
        self.assertEqual(set(managed['agents']), {'explore'})
        self.assertNotIn('providers', managed)
        self.assertNotIn('permissions', managed)
        updated = json.loads((self.root / 'opencode.json').read_text())
        for key in ('model', 'agent', 'provider'):
            self.assertEqual(updated[key], private[key])
        self.assertEqual(updated['plugin'], [private['plugin'][1], *(
            str(self.root / 'plugins' / name) for name in entry.SERVER_PLUGINS)])
        updated_cli = json.loads((self.root / 'cli.json').read_text())
        self.assertEqual(updated_cli['theme'], cli['theme'])
        self.assertEqual(updated_cli['keybinds'], cli['keybinds'])
        self.assertEqual(updated_cli['plugins'], ['unrelated-tui', './tui-plugins/session-title'])
        for name in ('plugins/first-prompt-title.js', 'tui-plugins/session-title.mjs'):
            self.assertEqual((self.root / name).resolve(), self.resources / 'opencode-config' / name)
        for name in ('kdco', *('plugins/' + name for name in entry.RETIRED)):
            self.assertFalse((self.root / name).exists() or (self.root / name).is_symlink())
        self.assertEqual((self.root / 'auth.json').read_bytes(), b'private-credential-fixture')
        self.assertEqual(self.database.read_bytes(), database)
        before = {p: p.read_bytes() for p in (self.root / 'opencode.json', self.root / 'cli.json')}
        self.assertFalse(entry.seed_opencode(self.home, self.resources)['changed'])
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.assertEqual(set(self.parent.iterdir()), {self.home, self.resources})
        self.assertFalse(any('archive' in p.name or p.name.endswith('.bak') or p.name.endswith('-v1')
                             for p in self.home.rglob('*')))

    def test_modified_agent_only_config_is_private_not_managed(self):
        private = json.loads(self.previous['config'])
        private['agent']['build']['description'] = 'Private modified description'
        self.assertFalse(entry.managed_legacy_agents(private, self.resources))
        (self.root / 'config.json').write_text(json.dumps(private))
        (self.root / 'config.json').chmod(0o640)
        entry.seed_opencode(self.home, self.resources)
        self.assertFalse((self.root / 'config.json').exists())
        updated = json.loads((self.root / 'opencode.json').read_text())
        self.assertEqual((self.root / 'opencode.json').stat().st_mode & 0o777, 0o640)
        self.assertEqual(updated['agent'], private['agent'])
        self.assertNotIn('agents', updated)
        self.assertNotIn('providers', updated)
        self.assertIn(str(self.root / 'plugins/background-subagents.js'), updated['plugins'])

    def test_current_regular_defaults_and_existing_v2_registration_reconcile(self):
        for name in ('plugins/first-prompt-title.js', 'tui-plugins/session-title.mjs'):
            (self.root / name).write_bytes((CANONICAL / name).read_bytes())
        (self.root / 'config.json').unlink()
        private = {'agents': {'build': {'disabled': True}}, 'permissions': [],
                   'plugins': ['unrelated-plugin', './plugins/first-prompt-title.js']}
        (self.root / 'opencode.json').write_text(json.dumps(private))
        entry.seed_opencode(self.home, self.resources)
        updated = json.loads((self.root / 'opencode.json').read_text())
        self.assertEqual(updated['agents'], private['agents'])
        self.assertEqual(updated['permissions'], [])
        self.assertEqual(updated['plugins'], ['unrelated-plugin', *(
            str(self.root / 'plugins' / name) for name in entry.SERVER_PLUGINS)])
        self.assertTrue((self.root / 'plugins/first-prompt-title.js').is_symlink())
        self.assertFalse(entry.seed_opencode(self.home, self.resources)['changed'])

    def test_private_discovery_is_not_blanket_rejected_or_given_global_defaults(self):
        (self.root / 'config.json').unlink()
        (self.root / 'agents').mkdir(mode=0o700)
        private = self.root / 'agents/private.md'
        private.write_text('---\npermission:\n  edit: deny\n---\nPrivate instructions\n')
        original = private.read_bytes()
        entry.seed_opencode(self.home, self.resources)
        self.assertEqual(private.read_bytes(), original)
        document = json.loads((self.root / 'opencode.json').read_text())
        self.assertEqual(set(document), {'$schema', 'plugins'})

    def test_private_filename_move_recovers_after_native_publication(self):
        private = {'agent': {'build': {'description': 'private'}}, 'permission': {'edit': 'deny'}}
        old = self.root / 'config.json'
        old.write_text(json.dumps(private))
        unlink = Path.unlink
        def interrupted(path, *args, **kwargs):
            if path == old:
                raise OSError('simulated interruption before old filename retirement')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', interrupted):
            with self.assertRaisesRegex(OSError, 'simulated interruption'):
                entry.seed_opencode(self.home, self.resources)
        self.assertTrue(old.is_file())
        self.assertTrue((self.root / 'opencode.json').is_file())
        self.assertTrue(entry.seed_opencode(self.home, self.resources)['changed'])
        self.assertFalse(old.exists())
        self.assertEqual(json.loads((self.root / 'opencode.json').read_text())['agent'], private['agent'])
        self.assertFalse(entry.seed_opencode(self.home, self.resources)['changed'])

    def test_jsonc_private_v1_settings_are_preserved_without_conversion(self):
        private = {'model': 'openai/private-model', 'agent': {'build': {'temperature': 0.7}},
                   'permission': {'edit': 'deny'}, 'plugin': ['unrelated-plugin']}
        (self.root / 'opencode.jsonc').write_text('// private comment\n' + json.dumps(private)[:-1] + ',}\n')
        entry.seed_opencode(self.home, self.resources)
        updated = entry.read_jsonc((self.root / 'opencode.jsonc').read_text())
        for key in ('model', 'agent', 'permission'):
            self.assertEqual(updated[key], private[key])
        self.assertEqual(updated['plugin'][0], 'unrelated-plugin')
        self.assertFalse((self.root / 'opencode.json').exists())

    def test_modified_title_preflights_without_retiring_other_assets(self):
        title = self.root / 'tui-plugins/session-title.mjs'
        title.write_bytes(title.read_bytes() + b'\n// private modification\n')
        before = (self.root / 'config.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            entry.seed_opencode(self.home, self.resources)
        self.assertFalse((self.root / 'plugins/first-prompt-title.js').is_symlink())
        self.assertTrue((self.root / 'kdco').is_symlink())
        self.assertEqual((self.root / 'config.json').read_bytes(), before)
        self.assertTrue(title.read_bytes().endswith(b'// private modification\n'))

    def test_modified_wrapper_and_unknown_targets_are_never_removed(self):
        wrapper = self.root / 'plugins/kdco-worktree.ts'
        wrapper.write_bytes(wrapper.read_bytes() + b'// custom\n')
        with self.assertRaisesRegex(ValueError, 'Unknown retired KDCO'):
            entry.seed_opencode(self.home, self.resources)
        self.assertTrue(wrapper.read_bytes().endswith(b'// custom\n'))
        wrapper.unlink()
        wrapper.symlink_to(self.resources / 'unknown/kdco-worktree.ts')
        with self.assertRaisesRegex(ValueError, 'Unknown retired KDCO'):
            entry.seed_opencode(self.home, self.resources)
        self.assertEqual(wrapper.readlink(), self.resources / 'unknown/kdco-worktree.ts')

    def test_exact_historical_publisher_symlinks_are_retired_even_when_dangling(self):
        for name in entry.RETIRED:
            path = self.root / 'plugins' / name
            path.unlink()
            path.symlink_to(self.resources / 'opencode-plugins/plugins' / name)
        entry.seed_opencode(self.home, self.resources)
        self.assertTrue(all(not (self.root / 'plugins' / name).is_symlink() for name in entry.RETIRED))

    def test_unknown_active_kdco_registration_preserves_everything(self):
        private = {'plugin': ['/unknown/kdco-worktree.ts']}
        (self.root / 'opencode.json').write_text(json.dumps(private))
        with self.assertRaisesRegex(ValueError, 'Unknown active KDCO'):
            entry.seed_opencode(self.home, self.resources)
        self.assertTrue((self.root / 'kdco').is_symlink())
        self.assertEqual(json.loads((self.root / 'opencode.json').read_text()), private)

    def test_fingerprints_are_verified_against_immutable_history(self):
        import hashlib
        evidence = entry.legacy_evidence()
        self.assertEqual(evidence['source_commit'], COMMIT)
        for name, fingerprint in evidence['asset_sha256'].items():
            self.assertEqual(hashlib.sha256(historical('opencode/.opencode/config/' + name)).hexdigest(), fingerprint)
        previous = json.loads(historical('opencode/.opencode/config/opencode.json'))
        for name, fingerprint in evidence['agent_sha256'].items():
            serialized = json.dumps(previous['agent'][name], sort_keys=True, separators=(',', ':')).encode()
            self.assertEqual(hashlib.sha256(serialized).hexdigest(), fingerprint)


if __name__ == '__main__':
    unittest.main()
