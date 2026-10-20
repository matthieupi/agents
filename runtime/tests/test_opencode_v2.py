"""V2 public source closure, immutable build evidence and credential isolation."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_shared_runtime as fixtures

installer, entry, runtime, ROOT, ID = fixtures.installer, fixtures.entry, fixtures.runtime, fixtures.ROOT, fixtures.ID


class V2Build(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'runtime'
        self.root.mkdir()
        for source in installer.build_sources('opencode', installer.catalog()):
            destination = self.root / source
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / source).read_bytes())
        self.resolution = fixtures.Installation().resolution()
        self.resolution['source'] = self.record()

    def record(self):
        with patch.object(installer.subprocess, 'run', return_value=Mock(stdout='a' * 40)):
            return installer.source_record(self.root, 'opencode')

    def test_exact_finite_public_closure(self):
        sources = installer.build_sources('opencode', installer.catalog(), self.root)
        for expected in ('plugins/background-subagents.js', 'plugins/first-prompt-title.js',
                         'tui-plugins/session-title.mjs', 'tui-plugins/session-title/tui.js', 'cli.json'):
            self.assertIn('opencode-defaults/' + expected, sources.values())
        self.assertTrue(any(name.startswith('../agent/system/') for name in sources))
        self.assertFalse(any('kdco' in name or 'package-lock' in name for name in sources))
        for harness in ('pi', 'omp', 't3', 'claude'):
            self.assertEqual(len(installer.build_sources(harness, installer.catalog())), 4)

    def test_every_source_byte_is_bound(self):
        sources = installer.build_sources('opencode', installer.catalog(), self.root)
        for name in sources:
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b' ')
                with patch.object(installer.subprocess, 'run', return_value=Mock(stdout='a' * 40)), \
                        patch.object(installer, 'ordinary'), patch.object(installer, 'docker') as docker:
                    with self.assertRaises((ValueError, json.JSONDecodeError)):
                        installer.build('opencode', self.root, self.resolution, refresh=False)
                    docker.assert_not_called()
                path.write_bytes(original)

    def test_missing_and_symlink_sources_refused(self):
        path = self.root / '../opencode/.opencode/config/plugins/first-prompt-title.js'
        content = path.read_bytes()
        path.unlink()
        with self.assertRaises(OSError):
            self.record()
        other = self.root / 'unlisted'
        other.write_bytes(content)
        path.symlink_to(other)
        with self.assertRaises(ValueError):
            self.record()

    def test_lifecycle_approval_cannot_be_broadened(self):
        resolution = fixtures.Installation().resolution()
        resolution['package']['allowScripts']['unreviewed'] = True
        with self.assertRaisesRegex(ValueError, 'lifecycle'):
            installer.validate_resolution('opencode', ROOT, resolution)

    def test_copy_time_drift_refused_after_validation(self):
        def validated(*args):
            path = self.root / '../opencode/.opencode/config/plugins/first-prompt-title.js'
            path.write_bytes(path.read_bytes() + b' ')
            return installer.catalog()
        with patch.object(installer, 'validate_resolution', side_effect=validated), \
                patch.object(installer, 'ordinary'), patch.object(installer, 'docker') as docker:
            with self.assertRaisesRegex(ValueError, 'while copying'):
                installer.build('opencode', self.root, self.resolution, refresh=False)
            docker.assert_not_called()

    def test_exact_context_bytes_and_immutable_receipt(self):
        resolution = self.resolution
        def docker(argv, **kwargs):
            if argv[0] == 'build':
                context = Path(argv[-1])
                for source, destination in installer.build_sources('opencode', installer.catalog(), self.root).items():
                    self.assertEqual((context / destination).read_bytes(), (self.root / source).read_bytes())
                self.assertEqual(json.loads((context / 'package.json').read_text())['allowScripts'], {'@opencode/cli': True})
                self.assertFalse((context / 'opencode-plugins').exists())
                Path(argv[argv.index('--iidfile') + 1]).write_text(ID)
                return subprocess.CompletedProcess(argv, 0)
            return subprocess.CompletedProcess(argv, 0, json.dumps([dict(Id=ID, Os='linux', Architecture='amd64',
                Config={'Labels': {'io.agents-runtime.harness': 'opencode', 'io.agents-runtime.contract': '1',
                                  'io.agents-runtime.resolution': installer.digest(installer.encoded(resolution))}})]))
        with patch.object(installer.subprocess, 'run', return_value=Mock(stdout='a' * 40)), \
                patch.object(installer, 'ordinary'), patch.object(installer, 'docker', side_effect=docker):
            receipt = installer.build('opencode', self.root, resolution, refresh=True)
        self.assertEqual(receipt['image'], ID)
        self.assertEqual(receipt['resolution'], resolution)


class V2Credentials(unittest.TestCase):
    def test_public_config_cannot_bake_private_credentials(self):
        installer.validate_public_config({'providers': {'fixture': {'settings': {'apiKey': '{env:FIXTURE_KEY}'}}}})
        for key in ('apiKey', 'password', 'access_token', 'Authorization'):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'environment references'):
                installer.validate_public_config({'providers': {'fixture': {'settings': {key: 'private'}}}})

    def test_credential_is_private_stable_and_home_specific(self):
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary) / 'first', Path(temporary) / 'second'
            first.mkdir(mode=0o700)
            second.mkdir(mode=0o700)
            password = entry.opencode_password(first)
            self.assertEqual(password, entry.opencode_password(first))
            self.assertNotEqual(password, entry.opencode_password(second))
            path = first / '.opencode-runtime-password'
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                entry.opencode_password(first)
            path.unlink()
            path.symlink_to(second / '.opencode-runtime-password')
            with self.assertRaises(OSError):
                entry.opencode_password(first)

    def test_authenticated_info_and_no_credential_in_argv(self):
        response = Mock(status=200)
        response.read.return_value = b'{"version":"2.0.32","pid":42}'
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(entry.http.client, 'HTTPConnection', return_value=connection):
            self.assertEqual(entry.opencode_info(4096, 'private')['pid'], 42)
        args, kwargs = connection.request.call_args
        self.assertEqual(args, ('GET', '/api/info'))
        self.assertTrue(kwargs['headers']['Authorization'].startswith('Basic '))
        self.assertEqual(entry.command('opencode', ['a b'], web=False, port=None),
                         [entry.BIN + 'opencode', '--server', 'http://127.0.0.1:4096', 'a b'])
        self.assertEqual(entry.command('opencode', [], web=True, port=4096)[1], 'serve')
        for arguments in (['--server', 'http://foreign'], ['--server=http://foreign'], ['serve'], ['upgrade']):
            with self.assertRaises(ValueError):
                entry.command('opencode', arguments, web=False, port=None)

    def test_server_first_client_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            server = Mock(pid=42)
            server.poll.return_value = None
            client = Mock(returncode=7)
            client.poll.return_value = 7
            with patch.dict(entry.os.environ, OPENCODE_PASSWORD='private'), \
                    patch.object(entry.subprocess, 'Popen', side_effect=[server, client]) as spawn, \
                    patch.object(entry, 'opencode_info', return_value={'pid': 42}):
                self.assertEqual(entry.run_opencode(['opencode', '--server', 'http://127.0.0.1:4096'], Path(temporary)), 7)
            self.assertEqual(spawn.call_args_list[0].args[0][1], 'serve')
            server.terminate.assert_called_once()
            server.wait.assert_called_once_with(timeout=10)

    def test_foreign_server_never_attaches_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            server = Mock(pid=42)
            server.poll.return_value = None
            with patch.dict(entry.os.environ, OPENCODE_PASSWORD='private'), \
                    patch.object(entry.subprocess, 'Popen', return_value=server) as spawn, \
                    patch.object(entry, 'opencode_info', return_value={'pid': 99}):
                with self.assertRaisesRegex(ValueError, 'another process'):
                    entry.run_opencode(['opencode', '--server', 'http://127.0.0.1:4096'], Path(temporary))
            self.assertEqual(spawn.call_count, 1)
            server.terminate.assert_called_once()

    def test_workstation_auth_uses_protected_file_not_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            password = entry.opencode_password(home)
            connection = Mock()
            connection.getresponse.return_value.status = 200
            connection.getresponse.return_value.read.return_value = b'{"version":"2.0.32","pid":42}'
            with patch.object(runtime.http.client, 'HTTPConnection', return_value=connection):
                runtime.web_request({'harness': 'opencode', 'home': str(home), 'port': 4096}, '/api/info')
            self.assertEqual(runtime.runtime_password(home), password)
            self.assertTrue(connection.request.call_args.kwargs['headers']['Authorization'].startswith('Basic '))


if __name__ == '__main__':
    unittest.main()
