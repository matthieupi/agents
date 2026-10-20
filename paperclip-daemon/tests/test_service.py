"""SSH custody invariants; no SSH server or live HOME is accessed."""
from pathlib import Path
import subprocess
import unittest


PRODUCT = Path(__file__).resolve().parents[1]


class SSHServiceTests(unittest.TestCase):
    def test_initializer_runs_as_agent_without_server_wrapper(self):
        entry = (PRODUCT / "service-entrypoint.sh").read_text()
        subprocess.run(["bash", "-n", str(PRODUCT / "service-entrypoint.sh")], check=True)
        self.assertIn('/usr/sbin/runuser -u "$USER"', entry)
        self.assertIn('/bin/bash /opt/opencode/service-entrypoint.sh /usr/bin/true', entry)
        self.assertIn('exec "$@"', entry)
        self.assertNotIn("serve", entry)
        self.assertNotIn("PASSWORD", entry)

    def test_ssh_authorization_and_host_keys_stay_outside_home(self):
        source = (PRODUCT / "sshd_config.j2").read_text()
        for line in ("HostKey /run/paperclip-ssh/ssh_host_ed25519_key",
                     "AuthorizedKeysFile /etc/paperclip-authorized_keys",
                     "PermitRootLogin no", "PasswordAuthentication no",
                     "KbdInteractiveAuthentication no", "PermitEmptyPasswords no",
                     "AuthenticationMethods publickey", "DisableForwarding yes",
                     "PermitUserEnvironment no", "PermitUserRC no"):
            self.assertIn(line, source)
        dockerfile = (PRODUCT / "Dockerfile.service").read_text()
        self.assertIn("rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_*", dockerfile)
        self.assertIn('CMD ["/usr/sbin/sshd", "-D", "-e", "-f", "/etc/paperclip-sshd.conf"]', dockerfile)
        self.assertNotIn("OPENCODE_SERVER_PASSWORD", dockerfile)
        self.assertEqual((PRODUCT / "Dockerfile.service.dockerignore").read_text().splitlines(),
                         ["**", "!Dockerfile.service", "!Dockerfile.service.dockerignore", "!service-entrypoint.sh"])


if __name__ == "__main__":
    unittest.main()
