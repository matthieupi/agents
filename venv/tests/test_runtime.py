"""VM runtime behavior: real private paths/locks, deterministic Docker API fixture."""
import copy
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import socket
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location('vm_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime, entry = load('launcher'), load('entry')


def policy(root, account):
    result = dict(schema=1, scope='vm', docker_access=True, target='devai:agent-coo',
                  workspace=str(root / 'workspace'), resources=str(root / 'resources'),
                  socket=str(root / 'docker.sock'), network='venv-agents', cgroup_parent='venv-agents.slice',
                  web_ready=True, web=dict(default_harness='pi', default_account=account, base_hostname='coo.example.org'),
                  accounts={account: dict(uid=os.getuid(), gid=os.getgid(), state=str(root / 'state'), autoentry=None)},
                  harnesses={})
    for i, name in enumerate(sorted(runtime.HARNESSES)):
        spec = dict(image='sha256:' + str(i + 1) * 64, memory_mb=512, cpus=0.5, pids=128,
                    home='/home/t3code' if name == 't3' else '/home/vm-' + name,
                    cli=[] if name == 't3' else ['/usr/bin/python3', '/opt/venv/entry.py', name])
        if name != 'omp':
            spec.update(web=['/usr/bin/python3', '/opt/venv/entry.py', name, '--web'], port=4100 + i,
                        container_port=5100 + i, hostname=name + '.coo.example.org')
        result['harnesses'][name] = spec
    return result


class Docker:
    """Model create's atomic name and ID-bound removal; no daemon success claim."""
    def __init__(self):
        self.instance = None
        self.calls = []
        self.lock = threading.Lock()
        self.fail_start = False
        self.fail_create = False
        self.exit_immediately = False

    def call(self, policy, args):
        with self.lock:
            self.calls.append(args)
            out, error, status = '', '', 0
            if args[:2] == ['container', 'inspect']:
                if self.instance is None:
                    error, status = 'Error: No such container: fixture', 1
                else:
                    out = json.dumps([self.instance])
            elif args[0] == 'create':
                if self.instance is not None or self.fail_create:
                    status = 1
                else:
                    one = lambda key: args[args.index(key) + 1]
                    many = lambda key: [args[i + 1] for i, a in enumerate(args) if a == key]
                    image = next(a for a in args if a.startswith('sha256:'))
                    bindings = one('--publish').split(':')
                    mounts = []
                    for value in many('--mount'):
                        fields = dict(x.split('=', 1) for x in value.split(',') if '=' in x)
                        mounts.append(dict(Type='bind', Source=fields['src'], Destination=fields['dst'], RW='readonly' not in value))
                    self.instance = dict(Id='a' * 64, Name='/' + one('--name'), Image=image, State=dict(Running=False, Status='created'),
                        Config=dict(Image=image, User=one('--user'), WorkingDir=one('--workdir'),
                                    Entrypoint=[one('--entrypoint')], Cmd=args[args.index(image) + 1:],
                                    Labels=dict(v.split('=', 1) for v in many('--label')), Env=many('--env')),
                        HostConfig=dict(NetworkMode=one('--network'), Privileged=False, GroupAdd=[one('--group-add')],
                                        PortBindings={bindings[2] + '/tcp': [dict(HostIp=bindings[0], HostPort=bindings[1])]},
                                        Memory=int(one('--memory')[:-1]) * 1024**2,
                                        MemorySwap=int(one('--memory-swap')[:-1]) * 1024**2,
                                        NanoCpus=int(float(one('--cpus')) * 10**9), PidsLimit=int(one('--pids-limit')),
                                        CgroupParent=one('--cgroup-parent'), Init=True, CapDrop=['ALL'],
                                        SecurityOpt=['no-new-privileges']), Mounts=mounts)
                    out = self.instance['Id'] + '\n'
            elif args[:2] == ['container', 'start']:
                if self.fail_start:
                    status = 1
                else:
                    self.instance['State'] = dict(Running=not self.exit_immediately,
                                                  Status='exited' if self.exit_immediately else 'running')
            elif args[:2] == ['container', 'stop']:
                self.instance['State'] = dict(Running=False, Status='exited')
            elif args[:2] == ['container', 'rm']:
                if self.instance and args[-1] == self.instance['Id']:
                    self.instance = None
                else:
                    status = 1
            else:
                raise AssertionError(args)
            return subprocess.CompletedProcess(args, status, out, error)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        if os.getuid() == 0:
            self.skipTest('real non-root fixture required')
        self.temp = tempfile.TemporaryDirectory(dir=Path.home(), prefix='vm-runtime-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.account = pwd.getpwuid(os.getuid()).pw_name
        self.data = policy(self.root, self.account)
        for relative in ['workspace', 'resources', 'state', *[f'state/{h}/home' for h in runtime.HARNESSES]]:
            (self.root / relative).mkdir(mode=0o700, parents=True, exist_ok=True)
        for h in runtime.HARNESSES:
            (self.root / 'state' / h).chmod(0o700)
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(str(self.root / 'docker.sock'))
        self.addCleanup(self.sock.close)
        self.docker = Docker()
        for name, replacement in [('validate_socket', lambda p: None), ('docker_call', self.docker.call)]:
            mock = patch.object(runtime, name, replacement)
            mock.start(); self.addCleanup(mock.stop)
        output = patch('sys.stdout', new_callable=io.StringIO)
        self.output = output.start(); self.addCleanup(output.stop)

    def command(self, harness='pi', web=True, arguments=None):
        return runtime.session_command(self.data, harness, self.account, web, arguments or [], False)

    def test_detached_argv_loopback_same_path_resources_and_no_secrets(self):
        args = self.command()
        self.assertEqual(args[:4], ['/usr/bin/docker', '--host', 'unix://' + self.data['socket'], 'create'])
        self.assertNotIn('--rm', args)
        self.assertNotIn('-i', args)
        self.assertIn('--pull=never', args)
        self.assertIn('127.0.0.1:4102:5102', args)
        self.assertIn('VENV_AGENT_RESOURCES=' + self.data['resources'], args)
        self.assertIn(f'type=bind,src={self.data["resources"]},dst={self.data["resources"]},readonly', args)
        self.assertEqual(args[args.index('--name') + 1], 'venv-agents-devai.agent-coo-pi-web')
        self.assertFalse(any('PASSWORD' in a or 'TOKEN' in a for a in args))

    def test_web_idempotence_never_reinitializes_private_state(self):
        self.assertEqual(runtime.run_web(self.data, 'pi'), 0)
        with patch.object(runtime, 'validate_runtime') as private:
            self.assertEqual(runtime.run_web(self.data, 'pi'), 0)
            private.assert_not_called()
        self.assertEqual(sum(c[0] == 'create' for c in self.docker.calls), 1)
        self.assertIn('https://pi.coo.example.org/', self.output.getvalue())

    def test_stop_exact_id_and_preserve_home(self):
        marker = self.root / 'state/pi/home/provider.json'
        marker.write_bytes(b'private-fixture-do-not-copy')
        runtime.run_web(self.data, 'pi')
        runtime.run_web(self.data, 'pi', 'stop')
        self.assertEqual(self.docker.calls[-2], ['container', 'stop', '--time', '30', 'a' * 64])
        self.assertEqual(self.docker.calls[-1], ['container', 'rm', 'a' * 64])
        self.assertEqual(marker.read_bytes(), b'private-fixture-do-not-copy')

    def test_foreign_and_owner_drift_never_take_over(self):
        runtime.run_web(self.data, 'pi')
        original = copy.deepcopy(self.docker.instance)
        for mutate in [lambda i: i['Config']['Labels'].update({'io.venv-agents.account': 'foreign'}),
                       lambda i: i['Config']['Labels'].update({'io.venv-agents.uid': '999'}),
                       lambda i: i['Config'].update(User='0:0'),
                       lambda i: i['HostConfig'].update(NetworkMode='host'),
                       lambda i: i['HostConfig'].update(Memory=1),
                       lambda i: i['Mounts'][0].update(Source='/'),
                       lambda i: i.update(Image='sha256:' + 'f' * 64)]:
            self.docker.instance = copy.deepcopy(original)
            mutate(self.docker.instance)
            before = len(self.docker.calls)
            with self.assertRaises(ValueError):
                runtime.run_web(self.data, 'pi')
            self.assertEqual(len(self.docker.calls), before + 1)

    def test_other_account_can_report_but_not_stop_or_replace_state(self):
        other = 'vmother'
        user = dict(uid=12345, gid=12345, state=str(self.root / 'other-state'), autoentry=None)
        self.data['accounts'][other] = user
        getpwnam = pwd.getpwnam
        with patch.object(runtime.pwd, 'getpwnam', side_effect=lambda n: SimpleNamespace(pw_uid=12345, pw_gid=12345, pw_dir='/home/vmother') if n == other else getpwnam(n)):
            args = runtime.session_command(self.data, 'opencode', other, True, [], False)
            self.docker.call(self.data, args[3:])
            self.docker.call(self.data, ['container', 'start', 'a' * 64])
            with patch.object(runtime, 'validate_runtime') as private:
                self.assertEqual(runtime.run_web(self.data, 'opencode'), 0)
                private.assert_not_called()
                with self.assertRaisesRegex(ValueError, 'Another account'):
                    runtime.run_web(self.data, 'opencode', 'stop')
            self.assertFalse((self.root / 'other-state').exists())

    def test_failed_create_never_cleans_up_foreign_id(self):
        self.docker.fail_create = True
        with self.assertRaisesRegex(ValueError, 'creation failed'):
            runtime.run_web(self.data, 'pi')
        self.assertFalse(any(c[:2] == ['container', 'rm'] for c in self.docker.calls))

    def test_start_failure_and_immediate_exit_clean_only_created_id(self):
        for failure in ('fail_start', 'exit_immediately'):
            self.docker = Docker()
            setattr(self.docker, failure, True)
            with patch.object(runtime, 'docker_call', self.docker.call):
                with self.assertRaises(ValueError):
                    runtime.run_web(self.data, 'pi')
            self.assertEqual(self.docker.calls[-1], ['container', 'rm', '--force', 'a' * 64])
            self.assertIsNone(self.docker.instance)

    def test_docker_atomic_create_race_reuses_winner_without_starting_it(self):
        base = self.docker.call
        def race(policy, args):
            if args[0] == 'create':
                base(policy, args)  # competing launcher reserves name first
                return subprocess.CompletedProcess(args, 1, '', 'name in use')
            return base(policy, args)
        with patch.object(runtime, 'docker_call', race):
            self.assertEqual(runtime.run_web(self.data, 'pi'), 0)
        self.assertEqual(self.docker.instance['State']['Status'], 'created')
        self.assertFalse(any(c[:2] == ['container', 'start'] for c in self.docker.calls))
        self.assertIn('created', self.output.getvalue())

    def test_concurrent_atomic_name_reservation_has_exactly_one_winner(self):
        barrier = threading.Barrier(2)
        results = []
        args = self.command()[3:]
        def create():
            barrier.wait(timeout=5)
            results.append(self.docker.call(self.data, args).returncode)
        threads = [threading.Thread(target=create) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(results), [0, 1])

    def test_real_cli_and_web_locks_are_independent_and_web_releases(self):
        lock = self.root / 'state/pi/.session.lock'
        lock.touch(mode=0o600)
        with lock.open() as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(runtime.run_web(self.data, 'pi'), 0)
        with (self.root / 'state/pi/.web-start.lock').open() as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(runtime.subprocess, 'Popen') as spawn:
                spawn.return_value.wait.return_value = 37
                self.assertEqual(runtime.run_session(self.data, 'pi', False, ['--version']), 37)

    def test_busy_web_startup_lock_refuses_without_create(self):
        lock = self.root / 'state/pi/.web-start.lock'
        lock.touch(mode=0o600)
        with lock.open() as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                runtime.run_web(self.data, 'pi')
        self.assertFalse(any(c[0] == 'create' for c in self.docker.calls))

    def test_native_pi_home_only_exact_identity_no_token_copy(self):
        user = self.data['accounts'][self.account]
        native = self.root / 'native-home'
        native.mkdir(mode=0o750)
        marker = native / 'auth.json'
        marker.write_bytes(b'preserved-native-fixture')
        user['native_pi_home'] = str(native)
        record = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_dir=str(native))
        with patch.object(runtime.pwd, 'getpwnam', return_value=record):
            runtime.validate_runtime(self.data, 'pi', self.account)
            args = self.command()
            self.assertIn(f'type=bind,src={native},dst={native}', args)
            self.assertIn('HOME=' + str(native), args)
            self.assertNotIn('HOME=' + str(native), self.command('opencode'))
            record.pw_dir = str(self.root / 'workspace')
            with self.assertRaisesRegex(ValueError, 'Native Pi HOME'):
                runtime.validate_runtime(self.data, 'pi', self.account)
        self.assertEqual(marker.read_bytes(), b'preserved-native-fixture')
        self.assertEqual(list((self.root / 'state/pi/home').iterdir()), [])

    def test_native_symlink_and_shared_ancestor_are_rejected(self):
        user = self.data['accounts'][self.account]
        user['native_pi_home'] = self.data['workspace']
        with self.assertRaises(ValueError):
            runtime.validate_policy(self.data)
        del user['native_pi_home']
        self.data['resources'] = str(Path(pwd.getpwuid(os.getuid()).pw_dir).parent)
        with self.assertRaises(ValueError):
            runtime.validate_runtime(self.data, 'pi', self.account)

    def test_readiness_and_omp_web_block_before_docker_or_state(self):
        for ready, harness in [(False, 'pi'), (False, 'opencode'), (False, 't3'), (True, 'omp')]:
            self.data['web_ready'] = ready
            with patch.object(runtime, 'validate_runtime') as private:
                with self.assertRaises(ValueError):
                    runtime.run_web(self.data, harness)
                private.assert_not_called()
        self.assertEqual(self.docker.calls, [])

    def test_flag_alone_missing_proxy_contract_is_not_readiness(self):
        del self.data['web']
        with self.assertRaises(ValueError):
            runtime.run_web(self.data, 'pi')
        self.assertEqual(self.docker.calls, [])

    def test_policy_rejects_bad_image_uid_home_and_unowned_policy_file(self):
        original = copy.deepcopy(self.data)
        for mutate in [lambda p: p['harnesses']['pi'].update(image='pi:latest'),
                       lambda p: p['accounts'][self.account].update(uid=0),
                       lambda p: p['accounts'][self.account].update(uid=2**32),
                       lambda p: p['harnesses']['pi'].update(home=p['workspace'])]:
            self.data = copy.deepcopy(original)
            mutate(self.data)
            with self.assertRaises(ValueError):
                self.command()
        path = self.root / 'policy.json'
        path.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, 'ownership/mode'):
            runtime.load_policy(path)

    def test_root_web_never_reads_private_state_or_spawns_docker(self):
        with patch.object(runtime.os, 'getuid', return_value=0), patch.object(runtime, 'validate_runtime') as private:
            with self.assertRaisesRegex(ValueError, 'non-root'):
                runtime.run_web(self.data, 'pi')
            private.assert_not_called()
        self.assertEqual(self.docker.calls, [])

    def test_revoked_readiness_keeps_owner_stop_available(self):
        runtime.run_web(self.data, 'pi')
        self.data['web_ready'] = False
        self.assertEqual(runtime.run_web(self.data, 'pi', 'stop'), 0)
        self.assertIsNone(self.docker.instance)

    def test_new_pi_web_requires_legacy_owner(self):
        self.data['accounts']['legacy'] = dict(uid=12345, gid=12345, state='/var/lib/venv/legacy', autoentry=None)
        self.data['web']['default_account'] = 'legacy'
        with self.assertRaisesRegex(ValueError, 'legacy owner'):
            runtime.run_web(self.data, 'pi')
        self.assertFalse(any(c[0] == 'create' for c in self.docker.calls))

    def test_t3_is_web_oriented_and_sets_native_identity(self):
        self.assertEqual(runtime.run_session(self.data, 't3', False, []), 0)
        self.assertIn('not a conversational CLI', self.output.getvalue())
        args = next(c for c in self.docker.calls if c[0] == 'create')
        for value in ['T3CODE_UID=' + str(os.getuid()), 'T3CODE_GID=' + str(os.getgid()), 'T3CODE_PROVIDER=none']:
            self.assertIn(value, args)
        with self.assertRaises(ValueError):
            runtime.run_session(self.data, 't3', False, ['--version'])

    def test_user_docker_flags_stay_after_image_but_web_flags_refused(self):
        arguments = ['--mount', 'type=bind,src=/,dst=/host', '--privileged', '$(false)']
        args = self.command(web=False, arguments=arguments)
        image = self.data['harnesses']['pi']['image']
        self.assertEqual(args[args.index(image) + 1:][-len(arguments):], arguments)
        with self.assertRaises(ValueError):
            self.command(arguments=arguments)
        for command in ('serve', 'web'):
            with self.assertRaises(ValueError):
                self.command('opencode', web=False, arguments=[command])

    def test_public_cli_markers_and_status(self):
        from contextlib import nullcontext
        # Dispatch-only fixture; kernel maintenance admission is covered separately.
        admission = patch.object(runtime, 'maintenance_lock', side_effect=lambda *a: nullcontext())
        admission.start()
        self.addCleanup(admission.stop)
        for marker in ('--', '--args'):
            with patch.object(runtime, 'load_policy', return_value=self.data), patch.object(runtime, 'run_session', return_value=7) as session:
                self.assertEqual(runtime.main(['pi', marker, '--version']), 7)
                self.assertEqual(session.call_args.args[-1], ['--version'])
        with patch.object(runtime, 'load_policy', return_value=self.data), patch.object(runtime, 'run_session', return_value=0) as session:
            runtime.main(['pi', '--', '--args', 'literal'])
            self.assertEqual(session.call_args.args[-1], ['--args', 'literal'])
        with patch.object(runtime, 'load_policy', return_value=self.data):
            self.assertEqual(runtime.main(['pi', '--web-status']), 0)
        self.assertIn('No managed', self.output.getvalue())

    def test_target_names_do_not_collapse_distinct_vm_identities(self):
        first = runtime.web_name(dict(target='dev:foo-bar'), 'pi')
        second = runtime.web_name(dict(target='dev-foo:bar'), 'pi')
        self.assertNotEqual(first, second)

    def test_docker_api_errors_are_not_absence_and_environment_is_clean(self):
        error = subprocess.CompletedProcess([], 1, '', 'permission denied')
        with patch.object(runtime, 'docker_call', return_value=error):
            with self.assertRaisesRegex(ValueError, 'Cannot inspect'):
                runtime.inspect_web(self.data, 'pi')
        # Exercise the real subprocess boundary rather than the Docker model.
        other = load('launcher')
        with patch.object(other.subprocess, 'run', return_value=error) as run, patch.dict(os.environ, DOCKER_HOST='tcp://foreign', API_KEY='not-forwarded'):
            other.docker_call(self.data, ['version'])
            self.assertEqual(set(run.call_args.kwargs['env']), {'PATH', 'HOME'})
            self.assertEqual(run.call_args.args[0][:3], ['/usr/bin/docker', '--host', 'unix://' + self.data['socket']])


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home, self.resources = self.root / 'home', self.root / 'resources'
        self.home.mkdir(mode=0o700)
        for name in ('prompts', 'skills', 'commands', 'system', 'gsd'):
            (self.resources / name).mkdir(parents=True)
        (self.resources / 'system/build.md').write_text('build persona fixture')

    def test_pi_native_state_and_legacy_agents_preserved(self):
        root = self.home / '.pi/agent'
        root.mkdir(mode=0o700, parents=True)
        token = root / 'auth.json'
        token.write_bytes(b'fixture-must-not-change')
        (root / 'AGENTS.md').symlink_to(self.resources / 'system/build.md')
        entry.initialize('pi', self.home, self.resources)
        entry.initialize('pi', self.home, self.resources)
        self.assertEqual(token.read_bytes(), b'fixture-must-not-change')
        self.assertEqual((root / 'AGENTS.md').resolve(), self.resources / 'system/build.md')
        self.assertEqual((root / 'skills').resolve(), self.resources / 'skills')

    def test_broken_legacy_agents_target_fails_without_replacement(self):
        root = self.home / '.pi/agent'
        root.mkdir(mode=0o700, parents=True)
        (root / 'AGENTS.md').symlink_to('/missing/old/coo/resource.md')
        with self.assertRaisesRegex(ValueError, 'Legacy Pi'):
            entry.initialize('pi', self.home, self.resources)
        self.assertEqual(os.readlink(root / 'AGENTS.md'), '/missing/old/coo/resource.md')

    def test_omp_uses_numeric_home_and_readonly_resource_references(self):
        skill = self.resources / 'skills/dev/testing'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('fixture')
        entry.initialize('omp', self.home, self.resources)
        root = self.home / '.omp/agent'
        self.assertEqual((root / 'skills/testing').resolve(), skill)
        self.assertEqual((root / 'agents/system-build.md').resolve(), self.resources / 'system/build.md')

    def test_opencode_no_provider_or_default_config_copy(self):
        entry.initialize('opencode', self.home, self.resources)
        root = self.home / '.config/opencode'
        self.assertEqual((root / 'commands').resolve(), self.resources / 'commands')
        self.assertFalse((root / 'opencode.json').exists())

    def test_image_identity_uses_nss_without_passwd_mutation(self):
        if os.getuid() == 0:
            self.skipTest('non-root identity required')
        private = self.root / 'container-tmp'
        private.mkdir(mode=0o700)
        with patch.object(entry.Path, 'glob', return_value=[Path('/usr/lib/x86_64-linux-gnu/libnss_wrapper.so')]), \
                patch.object(entry.tempfile, 'mkdtemp', return_value=str(private)), patch.dict(os.environ, USER='vmaccount'):
            entry.identity(self.home)
            record = (private / 'passwd').read_text().split(':')
            self.assertEqual(record[2:4], [str(os.getuid()), str(os.getgid())])
            self.assertEqual(record[5], str(self.home))
            self.assertEqual(os.environ['NSS_WRAPPER_PASSWD'], str(private / 'passwd'))
        self.assertEqual(list(self.home.iterdir()), [])

    def test_adapter_web_argv_is_actual_native_surface(self):
        for harness, expected in [('pi', ['--hostname', '0.0.0.0', '--port', '5102', '--no-open']),
                                  ('opencode', ['web', '--hostname', '0.0.0.0', '--port', '5102'])]:
            with patch.dict(os.environ, HOME=str(self.home), VENV_AGENT_RESOURCES=str(self.resources), VENV_AGENT_PORT='5102'), \
                    patch.object(entry, 'identity'), patch.object(entry.os, 'execvpe') as execute:
                entry.main([harness, '--web'])
                self.assertEqual(execute.call_args.args[1][1:], expected)

    def test_t3_preserves_component_init_pairing_logs_and_actual_workspace(self):
        source = (ROOT / 't3-start.sh').read_text()
        self.assertIn('source /opt/t3/scripts/entrypoint.sh\nvalidate_contract\ninitialize_home', source)
        self.assertIn('"$workspace"', source)
        self.assertNotIn('cd /workspace', source)
        self.assertIn('>>/home/t3code/logs/server.log 2>&1', source)
        result = subprocess.run(['bash', '-n', str(ROOT / 't3-start.sh')], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
