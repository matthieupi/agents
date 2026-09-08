#!/usr/bin/env python3
"""Inspect-only contract: Docker JSON on stdin; never print env or secret state.

owned emits an immutable ID; reuse emits nothing and checks current configuration.
This is production lifecycle validation, not a test harness.
"""
import json
import os
import re
import sys
from decimal import Decimal


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def main() -> None:
    items = json.load(sys.stdin)
    require(isinstance(items, list) and len(items) == 1, "expected exactly one container")
    container = items[0]
    config = container["Config"]
    labels = config.get("Labels") or {}
    env = os.environ
    require(labels.get("dev.xmist.agents.component") == "omp", "not labeled OMP")
    require(labels.get("dev.xmist.agents.owner") == env["OMP_COMPONENT_DIR"], "different component checkout owner")
    workspace = labels.get("dev.xmist.agents.workspace", "")
    require(workspace.startswith("/"), "missing absolute workspace label")
    identifier = container["Id"]
    require(re.fullmatch(r"[0-9a-f]{64}", identifier) is not None, "invalid container ID")
    if sys.argv[1] == "owned":
        print(identifier)
        return
    require(sys.argv[1] == "reuse", "unknown validation mode")
    require(workspace == env["WORKSPACE_PATH"], "workspace label mismatch")
    require(config["Image"] == env["OMP_IMAGE"], "image reference mismatch")
    require(container["Image"] == env["OMP_EXPECTED_IMAGE_ID"], "image was rebuilt; explicit recreation required")
    require(config["User"] == f'{env["OMP_UID"]}:{env["OMP_GID"]}', "runtime UID/GID mismatch")
    require(config["WorkingDir"] == "/workspace", "working directory mismatch")
    actual_env = dict(item.split("=", 1) for item in config.get("Env", []) if "=" in item)
    require(actual_env.get("HOME") == "/home/omp", "HOME mismatch")
    require(actual_env.get("OMP_PERSONA") == env["OMP_PERSONA"], "persona mismatch")
    require(not any(actual_env.get(key) for key in (
        "PI_CONFIG_DIR", "PI_CODING_AGENT_DIR", "OMP_PROFILE", "PI_PROFILE",
        "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "DOCKER_HOST",
    )), "unexpected state/profile/Docker environment override")
    expected = {
        "/workspace": (env["WORKSPACE_PATH"], True),
        "/home/omp/.omp": (env["OMP_STATE_DIR"], True),
        "/opt/agent": (env["OMP_AGENT_DIR"], True),
        "/opt/harness/init.sh": (env["OMP_COMPONENT_DIR"] + "/init.sh", False),
        "/home/omp/.ssh": (env["SSH_DIR_PATH"], False),
        "/home/omp/.gitconfig": (env["GITCONFIG_PATH"], False),
    }
    mounts = container.get("Mounts", [])
    require(len(mounts) == len(expected), "unexpected mount count")
    for mount in mounts:
        destination = mount["Destination"]
        require(destination in expected, "unexpected mount destination")
        require(mount["Type"] == "bind", "expected bind mount")
        require((mount["Source"], mount["RW"]) == expected.pop(destination), "mount source or access mismatch")
    require(not expected, "missing mounts")
    host = container["HostConfig"]
    require(not host.get("Privileged"), "privileged container refused")
    require(not host.get("CapAdd") and not host.get("Devices"), "extra capabilities/devices refused")
    require(host.get("PidMode", "") == "" and host.get("IpcMode") != "host", "host namespaces refused")
    require(not host.get("PortBindings"), "published ports refused")
    require(set(container["NetworkSettings"]["Networks"]) == {env["OMP_NETWORK"]}, "network mismatch")
    memory = re.fullmatch(r"([0-9]+)([bkmg]?)", env["OMP_MEMORY"].lower())
    require(memory is not None, "OMP_MEMORY must be a positive integer with optional b/k/m/g suffix")
    size = int(memory[1]) * 1024 ** {"": 0, "b": 0, "k": 1, "m": 2, "g": 3}[memory[2]]
    require(size > 0 and host["Memory"] == size, "memory limit mismatch")
    cpus = Decimal(env["OMP_CPUS"])
    require(cpus.is_finite() and cpus > 0 and host["NanoCpus"] == int(cpus * 10**9), "CPU limit mismatch")
    idle = ["bash", "-c", "/opt/harness/init.sh && exec sleep infinity"]
    require(config.get("Entrypoint") == idle or (
        not config.get("Entrypoint") and config.get("Cmd") == idle
    ), "startup command mismatch")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, IndexError, ArithmeticError):
        # Never include input JSON or environment in diagnostics.
        print("[omp] Container ownership/configuration contract failed; inspect its non-secret metadata privately.", file=sys.stderr)
        sys.exit(1)
