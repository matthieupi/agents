"""Offline contracts for retained service templates, never deployed state."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from typing import Any

try:
    from jinja2 import Environment, StrictUndefined  # type: ignore[import-not-found]
    import yaml  # type: ignore[import-not-found]
except ImportError:
    Environment = None
    StrictUndefined = None
    yaml = None


ROOT = Path(__file__).resolve().parents[2]


def compose_config(directory: Path) -> subprocess.CompletedProcess[str]:
    """Use an explicit standalone Compose binary or the default Docker plugin."""
    override = os.environ.get("DOCKER_COMPOSE_BINARY")
    executable = shutil.which(override or "docker")
    if not executable:
        if override:
            raise AssertionError(f"DOCKER_COMPOSE_BINARY is not executable: {override}")
        raise unittest.SkipTest("Docker unavailable; set DOCKER_COMPOSE_BINARY=/absolute/path/to/docker-compose")
    command = [executable] if override else [executable, "compose"]
    result = subprocess.run(
        command + ["--project-directory", str(directory), "--env-file", "/dev/null",
                   "-f", str(directory / "compose.yaml"), "config", "--format", "json"],
        env={"PATH": os.environ["PATH"], "HOME": str(directory),
             "DOCKER_CONFIG": str(directory / "docker")},
        capture_output=True, text=True, timeout=30,
    )
    if not override and result.returncode != 0 and any(marker in result.stderr.lower() for marker in (
        "unknown flag: --project-directory", "unknown command: docker compose",
        "'compose' is not a docker command", "unknown command \"compose\"",
    )):
        raise unittest.SkipTest(
            "Default Docker CLI cannot run Compose config; set "
            "DOCKER_COMPOSE_BINARY=/absolute/path/to/docker-compose. " + result.stderr.strip()
        )
    return result


def image_copies(product: str) -> dict[str, Path]:
    """Resolve the public COPY closure, including the finite named context."""
    copies = {}
    source = (ROOT / product / "Dockerfile.service").read_text()
    for line in source.splitlines():
        if not line.startswith("COPY "):
            continue
        tokens = shlex.split(line)[1:]
        context = ROOT / product
        while tokens[0].startswith("--"):
            flag = tokens.pop(0)
            if flag.startswith("--from="):
                if flag.split("=", 1)[1] not in ("opencode-inputs", "opencode_inputs"):
                    context = None  # External Docker CLI stage, not a public input.
                else:
                    context = ROOT / "opencode"
        if context is None:
            continue
        destination = tokens[-1]
        for relative in tokens[:-1]:
            target = destination + Path(relative).name if destination.endswith("/") else destination
            copies[target] = context / relative
    return copies


class ServiceTests(unittest.TestCase):
    def test_standalone_compose_binary_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            standalone = directory / "standalone-compose"
            standalone.write_text('#!/usr/bin/python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n')
            standalone.chmod(0o755)
            with patch.dict(os.environ, {"DOCKER_COMPOSE_BINARY": str(standalone)}):
                result = compose_config(directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [
                "--project-directory", tmp, "--env-file", "/dev/null", "-f",
                str(directory / "compose.yaml"), "config", "--format", "json",
            ])

    def test_unsupported_default_compose_skips_actionably(self):
        unsupported = subprocess.CompletedProcess([], 125, "", "unknown flag: --project-directory")
        with patch.dict(os.environ, {"DOCKER_COMPOSE_BINARY": ""}), \
                patch("shutil.which", return_value="/fixture/docker"), \
                patch("subprocess.run", return_value=unsupported):
            with self.assertRaisesRegex(unittest.SkipTest, "DOCKER_COMPOSE_BINARY="):
                compose_config(Path("/fixture"))
        invalid = subprocess.CompletedProcess([], 1, "", "services.opencode contains invalid property")
        with patch.dict(os.environ, {"DOCKER_COMPOSE_BINARY": ""}), \
                patch("shutil.which", return_value="/fixture/docker"), \
                patch("subprocess.run", return_value=invalid):
            self.assertEqual(compose_config(Path("/fixture")).returncode, 1)
        with patch.dict(os.environ, {"DOCKER_COMPOSE_BINARY": "/fixture/standalone"}), \
                patch("shutil.which", return_value="/fixture/standalone"), \
                patch("subprocess.run", return_value=unsupported):
            self.assertEqual(compose_config(Path("/fixture")).returncode, 125)

    def test_shared_publisher_copy_closure(self):
        wrapper = (ROOT / "opencode/service-entrypoint.sh").read_text().replace("\\\n", " ")
        commands = [shlex.split(line) for line in wrapper.splitlines()
                    if line.strip().startswith("node ")]
        self.assertEqual(len(commands), 1)
        publisher = commands[0][1]
        self.assertEqual(commands[0][2:],
                         ["config", "/opt/opencode-defaults", "/opt/agent", "$OPENCODE_CONFIG_DIR"])
        for product in ("opencode", "paseo-deamon", "paperclip-daemon"):
            with self.subTest(product=product):
                copies = image_copies(product)
                self.assertIn(publisher, copies, "Shared entrypoint's publisher must be installed")
                self.assertEqual(copies[publisher], ROOT / "opencode/scripts/publish-plugins.mjs")
                self.assertEqual(copies["/opt/opencode/service-entrypoint.sh"],
                                 ROOT / "opencode/service-entrypoint.sh")

    def test_daemon_startup_wrappers_reach_installed_publisher(self):
        for product in ("paseo-deamon", "paperclip-daemon"):
            with self.subTest(product=product), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                # Model only the Dockerfile's actual COPY destinations. Rebase
                # absolute /opt paths into a disposable filesystem, not host /opt.
                copies = image_copies(product)
                for destination, source in copies.items():
                    target = root / destination.lstrip("/")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if source.name == "publish-plugins.mjs":
                        target.write_text('import {appendFileSync} from "node:fs";\n'
                                          'appendFileSync(process.env.EVENTS, JSON.stringify(process.argv.slice(2))+"\\n");\n')
                    elif source.name == "entry.py":
                        target.write_text('import os\nfrom pathlib import Path\n'
                                          'Path(os.environ["DONE"]).write_text("paseo-deamon")\n')
                    else:
                        text = source.read_text().replace("/opt/", str(root / "opt") + "/")
                        text = text.replace("/usr/sbin/runuser", str(root / "usr/sbin/runuser"))
                        target.write_text(text)
                for directory in ("opt/agent", "opt/opencode-defaults", "home/agent"):
                    (root / directory).mkdir(parents=True, exist_ok=True)
                if product == "paperclip-daemon":
                    # Stub account switching and final sshd only. Run the real
                    # Paperclip -> shared wrapper chain; never start a server.
                    bindir = root / "usr/sbin"
                    bindir.mkdir(parents=True)
                    runuser = bindir / "runuser"
                    runuser.write_text('#!/bin/bash\n[[ "$1" == -u && "$3" == -- ]] || exit 90\nshift 3\nexec "$@"\n')
                    runuser.chmod(0o755)
                    sshd = bindir / "sshd"
                    sshd.write_text('#!/bin/bash\nprintf paperclip-daemon > "$DONE"\n')
                    sshd.chmod(0o755)
                dockerfile = (ROOT / product / "Dockerfile.service").read_text()
                entry = next(json.loads(line.removeprefix("ENTRYPOINT ")) for line in dockerfile.splitlines()
                             if line.startswith("ENTRYPOINT "))
                command = next(json.loads(line.removeprefix("CMD ")) for line in dockerfile.splitlines()
                               if line.startswith("CMD "))
                self.assertEqual(entry[:2], ["/usr/bin/tini", "--"])
                argv = [str(root / arg.lstrip("/")) if arg.startswith(("/opt/", "/usr/sbin/")) else arg
                        for arg in entry[2:] + command]
                result = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                                        env={"PATH": os.environ["PATH"], "HOME": str(root / "home/agent"),
                                             "USER": "agent", "OPENCODE_CONFIG_DIR": str(root / "home/agent/.config/opencode"),
                                             "EVENTS": str(root / "events"), "DONE": str(root / "done")})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root / "done").read_text(), product)
                events = [json.loads(line) for line in (root / "events").read_text().splitlines()]
                self.assertEqual(events, [["config", str(root / "opt/opencode-defaults"),
                                          str(root / "opt/agent"), str(root / "home/agent/.config/opencode")]])

    def test_native_installer_and_finite_inputs(self):
        for product in ("paseo-deamon", "paperclip-daemon"):
            dockerfile = (ROOT / product / "Dockerfile.service").read_text()
            self.assertNotIn("OPENCODE_VERSION", dockerfile)
            self.assertNotIn("kdco", dockerfile.lower())
            self.assertIn("; install_runtime; verify_runtime", dockerfile)
            self.assertIn('isolated_runtime "$OPENCODE_PREFIX" "$OPENCODE_HOME" --version', dockerfile)
            self.assertIn("/opt/opencode/component/.runtime", dockerfile)
            self.assertIn("/opt/opencode-install.json", dockerfile)
            copies = [line for line in dockerfile.splitlines() if "COPY --from=opencode" in line]
            self.assertEqual(len(copies), 3)
            self.assertTrue(all(any(source in line for source in (
                "scripts/entrypoint.sh", "scripts/publish-plugins.mjs", "service-entrypoint.sh"
            )) for line in copies))
            self.assertNotIn("OPENCODE_VERSION", (ROOT / product / "docker-compose.j2").read_text())
        paseo = ROOT / "paseo-deamon"
        for name in ("Dockerfile", "Dockerfile.service"):
            source = (paseo / name).read_text()
            self.assertIn('RUN node /opt/paseo-component/verify-paseo.mjs "$PASEO_VERSION"', source)
            self.assertIn("; install_runtime; verify_runtime", source)
        self.assertEqual((paseo / "Dockerfile.service.dockerignore").read_text().splitlines(),
                         ["**", "!entry.py", "!verify-paseo.mjs"])

    @unittest.skipUnless(Environment, "Jinja2/PyYAML unavailable; no dependencies installed by tests")
    def test_rendered_native_compose_contracts(self):
        assert Environment is not None
        assert yaml is not None
        env = Environment(undefined=StrictUndefined)
        env.filters["to_json"] = json.dumps
        # Public synthetic paths only. No credentials, host account or live state.
        values: dict[str, Any] = dict(
            agent_uid=1200, agent_gid=1300, agent_account="agent", agent_home="/home/agent",
            agent_workspace="/workspace", agent_docker_gid=1400,
            agent_docker_socket="/run/docker.sock", ansible_host="192.0.2.10",
            docker_service_path="/fixture/service", opencode_config_source_path="/fixture/public",
            agent_publication={"backend_network": {"name": "fixture-backends"}},
            opencode_backend_password="fixture-only-not-a-real-password",
            service_config=dict(image="ghcr.io/getpaseo/paseo:0.12.0@sha256:" + "a" * 64,
                                version="0.12.0", pi_version="0.85.1",
                                opencode_build_context="/fixture/public-inputs",
                                pids_limit=512, memory_limit="4g", cpus=2,
                                upstream_port=16767, container_port=6767,
                                host_port=2222, state_path="/fixture/state",
                                allowed_origins=["https://fixture.example.test"]),
        )
        expected_command = ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "6767",
                            "--cors", "https://fixture.example.test"]
        for product, socket in (("paseo-deamon", False), ("paperclip-daemon", False),
                                ("paperclip-daemon", True), ("opencode", False), ("opencode", True)):
            with self.subTest(product=product, socket=socket), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                values["docker_access"] = [product] if socket else []
                rendered = env.from_string((ROOT / product / "docker-compose.j2").read_text()).render(**values)
                self.assertNotIn("OPENCODE_VERSION", rendered)
                self.assertNotIn("--mdns", rendered)
                self.assertIn("/opt/opencode-defaults", rendered)
                self.assertIn("/opt/agent", rendered)
                template_service = yaml.safe_load(rendered)["services"][product]
                public_mounts = {mount["target"]: mount for mount in template_service["volumes"]}
                for target in ("/opt/agent", "/opt/opencode-defaults"):
                    self.assertIs(public_mounts[target]["bind"]["create_host_path"], False)
                compose = directory / "compose.yaml"
                compose.write_text(rendered)
                rendered_env = env.from_string((ROOT / product / "env.j2").read_text()).render(**values)
                (directory / ".env").write_text(rendered_env)
                if product == "opencode":
                    self.assertEqual(template_service["command"], expected_command)
                    self.assertEqual(template_service["build"]["args"], {"AGENT_UID": "1200", "AGENT_GID": "1300"})
                    self.assertIn("OPENCODE_PASSWORD=" + values["opencode_backend_password"], rendered_env.splitlines())
                    self.assertNotIn("OPENCODE_VERSION", rendered_env)
                    health = template_service["healthcheck"]["test"]
                    self.assertEqual(health, ["CMD", "node", "/opt/opencode/backend-health.mjs", "6767"])
                    self.assertEqual(image_copies(product)[health[2]], ROOT / "opencode/backend-health.mjs")
                result = compose_config(directory)
                self.assertEqual(result.returncode, 0, result.stderr)
                service = json.loads(result.stdout)["services"][product]
                mounts = {mount["target"]: mount for mount in service["volumes"]}
                for target in ("/opt/agent", "/opt/opencode-defaults"):
                    self.assertTrue(mounts[target]["read_only"])
                    # Compose omits false-valued fields in normalized JSON.
                    self.assertFalse(mounts[target]["bind"].get("create_host_path", False))
                self.assertEqual("/run/docker.sock" in mounts, socket)
                self.assertNotIn("privileged", service)
                if product == "paseo-deamon":
                    self.assertEqual(service["user"], "1200:1300")
                    self.assertTrue(service["read_only"])
                    self.assertEqual(service["cap_drop"], ["ALL"])
                    self.assertEqual(service["ports"][0]["host_ip"], "127.0.0.1")
                    self.assertIn("opencode-inputs", service["build"]["additional_contexts"])
                    self.assertNotIn("/home/agent", mounts)
                elif product == "paperclip-daemon":
                    self.assertEqual(service["user"], "0:0")
                    self.assertIn("opencode_inputs", service["build"]["additional_contexts"])
                    self.assertTrue(mounts["/run/paperclip-ssh"]["read_only"])
                    self.assertTrue(mounts["/etc/paperclip-authorized_keys"]["read_only"])
                    self.assertNotIn("SYS_ADMIN", service["cap_add"])
                    self.assertEqual(service["build"]["args"].get("AGENT_DOCKER_GID"),
                                     "1400" if socket else None)
                else:
                    self.assertEqual(service["user"], "1200:1300")
                    self.assertEqual(service["command"], expected_command)
                    self.assertEqual(service["environment"]["OPENCODE_PASSWORD"], values["opencode_backend_password"])
                    self.assertNotIn("OPENCODE_SERVER_PASSWORD", service["environment"])
                    self.assertEqual(service["healthcheck"]["test"], template_service["healthcheck"]["test"])
                    self.assertEqual(service["ports"][0]["host_ip"], "127.0.0.1")
                    self.assertEqual(service.get("group_add"), ["1400"] if socket else None)


if __name__ == "__main__":
    unittest.main()
