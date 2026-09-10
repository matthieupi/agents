"""Offline startup/resource contract: temporary public assets, no provider state."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('shared_entry_startup', ROOT / 'runtime/entry.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class Startup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / 'home'
        self.home.mkdir(mode=0o700)
        self.resources = self.base / 'public'
        self.resources.mkdir()
        for name in ('commands', 'skills', 'system', 'gsd', 'prompts'):
            (self.resources / name).mkdir()
        self.document = {'agent': {name: {'prompt': '{file:./system/' + name + '.md}',
            'temperature': 0.4, 'mode': 'primary', 'description': name,
            'permission': {'edit': 'ask'}} for name in ('build', 'review')}}
        for name in self.document['agent']:
            (self.resources / 'system' / (name + '.md')).write_text('Public ' + name)
        self.manifest = self.resources / 'opencode-agents.json'
        self.manifest.write_text(json.dumps(self.document))
        self.config = self.home / '.config/opencode'
        entry.directory(self.config)

    def seed(self):
        return entry.seed_opencode(self.home, self.resources)

    def test_config_only_seed_and_idempotence(self):
        entry.initialize('opencode', self.home, self.resources)
        path = self.config / 'config.json'
        before = path.read_bytes()
        document = json.loads(before)
        self.assertEqual(set(document), {'$schema', 'agent'})
        self.assertEqual(document['agent']['build']['prompt'],
                         '{file:' + str(self.resources / 'system/build.md') + '}')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        for name in ('commands', 'skills', 'system', 'gsd'):
            self.assertEqual((self.config / name).readlink(), self.resources / name)
        for name in ('agent', 'agents', 'auth.json'):
            self.assertFalse((self.config / name).exists())
        self.manifest.unlink()  # Existing private seed never needs public inspection.
        self.assertFalse(self.seed()['changed'])
        self.assertEqual(path.read_bytes(), before)

    def test_private_jsonc_override_excluded_not_merged(self):
        private = '// own policy\n{"agent":{"build":{"permission":{"edit":"deny"}}},}'
        path = self.config / 'opencode.jsonc'
        path.write_text(private)
        self.assertEqual(self.seed()['excluded'], ['build'])
        self.assertEqual(set(json.loads((self.config / 'config.json').read_text())['agent']), {'review'})
        self.assertEqual(path.read_text(), private)

    def test_private_policy_and_ambiguous_documents_skip(self):
        for text in ('{"permission":{}}', '{"tools":{}}', '{"mode":{}}', '{"version":1}',
                     '{"agent":[]}', '{"agent":{},"agent":{}}', '[]', '{broken'):
            with self.subTest(text=text):
                (self.config / 'opencode.json').write_text(text)
                self.assertFalse(self.seed()['changed'])
                self.assertFalse((self.config / 'config.json').exists())

    def test_legacy_discovery_preserved(self):
        for name in ('config', 'agent', 'agents', 'mode', 'modes'):
            with self.subTest(name=name):
                path = self.config / name
                path.mkdir()
                self.assertFalse(self.seed()['changed'])
                path.rmdir()

    def test_dangling_private_config_preserved(self):
        for name in ('config.json', 'opencode.json', 'opencode.jsonc'):
            path = self.config / name
            path.symlink_to(self.base / 'absent')
            self.assertFalse(self.seed()['changed'])
            self.assertTrue(path.is_symlink())
            path.unlink()

    def test_all_overrides_and_missing_manifest_skip(self):
        (self.config / 'opencode.json').write_text(json.dumps({'agent': self.document['agent']}))
        self.assertFalse(self.seed()['changed'])
        (self.config / 'opencode.json').unlink()
        self.manifest.unlink()
        self.assertFalse(self.seed()['changed'])

    def test_public_global_settings_never_copied(self):
        self.document.update(permission={'edit': 'allow'}, provider={'fixture': {}}, plugin=['untrusted'])
        self.manifest.write_text(json.dumps(self.document))
        self.seed()
        self.assertEqual(set(json.loads((self.config / 'config.json').read_text())), {'$schema', 'agent'})

    def test_invalid_public_metadata_rejected(self):
        for key, value in [('prompt', '{file:../outside}'), ('temperature', True),
                           ('temperature', 3), ('mode', 'legacy'), ('description', None),
                           ('permission', {'bash': {'*': 'allow'}}), ('provider', {})]:
            with self.subTest(key=key, value=value):
                document = json.loads(json.dumps(self.document))
                document['agent']['build'][key] = value
                self.manifest.write_text(json.dumps(document))
                with self.assertRaises(ValueError):
                    self.seed()
                self.assertFalse((self.config / 'config.json').exists())

    def test_public_redirects_rejected(self):
        outside = self.base / 'outside'
        outside.write_text('Not public')
        prompt = self.resources / 'system/build.md'
        prompt.unlink()
        prompt.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.seed()
        self.manifest.unlink()
        self.manifest.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.seed()

    def test_atomic_publication_preserves_concurrent_writer(self):
        destination = self.config / 'config.json'
        original = os.link

        def concurrent(source, target):
            Path(target).write_text('Concurrent private content')
            return original(source, target)

        with patch.object(entry.os, 'link', side_effect=concurrent):
            self.assertFalse(self.seed()['changed'])
        self.assertEqual(destination.read_text(), 'Concurrent private content')
        self.assertEqual(list(self.config.glob('.opencode-seed-*')), [])

    def test_unsafe_lock_refused_without_repair(self):
        path = self.config / '.runtime-init.lock'
        path.write_text('')
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            self.seed()
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_pi_uses_canonical_prompts_and_individual_system_agents(self):
        entry.initialize('pi', self.home, self.resources)
        root = self.home / '.pi/agent'
        self.assertEqual((root / 'prompts').readlink(), self.resources / 'prompts')
        self.assertFalse((root / 'agents').is_symlink())
        self.assertEqual((root / 'agents/system-build.md').readlink(), self.resources / 'system/build.md')
        self.assertFalse((root / 'AGENTS.md').exists())

    def test_omp_default_persona_and_flattened_skills(self):
        for name in ('direct', 'category/nested'):
            root = self.resources / 'skills' / name
            root.mkdir(parents=True)
            (root / 'SKILL.md').write_text('Public skill')
        entry.initialize('omp', self.home, self.resources)
        root = self.home / '.omp/agent'
        self.assertEqual((root / 'SYSTEM.md').readlink(), self.resources / 'system/build.md')
        for name in ('direct', 'nested'):
            self.assertTrue((root / 'skills' / name / 'SKILL.md').is_file())
        entry.initialize('omp', self.home, self.resources)

    def test_omp_duplicate_skill_names_fail(self):
        for name in ('one/same', 'two/same'):
            root = self.resources / 'skills' / name
            root.mkdir(parents=True)
            (root / 'SKILL.md').write_text('Public skill')
        with self.assertRaises(ValueError):
            entry.initialize('omp', self.home, self.resources)

    def test_custom_resources_preserved_and_conflicting_links_refused(self):
        (self.config / 'commands').mkdir()
        entry.initialize('opencode', self.home, self.resources)
        self.assertFalse((self.config / 'commands').is_symlink())
        (self.config / 'skills').unlink()
        (self.config / 'skills').symlink_to(self.base / 'absent')
        with self.assertRaises(ValueError):
            entry.initialize('opencode', self.home, self.resources)

    def test_no_resources_and_t3_do_not_seed(self):
        for harness in entry.MODES:
            entry.initialize(harness, self.home, None)
        self.assertFalse((self.config / 'config.json').exists())
        self.assertTrue((self.home / 'base').is_dir())
        self.assertEqual((self.home / 'logs').stat().st_mode & 0o777, 0o700)

    def test_t3_existing_data_roots_are_inspected_not_repaired(self):
        entry.initialize('t3', self.home, None)
        root = self.home / 'base'
        for name in ('userdata', 'worktrees', 'caches'):
            path = root / name
            self.assertFalse(path.exists())
            path.symlink_to(self.resources)
            with self.assertRaises(ValueError):
                entry.initialize('t3', self.home, None)
            self.assertTrue(path.is_symlink())
            path.unlink()
            path.mkdir(mode=0o755)
            with self.assertRaises(ValueError):
                entry.initialize('t3', self.home, None)
            self.assertEqual(path.stat().st_mode & 0o777, 0o755)
            path.rmdir()

    def test_main_exec_environment_is_private_and_update_disabled(self):
        environment = {'HOME': str(self.home), 'AGENTS_RUNTIME_SOURCE_MODE': 'baked'}
        with patch.dict(entry.os.environ, environment, clear=True), \
                patch.object(entry, '__file__', '/opt/agents-runtime/entry.py'), \
                patch.object(entry.os, 'getuid', return_value=0), \
                patch.object(entry.os, 'umask'), patch.object(entry, 'initialize') as initialize, \
                patch.object(entry.os, 'execvpe') as execute:
            entry.main(['pi', '--', 'a b', '$(false)'])
            initialize.assert_called_once_with('pi', self.home, None)
            binary, argv, env = execute.call_args.args
            self.assertEqual(argv, [binary, 'a b', '$(false)'])
            for name in ('OPENCODE_DISABLE_AUTOUPDATE', 'PI_WEB_SKIP_VERSION_CHECK',
                         'PI_SKIP_VERSION_CHECK', 'DISABLE_AUTOUPDATER', 'DISABLE_INSTALLATION_CHECKS'):
                self.assertEqual(env[name], '1')
            self.assertEqual(env['PI_CODING_AGENT_DIR'], str(self.home / '.pi/agent'))
            self.assertEqual(env['XDG_STATE_HOME'], str(self.home / '.local/state'))

    def test_command_contract_modes_and_verbatim_arguments(self):
        for harness in ('pi', 'omp', 'opencode', 'claude'):
            argv = ['a b', '$(false)', '--resume']
            self.assertEqual(entry.command(harness, argv, web=False, port=None)[1:], argv)
        for harness in ('pi', 'opencode'):
            command = entry.command(harness, [], web=True, port=4096)
            self.assertIn('0.0.0.0', command)
            self.assertIn('4096', command)
        for harness, web, argv, port in [('omp', True, [], 4096), ('t3', False, [], None),
                                       ('opencode', False, ['upgrade'], None),
                                       ('pi', True, ['extra'], 4096), ('pi', True, [], 80)]:
            with self.assertRaises(ValueError):
                entry.command(harness, argv, web=web, port=port)


if __name__ == '__main__':
    unittest.main()
