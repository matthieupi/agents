"""Offline workstation selection, receipt custody, and retired VM rejection."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_shared_runtime as fixtures

installer, ID = fixtures.installer, fixtures.ID


class Activation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = dict(scope='workstation', state=str(self.root))
        self.receipt = dict(schema=1, contract=1, harness='opencode', image=ID,
                            platform='linux/amd64', resolution=fixtures.Installation().resolution())
        self.path = self.root / ('opencode-' + ID[7:] + '.json')
        installer.atomic(self.path, self.receipt)
        self.selected = self.root / 'opencode-selected.json'
        installer.atomic(self.selected, {'keep': 'previous selection'})
        self.image = dict(Id=ID, Os='linux', Architecture='amd64', Config=dict(Labels={
            'io.agents-runtime.harness': 'opencode', 'io.agents-runtime.contract': '1',
            'io.agents-runtime.resolution': installer.digest(installer.encoded(self.receipt['resolution']))}))
        ordinary = patch.object(installer, 'ordinary')
        ordinary.start()
        self.addCleanup(ordinary.stop)

    def test_workstation_verifies_and_publishes_without_delegation(self):
        for harness in ('pi', 'opencode', 'claude'):
            receipt = dict(self.receipt, harness=harness, resolution=fixtures.Installation().resolution(harness))
            installer.atomic(self.root / (harness + '-' + ID[7:] + '.json'), receipt)
            image = copy.deepcopy(self.image)
            image['Config']['Labels'].update({'io.agents-runtime.harness': harness,
                'io.agents-runtime.resolution': installer.digest(installer.encoded(receipt['resolution']))})
            with self.subTest(harness=harness), \
                    patch.object(installer, 'docker', return_value=subprocess.CompletedProcess([], 0, json.dumps([image]))) as docker, \
                    patch.object(installer.subprocess, 'run') as run:
                self.assertEqual(installer.activate(harness, ID, self.settings), 0)
            docker.assert_called_once_with(['image', 'inspect', ID])
            run.assert_not_called()
            self.assertEqual(json.loads((self.root / (harness + '-selected.json')).read_text()), receipt)

    def test_workstation_cli_passes_only_selection_settings(self):
        with patch.object(installer, 'state_root', return_value=self.root), \
                patch.object(installer, 'activate', return_value=0) as activate:
            self.assertEqual(installer.main(['activate', 'opencode', ID]), 0)
        activate.assert_called_once_with('opencode', ID, self.settings)

    def test_vm_and_retired_cli_selectors_refused_before_state_or_external_calls(self):
        for action in ('activate', 'update', 'build'):
            for selectors in (['--scope', 'vm'], ['--vm-config', '/unused'], ['--target', 'devai:fixture']):
                with self.subTest(action=action, selectors=selectors), \
                        patch.object(installer, 'state_root') as state, \
                        patch.object(installer.subprocess, 'run') as run, \
                        patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit) as error:
                    installer.main([action, 'pi', *selectors])
                self.assertEqual(error.exception.code, 2)
                state.assert_not_called()
                run.assert_not_called()

    def test_vm_settings_and_retired_harnesses_refused_before_inspection(self):
        cases = [('opencode', dict(self.settings, **extra)) for extra in
                 ({'scope': 'vm'}, {'scope': 'unknown'}, {'vm_config': '/unused'}, {'target': 'devai:fixture'})]
        cases += [(harness, self.settings) for harness in ('omp', 't3', 't3code', 'venv')]
        for harness, settings in cases:
            with self.subTest(harness=harness, settings=settings), patch.object(installer, 'docker') as docker, \
                    patch.object(installer.subprocess, 'run') as run, self.assertRaises(ValueError):
                installer.activate(harness, ID, settings)
            docker.assert_not_called()
            run.assert_not_called()
        self.assertEqual(json.loads(self.selected.read_text()), {'keep': 'previous selection'})

    def test_receipt_missing_redirected_or_mismatched_preserves_selection(self):
        for mutation in ('missing', 'symlink', 'harness', 'image', 'platform', 'contract', 'schema'):
            self.path.unlink(missing_ok=True)
            changed = copy.deepcopy(self.receipt)
            if mutation not in ('missing', 'symlink'):
                changed[mutation] = 'wrong'
                installer.atomic(self.path, changed)
            elif mutation == 'symlink':
                other = self.root / 'receipt.json'
                installer.atomic(other, changed)
                self.path.symlink_to(other)
            with self.subTest(mutation=mutation), \
                    patch.object(installer, 'docker', return_value=subprocess.CompletedProcess([], 0, json.dumps([self.image]))), \
                    patch.object(installer.subprocess, 'run') as run, self.assertRaises((OSError, ValueError, KeyError)):
                installer.activate('opencode', ID, self.settings)
            run.assert_not_called()
            self.assertEqual(json.loads(self.selected.read_text()), {'keep': 'previous selection'})

    def test_image_drift_or_inspection_failure_preserves_selection(self):
        mutations = [lambda i: i.update(Id='sha256:' + 'b' * 64),
                     lambda i: i.update(Architecture='arm64'),
                     lambda i: i['Config']['Labels'].update({'io.agents-runtime.resolution': 'b' * 64}),
                     lambda i: i['Config']['Labels'].update({'io.agents-runtime.harness': 'pi'}),
                     lambda i: i['Config']['Labels'].update({'io.agents-runtime.contract': '2'})]
        for mutate in mutations:
            image = copy.deepcopy(self.image)
            mutate(image)
            with self.subTest(image=image), \
                    patch.object(installer, 'docker', return_value=subprocess.CompletedProcess([], 0, json.dumps([image]))), \
                    self.assertRaises(ValueError):
                installer.activate('opencode', ID, self.settings)
            self.assertEqual(json.loads(self.selected.read_text()), {'keep': 'previous selection'})
        with patch.object(installer, 'docker', side_effect=subprocess.CalledProcessError(1, ['inspect'])), \
                self.assertRaises(subprocess.CalledProcessError):
            installer.activate('opencode', ID, self.settings)
        self.assertEqual(json.loads(self.selected.read_text()), {'keep': 'previous selection'})


class CallerIdentity(unittest.TestCase):
    def test_caller_root_setuid_and_setgid_refused_before_state(self):
        for uid, euid, gid, egid in ((0, 0, 0, 0), (1000, 0, 1000, 1000), (1000, 1000, 1000, 0)):
            with self.subTest(uid=uid, euid=euid, gid=gid, egid=egid), \
                    patch.object(os, 'getuid', return_value=uid), patch.object(os, 'geteuid', return_value=euid), \
                    patch.object(os, 'getgid', return_value=gid), patch.object(os, 'getegid', return_value=egid), \
                    patch.object(installer, 'private') as private, patch.object(installer, 'docker') as docker, \
                    self.assertRaisesRegex(ValueError, 'ordinary user'):
                installer.activate('opencode', ID, {'scope': 'workstation', 'state': '/unused'})
            private.assert_not_called()
            docker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
