"""Maintained installer to protected VM endpoint: no real sudo/Docker calls."""
import copy
import json
import io
import os
from pathlib import Path
import pwd
import stat
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_shared_runtime as fixtures

installer, ID = fixtures.installer, fixtures.ID


class Activation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.receipt = dict(schema=1, contract=1, harness='opencode', image=ID,
                            platform='linux/amd64', resolution=fixtures.Installation().resolution())
        installer.atomic(self.root / ('opencode-' + ID[7:] + '.json'), self.receipt)
        self.command = self.root / 'launcher'
        self.command.write_text('protected fixture; never executed')
        self.config = self.root / 'build.json'
        self.config.write_text(json.dumps(dict(command=str(self.command), platform='linux/amd64',
                                              socket='/var/run/docker.sock')))
        self.account = pwd.getpwuid(os.getuid())
        source = self.receipt['resolution']['source']
        self.projection = dict(harness='opencode', platform='linux/amd64', contract=1,
                               resolution_sha256=installer.digest(installer.encoded(self.receipt['resolution'])),
                               source_sha256=source['public_sha256'], source_revision=source['revision'])
        self.policy = dict(schema=2, scope='vm', target='devai:fixture',
                           accounts={self.account.pw_name: dict(uid=os.getuid(), gid=os.getgid())},
                           shared_runtime=dict(target='devai:fixture', images={'opencode': {ID: self.projection}}))
        self.policy_path = self.root / 'policy.json'
        self.policy_path.write_text(json.dumps(self.policy))
        self.settings = dict(scope='vm', state=str(self.root), vm_config=str(self.config), target='devai:fixture')
        # Separate tests exercise real filesystem protection, without trusting /tmp.
        for name, kwargs in [('ordinary', {}), ('protected_path', {'side_effect': lambda value, **kw: Path(value)}),
                             ('prerequisites', {})]:
            mock = patch.object(installer, name, create=True, **kwargs)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(installer, 'VM_POLICY', self.policy_path, create=True)
        mock.start()
        self.addCleanup(mock.stop)

    def invoke(self, status=0):
        with patch.object(installer, 'docker') as docker, patch.object(installer, 'atomic') as publish, \
                patch.object(installer.subprocess, 'run', return_value=subprocess.CompletedProcess([], status)) as run:
            result = installer.activate('opencode', ID, self.settings)
        docker.assert_not_called()  # protected launcher inspects the image independently
        publish.assert_not_called()
        return result, run

    def test_vm_activation_delegates_only_finite_arguments(self):
        result, run = self.invoke()
        self.assertEqual(result, 0)
        self.assertEqual(run.call_args.args[0], ['/usr/bin/sudo', '-n', '--', str(self.command), 'activate', 'opencode', ID])
        self.assertEqual(run.call_args.kwargs['env'], {'PATH': '/usr/bin:/bin', 'LANG': 'C'})

    def test_vm_failure_preserves_workstation_selection(self):
        selected = self.root / 'opencode-selected.json'
        installer.atomic(selected, {'keep': 'workstation'})
        result, _ = self.invoke(status=17)
        self.assertEqual(result, 17)
        self.assertEqual(json.loads(selected.read_text()), {'keep': 'workstation'})

    def test_vm_cli_reaches_delegation(self):
        with patch.object(installer, 'state_root', return_value=self.root), \
                patch.object(installer, 'activate', return_value=0) as activate:
            self.assertEqual(installer.main(['activate', 'opencode', ID, '--scope', 'vm',
                                             '--vm-config', str(self.config), '--target', 'devai:fixture']), 0)
        self.assertEqual(activate.call_args.args[2], self.settings)

    def test_vm_preflight_refuses_target_caller_and_projection_drift(self):
        for mutate in (lambda p: p.update(target='devai:other'),
                       lambda p: p['shared_runtime'].update(target='devai:other'),
                       lambda p: p.update(accounts={}),
                       lambda p: p['accounts'][self.account.pw_name].update(gid=os.getgid() + 1),
                       lambda p: p.pop('shared_runtime'),
                       lambda p: p['shared_runtime']['images']['opencode'][ID].update(resolution_sha256='b' * 64),
                       lambda p: p['shared_runtime']['images']['opencode'][ID].update(source_revision='b' * 40)):
            policy = copy.deepcopy(self.policy)
            mutate(policy)
            self.policy_path.write_text(json.dumps(policy))
            with self.subTest(policy=policy), patch.object(installer.subprocess, 'run') as run:
                with self.assertRaises((ValueError, KeyError)):
                    installer.activate('opencode', ID, self.settings)
                run.assert_not_called()

    def test_receipt_missing_redirected_or_mismatched_never_delegates(self):
        path = self.root / ('opencode-' + ID[7:] + '.json')
        for mutation in ('missing', 'symlink', 'harness', 'image', 'platform', 'contract'):
            path.unlink(missing_ok=True)
            changed = copy.deepcopy(self.receipt)
            if mutation in ('harness', 'image', 'platform', 'contract'):
                changed[mutation] = 'wrong'
                installer.atomic(path, changed)
            elif mutation == 'symlink':
                other = self.root / 'receipt.json'
                installer.atomic(other, changed)
                path.symlink_to(other)
            with self.subTest(mutation=mutation), patch.object(installer.subprocess, 'run') as run:
                with self.assertRaises((OSError, ValueError, KeyError)):
                    installer.activate('opencode', ID, self.settings)
                run.assert_not_called()

    def test_vm_selectors_never_enable_update_build_or_workstation(self):
        for action in ('update', 'build'):
            with patch.object(installer, 'state_root') as state, patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(installer.main([action, 'pi', '--scope', 'vm']), 1)
                state.assert_not_called()
        for scope in ('workstation', 'unknown'):
            with patch.object(installer.subprocess, 'run') as run, self.assertRaises(ValueError):
                installer.activate('opencode', ID, dict(self.settings, scope=scope))
            run.assert_not_called()

    def test_claude_never_delegates_and_missing_selectors_refused(self):
        for key in ('target', 'vm_config'):
            settings = dict(self.settings)
            settings.pop(key)
            with self.assertRaises(ValueError):
                installer.activate('opencode', ID, settings)
        with patch.object(installer.subprocess, 'run') as run, self.assertRaises(ValueError):
            installer.vm_command('claude', self.receipt, self.settings)
        run.assert_not_called()

    def test_workstation_still_verifies_and_publishes_without_sudo(self):
        image = dict(Id=ID, Os='linux', Architecture='amd64', Config=dict(Labels={
            'io.agents-runtime.harness': 'opencode', 'io.agents-runtime.contract': '1',
            'io.agents-runtime.resolution': self.projection['resolution_sha256']}))
        with patch.object(installer, 'docker', return_value=subprocess.CompletedProcess([], 0, json.dumps([image]))), \
                patch.object(installer.subprocess, 'run') as run:
            self.assertEqual(installer.activate('opencode', ID, dict(scope='workstation', state=str(self.root))), 0)
        run.assert_not_called()
        self.assertEqual(json.loads((self.root / 'opencode-selected.json').read_text()), self.receipt)


class ProtectedPaths(unittest.TestCase):
    def metadata(self, path):
        return SimpleNamespace(st_uid=0, st_nlink=1,
                               st_mode=(stat.S_IFREG | 0o755) if path.name == 'launcher' else (stat.S_IFDIR | 0o755))

    def test_safe_root_custody_and_every_ancestor_checked(self):
        checked = []
        def metadata(path):
            checked.append(path)
            return self.metadata(path)
        path = Path('/protected/bin/launcher')
        with patch.object(Path, 'resolve', autospec=True, side_effect=lambda p, **kw: p), \
                patch.object(Path, 'lstat', autospec=True, side_effect=metadata):
            self.assertEqual(installer.protected_path(str(path), executable=True), path)
        self.assertEqual(checked, [path, *path.parents])

    def test_unsafe_owner_mode_kind_links_and_ancestors_refused(self):
        for location, key, value in [('launcher', 'st_uid', 1000), ('bin', 'st_uid', 1000),
                                     ('protected', 'st_mode', stat.S_IFDIR | 0o777),
                                     ('launcher', 'st_mode', stat.S_IFREG | 0o775),
                                     ('launcher', 'st_mode', stat.S_IFREG | 0o4755),
                                     ('launcher', 'st_mode', stat.S_IFREG | 0o644),
                                     ('launcher', 'st_mode', stat.S_IFIFO | 0o755),
                                     ('launcher', 'st_nlink', 2)]:
            def metadata(path):
                result = self.metadata(path)
                if path.name == location:
                    setattr(result, key, value)
                return result
            with self.subTest(location=location, key=key, value=value), \
                    patch.object(Path, 'resolve', autospec=True, side_effect=lambda p, **kw: p), \
                    patch.object(Path, 'lstat', autospec=True, side_effect=metadata), self.assertRaises(ValueError):
                installer.protected_path('/protected/bin/launcher', executable=True)

    def test_noncanonical_and_symlink_paths_refused(self):
        for value in ('relative', '/safe/../launcher', '/safe/./launcher', '//safe/launcher',
                      '/safe/launcher\n', '/safe/a b', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                installer.protected_path(value)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'real').write_text('unchanged')
            (root / 'alias').symlink_to(root / 'real')
            with self.assertRaisesRegex(ValueError, 'Redirected'):
                installer.protected_path(str(root / 'alias'))

    def test_caller_root_setuid_and_setgid_refused(self):
        for uid, euid, gid, egid in ((0, 0, 0, 0), (1000, 0, 1000, 1000), (1000, 1000, 1000, 0)):
            with patch.object(os, 'getuid', return_value=uid), patch.object(os, 'geteuid', return_value=euid), \
                    patch.object(os, 'getgid', return_value=gid), patch.object(os, 'getegid', return_value=egid), \
                    patch.object(installer.subprocess, 'run') as run, self.assertRaises(ValueError):
                installer.activate('opencode', ID, {'scope': 'vm'})
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
