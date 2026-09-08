"""Host workflow tests: real filesystem/metadata, Docker boundary replaced only."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import sys
import shutil
import subprocess
import socket
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("host", Path(__file__).resolve().parents[1] / "scripts/host.py")
sys.path.insert(0, str(Path(SPEC.origin).parent))
host = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(host)
IMAGE = "sha256:" + "a" * 64


class Workflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / "project with spaces"
        self.agent = self.base / "agent"
        self.root = self.base / "state"
        for path in (self.workspace, self.agent, self.root):
            path.mkdir(mode=0o700)
        self.env = patch.dict(os.environ, {
            "T3CODE_STATE_ROOT": str(self.root), "T3CODE_AGENT_ROOT": str(self.agent),
            "T3CODE_IMAGE": IMAGE,
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.calls = []
        def execute(args, capture=False, env=None):
            self.calls.append((args, env))
            if "inspect" in args and "image" in args:
                return json.dumps([{"Id": IMAGE}])
            if "ls" in args:
                return ""
            return ""
        self.execution = patch.object(host, "execute", side_effect=execute)
        self.execution.start()
        self.addCleanup(self.execution.stop)
        self.endpoint = patch.object(host, "local_daemon")
        self.endpoint.start()
        self.addCleanup(self.endpoint.stop)

    def profiles(self):
        return [json.loads(p.read_text()) for p in self.root.glob("*/profile.json")]

    def test_relative_dot_is_canonical_and_argv_preserved(self):
        previous = os.getcwd()
        try:
            os.chdir(self.workspace)
            host.launch(["."])
        finally:
            os.chdir(previous)
        profile, = self.profiles()
        self.assertEqual(profile["workspace"], str(self.workspace))
        argv, env = self.calls[-1]
        self.assertEqual(env["T3CODE_WORKSPACE"], str(self.workspace))
        self.assertIn("--no-recreate", argv)

    def test_defaults_initialize_private_state_without_repair(self):
        os.environ.pop("T3CODE_STATE_ROOT")
        os.environ.pop("T3CODE_AGENT_ROOT")
        home = self.base / "operator"
        home.mkdir(mode=0o700)
        with patch.object(host.pwd, "getpwuid") as account, patch.object(host, "COMPONENT", self.base / "t3code"):
            account.return_value.pw_dir = str(home)
            host.launch([str(self.workspace)])
        root = home / ".local/state/t3code"
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        profile, = list(root.glob("*/profile.json"))
        self.assertEqual(json.loads(profile.read_text())["agent"], str(self.agent))
        self.assertEqual(profile.stat().st_mode & 0o777, 0o600)
        root.chmod(0o755)
        os.environ["T3CODE_STATE_ROOT"] = str(root)
        with self.assertRaises(RuntimeError):
            host.registry()
        self.assertEqual(root.stat().st_mode & 0o777, 0o755)

    def test_build_captures_immutable_default_but_never_updates_profile(self):
        def built(args, **kwargs):
            self.calls.append((args, kwargs.get("env")))
            if "--iidfile" in args:
                iid = Path(args[args.index("--iidfile") + 1])
                iid.write_text(IMAGE)
                iid.chmod(0o600)
                return ""
            if "inspect" in args:
                return json.dumps([{"Id": IMAGE}])
            return ""
        with patch.object(host, "execute", side_effect=built):
            host.build()
        metadata = self.root / "build.json"
        self.assertEqual(json.loads(metadata.read_text())["image"], IMAGE)
        self.assertEqual(metadata.stat().st_mode & 0o777, 0o600)
        os.environ.pop("T3CODE_IMAGE")
        host.launch([str(self.workspace)])
        before = self.profiles()
        new_image = "sha256:" + "b" * 64
        value = json.loads(metadata.read_text())
        value["image"] = new_image
        host.write_private(metadata, value)
        host.launch([str(self.workspace)])
        self.assertEqual(self.profiles(), before)
        other = self.base / "other"
        other.mkdir()
        host.launch([str(other)])
        self.assertEqual({p["image"] for p in self.profiles()}, {IMAGE, new_image})

    def test_failed_build_or_bad_iid_preserves_default_and_profiles(self):
        host.launch([str(self.workspace)])
        metadata = self.root / "build.json"
        host.write_private(metadata, {"schema": 1, "image": IMAGE})
        before = metadata.read_bytes(), self.profiles()
        for result in (None, "latest", "", "repository@sha256:" + "a" * 64):
            def failed(args, **kwargs):
                if result is None:
                    raise RuntimeError("simulated build failure")
                iid = Path(args[args.index("--iidfile") + 1])
                iid.write_text(result)
                iid.chmod(0o600)
            with self.subTest(result=result), patch.object(host, "execute", side_effect=failed) as invocation:
                with self.assertRaises(RuntimeError):
                    host.build()
                invocation.assert_called_once()
            self.assertEqual((metadata.read_bytes(), self.profiles()), before)

    def test_bad_build_inputs_fail_before_docker(self):
        component = self.base / "component"
        shutil.copytree(host.COMPONENT / "runtime", component / "runtime", ignore=shutil.ignore_patterns("node_modules"))
        with patch.object(host, "COMPONENT", component), patch.object(host, "execute") as command:
            original = (component / "runtime/pins.json").read_text()
            for key, bad in (("NODE_IMAGE", "node:latest"), ("DEBIAN_SNAPSHOT", "today")):
                pins = json.loads(original)
                pins["build_args"][key] = bad
                (component / "runtime/pins.json").write_text(json.dumps(pins))
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    host.build()
            (component / "runtime/pins.json").write_text(original)
            lock = component / "runtime/package-lock.json"
            lock.write_text(lock.read_text() + " ")
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                host.build()
            command.assert_not_called()

    def test_build_uses_manifest_not_ambient_pin_overrides(self):
        os.environ["NODE_IMAGE"] = "node:latest"
        pins = host.build_inputs()
        self.assertNotEqual(pins["build_args"]["NODE_IMAGE"], "node:latest")
        self.assertEqual(pins["t3_version"], "0.0.40")
        os.environ["T3CODE_BUILD_PLATFORM"] = "linux/riscv64"
        with self.assertRaises(RuntimeError):
            host.build()
        self.assertEqual(self.calls, [])

    def test_root_identity_and_wrong_private_owner_refused(self):
        for uid, gid in ((0, 1000), (1000, 0)):
            with self.subTest(uid=uid, gid=gid), patch.object(host.os, "getuid", return_value=uid), patch.object(host.os, "getgid", return_value=gid):
                with self.assertRaises(RuntimeError):
                    host.operator()
        with patch.object(host.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaises(RuntimeError):
                host.registry()

    def test_symlink_workspace_state_and_metadata_refused(self):
        alias = self.base / "alias"
        alias.symlink_to(self.workspace, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            host.launch([str(alias)])
        state_alias = self.base / "state-alias"
        state_alias.symlink_to(self.root, target_is_directory=True)
        os.environ["T3CODE_STATE_ROOT"] = str(state_alias)
        with self.assertRaises(RuntimeError):
            host.registry()
        os.environ["T3CODE_STATE_ROOT"] = str(self.root)
        (self.root / "build.json").symlink_to(self.base / "missing")
        os.environ.pop("T3CODE_IMAGE")
        with self.assertRaises(RuntimeError):
            host.launch([str(self.workspace)])
        self.assertEqual(self.profiles(), [])

    def test_state_isolation_and_overlap_refusal(self):
        second = self.base / "second" / self.workspace.name
        second.mkdir(parents=True)
        host.launch([str(self.workspace)])
        host.launch([str(second)])
        profiles = self.profiles()
        self.assertEqual(len({p["name"] for p in profiles}), 2)
        self.assertEqual(len({p["home"] for p in profiles}), 2)
        for _, env in self.calls:
            if env:
                self.assertNotEqual(env["T3CODE_STATE_ROOT"], str(self.root))
                self.assertTrue(env["T3CODE_STATE_ROOT"].endswith("/home"))
        with self.assertRaises(RuntimeError):
            host.launch([str(self.root)])
        with self.assertRaises(RuntimeError):
            host.launch([str(self.agent)])

    def test_stop_and_remove_preserve_profile_home_and_workspace(self):
        host.launch([str(self.workspace)])
        profile, = self.profiles()
        marker = Path(profile["home"]) / "valuable-data"
        marker.write_text("retained")
        self.calls.clear()
        with patch.object(host, "container", return_value={"Id": "exact-managed-id"}):
            host.manage(["stop", profile["name"]])
            host.manage(["remove", profile["name"]])
        self.assertEqual(marker.read_text(), "retained")
        self.assertEqual(self.profiles(), [profile])
        self.assertTrue(self.workspace.is_dir())
        self.assertEqual([args[1:] for args, _ in self.calls], [
            ["container", "stop", "--time", "60", "exact-managed-id"],
            ["container", "stop", "--time", "60", "exact-managed-id"],
            ["container", "rm", "exact-managed-id"],
        ])

    def test_explicit_image_change_never_implicitly_replaces(self):
        host.launch([str(self.workspace)])
        before = self.profiles()
        self.calls.clear()
        os.environ["T3CODE_IMAGE"] = "sha256:" + "b" * 64
        with self.assertRaisesRegex(RuntimeError, "recreate"):
            host.launch([str(self.workspace)])
        self.assertEqual(self.profiles(), before)
        self.assertEqual(self.calls, [])

    def test_remote_docker_refused(self):
        os.environ["DOCKER_HOST"] = "ssh://unapproved.example"
        # Run the real endpoint validator (only its external Docker calls mocked).
        self.endpoint.stop()
        with self.assertRaisesRegex(RuntimeError, "local Unix"):
            host.local_daemon()
        self.assertEqual(self.calls, [])

    def test_dispatch_run_dot_and_management_help(self):
        for args, mode in ((["."], "run"), (["run", "."], "run"), (["build"], "manage")):
            with self.subTest(args=args), patch.object(sys, "argv", ["host.py", "dispatch", *args]), patch.object(host, "launch") as launch, patch.object(host, "manage") as manage:
                previous = os.umask(0o077)
                try:
                    host.main()
                finally:
                    os.umask(previous)
                (launch if mode == "run" else manage).assert_called_once_with(["."] if mode == "run" else ["build"])
        for wrapper in ("t3code", "t3code-run", "t3code-mgr"):
            result = subprocess.run([str(host.COMPONENT / wrapper), "--help"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_two_command_workflow_through_real_wrapper_processes(self):
        tools = self.base / "bin"
        tools.mkdir()
        fixture = tools / "docker"
        shutil.copyfile(Path(__file__).with_name("docker_fixture.py"), fixture)
        fixture.chmod(0o700)
        log = self.base / "docker.jsonl"
        env = dict(os.environ, PATH=f"{tools}:/usr/local/bin:/usr/bin:/bin", FAKE_DOCKER_LOG=str(log))
        env.pop("T3CODE_IMAGE")
        env["COMPOSE_FILE"] = "/unapproved.yml"
        env["NODE_IMAGE"] = "node:latest"
        wrapper = str(host.COMPONENT / "t3code")
        for args in (["build"], ["."], ["run", "."]):
            result = subprocess.run([wrapper, *args], cwd=self.workspace, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        profile, = self.profiles()
        self.assertEqual(profile["workspace"], str(self.workspace))
        self.assertEqual(profile["image"], "sha256:" + "c" * 64)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        build, = [c for c in calls if c["args"][0] == "build"]
        self.assertIn("NODE_IMAGE=" + host.build_inputs()["build_args"]["NODE_IMAGE"], build["args"])
        compose = [c for c in calls if c["args"][0] == "compose"]
        self.assertEqual(len(compose), 2)
        for call in compose:
            self.assertNotIn("COMPOSE_FILE", call["env"])
            self.assertEqual(call["env"]["T3CODE_IMAGE"], profile["image"])
            self.assertEqual(call["env"]["T3CODE_WORKSPACE"], str(self.workspace))
            self.assertIn("/dev/null", call["args"])
        before = (self.root / "build.json").read_bytes(), self.profiles()
        env["FAKE_BUILD_FAIL"] = "1"
        result = subprocess.run([wrapper, "build"], env=env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(((self.root / "build.json").read_bytes(), self.profiles()), before)

    def test_missing_or_unloaded_build_image_preserves_default(self):
        host.write_private(self.root / "build.json", {"schema": 1, "image": IMAGE})
        before = (self.root / "build.json").read_bytes()
        def wrong(args, **kwargs):
            if "--iidfile" in args:
                iid = Path(args[args.index("--iidfile") + 1])
                iid.write_text(IMAGE)
                iid.chmod(0o600)
            else:
                return json.dumps([{"Id": "sha256:" + "b" * 64}])
        for execute in (lambda *a, **k: "", wrong):
            with patch.object(host, "execute", side_effect=execute), self.assertRaises(RuntimeError):
                host.build()
            self.assertEqual((self.root / "build.json").read_bytes(), before)

    def test_lock_artifact_and_hooks_cannot_bypass_with_rehashed_lock(self):
        component = self.base / "component"
        shutil.copytree(host.COMPONENT / "runtime", component / "runtime", ignore=shutil.ignore_patterns("node_modules"))
        runtime = component / "runtime"
        original = (runtime / "package-lock.json").read_text()
        for key, value in (("integrity", "sha1-inadequate"), ("resolved", "https://unapproved.example/package.tgz"), ("hasInstallScript", True)):
            lock = json.loads(original)
            lock["packages"]["node_modules/yaml"][key] = value
            raw = json.dumps(lock).encode()
            (runtime / "package-lock.json").write_bytes(raw)
            pins = json.loads((runtime / "pins.json").read_text())
            pins["package_lock_sha256"] = host.hashlib.sha256(raw).hexdigest()
            (runtime / "pins.json").write_text(json.dumps(pins))
            with self.subTest(key=key), patch.object(host, "COMPONENT", component), self.assertRaises(RuntimeError):
                host.build_inputs()

    def test_missing_docker_gives_actionable_error_without_state_creation(self):
        tools = self.base / "without-docker"
        tools.mkdir()
        (tools / "python3").symlink_to(sys.executable)
        (tools / "dirname").symlink_to("/usr/bin/dirname")
        env = dict(os.environ, PATH=str(tools))
        env["T3CODE_STATE_ROOT"] = str(self.base / "not-created")
        result = subprocess.run([str(host.COMPONENT / "t3code"), "build"], env=env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Docker CLI", result.stderr)
        self.assertFalse(Path(env["T3CODE_STATE_ROOT"]).exists())

    def test_provider_none_is_usable_without_login_or_mapping(self):
        script = host.COMPONENT / "scripts/provider.sh"
        for action, expected in (("status", 0), ("initialize-home", 0), ("login", 69)):
            result = subprocess.run(["/bin/bash", str(script), action], env={"T3CODE_PROVIDER": "none"}, capture_output=True, text=True)
            self.assertEqual(result.returncode, expected, result.stderr)
            if action == "status":
                self.assertEqual(result.stdout.strip(), "unconfigured")
        result = subprocess.run(["/bin/bash", str(script), "status"], env={"T3CODE_PROVIDER": "claude"}, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_health_probe_checks_socket_not_provider_or_auth(self):
        node = shutil.which("node", path="/usr/local/bin:/usr/bin:/bin")
        if not node:
            self.skipTest("Node not available for local TCP health probe")
        script = host.COMPONENT / "scripts/healthcheck.mjs"
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            port = server.getsockname()[1]
            server.listen()
            result = subprocess.run([node, str(script)], env={"T3CODE_PORT": str(port)}, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0)
        for value in (str(port), "0", "03773", "65536", "invalid"):
            result = subprocess.run([node, str(script)], env={"T3CODE_PORT": value}, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
