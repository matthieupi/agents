"""Two containers sharing a config must not both reinstall the same graph."""
import subprocess

from test_plugin_install_reuse import InstallFixture


class ConcurrentInstall(InstallFixture):
    def test_concurrent_init_installs_the_shared_graph_once(self):
        processes = [subprocess.Popen(['/bin/bash', '-c', self.script], env=self.env,
                                     text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for _ in range(2)]
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual(self.installs(), 1, 'shared installation must be serialized and rechecked under lock')
