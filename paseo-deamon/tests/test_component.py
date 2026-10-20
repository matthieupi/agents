import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT.parent
spec = importlib.util.spec_from_file_location("paseo_entry", ROOT / "entry.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class ComponentTests(unittest.TestCase):
    def test_native_auth_validation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            path = Path(directory) / "config.json"
            config = json.loads((ROOT / "config.example.json").read_text())
            path.write_text(json.dumps(config))
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                entry.validate_config(path)
            # Syntax fixture only: does not prove bcrypt verification/authentication.
            config["daemon"]["auth"]["password"] = "$2b$12$" + "a" * 53
            path.write_text(json.dumps(config))
            self.assertEqual(entry.validate_config(path), config)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                entry.validate_config(path)
            path.chmod(0o600)
            link = Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                entry.validate_config(link)

    def test_mount_mapping_and_real_prompt_parity(self):
        service = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]["paseo"]
        mounts = {m["target"]: m for m in service["volumes"]}
        prefix = "/home/paseo/.config/opencode/"
        config = json.loads((AGENTS / "opencode/.opencode/config/opencode.json").read_text())
        for name in ("commands", "skills", "system", "gsd"):
            mount = mounts[prefix + name]
            self.assertEqual(mount["source"], "${AGENT_RESOURCES_PATH:?set managed agent tree}/" + name)
            self.assertTrue(mount["read_only"])
            self.assertTrue((AGENTS / "agent" / name).is_dir())
        for agent in config["agents"].values():
            reference = re.fullmatch(r"\{file:\./(.+)\}", agent.get("system", ""))
            if reference:
                resource = reference[1]
                self.assertIn(prefix + resource.split("/")[0], mounts)
                self.assertTrue((AGENTS / "agent" / resource).is_file(), resource)

    def test_confinement(self):
        compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
        service = compose["services"]["paseo"]
        self.assertTrue(service["read_only"])
        self.assertEqual(service["cap_drop"], ["ALL"])
        self.assertEqual(service["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(service["pull_policy"], "never")
        self.assertEqual(service["networks"], ["execution"])
        self.assertFalse(compose["networks"]["execution"]["internal"])
        self.assertIn("127.0.0.1", service["ports"][0])
        for forbidden in ("privileged", "devices", "pid", "network_mode"):
            self.assertNotIn(forbidden, service)
        self.assertNotIn("PASEO_PASSWORD", service["environment"])
        writable = []
        for mount in service["volumes"]:
            self.assertFalse(mount["bind"]["create_host_path"])
            self.assertNotIn("sock", mount["target"])
            if not mount.get("read_only", False):
                writable.append(mount["target"])
        self.assertEqual(writable, ["/workspace", "/state/paseo", "/state/provider"])

    def test_maintained_installer_and_no_startup_install(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("source /opt/opencode/native-contract.sh", dockerfile)
        self.assertIn("install_runtime", dockerfile)
        self.assertNotIn("npm install", dockerfile)
        self.assertIn("@opencode/cli@latest", dockerfile)
        self.assertIn(".runtime/node_modules/@opencode/cli/package.json", dockerfile)
        self.assertIn(".runtime/.native-install.json", dockerfile)
        self.assertIn('r.requested!=="latest"', dockerfile)
        self.assertIn('"opencode v"+p.version', dockerfile)
        self.assertIn("/opt/opencode-install.json", dockerfile)
        self.assertIn('verify_runtime "$OPENCODE_PREFIX" "$OPENCODE_HOME"', dockerfile)
        self.assertIn('isolated_runtime "$OPENCODE_PREFIX" "$OPENCODE_HOME" --version', dockerfile)
        for forbidden in ("OPENCODE_VERSION", "publish-plugins.mjs", "kdco", "opencode-ai"):
            self.assertNotIn(forbidden, dockerfile)
            self.assertNotIn(forbidden, (ROOT / "Dockerfile.dockerignore").read_text())
        # Assert the reused callable still installs the intended scoped package locally.
        installer = (AGENTS / "opencode/scripts/entrypoint.sh").read_text().split("install_runtime() (", 1)[1]
        self.assertIn('"@opencode/cli@latest"', installer)
        self.assertIn('--prefix "$stage/runtime"', installer)
        self.assertNotIn("publish-plugins.mjs", installer)
        for line in dockerfile.splitlines():
            if line.startswith("COPY "):
                self.assertTrue((AGENTS / line.split()[-2]).is_file(), line)
        self.assertIn('getent passwd 1000', dockerfile)
        self.assertIn('usermod --login paseo "$runtime_user"', dockerfile)
        self.assertIn('usermod --home /home/paseo paseo', dockerfile)
        self.assertNotIn("/home/runner", dockerfile)
        startup = (ROOT / "entry.py").read_text()
        for forbidden in ("npm", "npx", "docker", "install_runtime", "opencode serve"):
            self.assertNotIn(forbidden, startup)
        self.assertIn("os.execvp", startup)
        self.assertNotIn("kdco", startup.lower())
        self.assertNotIn("copytree", startup)

    def test_v2_assets_are_explicit_and_read_only(self):
        service = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]["paseo"]
        prefix = "/home/paseo/.config/opencode/"
        mounts = {m["target"]: m for m in service["volumes"]}
        assets = {
            "cli.json": "${OPENCODE_CLI_CONFIG_PATH:?set managed cli.json}",
            "plugins/first-prompt-title.js": "${OPENCODE_PLUGINS_PATH:?set canonical V2 plugins directory}/first-prompt-title.js",
            "plugins/background-subagents.js": "${OPENCODE_PLUGINS_PATH:?set canonical V2 plugins directory}/background-subagents.js",
            "tui-plugins/session-title.mjs": "${OPENCODE_TUI_PLUGINS_PATH:?set canonical V2 tui-plugins directory}/session-title.mjs",
            "tui-plugins/session-title/tui.js": "${OPENCODE_TUI_PLUGINS_PATH:?set canonical V2 tui-plugins directory}/session-title/tui.js",
        }
        for relative, source in assets.items():
            self.assertEqual(mounts[prefix + relative]["source"], source)
            self.assertTrue(mounts[prefix + relative]["read_only"])
            self.assertTrue((AGENTS / "opencode/.opencode/config" / relative).is_file())
        self.assertNotIn(prefix + "plugins", mounts)  # No stale wrapper directory exposure.
        self.assertNotIn(prefix + "tui.json", mounts)
        self.assertNotIn("OPENCODE_VERSION", service["build"]["args"])
        cli = json.loads((AGENTS / "opencode/.opencode/config/cli.json").read_text())
        self.assertIn("./tui-plugins/session-title", cli["plugins"])

    def test_paseo_home_mapping_and_volume_suppression(self):
        compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
        service = compose["services"]["paseo"]
        owner = "uid=${PASEO_UID:-1000},gid=${PASEO_GID:-1000}"
        self.assertIn("/home/paseo:rw,nosuid,nodev,noexec,size=1m,mode=0700," + owner, service["tmpfs"])
        self.assertIn("/home/paseo/.config/opencode:rw,nosuid,nodev,noexec,size=1m,mode=0700," + owner,
                      service["tmpfs"])
        targets = {mount["target"] for mount in service["volumes"]}
        self.assertIn("/home/paseo/.ssh", targets)
        self.assertIn("/home/paseo/.gitconfig", targets)
        self.assertFalse(any("/home/runner" in target for target in targets))

    @unittest.skipUnless(
        shutil.which("docker") and subprocess.run(
            ["docker", "compose", "version"], capture_output=True, timeout=30
        ).returncode == 0,
        "Docker Compose unavailable: no real rendering evidence",
    )
    def test_real_compose_render(self):
        env = dict(os.environ)
        for name in re.findall(r"\$\{([A-Z_]+):\?", (ROOT / "compose.yaml").read_text()):
            env[name] = "/tmp/opencode/fixture-" + name.lower()
        env.update(PASEO_IMAGE="paseo:test", PASEO_BASE="ghcr.io/getpaseo/paseo:0.12.0@sha256:" + "a" * 64,
                   PASEO_VERSION="0.12.0",
                   PASEO_UID="1000", PASEO_GID="1000", PASEO_BIND_ADDRESS="127.0.0.1",
                   PASEO_PORT="6767")
        result = subprocess.run(["docker", "compose", "-f", str(ROOT / "compose.yaml"),
                                 "config", "--format", "json"], env=env, check=True,
                                capture_output=True, text=True, timeout=30)
        service = json.loads(result.stdout)["services"]["paseo"]
        self.assertEqual(service["user"], "1000:1000")
        self.assertEqual(service["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(service["build"]["context"], str(AGENTS))
        self.assertEqual(service["build"]["dockerfile"], "paseo-deamon/Dockerfile")


if __name__ == "__main__":
    unittest.main()
