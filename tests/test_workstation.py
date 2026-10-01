"""Workstation scripts with isolated HOME and Docker/native boundary recorders.

No real Docker/Compose, credential files, package installs or network calls.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


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
        # No fallback PATH: only ordinary filesystem/text utilities used by these
        # copied scripts. Docker and sleep are always stubs.
        for name in ('dirname', 'basename', 'realpath', 'mkdir', 'id', 'grep', 'awk',
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
    if args[0] == 'ps':
        if 'status=running' in args:
            created = any(json.loads(line)[1][:1] == ['run']
                          for line in Path(os.environ['CALLS']).read_text().splitlines())
            if scenario != 'stale' or created:
                print('fixture-id')
        elif 'name=opencode-' in args and '-aq' in args:
            print('fixture-one\\nfixture-two')
        elif scenario in ('reuse', 'stale', 'mismatch', 'legacy', 'permission', 'unready-reuse'):
            print('Up fixture' if scenario != 'stale' else 'Exited fixture')
    elif args[0] == 'inspect':
        fmt = args[2]
        print('lab/opencode:latest' if fmt == '{{.Config.Image}}' else
              ('' if scenario == 'legacy' else 'web-v1') if '.lifecycle' in fmt else
              ('{"*":"allow"}' if scenario == 'permission' else '{}') if '.permission' in fmt else
              os.environ.get('EXPOSURE', 'none') if '.web"' in fmt else
              hashlib.sha256(bytes([0])).hexdigest() if '.volumes' in fmt else
              ('4' if scenario == 'mismatch' else '8.0') if '.cpus' in fmt else
              '16g' if '.memory' in fmt else '')
    elif args[0] == 'port':
        assert args[-1] == '4096/tcp', args
        print(os.environ.get('MAPPING', ''))
    elif args[0] == 'exec':
        if '--wait' in args and scenario.startswith('unready'):
            sys.exit(1)
        if 'attach' in args:
            # A second launcher must be able to enter while a TUI is attached.
            for lock in Path(os.environ['CALLS']).parent.glob('opencode/.opencode/locks/*'):
                with lock.open('w') as stream:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    elif args[:2] == ['image', 'inspect'] and scenario == 'missing-image':
        sys.exit(1)
'''
        for name in ('docker', 'sleep'):
            path = self.bin / name
            path.write_text(recorder)
            path.chmod(0o755)
        self.env = {'PATH': str(self.bin), 'HOME': str(self.home), 'CALLS': str(self.calls),
                    'PYTHONDONTWRITEBYTECODE': '1'}

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
        return result, [argv for tool, argv in calls if tool == 'docker']

    def test_direct_run_fresh_cli_mounts_identity_and_defaults(self):
        result, calls = self.run_copy('opencode/opencode-run', ['.'])
        self.assertEqual(result.returncode, 0, result.stderr)
        run = next(argv for argv in calls if argv[0] == 'run')
        for value in ('opencode-project with spaces', '1000:1000', 'HOME=/home/opencode',
                      'OPENCODE_DISABLE_AUTOUPDATE=1', 'ANTHROPIC_API_KEY=',
                      'lab/opencode:latest', '16g', '8.0', 'devai-xmist',
                      str(self.workspace) + ':/workspace:rw',
                      str(self.root / 'opencode/init.sh') + ':/opt/harness/init.sh:ro',
                      str(self.root / 'opencode/.opencode/data') + ':/home/opencode/.local/share/opencode:rw'):
            self.assertIn(value, run)
        self.assertNotIn('--cap-drop', run)  # Legacy privilege profile is not new-path policy.
        self.assertNotIn('-p', run)
        self.assertEqual(run[-1], '/opt/harness/init.sh && exec opencode web --hostname 0.0.0.0 --port 4096 --mdns false')
        self.assertEqual(calls[-1][-5:], ['opencode', 'attach', 'http://127.0.0.1:4096', '--dir', '/workspace'])
        self.assertIn('OPENCODE_EXPERIMENTAL_WORKSPACES=1', run)
        self.assertIn('OPENCODE_PERMISSION={}', run)
        self.assertIn('dev.xmist.opencode.lifecycle=web-v1', run)
        self.assertIn('node /opt/harness/backend-health.mjs', run)
        self.assertEqual(calls[-2][-3:], ['node', '/opt/harness/backend-health.mjs', '--wait'])
        self.assertFalse(any('init.sh' in str(call) for call in calls if call[0] == 'exec'))

    def test_direct_run_web_and_wlan_ports(self):
        for flags, published, port in [(['--web'], '127.0.0.1:4096:4096', '4096'),
                                       (['-w', '4097'], '127.0.0.1:4097:4096', '4097'),
                                       (['--wlan', '4098'], '0.0.0.0:4098:4096', '4098'),
                                       (['--web', '--port', '4099'], '127.0.0.1:4099:4096', '4099')]:
            with self.subTest(flags=flags):
                result, calls = self.run_copy('opencode/opencode-run', [*flags, '.'])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(published, next(argv for argv in calls if argv[0] == 'run'))
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
                self.assertFalse((self.root / 'opencode/.opencode').exists())

    def test_direct_run_reuse_and_recreation(self):
        for scenario in ('reuse', 'stale', 'mismatch', 'legacy', 'permission'):
            with self.subTest(scenario=scenario):
                result, calls = self.run_copy('opencode/opencode-run', ['.'], scenario)
                self.assertEqual(result.returncode, 0, result.stderr)
                operations = [argv[0] for argv in calls]
                self.assertEqual('run' in operations, scenario != 'reuse')
                self.assertEqual('rm' in operations, scenario != 'reuse')
                self.assertEqual(operations[-1], 'exec')

    def test_backend_permission_change_and_auth_are_server_wide(self):
        self.env.update(OPENCODE_SERVER_PASSWORD='fixture-secret', OPENCODE_SERVER_USERNAME='alice')
        result, calls = self.run_copy('opencode/opencode-run', ['-d', '.'], 'reuse')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(call[0] == 'rm' for call in calls))
        run = next(call for call in calls if call[0] == 'run')
        self.assertIn('OPENCODE_PERMISSION={"*":"allow"}', run)
        self.assertIn('dev.xmist.opencode.permission={"*":"allow"}', run)
        self.assertIn('OPENCODE_SERVER_PASSWORD=fixture-secret', run)
        self.assertNotIn('fixture-secret', result.stdout + result.stderr)
        for call in calls:
            if call[0] == 'exec':
                self.assertNotIn('-e', call)
                self.assertNotIn('--permission', call)
                self.assertNotIn('fixture-secret', str(call))
        result, calls = self.run_copy('opencode/opencode-run', ['-d', '.'], 'permission')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call[0] in ('run', 'rm') for call in calls))

    def test_backend_readiness_failure_never_attaches_or_reports_ready(self):
        for scenario in ('unready', 'unready-reuse'):
            for flags in ([], ['--web', '4097']):
                with self.subTest(scenario=scenario, flags=flags):
                    self.env.update(EXPOSURE='127.0.0.1:4097' if flags else 'none', MAPPING='127.0.0.1:4097')
                    result, calls = self.run_copy('opencode/opencode-run', [*flags, '.'], scenario)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('no client was attached', result.stderr)
                    self.assertNotIn('Browser backend ready', result.stdout)
                    self.assertFalse(any('attach' in call for call in calls))

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
        self.assertIn(f'{self.workspace}:/reference:ro', run)
        self.assertNotIn('-p', run)
        self.assertIn('attach', calls[-1])

    def test_direct_run_invalid_input_and_missing_image_do_not_launch(self):
        for argv, scenario in [(['--port', 'bad'], 'fresh'), (['--cpus', '0'], 'fresh'),
                               (['.'], 'missing-image')]:
            result, calls = self.run_copy('opencode/opencode-run', argv, scenario)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any(call[0] in ('run', 'exec', 'rm') for call in calls))
            if scenario == 'missing-image':
                self.assertIn('opencode rebuild', result.stderr)
                self.assertNotIn('docker compose', result.stderr)

    def test_leading_rebuild_differs_from_manager_update(self):
        result, calls = self.run_copy('opencode/opencode-run', ['-r', '.'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([argv[0] for argv in calls], ['build', 'build'])
        self.assertFalse(any('--pull' in argv for argv in calls))
        for target, count in [('cpu', 1), ('gpu', 1), ('all', 2)]:
            result, calls = self.run_copy('opencode/opencode-mgr', ['update', target])
            self.assertEqual(result.returncode, 0, result.stderr)
            builds = [argv for argv in calls if argv[0] == 'build']
            self.assertEqual(len(builds), count)
            self.assertTrue(all('--pull' in argv for argv in builds))
            self.assertEqual(calls[-1], ['rm', '-f', 'fixture-one', 'fixture-two'])

    def test_direct_manager_destructive_commands_are_only_recorded(self):
        for argv, expected in [(['stop', 'fixture name'], ['stop', 'fixture name']),
                               (['start', 'fixture name'], ['start', 'fixture name']),
                               (['remove', 'fixture name'], ['rm', '-f', 'fixture name']),
                               (['logs', 'fixture name'], ['logs', '-f', 'fixture name']),
                               (['shell', 'fixture name'], ['exec', '-it', '-e', 'OPENCODE_EXPERIMENTAL_WORKSPACES=1', 'fixture name', '/bin/bash'])]:
            result, calls = self.run_copy('opencode/opencode-mgr', argv)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(calls, [expected])
        result, calls = self.run_copy('opencode/opencode-mgr', ['remove', 'all'], stdin='n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])
        result, calls = self.run_copy('opencode/opencode-mgr', ['remove', 'all'], stdin='y\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-1], ['rm', '-f', 'fixture-one', 'fixture-two'])
        result, calls = self.run_copy('opencode/opencode-mgr', ['stop'])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_native_opencode_initialize_allowlist_and_conflict_preservation(self):
        component = self.root / 'opencode'
        component.mkdir()
        script = component / 'entrypoint.sh'
        shutil.copyfile(ROOT / 'opencode/scripts/entrypoint.sh', script)
        (component / 'scripts').mkdir()
        shutil.copyfile(ROOT / 'opencode/scripts/publish-plugins.mjs', component / 'scripts/publish-plugins.mjs')
        defaults = component / '.opencode/config'
        (defaults / 'kdco').mkdir(parents=True)
        (defaults / 'plugins').mkdir()
        for name in ('background-agents', 'worktree', 'notify'):
            (defaults / f'plugins/kdco-{name}.ts').write_text('export default async () => ({})')
        resources = self.root / 'agent'
        for name in ('commands', 'skills', 'system', 'gsd'):
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
      show) printf '{"fixture":true}\\n' ;;
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
        self.assertEqual(json.loads((config / 'opencode.json').read_text()), {'fixture': True})
        self.assertFalse((config / 'auth.json').exists())
        (config / 'opencode.json').write_text('private fixture config')
        self.assertEqual(initialize().returncode, 0)
        self.assertEqual((config / 'opencode.json').read_text(), 'private fixture config')
        (config / 'skills').unlink()
        (config / 'skills').mkdir()
        result = initialize()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('preserved conflicting resource', result.stderr)
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

    def test_compose_contracts_without_interpolation_or_docker(self):
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
