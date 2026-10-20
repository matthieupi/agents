"""Copied legacy scripts with isolated HOME and Docker/native boundary recorders.

No real Docker/Compose, credential files, package installs or network calls.
"""
import json
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


ROOT = Path(__file__).resolve().parents[2]


class LegacyDispatch(unittest.TestCase):
    def test_unaffected_dispatchers_byte_identical_to_head(self):
        # OpenCode intentionally migrated. Protect only unchanged dispatcher bytes;
        # do not turn unrelated dirty production trees or mode changes into failures.
        for relative in ('pi/pi', 'omp/omp', 'claudecode/claude', 't3code/t3code'):
            with self.subTest(relative=relative):
                result = subprocess.run(['git', '-C', str(ROOT), 'show', 'HEAD:' + relative],
                                        capture_output=True, check=True)
                self.assertEqual((ROOT / relative).read_bytes(), result.stdout)

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
            if component == 't3code':
                (root / 'scripts').mkdir()
                (root / 'scripts/host.py').write_text(recorder)
            result = subprocess.run(['/bin/bash', str(root / wrapper), *arguments],
                                    cwd=root, text=True, capture_output=True,
                                    env={'PATH': '/usr/bin:/bin'}, check=True)
            return json.loads(result.stdout)

    def test_opencode_run_verbatim(self):
        cases = [[], ['.'], ['/project'], ['--web'], ['-w', '4096', '.'],
                 ['--wlan', '4096'], ['--port', '4097'], ['--agent-web-port', '4098'],
                 ['--gpu', '0', '.'], ['--cpus', '4', '--memory', '8g'],
                 ['--publish', '3000'], ['-r', '.'], ['--', 'a b', '$(false)']]
        for argv in cases:
            with self.subTest(argv=argv):
                self.assertEqual(self.dispatch('opencode', 'opencode', argv), ['opencode-run', argv])

    def test_management_aliases(self):
        common = 'list ls stop start remove rm clean fclean logs shell'.split()
        for component, wrapper, extra in [('opencode', 'opencode', ['rebuild', 'update']),
                                          ('pi', 'pi', ['build', 'rebuild', 'update', 'login']),
                                          ('omp', 'omp', ['build', 'rebuild', 'update']),
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

    def test_omp_rebuild_and_native_resume(self):
        for argv, result in [(['-r', 'x'], ['omp-mgr', ['rebuild', 'x']]),
                             (['session', '-r'], ['omp-run', ['-r']]),
                             (['--', '-r'], ['omp-run', ['--', '-r']]),
                             (['.', '-r'], ['omp-run', ['.', '-r']]),
                             (['--resume'], ['omp-run', ['--resume']])]:
            self.assertEqual(self.dispatch('omp', 'omp', argv), result)

    def test_claude_run(self):
        for argv in ([], ['.'], ['-r', '.'], ['--dangerous', '.']):
            self.assertEqual(self.dispatch('claudecode', 'claude', argv), ['claude-run', argv])

    def test_t3_python_boundary(self):
        for argv in ([], ['.'], ['build'], ['recreate'], ['pair'], ['auth'], ['provider']):
            self.assertEqual(self.dispatch('t3code', 't3code', argv), ['host.py', ['dispatch', *argv]])


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
        # copied scripts. Docker, Python socket probes and sleep are always stubs.
        for name in ('dirname', 'basename', 'realpath', 'mkdir', 'id', 'grep', 'awk',
                      'xargs', 'readlink', 'ln', 'rm', 'mktemp', 'cat', 'stat', 'cmp',
                      'cp', 'mv', 'sha256sum'):
            executable = shutil.which(name)
            if executable is None:
                self.fail('Required characterization utility missing: ' + name)
            (self.bin / name).symlink_to(executable)
        recorder = '''#!/usr/bin/python3
import json, os, sys
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
        elif scenario in ('reuse', 'stale', 'mismatch', 'old-image', 'old-lifecycle', 'old-config'):
            print('Up fixture' if scenario != 'stale' else 'Exited fixture')
    elif args[0] == 'inspect':
        fmt = args[2]
        print(('sha256:old' if scenario == 'old-image' else 'sha256:new') if fmt == '{{.Image}}' else
              ('v1' if scenario == 'old-lifecycle' else 'v2-serve-1') if 'lifecycle' in fmt else
              ('old-config' if scenario == 'old-config' else 'fixture-config') if 'opencode.config' in fmt else
              ('4' if scenario == 'mismatch' else '8.0') if '.cpus' in fmt else
              '16g' if '.memory' in fmt else '')
    elif args[:2] == ['image', 'inspect']:
        if scenario == 'missing-image': sys.exit(1)
        if '--format' in args:
            print('sha256:new' if args[args.index('--format') + 1] == '{{.Id}}' else 'v2-serve-1')
elif tool == 'python3':
    # Stub only host fingerprint/socket boundaries, not the Docker server/client.
    if args[:1] == ['-'] and len(args) > 1 and args[1].startswith('/'):
        print('fixture-config')
    sys.exit(0)
'''
        for name in ('docker', 'sleep', 'python3', 'opencode'):
            path = self.bin / name
            path.write_text(recorder)
            path.chmod(0o755)
        self.env = {'PATH': str(self.bin), 'HOME': str(self.home), 'CALLS': str(self.calls),
                    'PYTHONDONTWRITEBYTECODE': '1', 'OPENCODE_PASSWORD': 'fixture-private-password'}

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
        for value in ('opencode-project with spaces', '1000:1000', 'HOME=/home/opencode',
                      'OPENCODE_DISABLE_AUTOUPDATE=1', 'ANTHROPIC_API_KEY=',
                      'lab/opencode:latest', '16g', '8.0', 'devai-xmist',
                      str(self.workspace) + ':/workspace:rw',
                      str(self.root / 'opencode/init.sh') + ':/opt/harness/init.sh:ro',
                      str(self.root / 'opencode/.opencode/data') + ':/home/opencode/.local/share/opencode:rw'):
            self.assertIn(value, run)
        self.assertNotIn('--cap-drop', run)  # Legacy privilege profile is not new-path policy.
        self.assertIn('OPENCODE_PASSWORD', run)
        self.assertIn('dev.xmist.opencode.lifecycle=v2-serve-1', run)
        self.assertIn(str(self.root / 'opencode/.opencode/state') + ':/home/opencode/.local/state/opencode:rw', run)
        self.assertEqual(run[-1], 'lab/opencode:latest')
        self.assertEqual(calls[-2][-3:], ['python3', '/opt/harness/docker-health.py', '--wait'])
        self.assertEqual(calls[-1][-2:], ['bash', '/opt/harness/docker-client.sh'])

    def test_direct_run_web_and_wlan_ports(self):
        for flags, published in [(['--web'], '127.0.0.1:4096:4096'),
                                  (['-w', '4097'], '127.0.0.1:4097:4096'),
                                  (['--wlan', '4098'], '0.0.0.0:4098:4096')]:
            with self.subTest(flags=flags):
                result, calls = self.run_copy('opencode/opencode-run', [*flags, '.'])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(published, next(argv for argv in calls if argv[0] == 'run'))
                self.assertEqual(calls[-1][-3:], ['python3', '/opt/harness/docker-health.py', '--wait'])
                self.assertFalse(any('/opt/harness/docker-client.sh' in call for call in calls))

    def test_direct_run_gpu_resources_and_publish(self):
        result, calls = self.run_copy('opencode/opencode-run',
            ['--gpu', '0,1', '--cpus', '4', '--memory', '8g', '--publish', '3000', '.'])
        self.assertEqual(result.returncode, 0, result.stderr)
        run = next(argv for argv in calls if argv[0] == 'run')
        for value in ('opencode-project with spaces-gpu', '--gpus', 'device=0,1', 'lab/opencode:gpu',
                      'dev.xmist.opencode.cpus=4', 'dev.xmist.opencode.memory=8g', '3000'):
            self.assertIn(value, run)

    def test_direct_run_agent_web_uses_stubbed_probe(self):
        result, calls = self.run_copy('opencode/opencode-run', ['--agent-web-port', '4096', '.'])
        self.assertEqual(result.returncode, 0, result.stderr)
        run = next(argv for argv in calls if argv[0] == 'run')
        self.assertIn('0.0.0.0:4096:4096', run)
        self.assertIn('OPENCODE_AGENT_WEB_URL=http://localhost:4096', run)
        self.assertEqual(calls[-1][-1], '/opt/harness/docker-client.sh')
        self.assertIn('python3', [json.loads(line)[0] for line in self.calls.read_text().splitlines()])

    def test_direct_run_reuse_and_recreation(self):
        sentinels = []
        for name in ('config', 'data', 'cache', 'state'):
            sentinel = self.root / 'opencode/.opencode' / name / 'existing-private-state'
            sentinel.parent.mkdir(parents=True)
            sentinel.write_bytes(b'preserve existing state\x00')
            sentinels.append(sentinel)
        for scenario in ('reuse', 'stale', 'mismatch', 'old-image', 'old-lifecycle', 'old-config'):
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
                for sentinel in sentinels:
                    self.assertEqual(sentinel.read_bytes(), b'preserve existing state\x00')
                self.assertFalse((self.root / 'opencode/.opencode/v2').exists())

    def test_direct_run_invalid_input_and_missing_image_do_not_launch(self):
        for argv, scenario in [(['--port', 'bad'], 'fresh'), (['--cpus', '0'], 'fresh'),
                               (['--web', '--agent-web-port', '4098'], 'fresh'),
                                (['--agent-web-port', '4099'], 'fresh'),
                                (['--publish', '4096'], 'fresh'), (['.'], 'missing-image')]:
            result, calls = self.run_copy('opencode/opencode-run', argv, scenario)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(any(call[0] in ('run', 'exec', 'rm') for call in calls))

    def test_direct_run_requires_password_before_mutating_container(self):
        self.env.pop('OPENCODE_PASSWORD')
        result, calls = self.run_copy('opencode/opencode-run', ['.'], 'old-image')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires OPENCODE_PASSWORD', result.stderr)
        self.assertFalse(any(call[0] in ('run', 'exec', 'stop', 'rm') for call in calls))

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
        defaults = component / '.opencode/config'
        for relative in ('opencode.json', 'cli.json', 'plugins/first-prompt-title.js',
                         'plugins/background-subagents.js', 'tui-plugins/session-title.mjs',
                         'tui-plugins/session-title/tui.js'):
            destination = defaults / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / 'opencode/.opencode/config' / relative, destination)
        (defaults / 'auth.json').write_text('{"private":"never seed"}')
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
        for relative in ('cli.json', 'plugins/first-prompt-title.js', 'plugins/background-subagents.js',
                         'tui-plugins/session-title.mjs', 'tui-plugins/session-title/tui.js'):
            self.assertEqual((config / relative).readlink(), defaults / relative)
        self.assertFalse((config / 'v2').exists())
        self.assertFalse((config / 'auth.json').exists())
        private = json.dumps({'agents': {'build': {'system': 'private fixture prompt'}}})
        (config / 'opencode.json').write_text(private)
        self.assertEqual(initialize().returncode, 0)
        self.assertEqual((config / 'opencode.json').read_text(), private)
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

    def test_t3_provider_contract_is_explicit_and_unconfigured(self):
        self.env['T3CODE_PROVIDER'] = 'none'
        for action, status, message in [('status', 0, 'unconfigured'),
                                         ('initialize-home', 0, ''),
                                         ('login', 69, 'no provider is configured')]:
            result, calls = self.run_copy('t3code/scripts/provider.sh', [action])
            self.assertEqual(result.returncode, status)
            self.assertIn(message, result.stdout + result.stderr)
            self.assertEqual(calls, [])
        self.env['T3CODE_PROVIDER'] = 'other'
        result, calls = self.run_copy('t3code/scripts/provider.sh', ['initialize-home'])
        self.assertEqual(result.returncode, 64)
        self.assertEqual(calls, [])

    @unittest.skipIf(yaml is None, 'Compose characterization requires PyYAML in the test environment')
    def test_compose_contracts_without_interpolation_or_docker(self):
        assert yaml is not None
        for component, service, image, home in [('opencode', 'opencode', 'lab/opencode:latest', '/home/opencode'),
                ('pi', 'pi', 'lab/pi:latest', '/home/pi'),
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
                if component == 'opencode':
                    self.assertEqual(spec['command'], ['bash', '/opt/harness/docker-server.sh'])
                    self.assertNotIn('entrypoint', spec)
                    self.assertEqual(spec['labels']['dev.xmist.opencode.lifecycle'], 'v2-serve-1')
                    self.assertIn('OPENCODE_PASSWORD=${OPENCODE_PASSWORD:-${OPENCODE_SERVER_PASSWORD:?Set a Docker V2 server password}}', spec['environment'])
                    self.assertIn('./.opencode/state:/home/opencode/.local/state/opencode:rw', spec['volumes'])
                    self.assertFalse(any('/.opencode/v2/' in value for value in spec['volumes']))
                else:
                    self.assertEqual(spec['entrypoint'], ['bash', '-lc', '/opt/harness/init.sh && tail -f /dev/null'])
                self.assertTrue(document['networks']['devai-xmist']['external'])
        copied = self.root / 'omp.yml'
        shutil.copyfile(ROOT / 'omp/docker-compose.yml', copied)
        spec = yaml.safe_load(copied.read_text())['services']['omp']
        self.assertEqual(spec['user'], '${OMP_UID:-1000}:${OMP_GID:-1000}')
        self.assertEqual(spec['environment']['OMP_PERSONA'], '${OMP_PERSONA:-build}')
        self.assertTrue(all(not mount['bind']['create_host_path'] for mount in spec['volumes']))
        self.assertEqual(spec['entrypoint'], ['bash', '-c', '/opt/harness/init.sh && exec sleep infinity'])


if __name__ == '__main__':
    unittest.main()
