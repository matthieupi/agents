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
        self.document = {'agents': {name: {'system': '{file:./system/' + name + '.md}',
            'request': {'body': {'temperature': 0.4}}, 'mode': 'primary', 'description': name,
            'permissions': [{'action': 'edit', 'resource': '*', 'effect': 'ask'}]} for name in ('build', 'review')}}
        for name in self.document['agents']:
            (self.resources / 'system' / (name + '.md')).write_text('Public ' + name)
        self.manifest = self.resources / 'opencode-agents.json'
        self.manifest.write_text(json.dumps(self.document))
        self.config = self.home / '.config/opencode'
        entry.directory(self.config)
        # Mirror only baked public defaults; never need a real container filesystem.
        self.defaults = self.base / 'defaults'
        self.defaults.mkdir()
        for name in ('opencode.json', 'cli.json'):
            (self.defaults / name).write_text('{}')
        for name in ('plugins', 'tui-plugins', 'system', 'gsd'):
            (self.defaults / name).mkdir()
        for name in ('plugins/first-prompt-title.js', 'plugins/background-subagents.js',
                     'tui-plugins/session-title.mjs', 'tui-plugins/session-title/tui.js'):
            path = self.defaults / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('// canonical ' + name)
        real_path = entry.Path
        self.paths = patch.object(entry, 'Path', side_effect=lambda value: self.defaults if value == '/opt/opencode-defaults' else real_path(value))
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def seed(self):
        return entry.seed_opencode(self.home, self.resources)

    def test_canonical_v2_config_seed_and_shared_prompt_links(self):
        canonical = dict(self.document, providers={'fixture': {'settings': {'apiKey': '{env:FIXTURE_KEY}'}}},
                         permissions=[{'action': '*', 'resource': '*', 'effect': 'allow'}])
        (self.defaults / 'opencode.json').write_text(json.dumps(canonical))
        entry.initialize('opencode', self.home, self.resources)
        self.assertEqual(json.loads((self.config / 'opencode.json').read_text()), canonical)
        self.assertFalse((self.config / 'opencode.json').is_symlink())
        self.assertFalse((self.config / 'config.json').exists())
        self.assertEqual((self.config / 'system').readlink(), self.resources / 'system')
        self.assertFalse((self.config / 'plugins').is_symlink())
        self.assertFalse((self.config / 'tui-plugins').is_symlink())
        self.assertEqual((self.config / 'plugins/background-subagents.js').readlink(),
                         self.defaults / 'plugins/background-subagents.js')
        self.assertEqual((self.config / 'opencode.json').stat().st_mode & 0o777, 0o600)
        before = (self.config / 'opencode.json').read_bytes()
        entry.initialize('opencode', self.home, self.resources)
        self.assertEqual((self.config / 'opencode.json').read_bytes(), before)

    def test_existing_private_plugin_directories_keep_unrelated_files(self):
        for name in ('plugins', 'tui-plugins'):
            path = self.config / name
            path.mkdir(mode=0o755)
            (path / 'private.js').write_text('private plugin')
        entry.initialize('opencode', self.home, self.resources)
        for name in ('plugins', 'tui-plugins'):
            self.assertEqual((self.config / name / 'private.js').read_text(), 'private plugin')
        for relative in ('plugins/first-prompt-title.js', 'plugins/background-subagents.js',
                         'tui-plugins/session-title.mjs', 'tui-plugins/session-title/tui.js'):
            self.assertEqual((self.config / relative).read_bytes(), (self.defaults / relative).read_bytes())

    def test_old_managed_directory_links_become_per_file_links(self):
        for name in ('plugins', 'tui-plugins'):
            (self.config / name).symlink_to(self.defaults / name)
        entry.initialize('opencode', self.home, self.resources)
        for name in ('plugins', 'tui-plugins'):
            self.assertFalse((self.config / name).is_symlink())
        self.assertTrue((self.config / 'tui-plugins/session-title/tui.js').is_file())
        # A new image changes bytes at the stable managed source path.
        (self.defaults / 'plugins/background-subagents.js').write_text('// next image')
        entry.initialize('opencode', self.home, self.resources)
        self.assertEqual((self.config / 'plugins/background-subagents.js').read_text(), '// next image')

    def test_required_private_name_conflict_is_explicit_and_preserved(self):
        (self.config / 'plugins').mkdir()
        conflict = self.config / 'plugins/background-subagents.js'
        conflict.write_text('private override')
        with self.assertRaisesRegex(ValueError, 'plugin name conflict'):
            entry.initialize('opencode', self.home, self.resources)
        self.assertEqual(conflict.read_text(), 'private override')
        self.assertFalse((self.config / 'plugins/first-prompt-title.js').exists())

    def test_unknown_plugin_directory_link_is_not_replaced(self):
        (self.config / 'plugins').symlink_to(self.resources)
        with self.assertRaisesRegex(ValueError, 'Unknown plugin directory link'):
            entry.initialize('opencode', self.home, self.resources)
        self.assertEqual((self.config / 'plugins').readlink(), self.resources)

    def test_v1_home_preserved_and_only_known_retired_kdco_links_removed(self):
        legacy = '{"agent":{"build":{"prompt":"private"}},"provider":{"private":{}},"plugin":[]}'
        (self.config / 'opencode.json').write_text(legacy)
        (self.home / 'session.db').write_text('existing database')
        (self.config / 'plugins').mkdir()
        for name in ('background-agents', 'worktree', 'notify'):
            relative = 'plugins/kdco-' + name + '.ts'
            (self.config / relative).symlink_to(self.defaults / relative)
        (self.config / 'plugins/private.js').write_text('private')
        entry.initialize('opencode', self.home, self.resources)
        self.assertEqual((self.config / 'opencode.json').read_text(), legacy)
        self.assertEqual((self.home / 'session.db').read_text(), 'existing database')
        self.assertEqual((self.config / 'plugins/private.js').read_text(), 'private')
        for name in ('background-agents', 'worktree', 'notify'):
            self.assertFalse((self.config / ('plugins/kdco-' + name + '.ts')).is_symlink())
        self.assertTrue((self.config / 'plugins/background-subagents.js').is_file())

    def test_previous_shared_runtime_seed_moves_without_global_default_injection(self):
        previous = {'$schema': 'https://opencode.ai/config.json', 'agent': {
            'build': {'prompt': '{file:' + str(self.resources / 'system/build.md') + '}',
                      'temperature': 0.4, 'mode': 'primary', 'description': 'build',
                      'permission': {'edit': 'ask'}}}}
        legacy = self.config / 'config.json'
        before = (json.dumps(previous, indent=2) + '\n').encode()
        legacy.write_bytes(before)
        legacy.chmod(0o600)
        inode = legacy.stat().st_ino
        (self.defaults / 'opencode.json').write_text(json.dumps(self.document | {
            'providers': {'public': {}}, 'permissions': [{'action': '*', 'resource': '*', 'effect': 'allow'}]}))
        for _ in range(2):
            entry.initialize('opencode', self.home, self.resources)
            native = self.config / 'opencode.json'
            self.assertEqual(native.read_bytes(), before)
            self.assertEqual(native.stat().st_ino, inode)
            self.assertEqual(native.stat().st_mode & 0o777, 0o600)
            self.assertFalse(legacy.exists())
            self.assertNotIn('providers', json.loads(native.read_text()))
            self.assertNotIn('permissions', json.loads(native.read_text()))

    def test_private_legacy_jsonc_syntax_credentials_and_database_are_preserved(self):
        before = b'// operator policy\n{"agent":{"build":{"temperature":0.1}},"permission":"ask",}\n'
        legacy = self.config / 'config.json'
        legacy.write_bytes(before)
        legacy.chmod(0o640)
        state = self.home / '.local/share/opencode'
        state.mkdir(parents=True)
        for name, content in (('auth.json', b'{"fixture":"private-credential"}'), ('opencode.db', b'private-database\x00')):
            (state / name).write_bytes(content)
        for _ in range(2):
            entry.initialize('opencode', self.home, self.resources)
            self.assertEqual((self.config / 'opencode.json').read_bytes(), before)
            self.assertEqual((self.config / 'opencode.json').stat().st_mode & 0o777, 0o640)
            self.assertEqual((state / 'auth.json').read_bytes(), b'{"fixture":"private-credential"}')
            self.assertEqual((state / 'opencode.db').read_bytes(), b'private-database\x00')
            self.assertFalse(legacy.exists())

    def test_existing_native_jsonc_does_not_seed_global_json_defaults(self):
        before = '// private\n{"agents":{"build":{"system":"private"}},}\n'
        (self.config / 'opencode.jsonc').write_text(before)
        entry.initialize('opencode', self.home, self.resources)
        self.assertEqual((self.config / 'opencode.jsonc').read_text(), before)
        self.assertFalse((self.config / 'opencode.json').exists())

    def test_legacy_and_native_filename_conflicts_are_explicit_and_preserved(self):
        legacy = self.config / 'config.json'
        legacy.write_text('{"permission":"ask"}')
        for name in ('opencode.json', 'opencode.jsonc'):
            with self.subTest(name=name):
                native = self.config / name
                native.write_text('{"permissions":[]}')
                with self.assertRaisesRegex(ValueError, 'reconcile precedence explicitly'):
                    entry.initialize('opencode', self.home, self.resources)
                self.assertEqual(legacy.read_text(), '{"permission":"ask"}')
                self.assertEqual(native.read_text(), '{"permissions":[]}')
                native.unlink()

    def test_malformed_legacy_config_is_preserved_without_seeding_defaults(self):
        legacy = self.config / 'config.json'
        for before in (b'{broken', b'[]', b'{"agent":{},"agent":{}}', b'\xff'):
            with self.subTest(before=before):
                legacy.write_bytes(before)
                with self.assertRaises(ValueError):
                    entry.initialize('opencode', self.home, self.resources)
                self.assertEqual(legacy.read_bytes(), before)
                self.assertFalse((self.config / 'opencode.json').exists())
                self.assertFalse((self.config / 'cli.json').exists())

    def test_redirected_legacy_config_is_preserved_without_seeding_defaults(self):
        outside = self.base / 'private-config'
        outside.write_text('{}')
        legacy = self.config / 'config.json'
        legacy.symlink_to(outside)
        with self.assertRaises(OSError):
            entry.initialize('opencode', self.home, self.resources)
        self.assertEqual(legacy.readlink(), outside)
        self.assertEqual(outside.read_text(), '{}')
        self.assertFalse((self.config / 'opencode.json').exists())

    def test_legacy_move_never_overwrites_a_concurrent_native_file(self):
        legacy, native = self.config / 'config.json', self.config / 'opencode.json'
        legacy.write_text('{"permission":"ask"}')
        original = os.link
        def concurrent(source, destination, **kwargs):
            native.write_text('{"private":"concurrent"}')
            return original(source, destination, **kwargs)
        with patch.object(entry.os, 'link', side_effect=concurrent):
            with self.assertRaises(FileExistsError):
                entry.initialize('opencode', self.home, self.resources)
        self.assertEqual(native.read_text(), '{"private":"concurrent"}')
        self.assertEqual(legacy.read_text(), '{"permission":"ask"}')

    def test_interrupted_legacy_filename_move_recovers_only_its_own_link(self):
        legacy, native = self.config / 'config.json', self.config / 'opencode.json'
        legacy.write_text('{"permission":"ask"}')
        with patch.object(entry.os, 'fsync', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                entry.initialize('opencode', self.home, self.resources)
        self.assertTrue(legacy.exists())
        self.assertEqual(legacy.stat().st_ino, native.stat().st_ino)
        entry.initialize('opencode', self.home, self.resources)
        self.assertFalse(legacy.exists())
        self.assertEqual(native.read_text(), '{"permission":"ask"}')

    def test_shared_resource_retired_links_are_removed_without_following_them(self):
        (self.config / 'plugins').mkdir()
        wrapper = self.config / 'plugins/kdco-notify.ts'
        wrapper.symlink_to('/opt/agent/opencode-plugins/plugins/kdco-notify.ts')
        entry.initialize('opencode', self.home, self.resources)
        self.assertFalse(wrapper.is_symlink())

    def test_unknown_retired_kdco_link_is_preserved_and_blocks_startup(self):
        (self.config / 'plugins').mkdir()
        wrapper = self.config / 'plugins/kdco-notify.ts'
        wrapper.symlink_to(self.resources / 'private.ts')
        with self.assertRaisesRegex(ValueError, 'Unrecognized retired KDCO'):
            entry.initialize('opencode', self.home, self.resources)
        self.assertEqual(wrapper.readlink(), self.resources / 'private.ts')

    def test_unknown_retired_kdco_wrapper_blocks_startup_without_deletion(self):
        (self.config / 'plugins').mkdir()
        wrapper = self.config / 'plugins/kdco-worktree.ts'
        wrapper.write_text('private wrapper')
        with self.assertRaisesRegex(ValueError, 'Unrecognized retired KDCO'):
            entry.initialize('opencode', self.home, self.resources)
        self.assertEqual(wrapper.read_text(), 'private wrapper')

    def test_config_only_seed_and_idempotence(self):
        self.seed()
        path = self.config / 'opencode.json'
        before = path.read_bytes()
        document = json.loads(before)
        self.assertEqual(set(document), {'$schema', 'agents'})
        self.assertEqual(document['agents']['build']['system'],
                         '{file:' + str(self.resources / 'system/build.md') + '}')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        entry.initialize('opencode', self.home, self.resources)
        for name in ('commands', 'skills', 'system', 'gsd'):
            self.assertEqual((self.config / name).readlink(), self.resources / name)
        for name in ('agent', 'agents', 'auth.json'):
            self.assertFalse((self.config / name).exists())
        self.manifest.unlink()  # Existing private seed never needs public inspection.
        self.assertFalse(self.seed()['changed'])
        self.assertEqual(path.read_bytes(), before)

    def test_private_jsonc_override_excluded_not_merged(self):
        private = '// own policy\n{"agents":{"build":{"permissions":[{"action":"edit","resource":"*","effect":"deny"}]}},}'
        path = self.config / 'opencode.jsonc'
        path.write_text(private)
        self.assertEqual(self.seed()['excluded'], ['build'])
        self.assertEqual(set(json.loads((self.config / 'opencode.json').read_text())['agents']), {'review'})
        self.assertEqual(path.read_text(), private)

    def test_private_policy_and_ambiguous_documents_skip(self):
        for text in ('{"permission":{}}', '{"tools":{}}', '{"mode":{}}', '{"version":1}',
                     '{"agent":[]}', '{"agent":{},"agent":{}}', '[]', '{broken'):
            with self.subTest(text=text):
                (self.config / 'opencode.jsonc').write_text(text)
                self.assertFalse(self.seed()['changed'])
                self.assertFalse((self.config / 'opencode.json').exists())

    def test_no_v1_isolation_or_discovery_seed(self):
        for name in ('config', 'agent', 'agents', 'mode', 'modes'):
            with self.subTest(name=name):
                path = self.config / name
                path.mkdir()
                self.assertTrue(self.seed()['changed'])
                (self.config / 'opencode.json').unlink()
                path.rmdir()

    def test_dangling_private_config_preserved(self):
        for name in ('opencode.json', 'opencode.jsonc'):
            path = self.config / name
            path.symlink_to(self.base / 'absent')
            self.assertFalse(self.seed()['changed'])
            self.assertTrue(path.is_symlink())
            path.unlink()

    def test_all_overrides_and_missing_manifest_skip(self):
        (self.config / 'opencode.json').write_text(json.dumps({'agents': self.document['agents']}))
        self.assertFalse(self.seed()['changed'])
        (self.config / 'opencode.json').unlink()
        self.manifest.unlink()
        self.assertFalse(self.seed()['changed'])

    def test_public_global_settings_never_copied(self):
        self.document.update(permissions=[], providers={'fixture': {}}, plugins=['untrusted'])
        self.manifest.write_text(json.dumps(self.document))
        self.seed()
        self.assertEqual(set(json.loads((self.config / 'opencode.json').read_text())), {'$schema', 'agents'})

    def test_invalid_public_metadata_rejected(self):
        for key, value in [('system', '{file:../outside}'), ('temperature', True),
                           ('temperature', 3), ('mode', 'legacy'), ('description', None),
                           ('permission', {'bash': {'*': 'allow'}}), ('provider', {})]:
            with self.subTest(key=key, value=value):
                document = json.loads(json.dumps(self.document))
                document['agents']['build'][key] = value
                self.manifest.write_text(json.dumps(document))
                with self.assertRaises(ValueError):
                    self.seed()
                self.assertFalse((self.config / 'opencode.json').exists())

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
        destination = self.config / 'opencode.json'
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
        self.assertTrue((self.config / 'opencode.json').is_file())
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
            path.chmod(0o755)  # Do not inherit a previous test's process umask.
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
            offset = 3 if harness == 'opencode' else 1
            self.assertEqual(entry.command(harness, argv, web=False, port=None)[offset:], argv)
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
