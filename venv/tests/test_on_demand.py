"""Real policy files/flock/build subprocess boundaries; no live Docker or gateway."""
import copy
import io
import json
import os
from pathlib import Path
import pwd
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_runtime import load, policy


runtime, builder = load('launcher'), load('build')


def bootstrap(root: Path) -> dict:
    account = pwd.getpwuid(os.getuid()).pw_name
    value = policy(root, account)
    value.update(schema=2, default_harness='native-pi', native_pi={'cli': ['/usr/local/bin/native-pi']})
    value['web']['default_harness'] = 'native-pi'
    value['accounts'][account]['autoentry'] = 'default'
    for spec in value['harnesses'].values():
        spec['image'] = None
    return value


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.data = bootstrap(Path('/var/lib/test-venv'))

    def test_explicit_empty_policy_and_missing_images(self):
        runtime.validate_policy(self.data)
        del self.data['harnesses']['pi']['image']
        with self.assertRaises(ValueError):
            runtime.validate_policy(self.data)

    def test_uninstalled_refused_before_state_socket_or_docker(self):
        with patch.object(runtime, 'validate_socket') as socket, patch.object(runtime, 'docker_call') as docker:
            for harness in runtime.HARNESSES:
                with self.assertRaisesRegex(ValueError, 'not installed'):
                    runtime.run_session(self.data, harness, False, [])
            socket.assert_not_called()
            docker.assert_not_called()

    def test_native_default_cli_preserves_environment_and_arguments(self):
        with patch.object(runtime.subprocess, 'call', return_value=23) as call:
            self.assertEqual(runtime.run_default(self.data, False, ['--version']), 23)
            call.assert_called_once_with(['/usr/local/bin/native-pi', '--version'])

    def test_native_web_url_and_omp_first_no_fallback(self):
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            runtime.run_default(self.data, True, [])
            self.assertIn('https://coo.example.org/ (native Pi)', output.getvalue())
        self.data['harnesses']['omp']['image'] = 'sha256:' + 'a' * 64
        self.data['default_harness'] = 'omp'
        self.data['web']['default_harness'] = None
        with patch.object(runtime, 'run_session') as session:
            with self.assertRaisesRegex(ValueError, 'No web default'):
                runtime.run_default(self.data, True, [])
            session.assert_not_called()
        self.data['web']['default_harness'] = 'pi'
        with self.assertRaises(ValueError):
            runtime.validate_policy(self.data)

    def test_installed_policy_cannot_retain_native_default(self):
        self.data['harnesses']['pi']['image'] = 'sha256:' + 'a' * 64
        with self.assertRaisesRegex(ValueError, 'native is initial only'):
            runtime.validate_policy(self.data)

    def test_default_dispatch_reads_current_policy(self):
        from contextlib import nullcontext
        with patch.object(runtime, 'load_policy', return_value=self.data), \
                patch.object(runtime, 'maintenance_lock', return_value=nullcontext()), \
                patch.object(runtime, 'run_default', return_value=17) as default:
            self.assertEqual(runtime.main(['default', '--', '--version']), 17)
            default.assert_called_once_with(self.data, False, ['--version'])

    def test_candidate_uses_only_protected_fixed_policy_path(self):
        from contextlib import nullcontext
        with patch.object(runtime, 'load_policy', return_value=self.data) as load_policy, \
                patch.object(runtime, 'maintenance_lock', return_value=nullcontext()), \
                patch.object(runtime, 'run_web', return_value=0) as web:
            self.assertEqual(runtime.main(['candidate-web', 'pi', 'start']), 0)
            load_policy.assert_called_once_with(runtime.POLICY.with_name('activation-candidate.json'))
            web.assert_called_once_with(self.data, 'pi', 'start')
        with patch.object(runtime.os, 'getuid', return_value=0), patch.object(runtime, 'load_policy') as load_policy:
            with self.assertRaisesRegex(ValueError, 'non-root'):
                runtime.run_candidate('pi', 'start')
            load_policy.assert_not_called()

    def test_native_cli_never_executes_as_root_and_fresh_has_no_fallback(self):
        with patch.object(runtime.os, 'getuid', return_value=0), patch.object(runtime.subprocess, 'call') as call:
            with self.assertRaisesRegex(ValueError, 'non-root'):
                runtime.run_default(self.data, False, [])
            call.assert_not_called()
        self.data['default_harness'] = self.data['web']['default_harness'] = None
        del self.data['native_pi']
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
                patch.object(builder.subprocess, 'run') as run, patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(builder.main(['omp']), 1)
            run.assert_not_called()

    def test_make_uses_only_selected_target(self):
        for harness in builder.HARNESSES:
            result = subprocess.run(['make', '-n', '-f', str(Path(builder.__file__).with_name('Makefile')), harness],
                                    text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout.strip(), '/usr/bin/python3 build.py ' + harness)

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
                patch.object(builder.subprocess, 'run') as run, patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(builder.main(['omp']), 0)
            run.assert_called_once_with(['/usr/bin/sudo', '--', '/usr/local/bin/venv-agents', 'activate', 'omp', image],
                                        check=True, timeout=1200)


class ActivationTests(unittest.TestCase):
    def setUp(self):
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
            return SimpleNamespace(st_uid=0, st_mode=info.st_mode, st_nlink=info.st_nlink)
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

    def gateway(self, config, phase, transaction, *, lock_fd=None):
        self.phases.append(phase)
        # No policy publication or provider mutation before successful gateway commit.
        self.assertEqual(json.loads(self.path.read_text()), transaction['previous'])
        self.assertEqual(self.marker.read_bytes(), b'unchanged-provider-fixture')
        self.assertEqual(json.loads(self.path.with_name('activation-candidate.json').read_text()), transaction['candidate'])

    def install(self, harness, digit='a'):
        return runtime.activate(harness, 'sha256:' + digit * 64)

    def test_first_success_all_choices_and_additions_preserve_defaults(self):
        for first in sorted(runtime.HARNESSES):
            with self.subTest(first=first):
                self.path.write_text(json.dumps(self.data))
                self.install(first)
                value = json.loads(self.path.read_text())
                self.assertEqual(value['default_harness'], first)
                self.assertEqual(value['web']['default_harness'], None if first == 'omp' else first)
                addition = next(h for h in sorted(runtime.HARNESSES) if h != first)
                self.install(addition, 'b')
                later = json.loads(self.path.read_text())
                self.assertEqual(later['default_harness'], first)
                self.assertEqual(later['web'], value['web'])
                self.assertEqual(self.marker.read_bytes(), b'unchanged-provider-fixture')

    def test_check_and_commit_failure_restore_native_and_retry(self):
        original = self.path.read_bytes()
        for failure in ('install-check', 'install-commit'):
            def gateway(config, phase, transaction, *, lock_fd=None):
                self.gateway(config, phase, transaction)
                if phase == failure:
                    raise ValueError('failed gateway')
            with patch.object(runtime, 'activation_gateway', side_effect=gateway):
                with self.assertRaisesRegex(ValueError, 'failed gateway'):
                    self.install('pi')
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(self.phases[-1], 'install-rollback')
            self.assertFalse(self.path.with_name('activation-pending.json').exists())
        self.assertEqual(self.install('pi'), 0)

    def test_failed_rollback_retains_journal_and_retry_recovers_first(self):
        with patch.object(runtime, 'activation_gateway', side_effect=ValueError('unavailable')):
            with self.assertRaises(ValueError):
                self.install('omp')
        self.assertTrue(self.path.with_name('activation-pending.json').exists())
        self.install('t3', 'b')
        self.assertEqual(self.phases, ['install-rollback', 'install-check', 'install-commit'])
        self.assertEqual(json.loads(self.path.read_text())['default_harness'], 't3')

    def test_published_candidate_journal_does_not_restore_native(self):
        candidate = copy.deepcopy(self.data)
        candidate['harnesses']['omp']['image'] = 'sha256:' + 'a' * 64
        candidate['default_harness'] = 'omp'
        candidate['web']['default_harness'] = None
        self.path.write_text(json.dumps(candidate))
        pending = self.path.with_name('activation-pending.json')
        pending.write_text(json.dumps(dict(harness='omp', previous=self.data, candidate=candidate)))
        self.install('omp')
        self.assertEqual(self.phases, [])
        self.assertFalse(pending.exists())

    def test_replacement_invalid_args_and_unenrolled_caller_refused(self):
        self.install('pi')
        with self.assertRaisesRegex(ValueError, 'replacement'):
            self.install('pi', 'b')
        for harness, image in [('all', 'sha256:' + 'a' * 64), ('pi', 'pi:latest'), ('pi', 'sha256:' + 'a' * 64 + ' --privileged')]:
            with self.assertRaises(ValueError):
                runtime.activate(harness, image)
        with patch.dict(os.environ, SUDO_USER='foreign'):
            with self.assertRaisesRegex(ValueError, 'Enrolled'):
                self.install('omp', 'b')

    def test_image_failure_never_creates_journal_or_calls_gateway(self):
        with patch.object(runtime, 'check_image', side_effect=ValueError('bad image')):
            with self.assertRaisesRegex(ValueError, 'bad image'):
                self.install('pi')
        self.assertEqual(self.phases, [])
        self.assertFalse(self.path.with_name('activation-pending.json').exists())
        self.assertEqual(json.loads(self.path.read_text()), self.data)

    def test_publication_failure_rolls_back_and_removes_candidate(self):
        atomic = runtime.atomic_json
        def fail_policy(path, value, mode=0o644):
            if path == self.path:
                raise OSError('publication failed')
            atomic(path, value, mode)
        with patch.object(runtime, 'atomic_json', side_effect=fail_policy):
            with self.assertRaisesRegex(OSError, 'publication failed'):
                self.install('pi')
        self.assertEqual(self.phases, ['install-check', 'install-commit', 'install-rollback'])
        self.assertEqual(json.loads(self.path.read_text()), self.data)
        self.assertFalse(self.path.with_name('activation-candidate.json').exists())

    def test_fsync_failure_after_publication_never_restores_native(self):
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
        self.assertTrue(self.path.with_name('activation-pending.json').exists())
        self.install('omp')
        self.assertNotIn('install-rollback', self.phases)
        self.assertFalse(self.path.with_name('activation-pending.json').exists())

    def test_real_concurrent_lock_only_one_first_default(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def gateway(config, phase, transaction, *, lock_fd=None):
            if phase == 'install-check':
                entered.set()
                self.assertTrue(release.wait(5))
            self.gateway(config, phase, transaction)
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


class ImageCheckTests(unittest.TestCase):
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

    def test_gateway_exact_argv_clean_environment_and_no_output_disclosure(self):
        transaction = dict(harness='pi', previous={'public': 1}, candidate={'public': 2})
        with patch.object(runtime, 'protected', return_value=SimpleNamespace(st_mode=0o100644)), \
                patch.object(runtime.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, 'private', 'private')) as run:
            with self.assertRaisesRegex(ValueError, 'Gateway install-check failed') as caught:
                runtime.activation_gateway({'gateway': '/usr/local/lib/gateway.py'}, 'install-check', transaction, lock_fd=7)
            self.assertNotIn('private', str(caught.exception))
            self.assertEqual(run.call_args.args[0], ['/usr/bin/python3', '-I', '/usr/local/lib/gateway.py', 'install-check', 'pi'])
            self.assertEqual(json.loads(run.call_args.kwargs['input']), {'previous': {'public': 1}, 'candidate': {'public': 2}})
            self.assertEqual(set(run.call_args.kwargs['env']), {'PATH', 'HOME'})
            self.assertEqual(run.call_args.kwargs['cwd'], '/')
            self.assertEqual(run.call_args.kwargs['pass_fds'], (7,))

    def test_real_protection_rejects_guest_owned_root_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / 'gateway.py'
            helper.write_text('raise SystemExit(0)')
            with patch.object(runtime.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'ownership/mode'):
                    runtime.activation_gateway({'gateway': str(helper)}, 'install-check',
                                               dict(harness='pi', previous={}, candidate={}))
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
