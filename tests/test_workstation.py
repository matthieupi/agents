"""Workstation scripts with isolated HOME and Docker/native boundary recorders.

No real Docker/Compose, credential files, package installs or network calls.
"""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

try:
    import yaml
except ModuleNotFoundError as error:
    if error.name != 'yaml':
        raise
    yaml = None


ROOT = Path(__file__).resolve().parents[1]


class LegacyDispatch(unittest.TestCase):
    def test_supported_dispatch_and_retired_entrypoints(self):
        # Stable behavior, independent of the current commit or merge state.
        for component, wrapper in [('pi', 'pi'), ('opencode', 'opencode'), ('claudecode', 'claude')]:
            with self.subTest(component=component):
                argv = ['.', '--', 'a b', '$(false)']
                self.assertEqual(self.dispatch(component, wrapper, argv), [wrapper + '-run', argv])
        for retired in ('omp/omp', 't3code/t3code', 'venv/venv'):
            with self.subTest(retired=retired):
                self.assertFalse((ROOT / retired).exists())

    def dispatch(self, component, wrapper, arguments, *, directory=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copyfile(ROOT / component / wrapper, root / wrapper)
            recorder = '#!/usr/bin/python3\nimport json,sys,os\nprint(json.dumps([os.path.basename(sys.argv[0]),sys.argv[1:]]))\n'
            for suffix in ('run', 'mgr', 'menu'):
                path = root / (wrapper + '-' + suffix)
                path.write_text(recorder)
                path.chmod(0o755)
            if directory:
                (root / directory).mkdir()
            result = subprocess.run(['/bin/bash', str(root / wrapper), *arguments],
                                    cwd=root, text=True, capture_output=True,
                                    env={'PATH': '/usr/bin:/bin'}, check=True)
            return json.loads(result.stdout)

    def test_opencode_run_verbatim(self):
        cases = [[], ['.'], ['/project'], ['--web'], ['-w', '4096', '.'],
                 ['--wlan', '4096'], ['--port', '4097'],
                 ['--privileged', '.'], ['--priviliged', '.'],
                 ['--gpu', '0', '.'], ['--cpus', '4', '--memory', '8g'],
                 ['--publish', '3000'], ['-r', '.'], ['--', 'a b', '$(false)']]
        for argv in cases:
            with self.subTest(argv=argv):
                self.assertEqual(self.dispatch('opencode', 'opencode', argv), ['opencode-run', argv])

    def test_management_aliases(self):
        common = 'list ls stop start remove rm clean fclean logs shell'.split()
        for component, wrapper, extra in [('opencode', 'opencode', ['rebuild', 'update']),
                                          ('pi', 'pi', ['build', 'rebuild', 'update', 'login']),
                                          ('claudecode', 'claude', [])]:
            for verb in common + extra:
                with self.subTest(component=component, verb=verb):
                    argv = [verb, 'all', 'a b']
                    self.assertEqual(self.dispatch(component, wrapper, argv), [wrapper + '-mgr', argv])

    def test_opencode_menu(self):
        for verb in ('menu', 'tui'):
            self.assertEqual(self.dispatch('opencode', 'opencode', [verb, 'x']), ['opencode-menu', ['x']])

    def test_pi_precedence_and_presets(self):
        self.assertEqual(self.dispatch('pi', 'pi', ['build', '-p', 'x'], directory='build'),
                         ['pi-run', ['build', '-p', 'x']])
        for verb, preset in [('ext-agent-team', 'agent-team'), ('ext-agent-teams', 'agent-team'),
                             ('ext-agent-chain', 'agent-chain'), ('ext-pi-pi', 'pi-pi')]:
            self.assertEqual(self.dispatch('pi', 'pi', [verb, '.']), ['pi-run', ['--extension-preset', preset, '.']])
        for verb in ('-r', '--rebuild'):
            self.assertEqual(self.dispatch('pi', 'pi', [verb, '.']), ['pi-mgr', ['build']])
        self.assertEqual(self.dispatch('pi', 'pi', ['--prompt', 'a b']), ['pi-run', ['-p', 'a b']])
        self.assertEqual(self.dispatch('pi', 'pi', []), ['pi-run', []])

    def test_claude_run(self):
        for argv in ([], ['.'], ['-r', '.'], ['--dangerous', '.']):
            self.assertEqual(self.dispatch('claudecode', 'claude', argv), ['claude-run', argv])


class LegacyExecution(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.workspace = self.root / 'project with spaces'
        self.workspace.mkdir()
        self.calls = self.root / 'calls.jsonl'
        component = self.root / 'opencode'
        (component / 'scripts').mkdir(parents=True)
        for name in ('workstation-common.sh', 'workstation-state.py'):
            shutil.copyfile(ROOT / 'opencode/scripts' / name, component / 'scripts' / name)
        for directory in (component / 'ssh', component / '.opencode/config', self.root / 'agent'):
            directory.mkdir(parents=True)
        (component / 'init.sh').write_text('# fixture\n')
        shutil.copyfile(ROOT / 'opencode/.opencode/config/publish-plugins.mjs',
                        component / '.opencode/config/publish-plugins.mjs')
        # No fallback PATH: only ordinary filesystem/text utilities used by these
        # copied scripts. Docker and sleep are always stubs.
        for name in ('dirname', 'basename', 'realpath', 'mkdir', 'grep', 'awk',
                     'xargs', 'readlink', 'ln', 'rm', 'mktemp', 'cat', 'stat', 'node',
                     'sha256sum', 'cut', 'flock', 'timeout'):
            executable = shutil.which(name)
            assert executable is not None, f'Missing test utility: {name}'
            (self.bin / name).symlink_to(executable)
        recorder = '''#!/usr/bin/python3
import json, os, sys, hashlib, fcntl
from pathlib import Path
args = sys.argv[1:]
tool = Path(sys.argv[0]).name
with open(os.environ['CALLS'], 'a') as stream:
    stream.write(json.dumps([tool, args]) + '\\n')
if tool == 'docker':
    scenario = os.environ.get('SCENARIO', 'fresh')
    if args[0] == 'context':
        print('fixture' if args[1] == 'show' else 'unix:///fixture/docker.sock')
    elif args[0] == 'build' and scenario == 'build-failed':
        sys.exit(1)
    elif args[0] == 'run' and scenario == 'run-failed':
        sys.exit(1)
    elif args[0] == 'ps':
        if 'status=running' in args:
            created = any(json.loads(line)[1][:1] == ['run']
                          for line in Path(os.environ['CALLS']).read_text().splitlines())
            if scenario != 'stale' or created:
                print('fixture-id')
        elif 'name=opencode-' in args:
            print('opencode-legacy\\nopencode-compose')
        elif scenario in ('reuse', 'stale', 'mismatch', 'old-image', 'old-lifecycle', 'old-config', 'legacy', 'unready-reuse', 'compose', 'unowned'):
            print('Up fixture' if scenario != 'stale' else 'Exited fixture')
    elif args[0] == 'inspect':
        fmt = args[2]
        print(('sha256:old' if scenario == 'old-image' else 'sha256:new') if fmt == '{{.Image}}' else
              ('v1' if scenario in ('legacy', 'old-lifecycle', 'compose', 'unowned') else 'v2-serve-1') if 'lifecycle' in fmt else
              'compose-project' if 'com.docker.compose.project' in fmt else
              ('old-config' if scenario == 'old-config' or os.environ.get('EXPOSURE', '') != os.environ.get('OPENCODE_DOCKER_WEB_ENDPOINT', '') else os.environ['OPENCODE_DOCKER_CONFIG_FINGERPRINT']) if 'opencode.config' in fmt else
              os.environ.get('PRIVILEGED', 'false') if fmt == '{{.HostConfig.Privileged}}' else
              'no' if fmt == '{{.HostConfig.RestartPolicy.Name}}' else
              hashlib.sha256(bytes([0])).hexdigest() if '.volumes' in fmt else
              ('4' if scenario == 'mismatch' else '8.0') if '.cpus' in fmt else
              '16g' if '.memory' in fmt else '')
    elif args[:2] == ['image', 'inspect']:
        if scenario == 'missing-image': sys.exit(1)
        if '--format' in args:
            fmt = args[args.index('--format') + 1]
            print(('9999:9999' if scenario == 'wrong-user' else os.environ['FIXTURE_USER']) if fmt == '{{.Config.User}}' else
                  'sha256:new' if fmt == '{{.Id}}' else 'v2-serve-1')
    elif args[0] == 'port':
        assert args[-1] == '4096/tcp', args
        print(os.environ.get('MAPPING', ''))
    elif args[0] == 'exec':
        if '--wait' in args and scenario.startswith('unready'):
            sys.exit(1)
        if '/opt/harness/docker-client.sh' in args:
            # A second launcher must be able to enter while a TUI is attached.
            for lock in Path(os.environ['CALLS']).parent.glob('opencode/.opencode/locks/*'):
                with lock.open('w') as stream:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
elif tool == 'python3':
    # Run real host fingerprinting, stub only container readiness.
    if args[:1] == ['-'] or args[0].endswith('/workstation-state.py'):
        os.execv('/usr/bin/python3', ['/usr/bin/python3', *args])
'''
        for name in ('docker', 'sleep', 'python3', 'opencode'):
            path = self.bin / name
            path.write_text(recorder)
            path.chmod(0o755)
        self.env = {'PATH': str(self.bin), 'HOME': str(self.home), 'CALLS': str(self.calls),
                    'PYTHONDONTWRITEBYTECODE': '1', 'OPENCODE_PASSWORD': 'fixture-private-password'}
        # Root CI simulates a non-root invoking identity; filesystem checks still
        # validate the actual fixture owner. No host account changes.
        self.uid = os.getuid() or 1234
        self.gid = os.getgid() or 1234
        (self.bin / 'id').write_text(f'#!/bin/bash\ncase "$1" in -u) echo {self.uid};; -g) echo {self.gid};; esac\n')
        (self.bin / 'id').chmod(0o755)
        self.env['FIXTURE_USER'] = f'{self.uid}:{self.gid}'

    def run_copy(self, script, arguments, scenario='fresh', stdin=''):
        source = ROOT / script
        target = self.root / script
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        self.calls.unlink(missing_ok=True)
        result = subprocess.run(['/bin/bash', str(target), *arguments], cwd=self.workspace,
                                env=dict(self.env, SCENARIO=scenario), input=stdin,
                                capture_output=True, text=True, timeout=10)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []
        self.assertNotIn('fixture-private-password', result.stdout + result.stderr + json.dumps(calls))
        return result, [argv for tool, argv in calls if tool == 'docker']

    def test_direct_run_fresh_cli_mounts_identity_and_defaults(self):
        result, calls = self.run_copy('opencode/opencode-run', ['.'])
        self.assertEqual(result.returncode, 0, result.stderr)
        run = next(argv for argv in calls if argv[0] == 'run')
        for value in ('opencode-project with spaces', self.env['FIXTURE_USER'], 'HOME=/home/opencode',
                      'OPENCODE_DISABLE_AUTOUPDATE=1', 'ANTHROPIC_API_KEY',
                      'lab/opencode:latest', '16g', '8.0',
                      f'type=bind,src={self.workspace},dst=/workspace',
                      f'type=bind,src={self.root}/opencode/init.sh,dst=/opt/harness/init.sh,readonly',
                      f'type=bind,src={self.root}/opencode/.opencode/data,dst=/home/opencode/.local/share/opencode'):
            self.assertIn(value, run)
        self.assertNotIn('--cap-drop', run)  # Legacy privilege profile is not new-path policy.
        self.assertIn('OPENCODE_PASSWORD', run)
        self.assertIn('dev.xmist.opencode.lifecycle=v2-serve-1', run)
        self.assertNotIn('--network', run)
        self.assertIn(f'type=bind,src={self.root}/opencode/.opencode/state,dst=/home/opencode/.local/state/opencode', run)
        self.assertEqual(run[-1], 'lab/opencode:latest')
        self.assertEqual(calls[-2][-3:], ['python3', '/opt/harness/docker-health.py', '--wait'])
        self.assertEqual(calls[-1][-2:], ['bash', '/opt/harness/docker-client.sh'])

        self.assertNotIn('--privileged', run)
        self.assertNotIn('--pid=host', run)
        self.assertNotIn('/:/host:rw', run)
        self.assertNotIn('-p', run)
        self.assertIn('OPENCODE_EXPERIMENTAL_WORKSPACES=1', run)
        self.assertIn(f'type=bind,src={self.root}/opencode/.opencode/config,dst=/opt/opencode-defaults,readonly', run)
        self.assertIn(f'type=bind,src={self.root}/opencode/.opencode/config/publish-plugins.mjs,dst=/opt/opencode/publish-plugins.mjs,readonly', run)
        self.assertIn(f'type=bind,src={self.root}/opencode/.opencode/home-config,dst=/home/opencode/.config/opencode', run)
        self.assertFalse(any('init.sh' in str(call) for call in calls if call[0] == 'exec'))

    def test_publisher_content_changes_workstation_fingerprint(self):
        fingerprints = []
        publisher = self.root / 'opencode/.opencode/config/publish-plugins.mjs'
        for suffix in ('', '\n// changed publisher\n'):
            publisher.write_text(publisher.read_text() + suffix)
            result, calls = self.run_copy('opencode/opencode-run', ['.'])
            self.assertEqual(result.returncode, 0, result.stderr)
            run = next(call for call in calls if call[0] == 'run')
            fingerprints.append(next(value for value in run if value.startswith('dev.xmist.opencode.config=')))
        self.assertNotEqual(*fingerprints)

    def test_direct_run_privileged_flags(self):
        for flag in ('--privileged', '--priviliged'):
            with self.subTest(flag=flag):
                result, calls = self.run_copy('opencode/opencode-run', [flag, '.'])
                self.assertEqual(result.returncode, 0, result.stderr)
                run = next(call for call in calls if call[0] == 'run')
                self.assertEqual(run[run.index('--restart') + 1], 'no')
                for value in ('--privileged', '--pid=host', '/:/host:rw',
                              self.env['FIXTURE_USER'], 'OPENCODE_PASSWORD'):
                    self.assertIn(value, run)
                self.assertIn('full host-root access', result.stdout)
                self.assertIn('persists across container restarts', result.stdout)

    def test_privileged_reuse_and_recreation_in_both_directions(self):
        for configured in ('false', 'true'):
            for requested in (False, True):
                with self.subTest(configured=configured, requested=requested):
                    self.env['PRIVILEGED'] = configured
                    flags = ['--privileged'] if requested else []
                    result, calls = self.run_copy('opencode/opencode-run', [*flags, '.'], 'reuse')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    changed = requested != (configured == 'true')
                    self.assertEqual(any(call[0] == 'rm' for call in calls), changed)
                    self.assertEqual(any(call[0] == 'run' for call in calls), changed)
                    if changed:
                        run = next(call for call in calls if call[0] == 'run')
                        for value in ('--privileged', '--pid=host', '/:/host:rw'):
                            self.assertEqual(value in run, requested)
                    if requested:
                        self.assertIn('full host-root access', result.stdout)

    def test_direct_run_web_and_wlan_ports(self):
        for flags, published, port in [(['--web'], '127.0.0.1:4096:4096', '4096'),
                                       (['-w', '4097'], '127.0.0.1:4097:4096', '4097'),
                                       (['--wlan', '4098'], '0.0.0.0:4098:4096', '4098'),
                                       (['--web', '--port', '4099'], '127.0.0.1:4099:4096', '4099')]:
            with self.subTest(flags=flags):
                result, calls = self.run_copy('opencode/opencode-run', [*flags, '.'])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(published, next(argv for argv in calls if argv[0] == 'run'))
                self.assertEqual(calls[-1][-3:], ['python3', '/opt/harness/docker-health.py', '--wait'])
                self.assertFalse(any('/opt/harness/docker-client.sh' in call for call in calls))
                self.assertIn('http://localhost:' + port, result.stdout)
                self.assertEqual(calls[-1][-1], '--wait')
                self.assertFalse(any('attach' in call for call in calls))

    def test_direct_run_gpu_resources_and_publish(self):
        result, calls = self.run_copy('opencode/opencode-run',
            ['--gpu', '0,1', '--cpus', '4', '--memory', '8g', '--publish', '3000', '.'])
        self.assertEqual(result.returncode, 0, result.stderr)
        run = next(argv for argv in calls if argv[0] == 'run')
        for value in ('opencode-project with spaces-gpu', '--gpus', 'device=0,1', 'lab/opencode:gpu',
                      'dev.xmist.opencode.cpus=4', 'dev.xmist.opencode.memory=8g', '3000'):
            self.assertIn(value, run)

    def test_retired_agent_web_port_is_rejected_before_side_effects(self):
        for argv in (['--agent-web-port', '4099', '.'], ['--agent-web-port=4099', '.'],
                     ['--agent-web-port'], ['--agent-web-port='],
                     ['--web', '--agent-web-port', '4099', '.'],
                     ['--wlan', '--agent-web-port=4099', '.'],
                     ['-r', '--agent-web-port=4099', '.']):
            with self.subTest(argv=argv):
                result, calls = self.run_copy('opencode/opencode-run', argv)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('--agent-web-port has been removed', result.stderr)
                self.assertIn('--web or --wlan', result.stderr)
                self.assertEqual(calls, [])
                self.assertFalse((self.root / 'opencode/.opencode/workstation-private').exists())

    def test_direct_run_reuse_and_recreation(self):
        sentinels = []
        for name in ('config', 'home-config', 'data', 'cache', 'state'):
            sentinel = self.root / 'opencode/.opencode' / name / 'existing-private-state'
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_bytes(b'preserve existing state\x00')
            sentinels.append(sentinel)
        for scenario in ('reuse', 'stale', 'mismatch', 'legacy', 'compose', 'unowned', 'old-image', 'old-config'):
            with self.subTest(scenario=scenario):
                result, calls = self.run_copy('opencode/opencode-run', ['.'], scenario)
                self.assertEqual(result.returncode, 0, result.stderr)
                operations = [argv[0] for argv in calls]
                self.assertEqual('run' in operations, scenario != 'reuse')
                self.assertEqual('rm' in operations, scenario != 'reuse')
                self.assertEqual('stop' in operations, scenario not in ('reuse', 'stale'))
                if scenario not in ('reuse', 'stale'):
                    self.assertLess(operations.index('stop'), operations.index('rm'))
                    self.assertLess(operations.index('rm'), operations.index('run'))
                    self.assertIn('active sessions will be interrupted', result.stdout)
                self.assertEqual(operations[-1], 'exec')
                self.assertFalse(any('-v' in call or '--volumes' in call for call in calls if call[0] == 'rm'))
                self.assertFalse(any('opencode.workstation' in str(call) for call in calls))
                for sentinel in sentinels:
                    self.assertEqual(sentinel.read_bytes(), b'preserve existing state\x00')
                self.assertFalse((self.root / 'opencode/.opencode/v2').exists())

    def test_auto_is_client_flag_and_credentials_never_enter_argv(self):
        result, calls = self.run_copy('opencode/opencode-run', ['-d', '.'], 'reuse')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call[0] in ('run', 'rm') for call in calls))
        self.assertEqual(calls[-1][-2:], ['/opt/harness/docker-client.sh', '--auto'])
        for call in calls:
            if call[0] == 'exec':
                self.assertNotIn('-e', call)
                self.assertNotIn('--permission', call)
        self.env['OPENCODE_SERVER_USERNAME'] = 'alice'
        result, calls = self.run_copy('opencode/opencode-run', ['.'], 'reuse')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('username opencode', result.stderr)
        self.assertFalse(any(call[0] in ('run', 'rm', 'exec') for call in calls))

    def test_backend_readiness_failure_never_attaches_or_reports_ready(self):
        for scenario in ('unready', 'unready-reuse'):
            for flags in ([], ['--web', '4097']):
                with self.subTest(scenario=scenario, flags=flags):
                    self.env.update(EXPOSURE='127.0.0.1:4097' if flags else 'none', MAPPING='127.0.0.1:4097')
                    result, calls = self.run_copy('opencode/opencode-run', [*flags, '.'], scenario)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('no client was attached', result.stderr)
                    self.assertNotIn('Browser backend ready', result.stdout)
                    self.assertFalse(any('/opt/harness/docker-client.sh' in call for call in calls))

    def test_backend_reuse_checks_internal_port_and_requested_host_binding(self):
        for flags, exposure, mapping in [
            (['--web', '4097'], '127.0.0.1:4097', '127.0.0.1:4097'),
            (['--wlan', '4098'], '0.0.0.0:4098', '0.0.0.0:4098'),
        ]:
            for actual in (mapping, '127.0.0.1:9999', ''):
                with self.subTest(flags=flags, actual=actual):
                    self.env.update(EXPOSURE=exposure, MAPPING=actual)
                    result, calls = self.run_copy('opencode/opencode-run', [*flags, '.'], 'reuse')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(['port', 'opencode-project with spaces', '4096/tcp'], calls)
                    self.assertEqual(any(call[0] == 'run' for call in calls), actual != mapping)
                    self.assertFalse(any('init.sh' in str(call) for call in calls if call[0] == 'exec'))
                    self.assertFalse(any('attach' in call for call in calls))
                    self.assertIn('Browser backend ready', result.stdout)

    def test_plain_invocation_removes_previous_web_exposure(self):
        self.env['EXPOSURE'] = '0.0.0.0:4096'
        result, calls = self.run_copy('opencode/opencode-run', ['.'], 'reuse')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('-p', next(call for call in calls if call[0] == 'run'))

    def test_port_flag_alone_does_not_publish(self):
        result, calls = self.run_copy('opencode/opencode-run', ['--port', '4097', '.'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('-p', next(call for call in calls if call[0] == 'run'))

    def test_backend_migration_preserves_custom_volume_request(self):
        result, calls = self.run_copy('opencode/opencode-run',
                                      ['--volume', f'{self.workspace}:/reference:ro', '.'], 'legacy')
        self.assertEqual(result.returncode, 0, result.stderr)
        run = next(call for call in calls if call[0] == 'run')
        self.assertIn(f'type=bind,src={self.workspace},dst=/reference,readonly', run)
        self.assertNotIn('-p', run)
        self.assertIn('/opt/harness/docker-client.sh', calls[-1])

    def test_direct_run_invalid_input_and_missing_image_do_not_launch(self):
        for argv, scenario in [(['--port', 'bad'], 'fresh'), (['--cpus', '0'], 'fresh'),
                               (['--web', '--agent-web-port', '4098'], 'fresh'),
                                (['--agent-web-port', '4099'], 'fresh'),
                                (['--publish', '4096'], 'fresh'), (['.'], 'missing-image')]:
            result, calls = self.run_copy('opencode/opencode-run', argv, scenario)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any(call[0] in ('run', 'exec', 'rm') for call in calls))
            if scenario == 'missing-image':
                self.assertIn('opencode rebuild', result.stderr)
                self.assertNotIn('docker compose', result.stderr)

    def test_direct_run_provisions_and_reuses_protected_password(self):
        self.env.pop('OPENCODE_PASSWORD')
        result, calls = self.run_copy('opencode/opencode-run', ['.'], 'old-image')
        self.assertEqual(result.returncode, 0, result.stderr)
        password = self.root / 'opencode/.opencode/workstation-private/backend-password'
        value = password.read_text()
        self.assertEqual(len(value), 65)
        self.assertEqual(password.stat().st_mode & 0o777, 0o600)
        self.assertEqual(password.parent.stat().st_mode & 0o777, 0o700)
        self.assertNotIn(value.strip(), result.stdout + result.stderr + json.dumps(calls))
        result, calls = self.run_copy('opencode/opencode-run', ['.'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(password.read_text(), value)

    def test_v2_server_serves_and_client_attaches_without_secret_argv(self):
        # Execute maintained helper bodies with only init and executable boundaries
        # stubbed. No real engine, socket, provider, HOME or /opt files are touched.
        (self.bin / 'bash').symlink_to('/bin/bash')
        initialize = self.root / 'init.sh'
        initialize.write_text('exit 0\n')
        server = self.root / 'docker-server.sh'
        text = (ROOT / 'opencode/scripts/docker-server.sh').read_text()
        self.assertEqual(text.count('bash /opt/harness/init.sh'), 1)
        server.write_text(text.replace('bash /opt/harness/init.sh', 'bash "$FIXTURE_INIT"'))
        result = subprocess.run(['/bin/bash', str(server)], env=dict(self.env, FIXTURE_INIT=str(initialize)),
                                capture_output=True, text=True, timeout=10)
        if os.geteuid() == 0:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('non-root', result.stderr)
        else:
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
            self.assertEqual(calls, [['opencode', ['serve', '--hostname', '0.0.0.0', '--port', '4096']]])
        self.calls.unlink(missing_ok=True)
        result = subprocess.run(['/bin/bash', str(ROOT / 'opencode/scripts/docker-client.sh'), '--auto'],
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(calls, [
            ['python3', ['/opt/harness/docker-health.py', '--wait']],
            ['opencode', ['--server', 'http://127.0.0.1:4096', '--auto']]])
        self.assertNotIn('fixture-private-password', json.dumps(calls) + result.stdout + result.stderr)
        for arguments in (['--server', 'http://foreign'], ['--server=http://foreign'], ['serve']):
            self.calls.unlink(missing_ok=True)
            result = subprocess.run(['/bin/bash', str(ROOT / 'opencode/scripts/docker-client.sh'), *arguments],
                                    env=self.env, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('server overrides', result.stderr)
            self.assertFalse(self.calls.exists())

    def test_existing_application_directory_permissions_are_preserved(self):
        for name in ('home-config', 'data', 'cache', 'state', 'locks'):
            directory = self.root / 'opencode/.opencode' / name
            directory.mkdir(exist_ok=True)
            directory.chmod(0o777)
        result, _ = self.run_copy('opencode/opencode-run', ['.'])
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('home-config', 'data', 'cache', 'state', 'locks'):
            directory = self.root / 'opencode/.opencode' / name
            self.assertEqual(directory.stat().st_mode & 0o777, 0o777)

    def test_concurrent_password_provisioning_is_stable(self):
        env = dict(self.env)
        env.pop('OPENCODE_PASSWORD')
        command = ['/usr/bin/python3', str(self.root / 'opencode/scripts/workstation-state.py'),
                   str(self.root / 'opencode')]
        processes = [subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True) for _ in range(8)]
        outputs = [process.communicate(timeout=10) for process in processes]
        self.assertTrue(all(process.returncode == 0 for process in processes), [err for _, err in outputs])
        self.assertEqual(len({out for out, _ in outputs}), 1)
        password = self.root / 'opencode/.opencode/workstation-private/backend-password'
        self.assertEqual(outputs[0][0], password.read_text())

    def test_credential_overrides_preserve_local_secret_and_provider_keys(self):
        self.env.pop('OPENCODE_PASSWORD')
        result, _ = self.run_copy('opencode/opencode-run', ['.'])
        self.assertEqual(result.returncode, 0, result.stderr)
        password = self.root / 'opencode/.opencode/workstation-private/backend-password'
        original = password.read_bytes()
        for preferred in ('', 'fixture-preferred'):
            self.env.update(OPENCODE_PASSWORD=preferred, OPENCODE_SERVER_PASSWORD='fixture-fallback',
                            OPENAI_API_KEY='fixture-provider')
            result, calls = self.run_copy('opencode/opencode-run', ['.'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(password.read_bytes(), original)
            for secret in ('fixture-preferred', 'fixture-fallback', 'fixture-provider'):
                self.assertNotIn(secret, result.stdout + result.stderr + json.dumps(calls))
            # The filesystem helper's private pipe resolves precedence, not argv.
            value = subprocess.run(['/usr/bin/python3', str(self.root / 'opencode/scripts/workstation-state.py'),
                                    str(self.root / 'opencode')], env=self.env,
                                   text=True, capture_output=True, check=True).stdout.strip()
            self.assertEqual(value, preferred or 'fixture-fallback')

    def test_unsafe_credential_is_preserved_and_fails_before_build(self):
        self.env.pop('OPENCODE_PASSWORD')
        private = self.root / 'opencode/.opencode/workstation-private'
        private.mkdir(mode=0o700)
        password = private / 'backend-password'
        outside = self.root / 'outside'
        outside.write_text('preserve')
        for kind in ('empty', 'mode', 'symlink', 'hardlink', 'directory'):
            with self.subTest(kind=kind):
                if kind == 'symlink':
                    password.symlink_to(outside)
                elif kind == 'hardlink':
                    os.link(outside, password)
                elif kind == 'directory':
                    password.mkdir()
                else:
                    password.write_text('' if kind == 'empty' else 'a' * 64 + '\n')
                    password.chmod(0o600 if kind == 'empty' else 0o644)
                result, calls = self.run_copy('opencode/opencode-run', ['-r', '.'], 'old-image')
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(call[0] in ('build', 'run', 'exec', 'stop', 'rm') for call in calls))
                self.assertEqual(outside.read_text(), 'preserve')
                if kind == 'directory':
                    password.rmdir()
                else:
                    password.unlink()
        private.chmod(0o755)
        result, _ = self.run_copy('opencode/opencode-run', ['.'])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(private.stat().st_mode & 0o777, 0o755)

    def test_failed_build_wrong_identity_and_remote_daemon_fail_closed(self):
        for scenario, flags in [('build-failed', ['-r']), ('wrong-user', [])]:
            result, calls = self.run_copy('opencode/opencode-run', [*flags, '.'], scenario)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any(call[0] in ('run', 'exec', 'stop', 'rm') for call in calls))
        result, calls = self.run_copy('opencode/opencode-mgr', ['rebuild'], 'build-failed')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call[0] in ('rm', 'stop') for call in calls))
        result, calls = self.run_copy('opencode/opencode-run', ['.'], 'run-failed')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call[0] == 'exec' for call in calls))
        self.env['DOCKER_HOST'] = 'ssh://unresolved-host'
        result, calls = self.run_copy('opencode/opencode-run', ['-r', '.'])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_root_launch_is_rejected_without_docker_operations(self):
        (self.bin / 'id').write_text('#!/bin/bash\necho 0\n')
        result, calls = self.run_copy('opencode/opencode-run', ['-r', '.'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('non-root', result.stderr)
        self.assertEqual(calls, [])

    def test_application_state_symlink_is_accepted_and_retained(self):
        data = self.root / 'opencode/.opencode/data'
        data.symlink_to(self.workspace)
        sentinel = self.workspace / 'session-state'
        sentinel.write_text('preserve')
        result, calls = self.run_copy('opencode/opencode-run', ['-r', '.'], 'old-image')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(data.is_symlink())
        self.assertEqual(sentinel.read_text(), 'preserve')
        self.assertTrue(any(call[0] == 'run' for call in calls))

    def test_missing_bind_sources_fail_without_repair(self):
        (self.root / 'opencode/ssh').rmdir()
        result, calls = self.run_copy('opencode/opencode-run', ['-r', '.'], 'old-image')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'opencode/ssh').exists())
        self.assertFalse(any(call[0] in ('build', 'run', 'stop', 'rm') for call in calls))

    def test_name_scoped_cleanup_includes_legacy_and_compose_containers(self):
        sentinel = self.root / 'opencode/.opencode/config/private-state'
        sentinel.write_text('preserve')
        for argv in (['rebuild'], ['clean'], ['fclean'], ['remove', 'all'], ['stop', 'all']):
            result, calls = self.run_copy('opencode/opencode-mgr', argv, stdin='y\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            for call in calls:
                if call[0] in ('rm', 'stop'):
                    self.assertIn('opencode-legacy', call)
                    self.assertIn('opencode-compose', call)
                    self.assertNotIn('-v', call)
            self.assertTrue(all('name=opencode-' in call for call in calls if call[0] == 'ps'))
            self.assertFalse(any(call[0] == 'inspect' for call in calls))
            self.assertEqual(sentinel.read_text(), 'preserve')
            self.assertTrue(any(call[0] in ('rm', 'stop') for call in calls))

    def test_leading_rebuild_differs_from_manager_update(self):
        for flags, image in [([], 'lab/opencode:latest'), (['--gpu', '0,1'], 'lab/opencode:gpu')]:
            result, calls = self.run_copy('opencode/opencode-run', ['-r', *flags, '.'])
            self.assertEqual(result.returncode, 0, result.stderr)
            builds = [argv for argv in calls if argv[0] == 'build']
            self.assertEqual(len(builds), 1)
            self.assertIn(image, builds[0])
            self.assertIn(f'LOCAL_UID={self.uid}', builds[0])
            self.assertIn(f'LOCAL_GID={self.gid}', builds[0])
            self.assertLess(calls.index(builds[0]), next(i for i, call in enumerate(calls) if call[0] == 'run'))
            self.assertIn('/opt/harness/docker-client.sh', calls[-1])
        for target, count in [('cpu', 1), ('gpu', 1), ('all', 2)]:
            result, calls = self.run_copy('opencode/opencode-mgr', ['update', target])
            self.assertEqual(result.returncode, 0, result.stderr)
            builds = [argv for argv in calls if argv[0] == 'build']
            self.assertEqual(len(builds), count)
            self.assertTrue(all('--pull' in argv for argv in builds))
            self.assertEqual(calls[-1], ['rm', '-f', 'opencode-legacy', 'opencode-compose'])

    def test_direct_manager_destructive_commands_are_only_recorded(self):
        for argv, expected in [(['stop', 'fixture name'], ['stop', 'fixture name']),
                               (['start', 'fixture name'], ['start', 'fixture name']),
                               (['remove', 'fixture name'], ['rm', '-f', 'fixture name']),
                               (['logs', 'fixture name'], ['logs', '-f', 'fixture name']),
                               (['shell', 'fixture name'], ['exec', '-it', '-e', 'OPENCODE_EXPERIMENTAL_WORKSPACES=1', 'fixture name', '/bin/bash'])]:
            result, calls = self.run_copy('opencode/opencode-mgr', argv)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls[-1], expected)
            self.assertEqual(calls, [expected])
        result, calls = self.run_copy('opencode/opencode-mgr', ['remove', 'all'], stdin='n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])
        result, calls = self.run_copy('opencode/opencode-mgr', ['remove', 'all'], stdin='y\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-1], ['rm', '-f', 'opencode-legacy', 'opencode-compose'])
        result, calls = self.run_copy('opencode/opencode-mgr', ['stop'])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_native_opencode_initialize_allowlist_and_conflict_preservation(self):
        component = self.root / 'opencode'
        component.mkdir(exist_ok=True)
        script = component / 'entrypoint.sh'
        shutil.copyfile(ROOT / 'opencode/scripts/entrypoint.sh', script)
        defaults = component / '.opencode/config'
        for relative in ('opencode.json', 'cli.json', 'publish-plugins.mjs',
                         'plugins/background-subagents.js', 'tui-plugins/session-title.mjs',
                         'tui-plugins/session-title/tui.js'):
            destination = defaults / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / 'opencode/.opencode/config' / relative, destination)
        (defaults / 'opencode.json').write_text(json.dumps({
            'agents': {'build': {'system': 'fixture'}}, 'providers': {}, 'permissions': []}))
        (defaults / 'auth.json').write_text('{"private":"never seed"}')
        resources = self.root / 'agent'
        for name in ('commands', 'skills', 'system'):
            (resources / name).mkdir(parents=True)
        config = self.home / '.config/opencode'
        env = dict(self.env, OPENCODE_HOME=str(self.home), OPENCODE_CONFIG_DIR=str(config),
                   OPENCODE_REPO=str(self.root), OPENCODE_ROOT=str(component), ENTRYPOINT=str(script))
        # Source function definitions only. Stub account guard and Git boundary;
        # no passwd lookup, real Git defaults, native runtime or lifecycle install.
        body = '''source "$ENTRYPOINT"
require_opencode_user() { :; }
opencode_git() {
    case "$1" in
      ls-files) printf '%s\\0' opencode/.opencode/config/opencode.json opencode/.opencode/config/auth.json ;;
      *) return 97 ;;
    esac
}
initialize_home
'''
        def initialize():
            return subprocess.run(['/bin/bash', '-c', body], cwd=self.workspace, env=env,
                                  capture_output=True, text=True, timeout=10)

        result = initialize()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((config / 'system').readlink(), resources / 'system')
        canonical = json.loads((defaults / 'opencode.json').read_text())
        self.assertEqual(json.loads((config / 'opencode.json').read_text()), canonical)
        self.assertIn('agents', canonical)
        self.assertIn('providers', canonical)
        self.assertIn('permissions', canonical)
        self.assertFalse((config / 'cli.json').is_symlink())
        self.assertEqual(json.loads((config / 'cli.json').read_text()),
                         json.loads((defaults / 'cli.json').read_text()))
        for relative in ('plugins/background-subagents.js',
                         'tui-plugins/session-title.mjs', 'tui-plugins/session-title/tui.js'):
            self.assertEqual((config / relative).readlink(), defaults / relative)
        self.assertFalse((config / 'v2').exists())
        self.assertFalse((config / 'plugins/first-prompt-title.js').exists())
        self.assertFalse((config / 'plugins/first-prompt-title.js').is_symlink())
        self.assertFalse((config / 'auth.json').exists())
        legacy_shared = self.home / '.agents'
        legacy_shared.mkdir()
        previous = self.root / 'previous-checkout'
        env['OPENCODE_PREVIOUS_REPO'] = str(previous)
        (config / 'gsd').symlink_to(resources / 'gsd')
        self.assertEqual(initialize().returncode, 0)
        self.assertFalse((config / 'gsd').is_symlink())
        # Previous checkout paths and .agents are not owned by this publisher;
        # unknown legacy content must survive instead of being guessed away.
        (config / 'gsd').symlink_to(previous / 'agent/gsd')
        (legacy_shared / 'gsd').symlink_to('/custom/legacy-gsd')
        self.assertEqual(initialize().returncode, 0)
        self.assertEqual((config / 'gsd').readlink(), previous / 'agent/gsd')
        self.assertEqual((legacy_shared / 'gsd').readlink(), Path('/custom/legacy-gsd'))
        (config / 'gsd').unlink()
        (legacy_shared / 'gsd').unlink()
        (config / 'gsd').symlink_to('/custom/gsd')
        (legacy_shared / 'gsd').mkdir()
        (legacy_shared / 'gsd/private.md').write_text('preserved')
        self.assertEqual(initialize().returncode, 0)
        self.assertEqual((config / 'gsd').readlink(), Path('/custom/gsd'))
        self.assertEqual((legacy_shared / 'gsd/private.md').read_text(), 'preserved')
        private = json.dumps({'agents': {'build': {'system': 'private fixture prompt'}}})
        (config / 'opencode.json').unlink()
        (config / 'opencode.json').write_text(private)
        self.assertNotEqual(initialize().returncode, 0)
        self.assertEqual((config / 'opencode.json').read_text(), private)
        (config / 'skills').unlink()
        (config / 'skills').mkdir()
        result = initialize()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('conflict', result.stderr.lower())
        self.assertTrue((config / 'skills').is_dir())
        self.assertFalse(self.calls.exists())

    def test_native_pi_import_is_individual_idempotent_and_conflict_safe(self):
        script = self.root / 'pi-init.sh'
        shutil.copyfile(ROOT / 'pi/init.sh', script)
        resources = self.root / 'agent'
        (resources / 'system').mkdir(parents=True)
        (resources / 'system/build.md').write_text('Public fixture')
        agents = self.home / 'agents'
        env = dict(self.env, INIT=str(script), RESOURCES=str(resources), AGENTS=str(agents))
        body = 'source "$INIT"; import_system_agents "$RESOURCES" "$AGENTS"'

        def initialize():
            return subprocess.run(['/bin/bash', '-c', body], env=env, cwd=self.workspace,
                                  capture_output=True, text=True, timeout=10)

        for _ in range(2):
            result = initialize()
            self.assertEqual(result.returncode, 0, result.stderr)
        imported = agents / 'system-build.md'
        self.assertEqual(imported.readlink(), resources / 'system/build.md')
        imported.unlink()
        imported.write_text('User fixture')
        self.assertNotEqual(initialize().returncode, 0)
        self.assertEqual(imported.read_text(), 'User fixture')
        imported.unlink()
        (resources / 'system/build.md').unlink()
        (resources / 'system/build.md').symlink_to(self.root / 'outside.md')
        (self.root / 'outside.md').write_text('Outside fixture')
        self.assertNotEqual(initialize().returncode, 0)
        self.assertFalse(imported.exists())

    @unittest.skipIf(yaml is None, 'Compose characterization requires PyYAML in the test environment')
    def test_compose_contracts_without_interpolation_or_docker(self):
        assert yaml is not None
        for component, service, image, home in [('pi', 'pi', 'lab/pi:latest', '/home/pi'),
                ('claudecode', 'claude-code', 'lab/claude-code:latest', '/home/claude')]:
            with self.subTest(component=component):
                copied = self.root / (component + '.yml')
                shutil.copyfile(ROOT / component / 'docker-compose.yml', copied)
                document = yaml.safe_load(copied.read_text())
                spec = document['services'][service]
                self.assertEqual(spec['image'], image)
                self.assertEqual(spec['user'], '${UID:-1000}:${GID:-1000}')
                self.assertEqual(spec['security_opt'], [])
                self.assertFalse(spec['read_only'])
                self.assertTrue(spec['stdin_open'] and spec['tty'])
                self.assertIn('HOME=' + home, spec['environment'])
                self.assertIn('../agent:/opt/agent:rw', spec['volumes'])
                self.assertIn('./init.sh:/opt/harness/init.sh:ro', spec['volumes'])
                self.assertEqual(spec['entrypoint'], ['bash', '-lc', '/opt/harness/init.sh && tail -f /dev/null'])
                self.assertTrue(document['networks']['devai-xmist']['external'])


if __name__ == '__main__':
    unittest.main()
