"""Vendored plugin provenance/context contracts. No Docker, network or activation."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_shared_runtime as shared

ID, ROOT, installer = shared.ID, shared.ROOT, shared.installer

BASE = '../opencode/.opencode/config/kdco/'
PLUGIN_INPUTS = tuple(name for name in installer.build_sources('opencode', installer.catalog()) if name.startswith('../opencode/'))


class PluginBuild(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'runtime'
        for relative in ('entry.py', 'harnesses.json', 'images/opencode/Dockerfile',
                         'images/opencode/Dockerfile.dockerignore',
                         *PLUGIN_INPUTS):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / relative).read_bytes())
        # Fixture Git identity only; bytes/hashes/copy validation are real.
        self.git = patch.object(installer.subprocess, 'run', return_value=
                                subprocess.CompletedProcess([], 0, stdout='c' * 40 + '\n'))
        self.git.start()
        self.addCleanup(self.git.stop)
        self.resolution = shared.Installation().resolution()
        self.resolution['source'] = installer.source_record(self.root, 'opencode')

    def test_source_record_binds_all_vendored_inputs_only_for_opencode(self):
        record = self.resolution['source']
        self.assertEqual(len(record['public_files']), 4 + len(PLUGIN_INPUTS))
        for relative in PLUGIN_INPUTS:
            self.assertEqual(record['public_files'][relative],
                             installer.digest((self.root / relative).read_bytes()))
        self.assertEqual(record['public_sha256'], installer.digest(installer.encoded(record['public_files'])))
        for harness in ('pi', 'omp', 't3', 'claude'):
            self.assertEqual(len(installer.source_record(ROOT, harness)['public_files']), 4)

    def test_each_input_edit_rejects_stale_resolution_before_docker(self):
        for name in PLUGIN_INPUTS:
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                try:
                    with patch.object(installer, 'ordinary'), patch.object(installer, 'docker') as docker:
                        with self.assertRaisesRegex(ValueError, 'Public source changed'):
                            installer.build('opencode', self.root, self.resolution, refresh=False)
                        docker.assert_not_called()
                finally:
                    path.write_bytes(original)

    def test_old_resolution_missing_plugin_provenance_is_not_reused(self):
        old = copy.deepcopy(self.resolution)
        old['source']['public_files'] = {k: v for k, v in old['source']['public_files'].items()
                                         if not k.startswith('../opencode/')}
        old['source']['public_sha256'] = installer.digest(installer.encoded(old['source']['public_files']))
        with patch.object(installer, 'ordinary'), patch.object(installer, 'docker') as docker:
            with self.assertRaisesRegex(ValueError, 'Public source changed'):
                installer.build('opencode', self.root, old, refresh=False)
            docker.assert_not_called()

    def test_missing_and_redirected_inputs_fail_closed(self):
        for name in PLUGIN_INPUTS:
            path = self.root / name
            original = path.read_bytes()
            path.unlink()
            with self.subTest(name=name, case='missing'), self.assertRaises((OSError, ValueError)):
                installer.source_record(self.root, 'opencode')
            target = self.root / 'foreign-source'
            target.write_bytes(original)
            path.symlink_to(target)
            with self.subTest(name=name, case='redirected'), self.assertRaises(ValueError):
                installer.source_record(self.root, 'opencode')
            path.unlink()
            path.write_bytes(original)

    def test_even_fresh_provenance_cannot_bypass_plugin_lock_policy(self):
        path = self.root / BASE / 'package-lock.json'
        original = json.loads(path.read_text())
        mutations = [lambda lock: lock.update(lockfileVersion=2),
                     lambda lock: lock['packages']['node_modules/uuid'].update(integrity='sha1-weak'),
                     lambda lock: lock['packages']['node_modules/uuid'].update(resolved='https://foreign.example/pkg.tgz'),
                     lambda lock: lock['packages']['node_modules/uuid'].update(link=True),
                     lambda lock: lock['packages']['node_modules/node-notifier'].update(version='0.0.0'),
                     lambda lock: lock['packages']['']['dependencies'].update(unknown='1.0.0')]
        for mutate in mutations:
            lock = copy.deepcopy(original)
            mutate(lock)
            path.write_text(json.dumps(lock))
            resolution = copy.deepcopy(self.resolution)
            resolution['source'] = installer.source_record(self.root, 'opencode')
            with self.subTest(mutate=mutate), patch.object(installer, 'ordinary'), \
                    patch.object(installer, 'docker') as docker:
                with self.assertRaises(ValueError):
                    installer.build('opencode', self.root, resolution, refresh=False)
                docker.assert_not_called()

    def test_copy_time_drift_is_rejected_even_after_resolution_validation(self):
        original_validate = installer.validate_resolution

        def race(*args):
            current = original_validate(*args)
            (self.root / BASE / 'background-agents.ts').write_text('unreviewed concurrent change')
            return current

        with patch.object(installer, 'ordinary'), patch.object(installer, 'validate_resolution', side_effect=race), \
                patch.object(installer, 'docker') as docker:
            with self.assertRaisesRegex(ValueError, 'Public source changed while copying'):
                installer.build('opencode', self.root, self.resolution, refresh=False)
            docker.assert_not_called()

    def test_exact_context_receipt_binding_and_nonroot_offline_verification(self):
        (self.root / BASE / '.credentials').write_text('must not copy')
        (self.root / BASE / 'unreviewed.ts').write_text('must not copy')
        calls = []
        labels = {'io.agents-runtime.harness': 'opencode', 'io.agents-runtime.contract': '1',
                  'io.agents-runtime.resolution': installer.digest(installer.encoded(self.resolution))}

        def docker(argv, **kwargs):
            calls.append(argv)
            if argv[0] == 'build':
                context = Path(argv[-1])
                public = installer.build_sources('opencode', installer.catalog(), self.root)
                expected = {public[name] for name in PLUGIN_INPUTS}
                actual = {str(p.relative_to(context)) for p in (context / 'opencode-plugins').rglob('*') if p.is_file()} | {'publish-plugins.mjs'}
                self.assertEqual(actual, expected)
                for name in PLUGIN_INPUTS:
                    data = (context / public[name]).read_bytes()
                    self.assertEqual(data, (self.root / name).read_bytes())
                    self.assertEqual(installer.digest(data), self.resolution['source']['public_files'][name])
                self.assertIn('io.agents-runtime.resolution=' + labels['io.agents-runtime.resolution'], argv)
                recipe = (context / 'Dockerfile').read_text()
                install = 'RUN npm ci --prefix /opt/opencode-defaults/kdco --ignore-scripts --no-audit --no-fund'
                self.assertIn(install, recipe)
                self.assertEqual(recipe[:recipe.index(install)].rsplit('USER ', 1)[1].splitlines()[0], 'node')
                self.assertIn('RUN --network=none cd /opt/agents-runtime/packages && npm_config_nodedir=/usr/local npm rebuild --offline', recipe)
                Path(argv[argv.index('--iidfile') + 1]).write_text(ID)
                return subprocess.CompletedProcess(argv, 0)
            return subprocess.CompletedProcess(argv, 0, json.dumps([dict(
                Id=ID, Os='linux', Architecture='amd64', Config={'Labels': labels})]))

        with patch.object(installer, 'ordinary'), patch.object(installer, 'docker', side_effect=docker), \
                patch.object(installer, 'activate') as activate:
            receipt = installer.build('opencode', self.root, self.resolution, refresh=False)
        self.assertEqual(receipt['resolution'], self.resolution)
        self.assertEqual([call[0] for call in calls], ['build', 'image'])
        activate.assert_not_called()
        inspected = dict(Id=ID, Os='linux', Architecture='amd64', Config={'Labels': labels})
        installer.verify_image(receipt, inspected)
        tampered = copy.deepcopy(receipt)
        tampered['resolution']['source']['public_files'][BASE + 'upstream.json'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Image/receipt contract mismatch'):
            installer.verify_image(tampered, inspected)


if __name__ == '__main__':
    unittest.main()
