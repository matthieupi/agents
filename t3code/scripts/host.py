#!/usr/bin/env python3
"""Local Linux Docker control plane. Profiles are private JSON data, never shell."""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import pwd
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


COMPONENT = Path(__file__).resolve().parent.parent
COMPOSE = COMPONENT / "docker-compose.yml"
BUILD_ARGS = (
    "NODE_IMAGE", "BUILDER_IMAGE", "NODE_VERSION", "T3_VERSION", "T3_INTEGRITY",
    "PACKAGE_LOCK_SHA256", "PREPARED_BASES_REVIEWED", "INSTALL_HOOKS_REVIEWED",
)
NAME = re.compile(r"t3code-[1-9][0-9]*-[a-z0-9-]{1,24}-[a-f0-9]{16}")
IMAGE = re.compile(r"(?:sha256:[a-f0-9]{64}|[a-zA-Z0-9][a-zA-Z0-9._:/-]*@sha256:[a-f0-9]{64})")
DOCKER_ENDPOINT = None


def fail(message):
    raise RuntimeError(message)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def recorded_path(value):
    if not isinstance(value, (str, Path)) or not value or any(ord(c) < 32 or c == '$' for c in str(value)):
        fail("An explicit canonical directory without control characters or '$' is required.")
    path = Path(value)
    if not path.is_absolute() or os.path.normpath(str(path)) != str(path):
        fail("Recorded directory must be absolute and normalized.")
    return path


def directory(value, private=False):
    """Require existing canonical directories, including symlink-free ancestors."""
    path = recorded_path(value)
    if not path.is_absolute() or str(path.resolve(strict=True)) != str(path):
        fail("Directory must be absolute, canonical and symlink-free.")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            fail("Symlinked path components are not supported.")
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode):
        fail("Expected an existing directory.")
    if private and (info.st_uid != os.getuid() or info.st_gid != os.getgid() or info.st_mode & 0o077):
        fail("Private state must belong to the current UID/GID and have mode 0700; reconcile offline.")
    return path


def private_file(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            info.st_uid != os.getuid() or info.st_gid != os.getgid() or info.st_mode & 0o077):
        fail("Unsafe private metadata file; reconcile offline without following links.")


def registry():
    return directory(os.environ.get("T3CODE_STATE_ROOT"), private=True)


def narrow_mounts(workspace, agent):
    # Do not let a nominal workspace/resource mount become the host home/root.
    home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    for path in (workspace, agent):
        if path == home or path in home.parents:
            fail("Workspace/shared resources must not mount the operator's entire home or its ancestors.")


@contextlib.contextmanager
def locked(root):
    fd = os.open(root / ".lifecycle.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        private_file(root / ".lifecycle.lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd
    finally:
        os.close(fd)


def execute(args, capture=False, env=None):
    # Never echo full subprocess argv: administrative arguments may be sensitive.
    if args[0] == "docker" and DOCKER_ENDPOINT is not None:
        env = dict(os.environ if env is None else env)
        # Freeze the inspected local endpoint; do not inherit a remote builder.
        for key in ("DOCKER_CONTEXT", "DOCKER_HOST", "BUILDX_BUILDER", "BUILDKIT_HOST"):
            env.pop(key, None)
    result = subprocess.run(args, env=env, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None, check=False)
    if result.returncode:
        fail("Command failed; instance/state retained. Inspect privately before retrying.")
    return result.stdout if capture else None


def docker_prefix():
    return ["docker", "--host", DOCKER_ENDPOINT] if DOCKER_ENDPOINT else ["docker"]


def docker(*args, capture=False):
    return execute([*docker_prefix(), *args], capture=capture)


def local_daemon():
    global DOCKER_ENDPOINT
    # Bind paths refer to this machine, never an implicit remote Docker endpoint.
    endpoint = os.environ.get("DOCKER_HOST", "")
    if os.environ.get("DOCKER_CONTEXT") or not endpoint:
        contexts = json.loads(docker("context", "inspect", capture=True))
        endpoint = contexts[0]["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith("unix://"):
        fail("Only a local Unix-socket Docker endpoint is supported; remote contexts are refused.")
    DOCKER_ENDPOINT = endpoint


def operator():
    if os.getuid() == 0 or os.getgid() == 0:
        fail("Run as the workstation's non-root operator, never via sudo.")
    local_daemon()


def profile_hash(profile):
    return digest(encode(profile))


def validate_profile(profile, root, name, resources=True):
    expected = {"schema", "name", "uid", "gid", "workspace", "workspace_id", "home",
                "agent", "image", "port", "cpus", "memory", "provider", "compose_sha256"}
    if not isinstance(profile, dict) or set(profile) != expected or profile["schema"] != 1:
        fail("Unknown profile schema; do not source or auto-migrate metadata.")
    if not NAME.fullmatch(name) or profile["name"] != name:
        fail("Invalid instance identity.")
    if profile["uid"] != os.getuid() or profile["gid"] != os.getgid():
        fail("Instance belongs to a different account.")
    # Stop/remove/status must remain usable if a former bind source disappears.
    path_check = directory if resources else recorded_path
    workspace = path_check(profile["workspace"])
    agent = path_check(profile["agent"])
    if resources:
        narrow_mounts(workspace, agent)
    if profile["workspace_id"] != digest(str(workspace)) or instance_name(workspace) != name:
        fail("Workspace identity mismatch.")
    if profile["home"] != str(root / name / "home"):
        fail("Instance state path mismatch.")
    directory(root / name, private=True)
    if resources:
        directory(profile["home"], private=True)
    # A workspace/shared resource mount must not expose private profiles or state.
    for a, b in ((root, workspace), (root, agent), (workspace, agent)):
        if a == b or a in b.parents or b in a.parents:
            fail("State, workspace and shared-resource roots must not overlap.")
    settings(profile)
    if not re.fullmatch(r"[a-f0-9]{64}", profile["compose_sha256"]):
        fail("Invalid Compose fingerprint.")


def settings(profile):
    if not IMAGE.fullmatch(profile["image"]):
        fail("T3CODE_IMAGE must be a local sha256 image ID or repository@sha256 digest, not a tag.")
    if profile["provider"] != "none":
        fail("No provider is approved; only T3CODE_PROVIDER=none is implemented.")
    port = str(profile["port"])
    if not re.fullmatch(r"[1-9][0-9]{0,4}", port) or int(port) > 65535:
        fail("Port must be a canonical integer from 1 to 65535.")
    if not re.fullmatch(r"(?:[1-9][0-9]{0,2}|0)(?:\.[0-9]{1,3})?", profile["cpus"]) or float(profile["cpus"]) <= 0:
        fail("CPUs must be a positive decimal, at most three integer/fractional digits.")
    if not re.fullmatch(r"[1-9][0-9]{0,6}[mg]", profile["memory"]):
        fail("Memory must use a positive integer with lowercase m or g units.")


def instance_name(workspace):
    readable = re.sub(r"[^a-z0-9]+", "-", workspace.name.lower()).strip("-")[:24] or "workspace"
    return f"t3code-{os.getuid()}-{readable}-{digest(str(workspace))[:16]}"


def load(root, name, resources=True):
    if not NAME.fullmatch(name):
        fail("Expected an exact managed instance name; wildcards and 'all' are unsupported.")
    directory(root / name, private=True)
    path = root / name / "profile.json"
    private_file(path)
    profile = json.loads(path.read_text())
    validate_profile(profile, root, name, resources=resources)
    return profile


def write_private(target, profile):
    if target.exists() or target.is_symlink():
        private_file(target)
    fd, path = tempfile.mkstemp(prefix=".profile-", dir=target.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(encode(profile) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(path, target)
        fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def save(root, profile):
    write_private(root / profile["name"] / "profile.json", profile)


def preserve_profile(root, profile):
    history = root / profile["name"] / "profile-history"
    if not history.exists() and not history.is_symlink():
        history.mkdir(mode=0o700)
    directory(history, private=True)
    target = history / f"{profile_hash(profile)}.json"
    if target.exists() or target.is_symlink():
        private_file(target)
        if target.read_text() != encode(profile) + "\n":
            fail("Recovery profile history conflicts; reconcile before recreation.")
    else:
        write_private(target, profile)


def compose(profile, *args):
    if digest(COMPOSE.read_text()) != profile["compose_sha256"]:
        fail("Compose specification changed. Review it, back up stopped state, then recreate --ack-stop.")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("T3CODE_", "COMPOSE_"))}
    env.update({
        "T3CODE_IMAGE": profile["image"], "T3CODE_NAME": profile["name"],
        "T3CODE_UID": str(profile["uid"]), "T3CODE_GID": str(profile["gid"]),
        "T3CODE_WORKSPACE": profile["workspace"], "T3CODE_WORKSPACE_ID": profile["workspace_id"],
        "T3CODE_STATE_ROOT": profile["home"], "T3CODE_AGENT_ROOT": profile["agent"],
        "T3CODE_PORT": str(profile["port"]), "T3CODE_CPUS": profile["cpus"],
        "T3CODE_MEMORY": profile["memory"], "T3CODE_PROVIDER": profile["provider"],
        "T3CODE_PROFILE_ID": profile_hash(profile),
        "COMPOSE_DISABLE_ENV_FILE": "1", "COMPOSE_IGNORE_ORPHANS": "true",
    })
    return execute([*docker_prefix(), "compose", "--env-file", "/dev/null", "--project-directory", str(COMPONENT),
                    "-f", str(COMPOSE), "-p", profile["name"], *args], env=env)


def container(profile):
    name = profile["name"]
    ids = docker("container", "ls", "--all", "--filter", f"name=^/{name}$", "--format", "{{.ID}}", capture=True).split()
    if not ids:
        return None
    if len(ids) != 1:
        fail("Ambiguous container identity.")
    info = json.loads(docker("container", "inspect", ids[0], capture=True))[0]
    labels = info["Config"].get("Labels") or {}
    expected = {"io.t3code.component": "t3code", "io.t3code.owner": str(os.getuid()),
                "io.t3code.workspace": profile["workspace_id"], "io.t3code.profile": profile_hash(profile),
                "com.docker.compose.project": name, "com.docker.compose.service": "t3code"}
    if info["Name"] != f"/{name}" or any(labels.get(k) != v for k, v in expected.items()):
        fail("Container ownership/profile mismatch. Refusing adoption or mutation.")
    mounts = {m["Destination"]: m for m in info.get("Mounts", [])}
    for destination, source, writable in (("/workspace", profile["workspace"], True),
                                          ("/opt/agent", profile["agent"], False),
                                          ("/home/t3code", profile["home"], True)):
        mount = mounts.get(destination, {})
        if mount.get("Source") != source or mount.get("Type") != "bind" or mount.get("RW") != writable:
            fail("Managed mount contract changed; refusing operation.")
    if info["Config"].get("User") != f'{profile["uid"]}:{profile["gid"]}':
        fail("Container user contract changed; refusing operation.")
    return info


def require_image(profile):
    # No implicit network pull or mutable-tag resolution during lifecycle changes.
    images = json.loads(docker("image", "inspect", profile["image"], capture=True))
    return images[0]["Id"]


def runtime_identity(profile, info):
    image_id = require_image(profile)
    if info and info["Image"] != image_id:
        fail("Existing container image does not match the immutable profile; stop/remove remain available.")


def show_logs(profile):
    terminal()
    home = directory(profile["home"], private=True)
    logs = directory(home / "logs", private=True)
    path = logs / "server.log"
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                info.st_uid != os.getuid() or info.st_gid != os.getgid() or info.st_mode & 0o077):
            fail("Unsafe private log; refusing to read it.")
        print("WARNING: private upstream logs can contain pairing credentials and conversations. Showing at most 64 KiB / 100 lines; no follow.", file=sys.stderr)
        stream.seek(max(0, info.st_size - 65536))
        data = stream.read(65536).decode("utf-8", errors="replace")
        # Logs can contain model/tool-controlled text. Render terminal controls
        # visibly rather than allowing escape sequences to manipulate the TTY.
        data = "".join(f"\\x{ord(c):02x}" if (ord(c) < 32 and c not in "\n\t") or 127 <= ord(c) <= 159 else c for c in data)
        print("\n".join(data.splitlines()[-100:]))


def terminal():
    if not all(os.isatty(fd) for fd in (0, 1, 2)):
        fail("This command may expose credentials or private output; an operator terminal is required on stdin/stdout/stderr.")


def launch(args):
    parser = argparse.ArgumentParser(prog="t3code-run", allow_abbrev=False)
    parser.add_argument("--port", default=os.environ.get("T3CODE_PORT", "3773"))
    parser.add_argument("--cpus", default=os.environ.get("T3CODE_CPUS", "2"))
    parser.add_argument("--memory", default=os.environ.get("T3CODE_MEMORY", "4g"))
    parser.add_argument("workspace", nargs="?", default=os.environ.get("T3CODE_WORKSPACE", os.getcwd()))
    options = parser.parse_args(args)
    operator()
    root = registry()
    workspace = directory(options.workspace)
    agent = directory(os.environ.get("T3CODE_AGENT_ROOT"))
    narrow_mounts(workspace, agent)
    name = instance_name(workspace)
    profile = {"schema": 1, "name": name, "uid": os.getuid(), "gid": os.getgid(),
               "workspace": str(workspace), "workspace_id": digest(str(workspace)),
               "agent": str(agent), "home": str(root / name / "home"),
               "image": os.environ.get("T3CODE_IMAGE", ""), "port": options.port,
               "cpus": options.cpus, "memory": options.memory,
               "provider": os.environ.get("T3CODE_PROVIDER", "none"),
               "compose_sha256": digest(COMPOSE.read_text())}
    settings(profile)
    # Validate root overlap before creating directories under it.
    for a, b in ((root, workspace), (root, agent), (workspace, agent)):
        if a == b or a in b.parents or b in a.parents:
            fail("State, workspace and shared-resource roots must not overlap.")
    with locked(root):
        instance = root / name
        if instance.exists() or instance.is_symlink():
            old = load(root, name)
            if profile != old:
                fail("Existing image/profile differs; use explicit recreate NAME --ack-stop, not implicit replacement.")
        else:
            instance.mkdir(mode=0o700)
            (instance / "home").mkdir(mode=0o700)
            save(root, profile)
        info = container(profile)
        runtime_identity(profile, info)
        if info:
            compose(profile, "start", "t3code")
        else:
            compose(profile, "up", "-d", "--no-build", "--pull", "never", "--no-recreate", "t3code")
        print(f"Instance: {name}\nRequested URL: http://127.0.0.1:{profile['port']}\nStart requested; health/auth/provider acceptance NOT established.")


def build():
    missing = [key for key in BUILD_ARGS if not os.environ.get(key)]
    if missing or not (COMPONENT / "runtime/package-lock.json").is_file():
        fail("Build blocked: supply reviewed build arguments, exact runtime dependency and real package-lock.json; see README.")
    # These gates run BEFORE Docker resolves/executes either base image.
    node = os.environ["NODE_VERSION"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", node):
        fail("An approved exact NODE_VERSION is required.")
    for key in ("NODE_IMAGE", "BUILDER_IMAGE"):
        image = os.environ[key]
        if not re.fullmatch(r"[^\s@]+:[A-Za-z0-9_][A-Za-z0-9_.-]*@sha256:[a-f0-9]{64}", image):
            fail("Both prepared bases require reviewed exact tags and digests.")
        tag = image.split("@")[0].rsplit(":", 1)[1]
        if tag.lower() in ("latest", "nightly") or tag.lower().startswith(("latest-", "nightly-")):
            fail("Mutable base tag names are not permitted, even with a digest.")
        if key == "NODE_IMAGE" and tag != node and not tag.startswith(node + "-"):
            fail("Runtime image tag must begin with the exact Node patch.")
    if any(os.environ[key] != "yes" for key in ("PREPARED_BASES_REVIEWED", "INSTALL_HOOKS_REVIEWED")):
        fail("Prepared bases and installation hooks require explicit review before building.")
    platform = os.environ.get("T3CODE_BUILD_PLATFORM", "")
    if platform not in ("linux/amd64", "linux/arm64"):
        fail("Set the reviewed T3CODE_BUILD_PLATFORM to linux/amd64 or linux/arm64.")
    # Content-addressed output only. No tag overwrite, Compose up, or container mutation.
    with tempfile.TemporaryDirectory(prefix="t3code-build-") as temporary:
        iid = Path(temporary) / "image.id"
        command = [*docker_prefix(), "build", "--platform", platform, "--iidfile", str(iid), "--file", str(COMPONENT / "Dockerfile")]
        for key in BUILD_ARGS:
            command.extend(["--build-arg", f"{key}={os.environ[key]}"])
        command.append(str(COMPONENT))
        execute(command)
        image = iid.read_text().strip()
        if not IMAGE.fullmatch(image):
            fail("Build returned an unexpected image identity.")
        print(f"Built image: {image}\nNot deployed or accepted. Review before setting T3CODE_IMAGE.")


def manage(args):
    parser = argparse.ArgumentParser(prog="t3code-mgr", allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("list", "build"):
        sub.add_parser(command, allow_abbrev=False)
    for command in ("status", "start", "stop", "remove", "logs", "shell", "pair", "auth", "provider", "recreate"):
        item = sub.add_parser(command, allow_abbrev=False)
        item.add_argument("name")
        if command == "recreate":
            item.add_argument("--ack-stop", action="store_true", required=True)
        if command == "provider":
            item.add_argument("action", choices=("status", "login"))
        if command == "auth":
            item.add_argument("auth_args", nargs=argparse.REMAINDER)
    options = parser.parse_args(args)
    operator()
    if options.command == "build":
        build()
        return
    root = registry()
    with locked(root) as lock_fd:
        if options.command == "list":
            for path in sorted(root.iterdir()):
                if NAME.fullmatch(path.name):
                    profile = load(root, path.name, resources=False)
                    info = container(profile)
                    print(f"{path.name}\t{info['State']['Status'] if info else 'absent'}")
            return
        profile = load(root, options.name, resources=options.command in ("start", "recreate", "shell", "pair", "auth", "provider"))
        info = container(profile)
        command = options.command
        if command == "status":
            print(f"{profile['name']}: {info['State']['Status'] if info else 'absent'}; provider unconfigured")
            print("Container state is not readiness or functional acceptance.")
        elif command == "start":
            runtime_identity(profile, info)
            if info:
                compose(profile, "start", "t3code")
            else:
                compose(profile, "up", "-d", "--no-build", "--pull", "never", "--no-recreate", "t3code")
        elif command in ("stop", "remove"):
            if info:
                # Exact inspected ID allows recovery even after a Compose file change.
                docker("container", "stop", "--time", "60", info["Id"])
                if command == "remove":
                    docker("container", "rm", info["Id"])
            print("Private home, profile and workspace retained; no network or volume cleanup performed.")
        elif command == "recreate":
            updated = dict(profile)
            for key, env in (("image", "T3CODE_IMAGE"), ("port", "T3CODE_PORT"),
                             ("cpus", "T3CODE_CPUS"), ("memory", "T3CODE_MEMORY")):
                if env in os.environ:
                    updated[key] = os.environ[env]
            updated["compose_sha256"] = digest(COMPOSE.read_text())
            settings(updated)
            require_image(updated)
            # Persist recovery metadata BEFORE stopping anything. History is
            # content-addressed so retries cannot overwrite an earlier profile.
            preserve_profile(root, profile)
            if info:
                docker("container", "stop", "--time", "60", info["Id"])
                docker("container", "rm", info["Id"])
            save(root, updated)
            compose(updated, "up", "-d", "--no-build", "--pull", "never", "--no-recreate", "t3code")
            print("Recreation requested; prior profile saved, state not backed up or rolled back automatically.")
        elif command == "logs":
            # Host-side bounded read also works after container failure/removal.
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            show_logs(profile)
        else:
            if not info or not info["State"]["Running"]:
                fail("An exact running managed instance is required.")
            terminal()
            runtime_identity(profile, info)
            if command == "shell":
                print("Operator shell: do not launch another server or modify installed runtime.", file=sys.stderr)
                invocation = ["/bin/bash", "--noprofile", "--norc"]
            elif command == "provider":
                invocation = ["/bin/bash", "/opt/t3/scripts/provider.sh", options.action]
            else:
                auth = ["pairing", "create"] if command == "pair" else options.auth_args
                valid = (auth in (["pairing", "list"], ["pairing", "create"], ["session", "list"]) or
                         (len(auth) == 3 and auth[:2] in (["pairing", "revoke"], ["session", "revoke"]) and
                          re.fullmatch(r"[A-Za-z0-9_-]{1,256}", auth[2])))
                if not valid:
                    fail("Auth supports pairing create/list/revoke ID or session list/revoke ID only. Administrative session issuance is deliberately excluded.")
                invocation = ["/opt/t3/runtime/node_modules/.bin/t3", "auth", *auth,
                              "--base-dir", "/home/t3code/base"]
            # Interactive sessions must not prevent an operator from stopping
            # the server. Exec uses the inspected immutable ID, never a new name.
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            docker("container", "exec", "-it", "--user", f"{os.getuid()}:{os.getgid()}",
                   info["Id"], "/bin/bash", "-c", 'umask 077; exec "$@"', "t3code-operator", *invocation)


def main():
    os.umask(0o077)
    args = sys.argv[1:]
    mode = args.pop(0) if args else "dispatch"
    management = {"list", "status", "build", "start", "stop", "remove", "logs", "shell", "pair", "auth", "provider", "recreate"}
    if mode == "dispatch":
        if args and args[0] == "run":
            args.pop(0)
            mode = "run"
        elif args and args[0] in management:
            mode = "manage"
        else:
            mode = "run"
    if mode not in ("run", "manage"):
        fail("Unknown dispatcher mode.")
    # Each parser handles help before its unconditional operator guard. A stray
    # --help inside auth arguments must never bypass account/endpoint checks.
    (launch if mode == "run" else manage)(args)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, TypeError, IndexError) as error:
        # OSError paths and JSON contents may be private. Avoid dumping tracebacks.
        print(f"t3code: {error if isinstance(error, RuntimeError) else 'Local contract or Docker metadata could not be read; inspect private configuration.'}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
