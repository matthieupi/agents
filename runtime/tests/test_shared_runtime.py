"""Offline contracts and fault injection. No Docker, npm or network calls."""
import ast
import base64
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location('shared_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer, runtime, entry = (load(name) for name in ('install', 'runtime', 'entry'))
ID = 'sha256:' + 'a' * 64
SRI = 'sha512-' + base64.b64encode(b'x' * 64).decode()


def contract():
    return dict(schema=1, harness='opencode', mode='cli', image=ID, platform='linux/amd64',
                uid=1000, gid=1000, name='agents-runtime-test', workspace='/work/project',
                home='/private/opencode', resources=None,
                source=dict(mode='baked', path=None, sha256='b' * 64, revision='c' * 40),
                grants=dict(root_user=False, docker_socket=None, cap_add=[], checkout_write=False),
                limits=dict(memory_mb=2048, cpus=2, pids=256), port=None,
                endpoint='unix:///var/run/docker.sock', receipt='d' * 64)


def instance(c):
    args = runtime.command(c, [], tty=False)
    return dict(Image=c['image'], Name='/' + c['name'],
                Config=dict(Labels={'io.agents-runtime.contract': runtime.fingerprint(c)},
                            User='0:0' if c['grants']['root_user'] else f'{c["uid"]}:{c["gid"]}',
                            Env=[k + '=' + v for k, v in runtime.environment(c).items()],
                            WorkingDir=c['workspace'], Entrypoint=['/usr/bin/python3'],
                            Cmd=args[args.index(c['image']) + 1:]),
                HostConfig=dict(Privileged=False, ReadonlyRootfs=True, CapDrop=['ALL'],
                                CapAdd=c['grants']['cap_add'], SecurityOpt=['no-new-privileges'],
                                NetworkMode='bridge', PidMode='', IpcMode='private', Devices=[],
                                DeviceRequests=[], VolumesFrom=[], GroupAdd=[str(c['grants']['docker_socket']['gid'])] if c['grants']['docker_socket'] else [],
                                Memory=c['limits']['memory_mb'] * 1024**2,
                                MemorySwap=c['limits']['memory_mb'] * 1024**2,
                                NanoCpus=int(c['limits']['cpus'] * 10**9), PidsLimit=c['limits']['pids'],
                                Tmpfs=dict({'/tmp': 'rw,nosuid,nodev,size=256m'}, **({'/home/agent': 'rw,nosuid,nodev,mode=0700,size=256m'} if c['grants']['root_user'] else {})),
                                PortBindings={str(c['port']) + '/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(c['port'])}]} if c['mode'] == 'web' else {}),
                Mounts=[dict(Type='bind', Source=a, Destination=b, RW=w) for a, b, w in runtime.mounts(c)])


class Contracts(unittest.TestCase):
    def test_default_no_socket_or_escalation(self):
        c = contract()
        argv = runtime.command(c, ['a b', '$(false)', '--mode', 'rpc'], tty=False)
        self.assertIn('--cap-drop=ALL', argv)
        self.assertIn('--security-opt=no-new-privileges', argv)
        self.assertIn('--pull=never', argv)
        self.assertNotIn('--group-add', argv)
        self.assertNotIn('--privileged', argv)
        self.assertFalse(any('DOCKER_HOST=' in a for a in argv))
        self.assertEqual(argv[-4:], ['a b', '$(false)', '--mode', 'rpc'])
        self.assertNotIn('-it', argv)
        runtime.inspect_contract(c, instance(c))

    def test_grants_independent_and_inspected(self):
        for grant, value in [('root_user', True), ('cap_add', ['NET_BIND_SERVICE']),
                             ('docker_socket', {'path': '/var/run/docker.sock', 'gid': 999})]:
            with self.subTest(grant=grant):
                c = contract()
                c['grants'][grant] = value
                runtime.inspect_contract(c, instance(c))
                argv = runtime.command(c, [], tty=True)
                self.assertEqual('--group-add' in argv, grant == 'docker_socket')
                self.assertEqual('--cap-add' in argv, grant == 'cap_add')

    def test_authority_changes_fingerprint(self):
        c = contract()
        old = runtime.fingerprint(c)
        for grant, value in [('root_user', True), ('cap_add', ['NET_BIND_SERVICE']),
                             ('docker_socket', {'path': '/var/run/docker.sock', 'gid': 999})]:
            d = copy.deepcopy(c)
            d['grants'][grant] = value
            self.assertNotEqual(runtime.fingerprint(d), old)

    def test_unknown_or_excess_authority(self):
        mutations = [lambda c: c.update(extra=True), lambda c: c.update(uid=0),
                     lambda c: c.update(image='opencode:latest'), lambda c: c.update(name='opencode-production'),
                     lambda c: c['grants'].update(cap_add=['SYS_ADMIN']),
                     lambda c: c['grants'].update(privileged=True), lambda c: c['limits'].update(memory_mb=999999),
                     lambda c: c.update(endpoint='tcp://foreign:2375'),
                     lambda c: c['grants'].update(docker_socket={'path': '/foreign.sock', 'gid': 1})]
        for mutate in mutations:
            c = contract()
            mutate(c)
            with self.assertRaises(ValueError):
                runtime.validate_contract(c)

    def test_mount_conflicts(self):
        for workspace in ('/', '/private', '/opt', '/opt/agents-runtime', '/etc', '/home/agent', '/work/../private', '/work,x=y'):
            c = contract()
            c['workspace'] = workspace
            with self.subTest(workspace=workspace), self.assertRaises(ValueError):
                runtime.validate_contract(c)
        c = contract()
        c['workspace'] = '/home/user/project'
        runtime.validate_contract(c)

    def test_root_refuses_live_and_mutable_resources(self):
        c = contract()
        c['grants']['root_user'] = True
        for mutation in (lambda c: c.update(resources='/public/resources'),
                         lambda c: c['source'].update(mode='live', path='/public/startup')):
            d = copy.deepcopy(c)
            mutation(d)
            with self.assertRaises(ValueError):
                runtime.validate_contract(d)
        argv = runtime.command(c, [], tty=False)
        self.assertIn('type=bind,src=/work/project,dst=/work/project,readonly', argv)
        self.assertFalse(any('src=/private/opencode' in arg for arg in argv))

    def test_live_write_requires_separate_grant(self):
        c = contract()
        c['source'].update(mode='live', path='/public/startup')
        self.assertIn('type=bind,src=/public/startup,dst=/public/startup,readonly', runtime.command(c, [], tty=False))
        c['grants']['checkout_write'] = True
        self.assertIn('type=bind,src=/public/startup,dst=/public/startup', runtime.command(c, [], tty=False))

    def test_modes_platforms_and_loopback(self):
        for harness, modes in runtime.MODES.items():
            for mode in ('cli', 'web'):
                c = contract()
                c.update(harness=harness, mode=mode, port=4096 if mode == 'web' else None)
                if mode not in modes:
                    with self.assertRaises(ValueError):
                        runtime.command(c, [], tty=False)
                else:
                    argv = runtime.command(c, [], tty=False)
                    runtime.inspect_contract(c, instance(c))
                    if mode == 'web':
                        self.assertIn('127.0.0.1:4096:4096', argv)
        c = contract()
        c.update(harness='omp', platform='linux/arm64')
        with self.assertRaises(ValueError):
            runtime.validate_contract(c)

    def test_inspect_rejects_each_drift(self):
        c = contract()
        mutations = [lambda i: i.update(Image='sha256:' + 'b' * 64),
                     lambda i: i.update(Name='/legacy'), lambda i: i['Config'].update(User='0:0'),
                     lambda i: i['Config'].update(Cmd=['-c', 'evil']),
                     lambda i: i['HostConfig'].update(Privileged=True),
                     lambda i: i['HostConfig'].update(CapAdd=['SYS_ADMIN']),
                     lambda i: i['HostConfig'].update(GroupAdd=['999']),
                     lambda i: i['HostConfig'].update(SecurityOpt=[]),
                     lambda i: i['HostConfig'].update(NetworkMode='host'),
                     lambda i: i['HostConfig'].update(PidMode='host'),
                     lambda i: i['HostConfig'].update(IpcMode='host'),
                     lambda i: i['HostConfig'].update(Devices=['anything']),
                     lambda i: i['HostConfig'].update(Memory=0),
                     lambda i: i['HostConfig'].update(Tmpfs={'/opt': 'rw'}),
                     lambda i: i['HostConfig'].update(PublishAllPorts=True),
                     lambda i: i['Mounts'].append(dict(Type='bind', Source='/var/run/docker.sock', Destination='/socket', RW=True)),
                     lambda i: i['Config']['Env'].append('DOCKER_HOST=unix:///socket')]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                value = instance(c)
                mutate(value)
                with self.assertRaises(ValueError):
                    runtime.inspect_contract(c, value)

    def test_gpu_and_privileged_flags_refused(self):
        for flag in ('--gpu', '--gpus', '-gpu', '--privileged'):
            with self.assertRaises(ValueError):
                runtime.command(contract(), [flag], tty=False)

    def test_root_cli_before_external_calls(self):
        with patch.object(runtime.os, 'getuid', return_value=0), patch.object(runtime.subprocess, 'Popen') as spawn, patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(runtime.main(['run', 'pi', '--workspace', '.']), 1)
            spawn.assert_not_called()

    def test_public_bundle_refuses_hidden_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'entry.py').write_text('pass')
            (root / 'harnesses.json').write_text('{}')
            before = runtime.public_source(root)
            (root / 'entry.py').write_text('pass # host edit')
            self.assertNotEqual(runtime.public_source(root), before)
            (root / '.credentials').write_text('private')
            with self.assertRaises(ValueError):
                runtime.public_source(root)
            self.assertEqual((root / '.credentials').read_text(), 'private')


class Installation(unittest.TestCase):
    def test_sources_parse_without_bytecode(self):
        for source in ROOT.rglob('*.py'):
            ast.parse(source.read_text(), filename=str(source))
        current = json.loads((ROOT / 'harnesses.json').read_text())
        self.assertEqual(set(current['harnesses']), set(runtime.MODES))

    def test_host_platform_and_all_cpu_checks_remain(self):
        with patch.object(installer.host_platform, 'machine', return_value='x86_64'):
            with self.assertRaises(ValueError):
                installer.prerequisites('pi', 'linux/arm64')
            for text, accepted in [('flags : sse4_2 avx\nflags : sse4_2\n', True),
                                   ('flags : sse4_2\nflags : sse2\n', False), ('', False)]:
                with patch.object(Path, 'read_text', return_value=text):
                    if accepted:
                        installer.prerequisites('omp', 'linux/amd64')
                    else:
                        with self.assertRaises(ValueError):
                            installer.prerequisites('omp', 'linux/amd64')

    def resolution(self, harness='opencode'):
        current = installer.catalog()
        packages = {name: {'version': bounds[0], 'integrity': SRI} for name, bounds in current['harnesses'][harness]['packages'].items()}
        dependencies = {name: spec['version'] for name, spec in packages.items()}
        lock = {'lockfileVersion': 3, 'packages': {'': {'dependencies': dependencies},
                **{'node_modules/' + name: dict(value, resolved='https://registry.npmjs.org/package.tgz') for name, value in packages.items()}}}
        return dict(schema=1, contract=1, harness=harness, platform='linux/amd64',
                    catalog_sha256=installer.digest(installer.encoded(current)),
                    source=installer.source_record(ROOT, harness), packages=packages,
                    package={'name': 'selected', 'version': '1.0.0', 'dependencies': dependencies},
                    lock=lock, lock_sha256=installer.digest(installer.encoded(lock)),
                    base=dict(image='node@' + ID, platform_digest=ID, manifest=ID, version='24.20.0'),
                    debian=dict(timestamp='20260910T000000Z', releases={}))

    def test_build_refresh_and_no_activation(self):
        resolution = self.resolution()
        for refresh in (False, True):
            calls = []
            def docker(argv, **kwargs):
                calls.append(argv)
                if argv[0] == 'build':
                    context = Path(argv[-1])
                    self.assertEqual({p.name for p in context.iterdir()}, {'Dockerfile', 'Dockerfile.dockerignore', 'entry.py', 'harnesses.json', 'package.json', 'package-lock.json', 'apt.sources', 'opencode-plugins', 'publish-plugins.mjs'})
                    self.assertIn('snapshot.debian.org/archive/debian/20260910T000000Z', (context / 'apt.sources').read_text())
                    Path(argv[argv.index('--iidfile') + 1]).write_text(ID)
                    return subprocess.CompletedProcess(argv, 0)
                return subprocess.CompletedProcess(argv, 0, json.dumps([dict(Id=ID, Os='linux', Architecture='amd64', Config={'Labels': {'io.agents-runtime.harness': 'opencode', 'io.agents-runtime.contract': '1', 'io.agents-runtime.resolution': installer.digest(installer.encoded(resolution))}})]))
            with patch.object(installer, 'ordinary'), patch.object(installer, 'docker', side_effect=docker), patch.object(installer, 'activate') as activate:
                receipt = installer.build('opencode', ROOT, resolution, refresh=refresh)
                activate.assert_not_called()
            self.assertEqual(receipt['image'], ID)
            self.assertEqual('--no-cache' in calls[0], refresh)
            self.assertIn('--pull=false', calls[0])
            self.assertNotIn('--pull', calls[0])

    def test_stale_source_or_lock_refuses_before_build(self):
        for mutate in (lambda r: r['source'].update(public_sha256='0' * 64),
                       lambda r: r.update(lock_sha256='0' * 64),
                       lambda r: r.update(catalog_sha256='0' * 64),
                       lambda r: r['base'].update(image='node:latest'),
                       lambda r: r['package']['dependencies'].update(unknown='1.0.0')):
            resolution = self.resolution()
            mutate(resolution)
            with patch.object(installer, 'ordinary'), patch.object(installer, 'docker') as docker:
                with self.assertRaises(ValueError):
                    installer.build('opencode', ROOT, resolution, refresh=False)
                docker.assert_not_called()

    def test_build_failure_has_no_receipt_or_activation(self):
        resolution = self.resolution()
        with patch.object(installer, 'ordinary'), patch.object(installer, 'docker', side_effect=subprocess.CalledProcessError(1, ['fixture'])), patch.object(installer, 'atomic') as publish, patch.object(installer, 'activate') as activate:
            with self.assertRaises(subprocess.CalledProcessError):
                installer.build('opencode', ROOT, resolution, refresh=True)
            publish.assert_not_called()
            activate.assert_not_called()

    def test_home_image_binding_no_unknown_upgrade(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            installer.bind_home(home, ID)
            installer.bind_home(home, ID)
            (home / 'credentials').write_text('unchanged')
            before = (home / '.agents-runtime-image.json').read_bytes()
            with self.assertRaises(ValueError):
                installer.bind_home(home, 'sha256:' + 'b' * 64)
            self.assertEqual((home / '.agents-runtime-image.json').read_bytes(), before)
            self.assertEqual((home / 'credentials').read_text(), 'unchanged')

    def test_unbound_private_state_never_adopted(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'session.db').write_text('existing')
            with self.assertRaises(ValueError):
                installer.bind_home(home, ID)
            self.assertFalse((home / '.agents-runtime-image.json').exists())

    def test_image_receipt_authority_validation(self):
        resolution = self.resolution()
        receipt = dict(schema=1, contract=1, image=ID, harness='opencode', platform='linux/amd64', resolution=resolution)
        image = dict(Id=ID, Os='linux', Architecture='amd64', Config=dict(Labels={
            'io.agents-runtime.harness': 'opencode', 'io.agents-runtime.contract': '1',
            'io.agents-runtime.resolution': installer.digest(installer.encoded(resolution))}, Env=['PATH=/usr/bin']))
        installer.verify_image(receipt, image)
        for mutate in (lambda i: i.update(Architecture='arm64'),
                       lambda i: i['Config'].update(Volumes={'/private': {}}),
                       lambda i: i['Config']['Env'].append('DOCKER_HOST=tcp://foreign'),
                       lambda i: i['Config']['Env'].append('LD_PRELOAD=/mutable/evil.so')):
            changed = copy.deepcopy(image)
            mutate(changed)
            with self.assertRaises(ValueError):
                installer.verify_image(receipt, changed)

    def test_compatible_stable_selection(self):
        self.assertEqual(installer.select(['1.2.0', '1.2.9', '1.2.10-beta', '2.0.0'], ['1.2.0', '2.0.0']), '1.2.9')
        with self.assertRaises(ValueError):
            installer.select(['2.0.0', '1.2.1-rc.1'], ['1.2.0', '2.0.0'])

    def test_resolution_exact_integrities(self):
        metadata = {'versions': {'1.18.29': {'dist': {'integrity': SRI, 'tarball': 'https://registry.npmjs.org/pkg.tgz'}},
                                 '2.0.0': {'dist': {}}}}
        with patch.object(installer, 'ordinary'), patch.object(installer, 'fetch', return_value=json.dumps(metadata).encode()), patch.object(installer, 'node_base', return_value={'image': 'node@' + ID}):
            result = installer.resolve('opencode', installer.catalog(), 'linux/amd64')
        self.assertEqual(result['packages']['opencode-ai'], {'version': '1.18.29', 'integrity': SRI})
        self.assertNotIn('image', result)

    def test_resolution_root_or_platform_before_network(self):
        with patch.object(installer.os, 'getuid', return_value=0), patch.object(installer, 'fetch') as fetch:
            with self.assertRaises(ValueError):
                installer.resolve('pi', installer.catalog(), 'linux/amd64')
            fetch.assert_not_called()
        with patch.object(installer, 'ordinary'), patch.object(installer, 'fetch') as fetch:
            for harness, platform in [('unknown', 'linux/amd64'), ('omp', 'linux/arm64')]:
                with self.assertRaises(ValueError):
                    installer.resolve(harness, installer.catalog(), platform)
            fetch.assert_not_called()

    def test_network_failure_has_no_activation(self):
        with patch.object(installer, 'ordinary'), patch.object(installer, 'fetch', side_effect=OSError('offline')), patch.object(installer, 'activate') as activate:
            with self.assertRaises(OSError):
                installer.resolve('pi', installer.catalog(), 'linux/amd64')
            activate.assert_not_called()

    def test_lock_rejects_transitive_drift(self):
        resolution = {'packages': {'pkg': {'version': '1.0.0', 'integrity': SRI}}}
        lock = {'lockfileVersion': 3, 'packages': {'': {}, 'node_modules/pkg':
                {'version': '1.0.0', 'integrity': SRI, 'resolved': 'https://registry.npmjs.org/pkg.tgz'}}}
        installer.validate_lock(resolution, lock)
        for key, value in [('integrity', 'sha1-weak'), ('resolved', 'file:/private'), ('link', True), ('version', '1.0.1')]:
            changed = copy.deepcopy(lock)
            changed['packages']['node_modules/pkg'][key] = value
            with self.assertRaises(ValueError):
                installer.validate_lock(resolution, changed)

    def test_atomic_failure_retains_old_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'selected.json'
            installer.atomic(path, {'image': 'old'})
            with patch.object(installer.os, 'replace', side_effect=OSError('injected')):
                with self.assertRaises(OSError):
                    installer.atomic(path, {'image': 'new'})
            self.assertEqual(json.loads(path.read_text()), {'image': 'old'})
            self.assertEqual(list(Path(temporary).iterdir()), [path])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_atomic_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'foreign').write_text('keep')
            (root / 'selected').symlink_to(root / 'foreign')
            with self.assertRaises(ValueError):
                installer.atomic(root / 'selected', {})
            self.assertEqual((root / 'foreign').read_text(), 'keep')

    def test_vm_activation_not_forwarded_to_legacy(self):
        with patch.object(installer, 'ordinary'), patch.object(installer, 'docker') as docker:
            with self.assertRaises(ValueError):
                installer.activate('pi', ID, {'scope': 'vm'})
            docker.assert_not_called()

    def test_missing_resolution_never_builds(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(installer, 'ordinary'), patch.object(installer, 'state_root', return_value=Path(temporary)), patch.object(installer, 'build') as build, patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(installer.main(['build', 'pi']), 1)
            build.assert_not_called()

    def test_make_is_explicit_and_not_autoactivating(self):
        for action in ('build', 'update'):
            result = subprocess.run(['make', '-n', '-C', str(ROOT), action, 'HARNESS=pi'], text=True, capture_output=True, check=True)
            self.assertIn(f'install.py {action} "$HARNESS"', result.stdout)
            self.assertNotIn('activate', result.stdout)

    def test_context_allowlists_and_single_harness(self):
        for harness, spec in installer.catalog()['harnesses'].items():
            recipe = (ROOT / spec['dockerfile']).read_text()
            ignore = (ROOT / (spec['dockerfile'] + '.dockerignore')).read_text().splitlines()
            self.assertEqual(ignore[0], '**')
            expected = {'!Dockerfile', '!Dockerfile.dockerignore', '!entry.py', '!harnesses.json', '!package.json', '!package-lock.json', '!apt.sources'}
            if harness == 'opencode':
                expected |= {'!opencode-plugins', '!opencode-plugins/**', '!publish-plugins.mjs'}
            self.assertEqual(set(ignore[1:]), expected)
            self.assertIn('FROM ${NODE_IMAGE}', recipe)
            self.assertIn('npm ci ', recipe)
            self.assertIn('--ignore-scripts', recipe)
            self.assertIn('RUN --network=none ', recipe)
            self.assertNotIn('sudo', recipe)
            self.assertNotIn('COPY . ', recipe)
            self.assertIn('io.agents-runtime.harness="' + harness + '"', recipe)


class Startup(unittest.TestCase):
    def test_command_matrix(self):
        for harness, modes in entry.MODES.items():
            for web in (False, True):
                if ('web' if web else 'cli') in modes:
                    selected = entry.command(harness, [] if web else ['a b'], web=web, port=4096 if web else None)
                    self.assertTrue(selected[0].startswith(entry.BIN))
                else:
                    with self.assertRaises(ValueError):
                        entry.command(harness, [], web=web, port=4096)

    def test_no_updater_or_unmanaged_server(self):
        for word in ('upgrade', 'web', 'serve'):
            with self.assertRaises(ValueError):
                entry.command('opencode', [word], web=False, port=None)

    def test_private_initialization_preserves_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            entry.initialize('pi', home, None)
            credential = home / '.pi/agent/auth.json'
            credential.write_text('private')
            entry.initialize('pi', home, None)
            self.assertEqual(credential.read_text(), 'private')

    def test_redirected_state_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'real').mkdir()
            (root / 'alias').symlink_to(root / 'real')
            with self.assertRaises(ValueError):
                entry.initialize('pi', root / 'alias', None)


@unittest.skipIf(os.getuid() == 0, 'Foreground CLI fixture requires an ordinary account')
class ForegroundCLI(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(os.umask, os.umask(0o077))
        self.root = Path(self.temporary.name)
        self.state = self.root / 'state'
        self.workspace = self.root / 'workspace'
        self.state.mkdir(mode=0o700)
        self.workspace.mkdir()
        self.resolution = Installation().resolution()
        self.receipt = dict(schema=1, contract=1, image=ID, harness='opencode',
                            platform='linux/amd64', resolution=self.resolution)
        installer.atomic(self.state / 'opencode-selected.json', self.receipt)
        self.calls = []
        self.orphan = False
        self.process = Mock()
        self.process.wait.return_value = 23

    def docker(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[:2] == ['container', 'ls']:
            return subprocess.CompletedProcess(argv, 0, 'owned-container' if self.orphan else '')
        self.assertEqual(argv, ['image', 'inspect', ID])
        image = dict(Id=ID, Os='linux', Architecture='amd64', Config=dict(Labels={
            'io.agents-runtime.harness': 'opencode', 'io.agents-runtime.contract': '1',
            'io.agents-runtime.resolution': installer.digest(installer.encoded(self.resolution))}, Env=[]))
        return subprocess.CompletedProcess(argv, 0, json.dumps([image]))

    def invoke(self, extra=()):
        with patch.dict(sys.modules, {'install': installer}), patch.object(installer, 'state_root', return_value=self.state), patch.object(installer, 'docker', side_effect=self.docker), patch.object(runtime.subprocess, 'Popen', return_value=self.process) as spawn, patch.object(runtime.os, 'isatty', return_value=False), patch('sys.stderr', new_callable=io.StringIO):
            result = runtime.main(['run', 'opencode', '--workspace', str(self.workspace), *extra,
                                   *([] if '--web' in extra else ['--', '--help'])])
            return result, spawn

    def test_foreground_exit_stdio_contract_and_no_build(self):
        with patch.dict(os.environ, {'DOCKER_HOST': 'tcp://foreign', 'API_KEY': 'private'}):
            result, spawn = self.invoke()
        self.assertEqual(result, 23)
        argv = spawn.call_args.args[0]
        self.assertEqual(argv[:3], ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock'])
        self.assertEqual(argv[-2:], ['--', '--help'])
        self.assertEqual(set(spawn.call_args.kwargs['env']), {'PATH', 'HOME'})
        self.assertNotIn('-it', argv)
        self.assertEqual(len(list(self.state.glob('agents-runtime-*.json'))), 1)
        self.assertEqual([call[:2] for call in self.calls], [['container', 'ls'], ['image', 'inspect']])

    def test_orphan_writer_refused_before_spawn(self):
        self.orphan = True
        result, spawn = self.invoke()
        self.assertEqual(result, 1)
        spawn.assert_not_called()
        self.assertEqual(len(self.calls), 1)

    def test_web_enters_supervision_with_selected_contract(self):
        with patch.object(runtime, 'supervise_web', return_value=19) as supervise:
            result, spawn = self.invoke(['--web'])
        self.assertEqual(result, 19)
        c, process = supervise.call_args.args
        self.assertEqual(c['mode'], 'web')
        self.assertEqual(c['image'], ID)
        self.assertIs(process, self.process)
        self.assertIn('127.0.0.1:4096:4096', spawn.call_args.args[0])

    def test_unknown_private_image_blocks_and_new_slot_is_independent(self):
        home = self.state / 'opencode-default-home'
        home.mkdir(mode=0o700)
        installer.bind_home(home, 'sha256:' + 'b' * 64)
        (home / 'session.db').write_text('preserve')
        result, spawn = self.invoke()
        self.assertEqual(result, 1)
        spawn.assert_not_called()
        result, spawn = self.invoke(['--state-slot', 'fresh'])
        self.assertEqual(result, 23)
        self.assertEqual((home / 'session.db').read_text(), 'preserve')
        self.assertNotIn(str(home), ' '.join(spawn.call_args.args[0]))


if __name__ == '__main__':
    unittest.main()
