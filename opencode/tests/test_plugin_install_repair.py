"""Reuse must inspect installed dependencies, not trust an install marker alone."""
import shutil

from test_plugin_install_reuse import InstallFixture


class Repair(InstallFixture):
    def test_malformed_stamp_is_not_reused(self):
        self.successful(self.initialize())
        (self.package / '.kdco-install.json').write_text('interrupted stamp')
        self.successful(self.initialize())
        self.successful(self.initialize())
        self.assertEqual(self.installs(), 2)

    def test_missing_tree_reinstalls_but_unchanged_tree_does_not(self):
        self.successful(self.initialize())
        self.successful(self.initialize())
        self.assertEqual(self.installs(), 1)
        self.assertTrue((self.package / '.kdco-install.json').exists())
        shutil.rmtree(self.package / 'node_modules')
        self.successful(self.initialize())
        self.assertEqual(self.installs(), 2)

    def test_changed_manifest_reinstalls_once(self):
        self.successful(self.initialize())
        package = self.package / 'package.json'
        package.write_text(package.read_text() + '\n')
        self.successful(self.initialize())
        self.successful(self.initialize())
        self.assertEqual(self.installs(), 2)

    def test_changed_installed_bytes_reinstall_once(self):
        self.successful(self.initialize())
        artifact = self.package / 'node_modules/fixture'
        artifact.write_text('damaged')
        self.successful(self.initialize())
        self.successful(self.initialize())
        self.assertEqual(self.installs(), 2)
        self.assertEqual(artifact.read_text(), 'fixture')

    def test_failed_install_removes_success_stamp_and_retry_repairs_partial_tree(self):
        self.successful(self.initialize())
        lock = self.package / 'package-lock.json'
        lock.write_text(lock.read_text() + '\n')
        self.env['FAIL_INSTALL'] = '1'
        self.assertNotEqual(self.initialize().returncode, 0)
        self.assertFalse((self.package / '.kdco-install.json').exists())
        self.assertEqual((self.package / 'node_modules/fixture').read_text(), 'partial')
        del self.env['FAIL_INSTALL']
        self.successful(self.initialize())
        self.successful(self.initialize())
        self.assertEqual(self.installs(), 3)
        self.assertEqual((self.package / 'node_modules/fixture').read_text(), 'fixture')

    def test_changed_lock_reinstalls_once(self):
        self.successful(self.initialize())
        self.successful(self.initialize())
        self.assertEqual(self.installs(), 1)
        lock = self.package / 'package-lock.json'
        lock.write_text(lock.read_text() + '\n')
        self.successful(self.initialize())
        self.successful(self.initialize())
        self.assertEqual(self.installs(), 2)

    def test_missing_installed_file_reinstalls_once(self):
        self.successful(self.initialize())
        self.successful(self.initialize())
        self.assertEqual(self.installs(), 1)
        (self.package / 'node_modules/fixture').unlink()
        self.successful(self.initialize())
        self.successful(self.initialize())
        self.assertEqual(self.installs(), 2)
