"""Offline behavioral tests. No apt/npm install, service action or network access.

Run with unittest discovery. Native launches execute locally.
"""
import os
from pathlib import Path
import pwd
import shlex
import subprocess
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SHA = "a" * 40


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pi-lifecycle-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o755)
        self.uid = pwd.getpwnam("nobody").pw_uid if os.geteuid() == 0 else os.geteuid()
        self.gid = pwd.getpwnam("nobody").pw_gid if os.geteuid() == 0 else os.getegid()
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)
        if os.geteuid() == 0:
            os.chown(self.home, self.uid, self.gid)
        self.deploy = self.root / "deploy"
        self.repo = self.deploy / "repo"
        self.prefix = self.deploy / "runtime"
        (self.repo / ".git").mkdir(parents=True)
        (self.prefix / "bin").mkdir(parents=True)
        self.workspace = self.root / "workspace with spaces"
        self.workspace.mkdir()
        for name in ("pi", "pi-web"):
            path = self.prefix / "bin" / name
            path.write_text('#!/bin/bash\nprintf "%s\\n" "$0" "$@" > "$TRACE"\nprintf "pid=%s\\nhome=%s\\ncwd=%s\\n" "$$" "$HOME" "$PWD" >> "$TRACE"\n')
            path.chmod(0o755)
        self.env = dict(os.environ, PI_ROOT=str(self.deploy), PI_REPO=str(self.repo),
                        PI_PREFIX=str(self.prefix), PI_USER="fixture", PI_BUILD_USER="builder", PI_HOME=str(self.home),
                        PI_UID=str(self.uid), PI_GID=str(self.gid), PI_UNIT="fixture-pi.service",
                        PI_WORKSPACE=str(self.workspace), PI_PORT="30141",
                        PI_WEB_PASSWORD="test-secret-not-logged", TRACE=str(self.home / "trace"),
                        PI_CODING_AGENT_DIR=str(self.home / ".pi/agent"))

    def run_shell(self, script, body, *, nonroot=False, contract=False, env=None):
        prelude = f'source {shlex.quote(str(SCRIPTS / script))}\n'
        if not contract:
            prelude += 'load_contract() { :; }\n'
        def demote():
            os.setgroups([])
            os.setgid(self.gid)
            os.setuid(self.uid)
        return subprocess.run(["/bin/bash", "-c", prelude + body], env=env or self.env,
                              text=True, capture_output=True,
                              preexec_fn=demote if nonroot and os.geteuid() == 0 else None)

    def trace(self):
        path = Path(self.env["TRACE"])
        return path.read_text() if path.exists() else ""

    def assert_failed(self, result, message):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)

    def test_service_and_session_launch_without_remote_adapter(self):
        for mode in ("service", "session"):
            with self.subTest(mode=mode):
                env = dict(self.env, PI_REMOTE_ADAPTER_READY="1", PI_EXECUTION_POLICY="local")
                result = self.run_shell("start.sh", f"start_main {mode}", nonroot=True, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("cwd=" + str(self.workspace), self.trace())

    @unittest.skipUnless(os.geteuid() == 0, "root rejection requires root test runner")
    def test_root_cannot_launch(self):
        self.assert_failed(self.run_shell("start.sh", "start_main session"), "never root")

    def test_service_launch_shape_and_exec(self):
        result = self.run_shell("start.sh", 'printf "%s" "$$" > "$HOME/expected-pid"; start_main service', nonroot=True,
                                env=dict(self.env, HOME=str(self.home), PI_WEB_HOSTNAME="0.0.0.0", PORT="9999"))
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.trace().splitlines()
        self.assertEqual(lines[1:6], ["--hostname", "127.0.0.1", "--port", "30141", "--no-open"])
        self.assertIn("pid=" + (self.home / "expected-pid").read_text(), lines)
        self.assertIn("home=" + str(self.home), lines)
        self.assertIn("cwd=" + str(self.workspace), lines)
        self.assertNotIn("test-secret", self.trace())

    def test_session_preserves_argument_boundaries(self):
        result = self.run_shell("start.sh", 'start_main session -p "two words" --resume', nonroot=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.trace().splitlines()[1:4], ["-p", "two words", "--resume"])
        self.assertIn("cwd=" + str(self.workspace), self.trace())

    def test_bad_service_inputs_never_launch(self):
        cases = [("PI_PORT", "0", "port must"), ("PI_PORT", "65536", "port must"),
                 ("PI_PORT", "030141", "port must"), ("PI_PORT", "80", "port must"),
                 ("PI_WEB_PASSWORD", "", "supply web password"),
                 ("PI_WORKSPACE", str(self.repo), "inside the deployment")]
        for key, value, message in cases:
            with self.subTest(key=key, value=value):
                result = self.run_shell("start.sh", "start_main service", nonroot=True,
                                        env=dict(self.env, **{key: value}))
                self.assert_failed(result, message)
        self.assert_failed(self.run_shell("start.sh", "start_main service --hostname 0.0.0.0", nonroot=True), "no extra flags")
        self.assertEqual(self.trace(), "")

    def test_contract_account_and_path_validation(self):
        record = 'getent() { printf "fixture:x:%s:%s::%s:/bin/bash\\n" "$PI_UID" "$PI_GID" "$PI_HOME"; }; load_contract'
        result = self.run_shell("entrypoint.sh", record, contract=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_failed(self.run_shell("entrypoint.sh", record, contract=True,
                                         env=dict(self.env, PI_PREFIX=str(self.repo / "runtime"))), "must not overlap")
        self.assert_failed(self.run_shell("entrypoint.sh", record, contract=True,
                                         env=dict(self.env, PI_UID="0")), "non-root account")
        self.assert_failed(self.run_shell("entrypoint.sh", record, contract=True,
                                         env=dict(self.env, PI_UNIT="--all")), "invalid unit")

    def test_home_seeding_preserves_auth_omp_and_existing_defaults(self):
        for name in ("prompts", "skills"):
            (self.repo / "agent" / name).mkdir(parents=True)
        setup = '''
        mkdir -p "$PI_CODING_AGENT_DIR"
        printf existing > "$PI_CODING_AGENT_DIR/settings.json"
        for f in auth.json agent.db config.yml models.json; do printf preserve > "$PI_CODING_AGENT_DIR/$f"; done
        git() {
            case " $* " in
                *" ls-files "*) printf '%s\\0' pi/.pi/agent/settings.json pi/.pi/agent/auth.json pi/.pi/agent/agent.db pi/.pi/agent/models.json pi/.pi/agent/extensions/demo.ts pi/.pi/agent/themes/nord.json ;;
                *" show "*) printf seeded ;;
                *) return 99 ;;
            esac
        }
        initialize_home
        initialize_home
        '''
        result = self.run_shell("entrypoint.sh", setup, nonroot=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.home / ".pi/agent"
        self.assertEqual((state / "settings.json").read_text(), "existing")
        for name in ("auth.json", "agent.db", "config.yml", "models.json"):
            self.assertEqual((state / name).read_text(), "preserve")
        self.assertEqual((state / "extensions/demo.ts").read_text(), "seeded")
        self.assertEqual((state / "skills").readlink(), self.repo / "agent/skills")

    def test_home_rejects_redirected_state(self):
        result = self.run_shell("entrypoint.sh", 'ln -s "$PI_REPO" "$PI_HOME/.pi"; initialize_home', nonroot=True)
        self.assert_failed(result, "preserved redirected Pi state")

    def test_home_conflicting_resource_is_not_moved(self):
        (self.repo / "agent").mkdir()
        result = self.run_shell("entrypoint.sh", 'mkdir -p "$PI_CODING_AGENT_DIR/agents"; printf keep > "$PI_CODING_AGENT_DIR/agents/mine"; initialize_home', nonroot=True)
        self.assert_failed(result, "preserved conflicting resource")
        self.assertEqual((self.home / ".pi/agent/agents/mine").read_text(), "keep")

    def test_failed_default_read_leaves_no_partial_file(self):
        for name in ("prompts", "skills"):
            (self.repo / "agent" / name).mkdir(parents=True)
        result = self.run_shell("entrypoint.sh", '''
        git() {
            case " $* " in
                *" ls-files "*) printf '%s\\0' pi/.pi/agent/settings.json ;;
                *" show "*) printf partial; return 1 ;;
            esac
        }
        initialize_home
        ''', nonroot=True)
        self.assertNotEqual(result.returncode, 0)
        state = self.home / ".pi/agent"
        self.assertFalse((state / "settings.json").exists())
        self.assertEqual(list(state.glob(".pi-default.*")), [])

    def update_mocks(self):
        return '''
        deployment_lock() { printf 'lock\\n' >> "$TRACE"; }
        systemctl() { printf '%s' "${STATE:-inactive}"; }
        timeout() { shift; "$@"; }
        git() {
            printf 'git %s\\n' "$*" >> "$TRACE"
            case " $* " in
                *" status "*) printf '%s' "${DIRTY:-}"; return "${STATUS_RESULT:-0}" ;;
                *" rev-parse HEAD "*) printf '%040d' 0 ;;
                *" rev-parse --verify "*) printf '%s' "${TARGET:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}" ;;
                *" fetch "*) return "${FETCH_RESULT:-0}" ;;
                *" checkout "*) return "${CHECKOUT_RESULT:-0}" ;;
                *) return 99 ;;
            esac
        }
        '''

    def test_update_check_fetches_but_never_checks_out(self):
        result = self.run_shell("manage.sh", self.update_mocks() + f"manage_main update-check {SHA}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fetch --quiet --no-tags origin " + SHA, self.trace())
        self.assertNotIn(" checkout ", self.trace())

    def test_update_exact_sha_detached_and_no_restart(self):
        result = self.run_shell("manage.sh", self.update_mocks() + f"manage_main update {SHA}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("checkout --quiet --detach --no-overwrite-ignore " + SHA, self.trace())
        self.assertIn("No automatic restart or rollback", result.stdout)
        self.assertNotIn("systemctl", self.trace())

    def test_update_failures_never_checkout(self):
        for extra, message in [({"DIRTY": "!! secret.env"}, "checkout is dirty"),
                               ({"STATUS_RESULT": "1"}, "cannot inspect checkout status"),
                               ({"STATE": "active"}, "stop the Ansible-managed unit"),
                               ({"TARGET": "b" * 40}, "revision mismatch"),
                               ({"FETCH_RESULT": "1"}, "fetch failed")]:
            with self.subTest(extra=extra):
                Path(self.env["TRACE"]).unlink(missing_ok=True)
                result = self.run_shell("manage.sh", self.update_mocks() + f"manage_main update {SHA}", env=dict(self.env, **extra))
                self.assert_failed(result, message)
                self.assertNotIn(" checkout ", self.trace())

    def test_update_rejects_branch_before_lock(self):
        result = self.run_shell("manage.sh", self.update_mocks() + "manage_main update main")
        self.assert_failed(result, "full lowercase commit SHA")
        self.assertEqual(self.trace(), "")

    def test_checkout_failure_does_not_claim_success(self):
        result = self.run_shell("manage.sh", self.update_mocks() + f"manage_main update {SHA}", env=dict(self.env, CHECKOUT_RESULT="1"))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Checkout updated", result.stdout)

    def test_management_start_restart_stop_status_logs(self):
        mocks = '''
        require_root() { :; }
        deployment_lock() { printf 'lock\\n' >> "$TRACE"; }
        systemctl() { printf 'systemctl %s\\n' "$*" >> "$TRACE"; }
        '''
        for command in ("start", "restart"):
            result = self.run_shell("manage.sh", mocks + f"manage_main {command}")
            self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_shell("manage.sh", mocks + "manage_main stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.trace().splitlines(), ["lock", "systemctl start fixture-pi.service", "lock", "systemctl restart fixture-pi.service", "systemctl stop fixture-pi.service"])
        # exec bypasses shell functions: intercept exec itself, never invoke host services.
        for command, expected in (("status", "systemctl --no-pager --full status fixture-pi.service"),
                                  ("logs", "journalctl --no-pager -u fixture-pi.service -n 100")):
            result = self.run_shell("manage.sh", 'exec() { printf "%s\\n" "$*"; }; manage_main ' + command)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), expected)

    def test_provision_rejects_active_unit_and_unpinned_dependencies(self):
        mocks = 'deployment_lock() { :; }; git() { :; }; getent() { printf "builder:x:12345:12345::/nonexistent:/usr/sbin/nologin\\n"; }; systemctl() { printf "%s" "${STATE:-inactive}"; }; timeout() { printf unexpected-install >> "$TRACE"; return 99; }; '
        for extra, message in [({"STATE": "active"}, "stop the Ansible-managed unit"),
                               ({"PI_APT_PACKAGES": "nodejs"}, "exact version"),
                               ({"PI_APT_PACKAGES": "nodejs=22.19.0"}, "missing required apt pin")]:
            result = self.run_shell("entrypoint.sh", mocks + "provision", env=dict(self.env, **extra))
            self.assert_failed(result, message)
        self.assertEqual(self.trace(), "")

    def provision_mocks(self):
        return '''
        deployment_lock() { printf 'lock\\n' >> "$TRACE"; }
        git() { :; }
        getent() { printf 'builder:x:12345:12345::/nonexistent:/usr/sbin/nologin\\n'; }
        systemctl() { printf inactive; }
        timeout() { shift; if [[ $1 == apt-get ]]; then printf 'apt\\n' >> "$TRACE"; else "$@"; fi; }
        env() { printf 'node-version-check\\n' >> "$TRACE"; }
        install() { mkdir -p -- "${@: -1}"; }
        chown() { printf 'chown\\n' >> "$TRACE"; }
        chmod() { :; }
        runuser() {
            printf 'runuser %s\\n' "$*" >> "$TRACE"
            local next=0 arg
            for arg in "$@"; do
                if (( next )); then printf ready > "$arg/ready"; break; fi
                [[ $arg != --prefix ]] || next=1
            done
        }
        verify_runtime() {
            printf 'verify %s\\n' "$1" >> "$TRACE"
            [[ ${VERIFY_FAIL:-0} != 1 && -f "$1/ready" ]]
        }
        '''

    def pinned_apt_env(self, **extra):
        pins = " ".join(name + "=1" for name in (
            "ca-certificates", "git", "nodejs", "npm", "ripgrep", "python3", "openssh-client", "build-essential"))
        return dict(self.env, PI_APT_PACKAGES=pins, **extra)

    def test_provision_stages_nonroot_installs_once_and_leaves_unit_stopped(self):
        result = self.run_shell("entrypoint.sh", self.provision_mocks() + "provision; provision", env=self.pinned_apt_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        trace = self.trace()
        self.assertEqual(trace.count("npm install --global"), 1)
        self.assertIn("runuser -u builder -- env -i HOME=", trace)
        self.assertIn("--ignore-scripts=false", trace)
        self.assertIn("@earendil-works/pi-coding-agent@0.85.1 @agegr/pi-web@0.9.0", trace)
        self.assertIn("chown\nverify ", trace)
        self.assertTrue((self.prefix / "ready").exists())
        self.assertIn("Unit remains stopped", result.stdout)
        self.assertNotIn("systemctl start", trace)
        self.assertEqual(list(self.deploy.glob(".build.*")), [])

    def test_failed_stage_preserves_existing_runtime_and_evidence(self):
        before = (self.prefix / "bin/pi").read_bytes()
        result = self.run_shell("entrypoint.sh", self.provision_mocks() + "provision", env=self.pinned_apt_env(VERIFY_FAIL="1"))
        self.assert_failed(result, "staged runtime verification failed")
        self.assertIn("inspect retained stage", result.stderr)
        self.assertEqual((self.prefix / "bin/pi").read_bytes(), before)
        self.assertEqual(len(list(self.deploy.glob(".build.*"))), 1)
        self.assertNotIn("provisioned.", result.stdout)

    def test_real_lock_contention_with_mocked_ownership(self):
        result = self.run_shell("entrypoint.sh", 'require_root() { :; }; trusted_path() { :; }; find() { :; }; exec 8>"$PI_ROOT/.lifecycle.lock"; flock -n 8; deployment_lock')
        self.assert_failed(result, "another lifecycle operation")

    def test_untrusted_deployment_path(self):
        result = self.run_shell("entrypoint.sh", 'trusted_path "$PI_ROOT"')
        self.assert_failed(result, "not root-owned/non-writable")

    def test_nonroot_cannot_manage_privileged_operations(self):
        for command in ("start", "stop", "restart"):
            result = self.run_shell("manage.sh", "manage_main " + command, nonroot=True)
            self.assert_failed(result, "administrator/root required")

    def test_start_restart_still_require_lifecycle_lock(self):
        for command in ("start", "restart"):
            result = self.run_shell("manage.sh", 'deployment_lock() { die "lock busy"; }; '
                                    'systemctl() { printf unexpected; }; manage_main ' + command)
            self.assert_failed(result, "lock busy")
            self.assertNotIn("unexpected", result.stdout)

    def test_stop_bypasses_contract_audit_and_lock_and_preserves_exit(self):
        result = self.run_shell("manage.sh", '''
        require_root() { :; }
        load_contract() { die 'broken deployment'; }
        deployment_lock() { die 'lock busy'; }
        systemctl() { printf '%s\n' "$*"; return 23; }
        manage_main stop
        ''')
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(result.stdout.strip(), "stop fixture-pi.service")

    def test_stop_rejects_invalid_unit_and_extra_arguments(self):
        for unit, args in [("--all", "stop"), ("other.service extra", "stop"), ("pi.service", "stop extra")]:
            result = self.run_shell("manage.sh", 'require_root() { :; }; systemctl() { printf unexpected; }; manage_main ' + args,
                                    env=dict(self.env, PI_UNIT=unit))
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("unexpected", result.stdout)


if __name__ == "__main__":
    unittest.main()
