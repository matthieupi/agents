"""Focused lifecycle tests. No host installs, units, accounts or network changes."""
import os
from pathlib import Path
import pwd
import subprocess
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class NativeLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="opencode-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.runtime = self.root / "runtime"
        (self.runtime / "bin").mkdir(parents=True)
        self.workspace = self.root / "project with spaces"
        self.workspace.mkdir()
        self.log = self.root / "calls"
        self.uid = os.getuid()
        self.user = pwd.getpwuid(self.uid).pw_name
        self.env = dict(os.environ, PATH=f"{self.bin}:/usr/bin:/bin",
                        OPENCODE_USER=self.user, OPENCODE_ROOT=str(self.root),
                        OPENCODE_REPO=str(self.repo), OPENCODE_PREFIX=str(self.runtime),
                        OPENCODE_WORKSPACE=str(self.workspace), OPENCODE_PORT="4096",
                        OPENCODE_SERVER_PASSWORD="test-secret-not-in-output", CALL_LOG=str(self.log))
        # Account lookup is mocked so no real home is modified.
        self.mock("getent", f"printf '%s\\n' '{self.user}:x:{self.uid}:1000::'{self.home}':/bin/bash'")
        self.mock("systemctl", 'printf "%s\\n" "$*" >> "$CALL_LOG"; '
                  'case "$1" in show) printf "%s\\n" "${TEST_UNIT_STATE:-inactive}";; esac')
        self.mock("journalctl", 'printf "%s\\n" "$*" >> "$CALL_LOG"')
        binary = self.runtime / "bin/opencode"
        binary.write_text('#!/bin/bash\nprintf "cwd=%s\\nhome=%s\\nauto=%s\\n" "$PWD" "$HOME" "$OPENCODE_DISABLE_AUTOUPDATE"\nprintf "arg=%s\\n" "$@"\n')
        binary.chmod(0o755)

    def mock(self, name, body):
        target = self.bin / name
        target.write_text("#!/bin/bash\nset -eu\n" + body + "\n")
        target.chmod(0o755)

    def run_script(self, name, *args, **env):
        return subprocess.run(["bash", str(SCRIPTS / name), *args], env=dict(self.env, **env),
                              text=True, capture_output=True)

    def shell(self, body, **env):
        return subprocess.run(["bash", "-c", body], env=dict(self.env, **env), text=True, capture_output=True)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True).strip()

    def make_repo(self):
        self.git("init", "-q")
        (self.repo / "tracked").write_text("one")
        self.git("add", "tracked")
        self.commit("first")
        first = self.git("rev-parse", "HEAD")
        (self.repo / "tracked").write_text("two")
        self.git("add", "tracked")
        self.commit("second")
        second = self.git("rev-parse", "HEAD")
        self.git("remote", "add", "origin", str(self.repo))
        self.git("checkout", "-q", "--detach", first)
        return first, second

    def commit(self, message):
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", message)

    def update(self, action, revision, **env):
        # Simulate administrator authorization only. Git, clean-tree checks,
        # lock, revision resolution, and checkout are real local operations.
        self.mock("find", "exit 0")
        return self.shell(f'source "{SCRIPTS / "manage.sh"}"; '
                          'require_root() { :; }; trusted_path() { :; }; '
                          f'manage_main {action} "{revision}"', **env)

    @unittest.skipIf(os.getuid() == 0, "runtime tests require a real non-root test runner")
    def test_service_exec_contract(self):
        result = self.run_script("start.sh", "service")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"cwd={self.workspace}", result.stdout)
        self.assertIn(f"home={self.home}", result.stdout)
        self.assertIn("auto=1", result.stdout)
        self.assertIn("arg=web\narg=--hostname\narg=127.0.0.1\narg=--port\narg=4096\narg=--mdns\narg=false", result.stdout)
        self.assertNotIn(self.env["OPENCODE_SERVER_PASSWORD"], result.stdout + result.stderr)

    @unittest.skipIf(os.getuid() == 0, "requires non-root test runner")
    def test_service_rejects_bad_inputs_and_extra_flags(self):
        for port in ("0", "80", "65536", "04096", "1;id"):
            self.assertNotEqual(self.run_script("start.sh", "service", OPENCODE_PORT=port).returncode, 0)
        self.assertNotEqual(self.run_script("start.sh", "service", OPENCODE_SERVER_PASSWORD="").returncode, 0)
        self.assertNotEqual(self.run_script("start.sh", "service", "--hostname", "0.0.0.0").returncode, 0)
        self.assertNotEqual(self.run_script("start.sh", "service", OPENCODE_WORKSPACE="relative").returncode, 0)

    @unittest.skipIf(os.getuid() == 0, "requires non-root test runner")
    def test_session_passes_arguments_without_installing(self):
        result = self.run_script("start.sh", "session", "--agent", "plan", "--prompt", "two words")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("arg=--prompt\narg=two words", result.stdout)
        self.assertIn(f"cwd={self.workspace}", result.stdout)
        self.assertFalse(self.log.exists())

    def test_root_account_and_opt_paths_rejected(self):
        self.assertNotEqual(self.run_script("start.sh", "session", OPENCODE_ROOT="/opt/opencode").returncode, 0)
        self.mock("getent", "printf 'root:x:0:0::/root:/bin/bash\\n'")
        result = self.run_script("start.sh", "session", OPENCODE_USER="root")
        self.assertIn("non-root account", result.stderr)

    def test_status_and_bounded_logs(self):
        for command in ("status", "logs"):
            result = self.run_script("manage.sh", command)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--no-pager --full status opencode.service", self.log.read_text())
        self.assertIn("--no-pager -u opencode.service -n 100", self.log.read_text())

    def test_systemctl_failures_are_preserved(self):
        self.mock("systemctl", "exit 3")
        self.assertEqual(self.run_script("manage.sh", "status").returncode, 3)
        result = self.shell(f'source "{SCRIPTS / "manage.sh"}"; '
                            'require_root() { :; }; deployment_lock() { :; }; manage_main restart')
        self.assertEqual(result.returncode, 3)

    def test_service_control_takes_lifecycle_lock(self):
        result = self.shell(f'source "{SCRIPTS / "manage.sh"}"; '
                            'require_root() { :; }; deployment_lock() { die "lock busy"; }; manage_main start')
        self.assertIn("lock busy", result.stderr)
        self.assertFalse(self.log.exists())

    def test_stop_bypasses_contract_audit_and_lock_and_preserves_exit(self):
        self.mock("systemctl", 'printf "%s\n" "$*"; exit 23')
        result = self.shell(f'source "{SCRIPTS / "manage.sh"}"; '
                            'require_root() { :; }; load_contract() { die "broken deployment"; }; '
                            'deployment_lock() { die "lock busy"; }; manage_main stop')
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(result.stdout.strip(), "stop opencode.service")

    def test_stop_rejects_invalid_unit_and_extra_arguments(self):
        for unit, args in [("--all", "stop"), ("other.service extra", "stop"), ("opencode.service", "stop extra")]:
            result = self.shell(f'source "{SCRIPTS / "manage.sh"}"; '
                                'require_root() { :; }; manage_main ' + args, OPENCODE_UNIT=unit)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.log.exists())

    @unittest.skipIf(os.getuid() == 0, "requires non-root test runner")
    def test_seed_failure_and_concurrent_user_content_are_preserved(self):
        for name in ("commands", "skills", "system", "gsd"):
            (self.repo / "agent" / name).mkdir(parents=True)
        config = self.home / ".config/opencode"
        body = f'''source "{SCRIPTS / 'entrypoint.sh'}"; load_contract
        git() {{
            case " $* " in
                *" ls-files "*) printf '%s\\0' opencode/.opencode/config/tui.json ;;
                *" show "*)
                    printf partial
                    if [[ $SEED_CASE == failure ]]; then return 42; fi
                    printf user-content > "$OPENCODE_CONFIG_DIR/tui.json" ;;
            esac
        }}
        initialize_home
        '''
        result = self.shell(body, SEED_CASE="failure")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertFalse((config / "tui.json").exists())
        self.assertEqual(list(config.glob(".opencode-default.*")), [])
        result = self.shell(body, SEED_CASE="concurrent")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((config / "tui.json").read_text(), "user-content")
        self.assertEqual(list(config.glob(".opencode-default.*")), [])

    def test_wrong_home_owner_rejected(self):
        self.mock("stat", "printf '999999\\n'")
        result = self.run_script("start.sh", "session")
        self.assertIn("account must own its home", result.stderr)

    @unittest.skipIf(os.getuid() == 0, "requires non-root test runner")
    def test_admin_operations_never_escalate(self):
        for command in ("start", "stop", "restart"):
            result = self.run_script("manage.sh", command)
            self.assertIn("no automatic sudo", result.stderr)
        result = self.run_script("entrypoint.sh", "provision")
        self.assertIn("no automatic sudo", result.stderr)
        self.assertFalse(self.log.exists())

    def test_trusted_path_rejects_writable_ancestors_and_symlinks(self):
        result = self.shell(f'source "{SCRIPTS / "entrypoint.sh"}"; trusted_path "$OPENCODE_ROOT"')
        self.assertNotEqual(result.returncode, 0)
        (self.root / "link").symlink_to(self.repo)
        result = self.shell(f'source "{SCRIPTS / "entrypoint.sh"}"; trusted_path "$OPENCODE_ROOT/link"')
        self.assertIn("symlink", result.stderr)

    def test_update_check_and_explicit_checkout(self):
        first, second = self.make_repo()
        result = self.update("update-check", second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD"), first)
        result = self.update("update", second)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD"), second)
        self.assertIn("No automatic rollback", result.stdout)

    def test_update_refuses_dirty_tree_branch_and_active_service(self):
        first, second = self.make_repo()
        self.assertIn("full lowercase commit", self.update("update", "main").stderr)
        self.assertIn("stop the unit", self.update("update", second, TEST_UNIT_STATE="active").stderr)
        (self.repo / "untracked").write_text("keep me")
        self.assertIn("dirty", self.update("update", second).stderr)
        self.assertEqual(self.git("rev-parse", "HEAD"), first)
        self.assertEqual((self.repo / "untracked").read_text(), "keep me")

    def test_update_lock_and_fetch_failure(self):
        import fcntl
        first, second = self.make_repo()
        with (self.root / ".lifecycle.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertIn("another lifecycle", self.update("update", second).stderr)
        self.git("remote", "set-url", "origin", "file:///nonexistent/secret-value")
        result = self.update("update", "f" * 40)
        self.assertIn("fetch failed", result.stderr)
        self.assertNotIn("secret-value", result.stdout + result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD"), first)

    @unittest.skipIf(os.getuid() == 0, "requires non-root test runner")
    def test_initialize_preserves_config_plugins_and_skips_ignored_cache(self):
        self.git("init", "-q")
        source = self.repo / "opencode/.opencode/config"
        (source / "plugins").mkdir(parents=True)
        (source / "opencode.json").write_text('{"plugin":["existing@1.0.0"]}')
        (source / "plugins/test.js").write_text("export default () => ({})")
        (self.repo / ".gitignore").write_text("node_modules/\nauth.json\n")
        (source / "node_modules").mkdir()
        (source / "node_modules/huge-cache").write_text("do not copy")
        (source / "auth.json").write_text("do not copy credential")
        for name in ("commands", "skills", "system", "gsd"):
            folder = self.repo / "agent" / name
            folder.mkdir(parents=True)
            (folder / ".keep").touch()
        self.git("add", ".")
        self.commit("defaults")
        config = self.home / ".config/opencode"
        config.mkdir(parents=True)
        (config / "opencode.json").write_text("existing user config")
        (self.home / ".agents").mkdir()
        (self.home / ".agents/skills").symlink_to(self.repo / "agent/skills")
        result = self.run_script("entrypoint.sh", "initialize-home")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((config / "opencode.json").read_text(), "existing user config")
        self.assertTrue((config / "plugins/test.js").is_file())
        self.assertFalse((config / "node_modules").exists())
        self.assertFalse((config / "auth.json").exists())
        self.assertFalse((self.home / ".agents/skills").is_symlink())
        for name in ("commands", "skills", "system", "gsd"):
            self.assertEqual((config / name).resolve(), self.repo / "agent" / name)
        self.assertEqual(self.run_script("entrypoint.sh", "initialize-home").returncode, 0)
        # Existing JSONC is equally authoritative; don't introduce JSON beside it.
        (config / "opencode.json").rename(config / "opencode.jsonc")
        self.assertEqual(self.run_script("entrypoint.sh", "initialize-home").returncode, 0)
        self.assertFalse((config / "opencode.json").exists())
        self.assertEqual((config / "opencode.jsonc").read_text(), "existing user config")
        (config / "plugins/test.js").unlink()
        (config / "plugins").rmdir()
        external = self.root / "external-plugins"
        external.mkdir()
        (config / "plugins").symlink_to(external)
        result = self.run_script("entrypoint.sh", "initialize-home")
        self.assertIn("preserved redirected plugin directory", result.stderr)
        self.assertEqual(list(external.iterdir()), [])
        (config / "plugins").unlink()
        (config / "skills").unlink()
        (config / "skills").mkdir()
        self.assertIn("preserved conflicting resource", self.run_script("entrypoint.sh", "initialize-home").stderr)

    def test_provision_validates_pins_before_install(self):
        body = (f'source "{SCRIPTS / "entrypoint.sh"}"; load_contract; '
                'deployment_lock() { :; }; provision')
        result = self.shell(body, OPENCODE_VERSION="latest", OPENCODE_APT_PACKAGES="git=1")
        self.assertIn("exact stable version", result.stderr)
        result = self.shell(body, OPENCODE_VERSION="1.2.15", OPENCODE_APT_PACKAGES="git")
        self.assertIn("exact version", result.stderr)
        result = self.shell(body, OPENCODE_VERSION="1.2.15", OPENCODE_APT_PACKAGES="git=1")
        self.assertIn("missing required apt pin", result.stderr)

    def test_provision_install_contract_mocked(self):
        pins = " ".join(f"{name}=1.0" for name in (
            "ca-certificates", "git", "nodejs", "npm", "ripgrep", "python3", "python3-venv", "openssh-client"))
        body = (f'source "{SCRIPTS / "entrypoint.sh"}"; load_contract; '
                'deployment_lock() { :; }; '
                'timeout() { shift; "$@"; }; '
                'apt-get() { printf "apt %s\\n" "$*" >> "$CALL_LOG"; }; '
                'install() { :; }; '
                'env() { printf "env %s\\n" "$*" >> "$CALL_LOG"; }; '
                'runuser() { printf "runuser %s\\n" "$*" >> "$CALL_LOG"; '
                'if [[ "$*" == *--version ]]; then printf "1.2.15\\n"; fi; }; provision')
        result = self.shell(body, OPENCODE_VERSION="1.2.15", OPENCODE_APT_PACKAGES=pins)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text()
        self.assertIn("--no-install-recommends -- ca-certificates=1.0", calls)
        self.assertIn("--ignore-scripts --no-audit --no-fund --include=optional", calls)
        self.assertIn("opencode-ai@1.2.15", calls)
        self.assertIn(f"runuser -u {self.user} -- env -i", calls)
        self.assertIn("initialize-home", calls)
        self.assertNotIn(self.env["OPENCODE_SERVER_PASSWORD"], calls)
        self.assertIn("unit remains stopped", result.stdout)

    def test_failed_install_cleans_cache_and_never_initializes_or_starts(self):
        pins = " ".join(f"{name}=1.0" for name in (
            "ca-certificates", "git", "nodejs", "npm", "ripgrep", "python3", "python3-venv", "openssh-client"))
        body = (f'source "{SCRIPTS / "entrypoint.sh"}"; load_contract; '
                'deployment_lock() { :; }; timeout() { shift; "$@"; }; '
                'apt-get() { return "${TEST_APT_EXIT:-0}"; }; install() { :; }; '
                'env() { return 42; }; '
                'runuser() { printf "unexpected runtime launch\\n" >> "$CALL_LOG"; }; provision')
        for apt_exit, expected in (("0", 42), ("23", 23)):
            with self.subTest(apt_exit=apt_exit):
                result = self.shell(body, OPENCODE_VERSION="1.2.15", OPENCODE_APT_PACKAGES=pins,
                                    TEST_APT_EXIT=apt_exit)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(list(self.root.glob(".npm.*")), [])
                self.assertNotIn("unbound variable", result.stderr)
                self.assertNotIn("provisioned", result.stdout)
                self.assertNotIn("unexpected runtime launch", self.log.read_text())

    def test_initialize_rejects_redirected_docker_config(self):
        config = self.home / ".config"
        config.mkdir()
        (config / "opencode").symlink_to(self.repo)
        result = self.run_script("entrypoint.sh", "initialize-home")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((config / "opencode").is_symlink())
        self.assertEqual(list(self.repo.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
