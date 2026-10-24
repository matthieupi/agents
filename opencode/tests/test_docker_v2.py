"""Docker-only migration tests. Live smoke is opt-in and uses no host mounts."""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
IMAGE_ASSETS = (
    "opencode.json", "cli.json",
    "plugins/background-subagents.js", "tui-plugins/session-title.mjs",
    "tui-plugins/session-title/tui.js",
)


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DockerV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.config = self.base / "config"
        # Mirror the image's finite public closure, not the entire checkout.
        self.defaults = self.base / 'defaults'
        for asset in IMAGE_ASSETS:
            destination = self.defaults / asset
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / '.opencode/config' / asset).read_bytes())

    def run_init(self):
        home = self.base / "home"
        resources = self.base / "resources"
        home.mkdir(exist_ok=True)
        for folder in ("commands", "skills", "system"):
            (resources / folder).mkdir(parents=True, exist_ok=True)
        return subprocess.run(["bash", str(ROOT / "init.sh")], cwd=self.base,
                              env={**os.environ, "HOME": str(home),
                                    "OPENCODE_CONFIG_DIR": str(self.config),
                                    "OPENCODE_DEFAULTS": str(self.defaults),
                                    "OPENCODE_PUBLISHER": str(ROOT / '.opencode/config/publish-plugins.mjs'),
                                   "OPENCODE_RESOURCES": str(resources)},
                              capture_output=True, text=True, timeout=10)

    def test_init_publishes_canonical_links_and_preserves_private_state(self):
        self.config.mkdir()
        original = '{"private":"preserve"}\n'
        (self.config / "auth.json").write_text(original)
        for _ in range(2):
            result = self.run_init()
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.config / "auth.json").read_text(), original)
        for asset in IMAGE_ASSETS:
            if asset == "cli.json":
                self.assertFalse((self.config / asset).is_symlink())
                self.assertEqual((self.config / asset).read_bytes(), (self.defaults / asset).read_bytes())
            else:
                self.assertEqual((self.config / asset).readlink(), self.defaults / asset)
        for name in ("system", "commands", "skills"):
            self.assertEqual((self.config / name).resolve(), self.base / "resources" / name)
        self.assertFalse((self.config / 'gsd').exists())
        self.assertFalse((self.config / 'plugins/first-prompt-title.js').exists())
        self.assertFalse((self.config / 'plugins/first-prompt-title.js').is_symlink())
        preferences = {"theme": {"name": "custom"}, "plugins": ["private-plugin"]}
        (self.config / 'cli.json').write_text(json.dumps(preferences))
        result = self.run_init()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.config / 'cli.json').read_text()), {
            **preferences, "plugins": ["private-plugin", "./tui-plugins/session-title"],
        })
        (self.config / 'cli.json').write_text('private cli config')
        result = self.run_init()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.config / 'cli.json').read_text(), 'private cli config')
        self.assertFalse((ROOT / "scripts/docker-init.py").exists())
        self.assertFalse(any((ROOT / ".opencode/config/v2").rglob("*")))

    def test_private_or_project_kdco_loaders_fail_actionably_without_deletion(self):
        for folder in (self.config / "plugins", self.base / ".opencode/plugins"):
            folder.mkdir(parents=True, exist_ok=True)
            plugin = folder / "kdco-worktree.ts"
            plugin.write_text("private-unreviewed-loader")
            unrelated = folder / "custom.ts"
            unrelated.write_text("preserve")
            result = self.run_init()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(str(plugin), result.stderr)
            self.assertIn("preserv", result.stderr.lower())
            self.assertEqual(plugin.read_text(), "private-unreviewed-loader")
            self.assertEqual(unrelated.read_text(), "preserve")
            plugin.unlink()

    def test_redirected_private_config_is_preserved_and_never_followed(self):
        outside = self.base / 'outside'
        outside.mkdir()
        sentinel = outside / 'private.json'
        sentinel.write_text('preserve')
        self.config.symlink_to(outside, target_is_directory=True)
        result = self.run_init()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.config.is_symlink())
        self.assertEqual(sentinel.read_text(), 'preserve')
        self.assertEqual(list(outside.iterdir()), [sentinel])

    def test_only_exact_legacy_resource_self_links_are_retired(self):
        self.assertEqual(self.run_init().returncode, 0)
        resources = self.base / 'resources'
        managed = resources / 'commands/commands'
        managed.symlink_to('/opt/agent/commands')
        custom = resources / 'skills/skills'
        custom.symlink_to('/private/custom-skills')
        result = self.run_init()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(managed.is_symlink())
        self.assertEqual(custom.readlink(), Path('/private/custom-skills'))

    def test_missing_resource_tree_fails_actionably(self):
        result = subprocess.run(["bash", str(ROOT / "init.sh")], cwd=self.base,
                                env={**os.environ, "HOME": str(self.base),
                                     "OPENCODE_CONFIG_DIR": str(self.config),
                                     "OPENCODE_RESOURCES": str(self.base / "absent")},
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mount the complete agent tree", result.stderr)

    def test_canonical_config_native_roster_models_permissions_and_title_loading(self):
        config = ROOT / ".opencode/config"
        values = json.loads((config / "opencode.json").read_text())
        expected = {"Orchestrator", "explore", "reviewer", "COO", "DevOps", "DevOps Junior",
                    "SecOps", "plan", "build", "plan-inline", "title", "worker"}
        self.assertEqual(set(values["agents"]), expected)
        self.assertEqual(values["model"], "openai/gpt-6-astra")
        self.assertEqual(values["agents"]["DevOps"]["mode"], "all")
        self.assertEqual(values["agents"]["DevOps Junior"]["model"], "openai/gpt-6-sol")
        self.assertEqual(values["agents"]["title"]["model"], "openai/gpt-5-mini")
        worker = values["agents"]["worker"]
        self.assertEqual(worker["model"], "openai/gpt-6-luna")
        self.assertEqual(worker["mode"], "subagent")
        self.assertFalse(worker.get("hidden", False))
        self.assertEqual(worker["system"], "{file:./system/worker.md}")
        self.assertEqual(worker["permissions"], [{"action": "subagent", "resource": "*", "effect": "deny"}])
        self.assertEqual(values["compaction"], {"auto": False, "buffer": 50000})
        self.assertEqual(values["permissions"], [{"action": "*", "resource": "*", "effect": "allow"}])
        self.assertEqual(values["providers"]["openai"]["models"]["gpt-6-astra"]["limit"]["input"], 320000)
        self.assertEqual(values["providers"]["ollama"]["package"], "@opencode/ai/providers/openai-compatible")
        self.assertEqual(values["providers"]["ollama"]["settings"], {"baseURL": "{env:OLLAMA_HOST}/v1"})
        for name, definition in values["agents"].items():
            if name == "title":
                continue
            relative = definition["system"].removeprefix("{file:./").removesuffix("}")
            self.assertTrue((ROOT.parent / "agent" / relative).is_file(), name)
            self.assertNotIn("prompt", definition)
            self.assertNotIn("permission", definition)
        cli = json.loads((config / "cli.json").read_text())
        self.assertEqual(cli["theme"], {"name": "opencode"})
        self.assertEqual(cli["plugins"], ["./tui-plugins/session-title"])
        self.assertTrue((config / "tui-plugins/session-title/tui.js").is_file())
        self.assertFalse(list((config / "plugins").glob("kdco-*")))
        self.assertFalse((config / "plugins/first-prompt-title.js").exists())
        self.assertNotIn("first-prompt-title", json.dumps(values))

    def test_fingerprint_changes_with_canonical_config_credentials_and_web_exposure(self):
        def fingerprint(*args):
            result, calls = self.run_wrapper(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            run = next(call for call in calls if call[0] == "run")
            return next(value for value in run if value.startswith("dev.xmist.opencode.config="))

        initial = fingerprint()
        self.assertEqual(initial, fingerprint())
        config = self.base / ".opencode/config/opencode.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('{"model":"openai/changed"}')
        changed = fingerprint()
        self.assertNotEqual(initial, changed)
        self.assertNotEqual(changed, fingerprint("--web", "7777"))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key"}):
            self.assertNotEqual(changed, fingerprint())
        plugin = self.base / ".opencode/config/plugins/background-subagents.js"
        plugin.parent.mkdir(exist_ok=True)
        plugin.write_text((ROOT / ".opencode/config/plugins/background-subagents.js").read_text())
        with_plugin = fingerprint()
        self.assertNotEqual(changed, with_plugin)
        plugin.write_text(plugin.read_text() + "\n// changed source\n")
        self.assertNotEqual(with_plugin, fingerprint())

    def test_image_asset_manifest_and_background_source_closure(self):
        allowlist = (ROOT / ".dockerignore").read_text().splitlines()
        self.assertNotIn("!.opencode/config/plugins/first-prompt-title.js", allowlist)
        for asset in IMAGE_ASSETS:
            source = ROOT / ".opencode/config" / asset
            self.assertTrue(source.is_file(), asset)
            self.assertIn("!.opencode/config/" + asset, allowlist)
            for image in ("Dockerfile", "Dockerfile.gpu"):
                self.assertIn(".opencode/config/" + asset, (ROOT / image).read_text())
        # This plugin is standalone. Adding an import requires reviewing and
        # extending the closed image manifest rather than silently omitting it.
        background = (ROOT / ".opencode/config/plugins/background-subagents.js").read_text()
        self.assertNotRegex(background, r"(?m)^\s*import\s|\bimport\s*\(|\brequire\s*\(|(?m:^\s*export\s.+\sfrom\s)")

    def test_authenticated_health_rejects_bad_password_and_v1_response(self):
        health = load("docker-health")
        expected = "Basic " + base64.b64encode(b"opencode:test-secret").decode()

        class Handler(BaseHTTPRequestHandler):
            version = "2.0.32"

            def do_GET(self):
                if self.path != "/api/info" or self.headers.get("Authorization") != expected:
                    self.send_error(401)
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"version": self.version, "pid": 1}).encode())

            def log_message(self, format, *args):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            with patch.dict(os.environ, {"OPENCODE_PASSWORD": "test-secret",
                                        "OPENCODE_DOCKER_PORT": str(server.server_port)}):
                self.assertEqual(health.request_info()["version"], "2.0.32")
                with patch.dict(os.environ, {"OPENCODE_PASSWORD": "wrong"}):
                    with self.assertRaises(Exception):
                        health.request_info()
                Handler.version = "1.18.29"
                with self.assertRaises(RuntimeError):
                    health.request_info()
            server.shutdown()
            worker.join()

    def test_image_and_client_contracts(self):
        for name in ("Dockerfile", "Dockerfile.gpu"):
            text = (ROOT / name).read_text()
            self.assertIn("npm install -g @opencode/cli@latest", text)
            self.assertNotIn("COPY .opencode/config/kdco", text)
            self.assertNotIn(".opencode/config/v2", text)
            self.assertNotIn("first-prompt-title", text)
            self.assertIn(".opencode/config/plugins/background-subagents.js", text)
            self.assertIn(".opencode/config/tui-plugins/session-title/tui.js", text)
            self.assertIn(".opencode/config/cli.json", text)
            self.assertIn("COPY .opencode/config/publish-plugins.mjs /opt/opencode/publish-plugins.mjs", text)
            self.assertIn('CMD ["bash", "/opt/harness/docker-server.sh"]', text)
            self.assertIn("CMD python3 /opt/harness/docker-health.py", text)
        client = (ROOT / "scripts/docker-client.sh").read_text()
        self.assertIn('exec opencode --server', client)
        self.assertNotIn("--standalone", client)
        wrapper = (ROOT / "opencode-run").read_text()
        self.assertNotIn("tail -f", wrapper)
        self.assertNotIn("opencode web", wrapper)
        self.assertNotIn("--permission", wrapper)
        self.assertIn("{{.Image}}", wrapper)
        self.assertIn("has_requested_lifecycle_config", wrapper)
        self.assertIn('!.opencode/config/publish-plugins.mjs', (ROOT / '.dockerignore').read_text())
        self.assertNotIn('!scripts/publish-plugins.mjs', (ROOT / '.dockerignore').read_text())

    def run_wrapper(self, *args, existing=False, old_image=False, old_lifecycle=False, old_config=False, stopped=False):
        launcher = self.base / "opencode-run"
        # Docker is mocked; never bind real host ports in launcher unit tests.
        launcher.write_text((ROOT / "opencode-run").read_text().replace(
            'if ! ensure_host_port_free "${AGENT_WEB_BIND_HOST}" "${AGENT_WEB_PORT}"; then',
            'if ! true; then'))
        workspace = self.base / "project"
        workspace.mkdir(exist_ok=True)
        fake = self.base / "docker"
        fake.write_text('''#!/usr/bin/env python3
import hashlib, json, os, sys
args = sys.argv[1:]
with open(os.environ["DOCKER_TEST_LOG"], "a") as output:
    output.write(json.dumps(args) + "\\n")
if args[:2] == ["image", "inspect"]:
    print("sha256:new" if "{{.Id}}" in args else "v2-serve-1")
elif args[0] == "ps" and (os.environ["EXISTING"] == "1" or any(
        json.loads(line)[0] == "run" for line in open(os.environ["DOCKER_TEST_LOG"]))):
    if "-a" in args: print("Exited (0)" if os.environ["STOPPED"] == "1" else "Up 1 minute")
    elif os.environ["STOPPED"] != "1" or any(json.loads(line)[0] == "run" for line in open(os.environ["DOCKER_TEST_LOG"])):
        print("container-id")
elif args[0] == "inspect":
    template = args[args.index("--format") + 1]
    if template == "{{.Image}}":
        print("sha256:old" if os.environ["OLD_IMAGE"] == "1" else "sha256:new")
    elif "lifecycle" in template:
        print("v1" if os.environ["OLD_LIFECYCLE"] == "1" else "v2-serve-1")
    elif "opencode.config" in template:
        print("old-config" if os.environ["OLD_CONFIG"] == "1" else os.environ["OPENCODE_DOCKER_CONFIG_FINGERPRINT"])
    elif "cpus" in template: print("8.0")
    elif "memory" in template: print("16g")
    elif "publish" in template: print("")
    elif "volumes" in template: print(hashlib.sha256(bytes([0])).hexdigest())
    elif template == "{{.HostConfig.Privileged}}": print("false")
elif args[0] == "port": print("127.0.0.1:7777")
''')
        fake.chmod(0o755)
        log = self.base / "docker-calls.jsonl"
        log.write_text("")
        env = {**os.environ, "PATH": f"{self.base}:{os.environ['PATH']}",
               "OPENCODE_PASSWORD": "not-in-argv", "DOCKER_TEST_LOG": str(log),
               "EXISTING": str(int(existing)), "OLD_IMAGE": str(int(old_image)),
               "OLD_LIFECYCLE": str(int(old_lifecycle)), "OLD_CONFIG": str(int(old_config)),
               "STOPPED": str(int(stopped))}
        result = subprocess.run(["bash", str(launcher), *args, str(workspace)],
                                env=env, capture_output=True, text=True, timeout=10)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertNotIn("not-in-argv", log.read_text() + result.stdout + result.stderr)
        return result, calls

    def test_wrapper_creates_foreground_default_and_connects_auto_client(self):
        result, calls = self.run_wrapper("--dangerous", "--cpus", "4", "--memory", "8g", "--gpu", "0")
        self.assertEqual(result.returncode, 0, result.stderr)
        run = next(call for call in calls if call[0] == "run")
        self.assertEqual(run[-1], "lab/opencode:gpu")
        self.assertIn("--gpus", run)
        self.assertIn("4", run)
        self.assertIn("8g", run)
        self.assertIn("OPENCODE_PASSWORD", run)
        for name in ("home-config", "data", "cache", "state"):
            self.assertTrue(any(f"/.opencode/{name}:" in arg for arg in run))
        self.assertFalse(any("/.opencode/v2/" in arg or "/opt/opencode-source" in arg for arg in run))
        self.assertEqual(run[run.index("--name") + 1], "opencode-project-gpu")
        self.assertEqual(calls[-1][-2:], ["/opt/harness/docker-client.sh", "--auto"])

    def test_wrapper_reuses_only_immutable_matching_v2_and_web_never_launches_server(self):
        result, calls = self.run_wrapper("--web", "7777", existing=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call[0] in ("run", "rm") for call in calls))
        self.assertEqual(calls[-1][-2:], ["/opt/harness/docker-health.py", "--wait"])
        for kwargs in ({"old_image": True}, {"old_lifecycle": True}, {"old_config": True}):
            result, calls = self.run_wrapper(existing=True, **kwargs)
            self.assertEqual(result.returncode, 0, result.stderr)
            actions = [call[0] for call in calls]
            self.assertLess(actions.index("stop"), actions.index("rm"))
            self.assertLess(actions.index("rm"), actions.index("run"))
            self.assertIn("active sessions will be interrupted", result.stdout)

    def test_wrapper_replaces_running_configuration_changes_and_stopped_containers(self):
        sentinels = []
        for folder in ("data", "cache", "state"):
            state = self.base / ".opencode" / folder / "existing-private-state"
            state.parent.mkdir(parents=True)
            state.write_bytes(b"keep existing state\x00")
            sentinels.append(state)
        for args in (("--cpus", "4"), ("--memory", "8g"), ("--web", "8888"),
                     ("--wlan", "7777"), ("--publish", "3000"), ("--gpu", "0")):
            result, calls = self.run_wrapper(*args, existing=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(any(call[0] == "stop" for call in calls))
            self.assertTrue(any(call[0] == "rm" for call in calls))
            self.assertTrue(any(call[0] == "run" for call in calls))
        result, calls = self.run_wrapper(existing=True, stopped=True, old_image=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        removed = next(call for call in calls if call[0] == "rm")
        self.assertIn("-f", removed)
        self.assertTrue(any(call[0] == "run" for call in calls))
        for state in sentinels:
            self.assertEqual(state.read_bytes(), b"keep existing state\x00")

    def test_wrapper_rejects_conflicting_agent_or_reserved_ports_before_docker(self):
        for args in (("--agent-web-port", "7777"), ("--publish", "4096"),
                     ("--web", "--agent-web-port", "4096")):
            result, calls = self.run_wrapper(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])

    @unittest.skipUnless(os.environ.get("OPENCODE_DOCKER_SMOKE_IMAGE"), "set disposable smoke image")
    def test_real_disposable_server_auth_client_and_canonical_config(self):
        image = os.environ["OPENCODE_DOCKER_SMOKE_IMAGE"]
        original = json.loads((ROOT / ".opencode/config/opencode.json").read_text())
        agent = self.base / "agent"
        for folder in ("commands", "skills", "system"):
            (agent / folder).mkdir(parents=True)
        for definition in original["agents"].values():
            if "system" not in definition:
                continue
            relative = definition["system"].removeprefix("{file:./").removesuffix("}")
            (agent / relative).write_text("Disposable prompt resource: " + relative + "\n")
        for target in (agent, *agent.rglob("*")):
            target.chmod(0o755 if target.is_dir() else 0o644)

        def docker(*args, check=True):
            result = subprocess.run(["docker", *args], text=True, capture_output=True, timeout=120)
            if check:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result

        missing = docker("run", "--rm", image, check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("Set OPENCODE_PASSWORD", missing.stderr)

        # No host mounts, real providers, SSH, shared resources, or persisted sessions.
        with patch.dict(os.environ, {"OPENCODE_PASSWORD": "disposable-smoke-password"}):
            container = docker("create", "-e", "OPENCODE_PASSWORD", "-e", "OPENCODE_DISABLE_MODELS_FETCH=1",
                               "-e", "OLLAMA_HOST=http://127.0.0.1:18765", image).stdout.strip()
        self.addCleanup(lambda: docker("rm", "-f", container, check=False))
        docker("cp", str(agent), container + ":/opt/agent")
        docker("start", container)
        ready = docker("exec", container, "python3", "/opt/harness/docker-health.py", "--wait", check=False)
        logs = docker("logs", container)
        self.assertEqual(ready.returncode, 0, logs.stdout + logs.stderr + ready.stderr)
        version = docker("exec", container, "opencode", "--version").stdout.strip()
        self.assertRegex(version, r"^opencode v2\.\d+\.\d+$")
        # An API command with explicit --server exercises real client authentication.
        result = docker("exec", container, "opencode", "api", "--server", "http://127.0.0.1:4096", "GET", "/api/info")
        self.assertEqual(json.loads(result.stdout)["version"], version.removeprefix("opencode v"))
        plugins = docker("exec", container, "opencode", "api", "--server", "http://127.0.0.1:4096",
                         "GET", "/api/plugin?directory=/workspace")
        for _ in range(10):
            if "background-subagents.js" in plugins.stdout:
                break
            time.sleep(1)
            plugins = docker("exec", container, "opencode", "api", "--server", "http://127.0.0.1:4096",
                             "GET", "/api/plugin?directory=/workspace")
        logs = docker("logs", container)
        configs = docker("exec", container, "opencode", "api", "--server", "http://127.0.0.1:4096",
                         "GET", "/api/config?directory=/workspace")
        documents = [item["info"] for item in json.loads(configs.stdout) if item["type"] == "document"]
        public = next(item for item in documents if "agents" in item)
        self.assertEqual(set(public["agents"]), set(original["agents"]))
        provider, model = original["model"].split("/", 1)
        self.assertEqual(public["model"], {"providerID": provider, "model": model})
        self.assertEqual(public["agents"]["Orchestrator"]["system"], "Disposable prompt resource: system/orchestrator.md")
        self.assertEqual(public["agents"]["build"]["request"], {"body": {"temperature": 0.3}})
        self.assertEqual(public["providers"]["ollama"]["package"], "@opencode/ai/providers/openai-compatible")
        self.assertEqual(public["providers"]["openai"]["models"]["gpt-6-astra"]["limit"]["input"], 320000)
        self.assertEqual(public["compaction"], original["compaction"])
        self.assertEqual(public["agents"]["title"]["model"], {"providerID": "openai", "model": "gpt-5-mini"})
        self.assertEqual(public["permissions"], [{"action": "*", "resource": "*", "effect": "allow"}])
        self.assertIn({"action": "subagent", "resource": "*", "effect": "allow"}, public["agents"]["Orchestrator"]["permissions"])
        self.assertIn({"action": "shell", "resource": "*", "effect": "allow"}, public["agents"]["Orchestrator"]["permissions"])
        self.assertIn({"action": "edit", "resource": "*", "effect": "deny"}, public["agents"]["explore"]["permissions"])
        agents = docker("exec", container, "opencode", "api", "--server", "http://127.0.0.1:4096",
                        "GET", "/api/agent?directory=/workspace")
        registered = {item["id"]: item for item in json.loads(agents.stdout)["data"]}
        self.assertTrue(set(original["agents"]) - {"title"} <= registered.keys(), agents.stdout)
        for name, definition in original["agents"].items():
            if "system" not in definition:
                continue
            self.assertEqual(registered[name]["mode"], definition["mode"])
            self.assertTrue(registered[name]["system"].startswith("Disposable prompt resource: "), name)
        links = docker("exec", container, "python3", "-c",
                       "from pathlib import Path; import json; print(json.dumps({n:str(Path('/home/opencode/.config/opencode',n).readlink()) for n in ['system','commands','skills']}))")
        self.assertEqual(json.loads(links.stdout), {name: "/opt/agent/" + name for name in ("system", "commands", "skills")})
        self.assertNotIn("first-prompt-title", plugins.stdout)
        self.assertNotIn("kdco-", plugins.stdout)
        background = next(item for item in json.loads(plugins.stdout)["data"]
                          if item.get("id") == "background-subagents")
        self.assertEqual(background["state"], {"status": "active"})
        # Assert exact copied source bytes, not just a matching plugin ID. No
        # arbitrary config trees, helpers, or installed dependencies are copied.
        manifest = docker("exec", container, "python3", "-c",
                          "import hashlib,json,pathlib,sys; root=pathlib.Path('/home/opencode/.config/opencode'); "
                          "print(json.dumps({name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in json.loads(sys.argv[1])}))",
                          json.dumps(IMAGE_ASSETS))
        self.assertEqual(json.loads(manifest.stdout), {
            name: hashlib.sha256((ROOT / ".opencode/config" / name).read_bytes()).hexdigest()
            for name in IMAGE_ASSETS})
        # Capture a real outbound model request against a loopback stub, never
        # an external provider. This exercises context hooks in the real engine.
        docker("exec", "-d", container, "python3", "-c", '''
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import json
class Stub(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        Path('/tmp/background-model-request.json').write_bytes(body)
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        chunk = {'id': 'disposable', 'object': 'chat.completion.chunk', 'created': 1,
                 'model': 'qwen2.5-coder:32b', 'choices': [{'index': 0,
                 'delta': {'role': 'assistant', 'content': 'Disposable response'}, 'finish_reason': None}]}
        self.wfile.write(('data: ' + json.dumps(chunk) + '\\n\\n').encode())
        chunk['choices'][0].update(delta={}, finish_reason='stop')
        self.wfile.write(('data: ' + json.dumps(chunk) + '\\n\\ndata: [DONE]\\n\\n').encode())
    def log_message(self, *args):
        pass
HTTPServer(('127.0.0.1', 18765), Stub).serve_forever()
''')
        context = docker("exec", container, "python3", "-c", '''
import base64, json, os, time, urllib.error, urllib.request
from pathlib import Path
auth = 'Basic ' + base64.b64encode(('opencode:' + os.environ['OPENCODE_PASSWORD']).encode()).decode()
def api(path, body=None):
    request = urllib.request.Request('http://127.0.0.1:4096' + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Authorization': auth, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode()) from error
session = api('/api/session', {'agent': 'build', 'model': {
    'providerID': 'ollama', 'id': 'qwen2.5-coder:32b'}})['data']
api('/api/session/' + session['id'] + '/prompt', {'text': 'Reply with a short acknowledgement.'})
capture = Path('/tmp/background-model-request.json')
deadline = time.monotonic() + 20
while not capture.exists() and time.monotonic() < deadline:
    time.sleep(0.1)
if not capture.exists():
    raise RuntimeError('Loopback model stub received no request: ' + json.dumps(api('/api/session/' + session['id'] + '/message')))
print(capture.read_text())
''')
        self.assertIn("native subagent policy", context.stdout)
        self.assertIn("background execution is the default", context.stdout)
        self.assertIn("background:false", context.stdout)
        rejected = docker("exec", "-e", "OPENCODE_PASSWORD=wrong", container, "opencode", "api", "--server",
                          "http://127.0.0.1:4096", "GET", "/api/info", check=False)
        self.assertNotEqual(rejected.returncode, 0)
        # TUI gets config before rendering. Bound lifetime, no provider calls.
        docker("exec", "-t", container, "timeout", "12", "bash", "/opt/harness/docker-client.sh", check=False)
        cli = docker("exec", container, "python3", "-c",
                     "import pathlib; print(pathlib.Path('/home/opencode/.config/opencode/cli.json').read_text())")
        migrated = json.loads(cli.stdout)
        self.assertEqual(migrated["theme"]["name"], "opencode")
        self.assertIn("./tui-plugins/session-title", migrated["plugins"])
        processes = docker("top", container, "-eo", "pid,args").stdout
        self.assertEqual(processes.count("opencode serve"), 1, processes)
        self.assertNotIn("serve --service", processes)
        self.assertNotIn("disposable-smoke-password", docker("logs", container).stdout)
        self.assertEqual(docker("exec", container, "id", "-u").stdout.strip(), "1000")


if __name__ == "__main__":
    unittest.main()
