"""Real policy files/flock/build subprocess boundaries; no live Docker or gateway."""
import copy
from contextlib import nullcontext
import io
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_runtime import IdentityFixture, load, policy


runtime, builder = load('launcher'), load('build')


def bootstrap(root: Path) -> dict:
    account = pwd.getpwuid(os.getuid()).pw_name
    value = policy(root, account)
    value['default_harness'] = None
    value['web']['default_harness'] = None
    for spec in value['harnesses'].values():
        spec['image'] = None
    return value


class PolicyTests(IdentityFixture):
    def setUp(self):
        super().setUp()
        self.data = bootstrap(Path('/var/lib/test-venv'))

    def test_explicit_empty_policy_and_missing_images(self):
        runtime.validate_policy(self.data)
        del self.data['harnesses']['pi']['image']
        with self.assertRaises(ValueError):
            runtime.validate_policy(self.data)

    def test_current_schema_accepts_only_current_optional_extensions(self):
        runtime.validate_policy(self.data)
        for extension in ('shared_runtime', 'schema_history', 'legacy_defaults'):
            candidate = copy.deepcopy(self.data)
            candidate[extension] = {}
            with self.subTest(extension=extension), self.assertRaisesRegex(ValueError, 'Exact current VM policy'):
                runtime.validate_policy(candidate)

    def test_retired_deployment_markers_do_not_block_current_policy_or_admit_old_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'policy.json'
            path.write_text(json.dumps(self.data))
            for name in ('bootstrap-pending.json', 'resource-update-pending.json'):
                path.with_name(name).touch()
            with patch.object(runtime, 'protected', side_effect=lambda value, **kwargs: value.stat()):
                self.assertEqual(runtime.load_policy(path), self.data)
                old = copy.deepcopy(self.data)
                old['schema'] = 1
                path.write_text(json.dumps(old))
                with self.assertRaisesRegex(ValueError, 'Current VM policy schema required'):
                    runtime.load_policy(path)

    def test_uninstalled_refused_before_state_socket_or_docker(self):
        with patch.object(runtime, 'validate_socket') as socket, patch.object(runtime, 'docker_call') as docker:
            for harness in runtime.HARNESSES:
                with self.assertRaisesRegex(ValueError, 'not installed'):
                    runtime.run_session(self.data, harness, False, [])
            socket.assert_not_called()
            docker.assert_not_called()

    def test_default_dispatch_reads_current_policy(self):
        from contextlib import nullcontext
        with patch.object(runtime, 'load_policy', return_value=self.data), \
                patch.object(runtime, 'maintenance_lock', return_value=nullcontext()), \
                patch.object(runtime, 'run_default', return_value=17) as default:
            self.assertEqual(runtime.main(['default', '--', '--version']), 17)
            default.assert_called_once_with(self.data, False, ['--version'])

    def test_standalone_candidate_cannot_read_leftover_policy(self):
        from contextlib import nullcontext
        with patch.object(runtime, 'load_policy', return_value=self.data) as load_policy, \
                patch.object(runtime, 'maintenance_lock', return_value=nullcontext()), \
                patch.object(runtime, 'run_web', return_value=0) as web:
            self.assertEqual(runtime.main(['candidate-web', 'pi', 'start']), 1)
            load_policy.assert_not_called()
            web.assert_not_called()
        with patch.object(runtime.os, 'getuid', return_value=0), patch.object(runtime, 'load_policy') as load_policy:
            with self.assertRaisesRegex(ValueError, 'non-root'):
                runtime.run_candidate('pi', 'start')
            load_policy.assert_not_called()

    def test_candidate_diagnostic_emits_only_fixed_public_category_metadata(self):
        candidate = copy.deepcopy(self.data)
        candidate['harnesses']['pi']['image'] = 'sha256:' + 'a' * 64
        candidate['harnesses']['pi']['requested_interfaces']['web'] = True
        instance = {'Id': 'a' * 64, 'State': {'Status': 'exited', 'ExitCode': 1,
                                               'OOMKilled': False, 'Error': 'private runtime value'}}
        logs = subprocess.CompletedProcess([], 0,
                                           'OpenCodeConfigInvalidError: private=/token/value', '')
        output = io.StringIO()
        with patch.object(runtime.os, 'getuid', return_value=1000), \
                patch.object(runtime, 'inherited_activation_fd'), \
                patch.object(runtime, 'load_policy', return_value=candidate), \
                patch.object(runtime.pwd, 'getpwuid', return_value=SimpleNamespace(pw_name='agents')), \
                patch.object(runtime.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1000, pw_gid=1000)), \
                patch.object(runtime, 'protected', return_value=SimpleNamespace(st_mode=stat.S_IFREG)), \
                patch.object(runtime, 'validate_socket'), \
                patch.object(runtime, 'inspect_web', return_value=instance), \
                patch.object(runtime, 'validate_web_instance', return_value='agents'), \
                patch.object(runtime, 'docker_call', return_value=logs), \
                patch('sys.stdout', output):
            assert runtime.run_candidate('pi', 'diagnose') == 0
        result = json.loads(output.getvalue())
        assert result == {'state': 'exited', 'exit_code': 1, 'oom_killed': False,
                          'category': 'opencode-config-invalid', 'runtime_error_present': True}

    def test_default_dispatch_never_executes_as_root_and_has_no_fallback(self):
        with patch.object(runtime.os, 'getuid', return_value=0), patch.object(runtime.subprocess, 'call') as call:
            with self.assertRaisesRegex(ValueError, 'non-root'):
                runtime.run_default(self.data, False, [])
            call.assert_not_called()
        with patch.object(runtime.subprocess, 'call') as call:
            with self.assertRaisesRegex(ValueError, 'No harness installed'):
                runtime.run_default(self.data, False, [])
            call.assert_not_called()


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 't3code/runtime').mkdir(parents=True)
        (self.root / 't3code/runtime/pins.json').write_text(json.dumps({'build_args': {
            'NODE_IMAGE': 'node@sha256:' + 'a' * 64, 'DEBIAN_SNAPSHOT': '20260908T000000Z'}}))
        for relative in ('t3code/.dockerignore', 'omp/.dockerignore', 'pi/Dockerfile.vm.dockerignore',
                         'venv/Dockerfile.base.dockerignore', 'venv/Dockerfile.opencode.dockerignore',
                         'venv/Dockerfile.vm.dockerignore'):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('**\n')
        self.settings = dict(platform='linux/amd64', docker_cli_image='docker@sha256:' + 'b' * 64,
                             opencode_version='1.18.29', socket='/run/docker.sock', command='/usr/local/bin/venv-agents')
        self.calls, self.tags = [], {}

    def docker(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        self.assertEqual(argv[:3], ['/usr/bin/docker', '--host', 'unix:///run/docker.sock'])
        self.assertEqual(set(kwargs['env']), {'PATH', 'HOME', 'DOCKER_BUILDKIT'})
        args = argv[3:]
        if args[0] == 'build':
            self.tags[args[args.index('-t') + 1]] = 'sha256:' + f'{len(self.tags) + 1:064x}'
            return subprocess.CompletedProcess(argv, 0, '')
        return subprocess.CompletedProcess(argv, 0, self.tags[args[-1]])

    def run_build(self, harness):
        with patch.object(builder, 'prerequisites'), patch.object(builder.platform, 'machine', return_value='x86_64'), \
                patch.object(builder.subprocess, 'run', side_effect=self.docker):
            return builder.build(harness, self.root, self.settings)

    def test_selected_graphs_no_all_build_and_cache_retained(self):
        for harness, expected in {
            'pi': ['t3code/Dockerfile', 'venv/Dockerfile.base', 'pi/Dockerfile.vm', 'venv/Dockerfile.vm'],
            'omp': ['omp/Dockerfile', 'venv/Dockerfile.vm'],
            'opencode': ['t3code/Dockerfile', 'venv/Dockerfile.base', 'venv/Dockerfile.opencode', 'venv/Dockerfile.vm'],
            't3': ['t3code/Dockerfile', 'venv/Dockerfile.vm'],
        }.items():
            with self.subTest(harness=harness):
                self.calls.clear()
                result = self.run_build(harness)
                commands = [a for a, _ in self.calls if a[3] == 'build']
                self.assertEqual([a[a.index('-f') + 1] for a in commands], expected)
                self.assertTrue(result.startswith('sha256:'))
                self.assertFalse(any('--no-cache' in a or 'prune' in a for a, _ in self.calls))
                self.assertIn('--target', commands[0]) if harness in ('pi', 'opencode') else self.assertNotIn('--target', commands[0])

    def test_bun_gate_all_processors_and_no_gate_for_node_only(self):
        for harness in ('omp', 'opencode'):
            for info in ('', 'flags : sse sse2', 'flags : sse4_2\nflags : sse2'):
                with self.assertRaisesRegex(ValueError, 'SSE4.2'):
                    builder.prerequisites(harness, 'x86_64', info)
            builder.prerequisites(harness, 'x86_64', 'flags : sse4_2')
        for harness in ('pi', 't3'):
            builder.prerequisites(harness, 'x86_64', '')
        with self.assertRaisesRegex(ValueError, 'amd64 only'):
            builder.prerequisites('omp', 'aarch64', '')

    def test_root_and_cpu_failure_precede_docker(self):
        with patch.object(builder.os, 'getuid', return_value=0), patch.object(builder.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'never root'):
                builder.build('pi', self.root, self.settings)
            run.assert_not_called()
        with patch.object(builder, 'prerequisites', side_effect=ValueError('SSE4.2')), \
                patch.object(builder.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'SSE4.2'):
                builder.build('omp', self.root, self.settings)
            run.assert_not_called()

    def test_drift_or_build_failure_never_activates(self):
        original = self.docker
        def drift(argv, **kwargs):
            result = original(argv, **kwargs)
            if argv[3] == 'build' and 'COMPONENT_IMAGE=' in ' '.join(argv):
                first = next(iter(self.tags))
                self.tags[first] = 'sha256:' + 'f' * 64
            return result
        with patch.object(builder, 'prerequisites'), patch.object(builder.platform, 'machine', return_value='x86_64'), \
                patch.object(builder.subprocess, 'run', side_effect=drift):
            with self.assertRaisesRegex(ValueError, 'drift'):
                builder.build('omp', self.root, self.settings)
        path = self.root / 'build.json'
        path.write_text(json.dumps(self.settings))
        with patch.object(builder, 'SETTINGS', path), patch.object(builder, 'build', side_effect=ValueError('failed')), \
                patch.object(builder, 'source_snapshot', return_value=nullcontext(self.settings)), \
                patch.object(builder.subprocess, 'run') as run, patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(builder.main(['omp']), 1)
            run.assert_not_called()

    def test_omp_never_reads_other_component_pins(self):
        (self.root / 't3code/runtime/pins.json').unlink()
        self.run_build('omp')

    def test_missing_context_allowlist_refuses_before_build(self):
        (self.root / 'omp/.dockerignore').unlink()
        with self.assertRaisesRegex(ValueError, 'context allowlist'):
            self.run_build('omp')
        self.assertEqual(self.calls, [])

    def test_success_hands_only_finite_id_to_protected_sudo_launcher(self):
        path = self.root / 'build.json'
        path.write_text(json.dumps(self.settings))
        image = 'sha256:' + 'a' * 64
        with patch.object(builder, 'SETTINGS', path), patch.object(builder, 'build', return_value=image), \
                patch.object(builder, 'source_snapshot', return_value=nullcontext(self.settings)), \
                patch.object(builder.subprocess, 'run') as run, patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(builder.main(['omp']), 0)
            run.assert_called_once_with(['/usr/bin/sudo', '--', '/usr/local/bin/venv-agents', 'activate', 'omp', image],
                                        check=True, timeout=1200)


class ActivationTests(IdentityFixture):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = bootstrap(self.root)
        self.account = next(iter(self.data['accounts']))
        self.uid = self.data['accounts'][self.account]['uid']
        self.path = self.root / 'policy.json'
        self.path.write_text(json.dumps(self.data))
        self.config = self.root / 'activation.json'
        self.config.write_text('{"gateway":"/usr/local/lib/venv-agents/gateway.py"}')
        self.marker = self.root / 'provider.json'
        self.marker.write_bytes(b'unchanged-provider-fixture')
        self.phases = []
        original_fstat = os.fstat
        def fstat(fd):
            info = original_fstat(fd)
            return SimpleNamespace(st_uid=0, st_gid=0, st_mode=info.st_mode, st_nlink=info.st_nlink,
                                   st_dev=info.st_dev, st_ino=info.st_ino)
        for name, replacement in [('POLICY', self.path), ('ACTIVATION', self.config),
                                  ('protected', lambda path, **kwargs: path.stat()),
                                  ('activation_gateway', self.gateway), ('check_image', lambda *args: None)]:
            mocked = patch.object(runtime, name, replacement)
            mocked.start(); self.addCleanup(mocked.stop)
        for name, replacement in [('getuid', lambda: 0), ('geteuid', lambda: 0), ('fstat', fstat)]:
            mocked = patch.object(runtime.os, name, replacement)
            mocked.start(); self.addCleanup(mocked.stop)
        mocked = patch.dict(os.environ, SUDO_USER=self.account, SUDO_UID=str(self.uid))
        mocked.start(); self.addCleanup(mocked.stop)
        mocked = patch('sys.stdout', new_callable=io.StringIO)
        mocked.start(); self.addCleanup(mocked.stop)

    def gateway(self, config, phase, candidate, *, lock_fd=None):
        self.phases.append(phase)
        self.assertIn(phase, ('install-current', 'select-current'))
        self.assertIsNotNone(lock_fd)
        self.assertEqual(self.marker.read_bytes(), b'unchanged-provider-fixture')
        self.assertEqual(set(candidate), {'harness', 'candidate'})
        self.assertEqual(json.loads(self.path.with_name('activation-candidate.json').read_text()), candidate['candidate'])

    def install(self, harness, digit='a'):
        return runtime.activate(harness, 'sha256:' + digit * 64)

    def test_old_journals_are_inert_even_if_unreadable_json(self):
        paths = [self.path.with_name(name) for name in ('image-install.json', 'select-default-pending.json')]
        for path in paths:
            path.write_text('not a journal to parse')
        with patch.object(runtime, 'activation_gateway') as gateway:
            self.install('pi')
        self.assertEqual(gateway.call_args.args[1], 'install-current')
        for path in paths:
            self.assertEqual(path.read_text(), 'not a journal to parse')

    def test_current_image_replacement_is_allowed(self):
        with patch.object(runtime, 'activation_gateway') as gateway:
            self.install('pi')
            self.install('pi', 'b')
            self.install('pi', 'b')
        self.assertEqual(gateway.call_count, 3)
        self.assertEqual(json.loads(self.path.read_text())['harnesses']['pi']['image'], 'sha256:' + 'b' * 64)

    def test_first_success_all_choices_and_additions_preserve_defaults(self):
        for first in sorted(runtime.HARNESSES):
            with self.subTest(first=first):
                self.path.write_text(json.dumps(self.data))
                self.install(first)
                value = json.loads(self.path.read_text())
                self.assertEqual(value['default_harness'], None if first == 't3' else first)
                self.assertEqual(value['web']['default_harness'], None if first == 'omp' else first)
                addition = next(h for h in sorted(runtime.HARNESSES) if h != first)
                self.install(addition, 'b')
                later = json.loads(self.path.read_text())
                expected_cli = value['default_harness'] or (addition if addition != 't3' else None)
                expected_web = value['web']['default_harness'] or (addition if addition != 'omp' else None)
                self.assertEqual(later['default_harness'], expected_cli)
                self.assertEqual(later['web']['default_harness'], expected_web)
                self.assertEqual(self.marker.read_bytes(), b'unchanged-provider-fixture')

    def test_partial_failure_leaves_candidate_and_retry_converges_forward(self):
        original = self.path.read_bytes()
        def fail(config, phase, candidate, *, lock_fd=None):
            self.gateway(config, phase, candidate, lock_fd=lock_fd)
            raise ValueError('failed gateway')
        with patch.object(runtime, 'activation_gateway', side_effect=fail):
            with self.assertRaisesRegex(ValueError, 'failed gateway'):
                self.install('pi')
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.phases, ['install-current'])
        self.assertTrue(self.path.with_name('activation-candidate.json').exists())
        self.assertEqual(self.install('pi', 'b'), 0)
        self.assertEqual(self.phases, ['install-current', 'install-current'])
        self.assertFalse(self.path.with_name('activation-candidate.json').exists())
        self.assertEqual(json.loads(self.path.read_text())['harnesses']['pi']['image'], 'sha256:' + 'b' * 64)

    def test_invalid_args_and_unenrolled_caller_refused(self):
        self.install('pi')
        for harness, image in [('all', 'sha256:' + 'a' * 64), ('pi', 'pi:latest'), ('pi', 'sha256:' + 'a' * 64 + ' --privileged')]:
            with self.assertRaises(ValueError):
                runtime.activate(harness, image)
        with patch.dict(os.environ, SUDO_USER='foreign'):
            with self.assertRaisesRegex(ValueError, 'shared execution account'):
                self.install('omp', 'b')

    def test_image_failure_never_creates_journal_or_calls_gateway(self):
        with patch.object(runtime, 'check_image', side_effect=ValueError('bad image')):
            with self.assertRaisesRegex(ValueError, 'bad image'):
                self.install('pi')
        self.assertEqual(self.phases, [])
        self.assertFalse(self.path.with_name('image-install.json').exists())
        self.assertEqual(json.loads(self.path.read_text()), self.data)

    def test_publication_failure_does_not_restore_gateway_and_retry_is_current(self):
        atomic = runtime.atomic_json
        def fail_policy(path, value, mode=0o644):
            if path == self.path:
                raise OSError('publication failed')
            atomic(path, value, mode)
        with patch.object(runtime, 'atomic_json', side_effect=fail_policy):
            with self.assertRaisesRegex(OSError, 'publication failed'):
                self.install('pi')
        self.assertEqual(self.phases, ['install-current'])
        self.assertEqual(json.loads(self.path.read_text()), self.data)
        self.assertTrue(self.path.with_name('activation-candidate.json').exists())
        self.install('pi')
        self.assertEqual(self.phases, ['install-current', 'install-current'])
        self.assertFalse(self.path.with_name('activation-candidate.json').exists())

    def test_install_preserves_only_original_gateway_error(self):
        def gateway(config, phase, transaction, *, lock_fd=None):
            self.gateway(config, phase, transaction, lock_fd=lock_fd)
            raise runtime.GatewayError('install-current', 'GW_CHECK_L101', 17)

        with patch.object(runtime, 'activation_gateway', side_effect=gateway):
            with self.assertRaises(runtime.GatewayError) as caught:
                self.install('pi')
        error = caught.exception
        self.assertEqual((error.phase, error.code, error.returncode), ('install-current', 'GW_CHECK_L101', 17))
        self.assertEqual(self.phases, ['install-current'])

    def test_fsync_failure_after_publication_never_restores_previous_policy(self):
        atomic = runtime.atomic_json
        def fail_after_publish(path, value, mode=0o644):
            atomic(path, value, mode)
            if path == self.path:
                raise OSError('fsync failed')
        with patch.object(runtime, 'atomic_json', side_effect=fail_after_publish):
            with self.assertRaisesRegex(OSError, 'fsync failed'):
                self.install('omp')
        self.assertNotIn('install-rollback', self.phases)
        self.assertEqual(json.loads(self.path.read_text())['default_harness'], 'omp')
        self.assertTrue(self.path.with_name('activation-candidate.json').exists())
        self.install('omp')
        self.assertNotIn('install-rollback', self.phases)
        self.assertFalse(self.path.with_name('image-install.json').exists())

    def test_real_concurrent_lock_only_one_first_default(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def gateway(config, phase, transaction, *, lock_fd=None):
            if phase == 'install-current':
                entered.set()
                self.assertTrue(release.wait(5))
            self.gateway(config, phase, transaction, lock_fd=lock_fd)
        def first():
            try:
                self.install('omp')
            except BaseException as error:
                errors.append(error)
        with patch.object(runtime, 'activation_gateway', side_effect=gateway):
            worker = threading.Thread(target=first)
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(BlockingIOError):
                    self.install('pi', 'b')
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.install('pi', 'b')
        self.assertEqual(json.loads(self.path.read_text())['default_harness'], 'omp')

    def test_default_selection_is_root_only_current_and_ignores_old_files(self):
        self.install('pi')
        self.install('opencode', 'b')
        with self.assertRaisesRegex(ValueError, 'controller root'):
            runtime.select_default('opencode')
        original = json.loads(self.path.read_text())
        for name in ('image-install.json', 'select-default-pending.json', 'activation-candidate.json'):
            self.path.with_name(name).write_text('inert prior bytes')
        with patch.dict(os.environ, {}, clear=True):
            runtime.select_default('opencode')
            runtime.select_default('opencode')
        selected = json.loads(self.path.read_text())
        expected = copy.deepcopy(original)
        expected['default_harness'] = expected['web']['default_harness'] = 'opencode'
        self.assertEqual(selected, expected)
        self.assertEqual(self.phases[-2:], ['select-current', 'select-current'])
        self.assertFalse(self.path.with_name('activation-candidate.json').exists())
        self.assertEqual(self.path.with_name('select-default-pending.json').read_text(), 'inert prior bytes')


class ImageCheckTests(IdentityFixture):
    def test_mountless_selected_version_check_and_id_cleanup_on_timeout(self):
        data = bootstrap(Path('/var/lib/test-venv'))
        image, container = 'sha256:' + 'a' * 64, 'b' * 64
        for harness in sorted(runtime.HARNESSES):
            calls = []
            def docker(policy, args):
                calls.append(args)
                if args[0] == 'image':
                    out = image
                elif args[0] == 'create':
                    out = container
                elif args[:2] == ['container', 'start']:
                    raise subprocess.TimeoutExpired(args, 60)
                else:
                    out = ''
                return subprocess.CompletedProcess(args, 0, out, '')
            with patch.object(runtime, 'docker_call', side_effect=docker):
                with self.assertRaises(subprocess.TimeoutExpired):
                    runtime.check_image(data, harness, image)
            create = calls[1]
            self.assertNotIn('--mount', create)
            self.assertIn('--read-only', create)
            self.assertEqual(create[create.index('--network') + 1], 'none')
            self.assertEqual(calls[-1], ['container', 'rm', '--force', container])

    def test_nonzero_container_exit_and_empty_version_fail(self):
        data = bootstrap(Path('/var/lib/test-venv'))
        image, container = 'sha256:' + 'a' * 64, 'b' * 64
        for output, exit_code in [('', '0'), ('version', '1'), ('version', '0')]:
            results = [subprocess.CompletedProcess([], 0, text, '') for text in (image, container, output, exit_code, '')]
            with patch.object(runtime, 'docker_call', side_effect=results):
                if output and exit_code == '0':
                    runtime.check_image(data, 'pi', image)
                else:
                    with self.assertRaisesRegex(ValueError, 'version check failed'):
                        runtime.check_image(data, 'pi', image)

    def test_gateway_exact_argv_clean_environment_and_safe_fixed_diagnostics(self):
        transaction = dict(harness='pi', candidate={'public': 2})
        codes = ('GW_CHECK_L101', 'GW_INTERNAL_JSON_L102', 'GW_INTERNAL_KEY_L103',
                 'GW_INTERNAL_OS_L104', 'GW_INTERNAL_SUBPROCESS_L105',
                 'GW_INTERNAL_VALUE_L106', 'GW_INTERNAL_UNEXPECTED_L107')
        for code in codes:
            stderr = io.StringIO()
            print(f'GW_ERROR action=install-current code={code}', file=stderr)
            with self.subTest(code=code), \
                    patch.object(runtime, 'protected', return_value=SimpleNamespace(st_mode=0o100644)), \
                    patch.object(runtime.subprocess, 'run', return_value=subprocess.CompletedProcess(
                        [], 17, '', stderr.getvalue())) as run:
                with self.assertRaises(runtime.GatewayError) as caught:
                    runtime.activation_gateway({'gateway': '/usr/local/lib/gateway.py'}, 'install-current', transaction, lock_fd=7)
                error = caught.exception
                self.assertEqual((error.phase, error.code, error.returncode), ('install-current', code, 17))
                self.assertEqual(run.call_args.args[0], ['/usr/bin/python3', '-I', '/usr/local/lib/gateway.py', 'install-current', 'pi'])
                self.assertEqual(json.loads(run.call_args.kwargs['input']), {'public': 2})
                self.assertEqual(set(run.call_args.kwargs['env']), {'PATH', 'HOME', 'VENV_ACTIVATION_LOCK_FD'})
                self.assertEqual(run.call_args.kwargs['cwd'], '/')
                self.assertEqual(run.call_args.kwargs['pass_fds'], (7,))

    def test_gateway_malformed_or_secret_output_is_unclassified_and_never_disclosed(self):
        transaction = dict(harness='pi', candidate={'public': 2})
        valid = io.StringIO()
        print('GW_ERROR action=install-current code=GW_CHECK_L1', file=valid)
        outputs = [
            ('', 'secret=do-not-disclose'),
            ('secret=do-not-disclose', valid.getvalue()),
            ('', 'GW_ERROR action=install-rollback code=GW_CHECK_L1\n'),
            ('', 'GW_ERROR action=install-current code=GW_INTERNAL_TYPE_L1\n'),
            ('', valid.getvalue() + 'secret=do-not-disclose\n'),
        ]
        for stdout, stderr in outputs:
            with self.subTest(stdout=bool(stdout), stderr=stderr.startswith('GW_ERROR')), \
                    patch.object(runtime, 'protected', return_value=SimpleNamespace(st_mode=0o100644)), \
                    patch.object(runtime.subprocess, 'run', return_value=subprocess.CompletedProcess([], 19, stdout, stderr)):
                with self.assertRaises(runtime.GatewayError) as caught:
                    runtime.activation_gateway({'gateway': '/usr/local/lib/gateway.py'}, 'install-current', transaction)
                error = caught.exception
                self.assertEqual((error.phase, error.code, error.returncode), ('install-current', 'GW_UNCLASSIFIED', 19))
                self.assertNotIn('secret', str(error))

    def test_real_protection_rejects_guest_owned_root_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / 'gateway.py'
            helper.write_text('raise SystemExit(0)')
            with patch.object(runtime.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'ownership/mode'):
                    runtime.activation_gateway({'gateway': str(helper)}, 'install-current',
                                               dict(harness='pi', candidate={}))
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
