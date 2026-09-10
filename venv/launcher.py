#!/usr/bin/python3 -I
"""VM-only CLI sessions and managed web. Docker authority is host-root authority.

This is a runtime leaf, not an image builder, credential migrator or workstation
launcher. No environment or command-line input can add Docker mounts/options.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import signal
import stat
import subprocess
import sys
import tempfile
import uuid
import importlib.util
import types


HARNESSES = {"pi", "omp", "opencode", "t3"}
IMAGE = re.compile(r"(?:sha256:[a-f0-9]{64}|[a-z0-9][a-z0-9._:/-]*@sha256:[a-f0-9]{64})")
POLICY = Path("/etc/venv-agents/policy.json")
ACTIVATION = Path('/etc/venv-agents/activation.json')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def path_value(value):
    require(isinstance(value, str) and re.fullmatch(r"/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", value)
            and all(part not in (".", "..") for part in value.split("/")), "Invalid absolute path")
    return Path(value)


def validate_policy(policy: dict) -> None:
    require(isinstance(policy, dict), "Policy mapping required")
    require(policy.get("schema") in (1, 2) and policy.get("scope") == "vm", "VM policy required")
    ondemand = policy['schema'] == 2
    require(policy.get("docker_access") is True, "Explicit VM-root Docker authorization required")
    require(type(policy.get("web_ready")) is bool, "Explicit frontend readiness required")
    if policy.get("web_ready") or "web" in policy:
        web = policy.get("web", {})
        require(set(web) == {"default_harness", "default_account", "base_hostname"}, "Public frontend web routing fields required; no secrets")
        require(web["default_account"] in policy.get("accounts", {}), "Enrolled default web owner required")
        require(web['default_harness'] in (None, 'native-pi', 'pi', 'opencode', 't3') if ondemand
                else web['default_harness'] == 'pi', 'Invalid web default')
        require(re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)+", web["base_hostname"]), "Invalid base hostname")
    require(re.fullmatch(r"[a-z0-9-]+:[a-z0-9-]+", policy.get("target", "")), "Exact target required")
    require(set(policy.get("harnesses", {})) == HARNESSES, "All four independent harnesses required")
    for key in ("workspace", "resources", "socket"):
        path_value(policy[key])
    workspace, resources = Path(policy['workspace']), Path(policy['resources'])
    require(workspace != resources and workspace not in resources.parents and resources not in workspace.parents,
            "Shared binds must not overlap")
    require(('container_workspace' in policy) == ('services_root' in policy), 'Complete optional mount extension required')
    if 'container_workspace' in policy:
        require(path_value(policy['container_workspace']) == workspace, 'Identical VM/container workspace required')
        services = path_value(policy['services_root'])
        require(workspace != services and workspace not in services.parents and services not in workspace.parents,
                'Workspace and services must differ')
        require(resources != services and services in resources.parents, 'Resources must be a narrow services subtree')
    if 'legacy_workspace' in policy:
        legacy = path_value(policy['legacy_workspace'])
        require('services_root' in policy and legacy != workspace and workspace not in legacy.parents
                and legacy not in workspace.parents, 'Distinct legacy workspace alias required')
        require(legacy != resources and legacy not in resources.parents and resources not in legacy.parents,
                'Legacy workspace must not overlap resources')
    shared = [Path(source) for source, _, _ in shared_mounts(policy)]
    require(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]+", policy["network"])
            and policy["network"] not in ("host", "none", "container", "bridge"), "Dedicated bridge required")
    require(policy.get('cgroup_parent') == 'venv-agents.slice', "Shared bounded VM cgroup required")
    ports = []
    for name, spec in policy["harnesses"].items():
        require((ondemand and 'image' in spec and spec['image'] is None)
                or (isinstance(spec.get('image'), str) and IMAGE.fullmatch(spec['image'])),
                f"{name}: verified immutable image or explicit uninstalled null required")
        if ondemand and spec['image'] is not None:
            require(re.fullmatch(r'sha256:[a-f0-9]{64}', spec['image']), 'On-demand installations require local image IDs')
        require(type(spec["memory_mb"]) is int and 128 <= spec["memory_mb"] <= (4096 if 'resource_budget' in policy else 1024), "Bounded memory limit required")
        require(type(spec["cpus"]) in (int, float) and 0 < spec["cpus"] <= (4 if 'resource_budget' in policy else 2), "CPU limit required")
        require(type(spec["pids"]) is int and 16 <= spec["pids"] <= 512, "PID limit required")
        path_value(spec["home"])
        for command in ("cli", "web"):
            argv = spec.get(command, [])
            require(isinstance(argv, list) and all(isinstance(a, str) and a and not any(ord(c) < 32 for c in a) for a in argv), "Invalid command array")
        require(name == 't3' or spec["cli"], f"{name}: CLI command required")
        for command in ('cli', 'web'):
            if spec.get(command):
                path_value(spec[command][0])
        if name == "omp":
            require(not spec.get("web") and "port" not in spec, "OMP is SSH CLI only")
        else:
            require(spec.get("web"), f"{name}: web command required")
            require(type(spec["port"]) is int and 1024 <= spec["port"] <= 65535, "Invalid web port")
            require(type(spec["container_port"]) is int and 1024 <= spec["container_port"] <= 65535, "Invalid container port")
            require(re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)+", spec["hostname"]), "Invalid web hostname")
            ports.append(spec["port"])
    require(len(ports) == len(set(ports)), "Web ports must be distinct")
    images = [s['image'] for s in policy['harnesses'].values() if s['image'] is not None]
    require(len(set(images)) == len(images), "Harness images must remain independent")
    if ondemand:
        require('default_harness' in policy and 'web' in policy, 'Explicit CLI/web defaults required')
        default = policy['default_harness']
        require(default in (None, 'native-pi', *HARNESSES), 'Invalid default harness')
        require((not images and default in (None, 'native-pi')) or
                (default in HARNESSES and installed(policy, default)), 'Default must be installed; native is initial only')
        require(policy['web']['default_harness'] == (None if default == 'omp' else default),
                'CLI/web defaults must agree; OMP has explicitly no web default')
        if default == 'native-pi':
            argv = policy.get('native_pi', {}).get('cli')
            require(isinstance(argv, list) and argv and all(isinstance(a, str) and a and '\x00' not in a for a in argv),
                    'Explicit native Pi CLI required')
            path_value(argv[0])
    if 'resource_budget' in policy:
        budget = policy['resource_budget']
        require(isinstance(budget, dict) and set(budget) == {'memory_max_mb', 'cpu_quota_percent', 'tasks_max', 'full_containers', 'spare_mb'}, 'Explicit shared resource budget required')
        require(all(type(v) is int for v in budget.values()), 'Integer shared resource budget required')
        require(0 < budget['memory_max_mb'] <= 9216 and 0 < budget['cpu_quota_percent'] <= 600 and 0 < budget['tasks_max'] <= 2048, 'Bounded shared resource budget required')
        require(budget['full_containers'] == 2 and budget['spare_mb'] >= 1024, 'Budget two full containers plus spare, not every account')
        require(2 * max(s['memory_mb'] for s in policy['harnesses'].values()) + budget['spare_mb'] <= budget['memory_max_mb'], 'Shared memory reserve insufficient')
    else:
        require(sum(s["memory_mb"] for s in policy["harnesses"].values()) <= 2816, "Reserve at least 1280 MiB on a 4GiB VM")
    resource_validate_origins(policy)
    require(policy.get("accounts"), "Explicit account policy required")
    for account, spec in policy["accounts"].items():
        require(re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", account) and account != "root", "Non-root account required")
        require(type(spec["uid"]) is int and 0 < spec["uid"] < 2**32 - 1 and type(spec["gid"]) is int and 0 < spec["gid"] < 2**32 - 1, "Discovered nonzero UID/GID required")
        path_value(spec["state"])
        state = Path(spec["state"])
        if 'native_pi_home' in spec:
            native = path_value(spec['native_pi_home'])
            for source in (*shared, state):
                require(native != source and native not in source.parents and source not in native.parents,
                        "Native Pi HOME must not overlap state/shared binds")
        for source in shared:
            require(state != source and state not in source.parents and source not in state.parents, "Private state must not overlap shared binds")
        require(spec.get("autoentry") in (None, *HARNESSES, *(('default',) if ondemand else ())), "Invalid autoentry")
        require(account != "sysops" or spec.get("autoentry") is None, "Sysops must retain ordinary shell")
    require(len({s["uid"] for s in policy["accounts"].values()}) == len(policy["accounts"]), "Accounts must have distinct UIDs")
    states = [Path(s['state']) for s in policy['accounts'].values()]
    require(all(a != b and a not in b.parents and b not in a.parents
                for i, a in enumerate(states) for b in states[i + 1:]), "Account state roots must not overlap")
    if 'shared_runtime' in policy:
        shared_module(policy).validate_extension(policy['shared_runtime'], policy)


def shared_module(policy):
    """Import only hash-bound protected controller artifacts, never guest checkout."""
    item = policy['shared_runtime']['controls']['adapter']
    path = path_value(item['path'])
    require(stat.S_ISREG(protected(path).st_mode) and path.name == 'shared.py'
            and hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], 'Unsealed shared adapter refused')
    spec = importlib.util.spec_from_file_location('venv_shared_runtime', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shared_selected(policy, harness):
    return 'shared_runtime' in policy and policy['harnesses'][harness]['image'] in policy['shared_runtime']['images'].get(harness, {})


def shared_host():
    return types.SimpleNamespace(**globals())


def protected(path, *, owner=0, private=False):
    require(path.resolve(strict=True) == path, "Symlinked managed path refused")
    info = path.lstat()
    require(info.st_uid == owner and not info.st_mode & (0o077 if private else 0o022), "Unsafe managed path ownership/mode")
    for parent in path.parents:
        info_parent = parent.stat()
        require(info_parent.st_uid in (0, owner) and not info_parent.st_mode & 0o022, "Writable managed ancestor refused")
    return info


def load_policy(path: Path) -> dict:
    require(stat.S_ISREG(protected(path).st_mode), "Regular policy required")
    require(not path.with_name('resource-update-pending.json').exists(), 'Resource update in progress; retry after operator recovery')
    require(not path.with_name('shared-runtime-upgrade.json').exists(), 'Protected control upgrade pending; use maintained enrollment recovery')
    policy = json.loads(path.read_text())
    validate_policy(policy)
    return policy


def installed(policy: dict, harness: str) -> bool:
    return harness in HARNESSES and policy['harnesses'][harness].get('image') is not None


def run_default(policy: dict, web: bool, arguments: list[str]) -> int:
    validate_policy(policy)
    account = pwd.getpwuid(os.getuid()).pw_name
    require(os.getuid() > 0 and account in policy['accounts'], 'Enrolled non-root account required')
    user = policy['accounts'][account]
    require((os.getuid(), os.getgid()) == (user['uid'], user['gid']), 'Account identity drift')
    default = policy.get('default_harness', 'pi')
    if default == 'native-pi':
        if web:
            require(not arguments and policy['web_ready'], 'Prepared native frontend required')
            print(f'https://{policy["web"]["base_hostname"]}/ (native Pi)')
            return 0
        command = policy['native_pi']['cli']
        # Preserve native package-bin symlinks. Only the verified non-root caller
        # executes this existing installation; root never executes guest code.
        return subprocess.call([*command, *arguments])
    if web:
        default = policy['web']['default_harness']
    require(default is not None, 'No web default (CLI-only install)' if web else 'No harness installed; run make pi|omp|opencode|t3')
    return run_session(policy, default, web, arguments)


def session_command(policy: dict, harness: str, account: str, web: bool,
                    arguments: list[str], tty: bool) -> list[str]:
    validate_policy(policy)
    require(harness in HARNESSES and account in policy["accounts"], "Account/harness not enrolled")
    require(installed(policy, harness), f'{harness} is not installed; run make {harness} in the deployed agents-source/venv directory')
    if web:
        require(policy['web_ready'] and harness != 'omp' and not arguments, "Enrolled authenticated web required; no web arguments allowed")
    else:
        require(harness != 't3', "T3 is web-oriented; use --web")
        require(not (harness == 'opencode' and any(a in ('serve', 'web') for a in arguments)), "Use managed --web, not a CLI server")
    spec, user = policy["harnesses"][harness], policy["accounts"][account]
    if shared_selected(policy, harness):
        return shared_module(policy).session_command(shared_host(), policy, harness, account, web, arguments, tty)
    source_home, container_home = home_mount(policy, harness, account)
    command = ["/usr/bin/docker", "--host", "unix://" + policy["socket"], "create" if web else "run", "--init", "--pull=never",
               "--name", web_name(policy, harness) if web else f"venv-agents-{os.getuid()}-{harness}-{uuid.uuid4().hex}",
               "--label", "io.venv-agents.target=" + policy["target"],
               "--label", "io.venv-agents.account=" + account,
               "--label", "io.venv-agents.harness=" + harness,
               "--label", "io.venv-agents.mode=" + ('web' if web else 'cli'),
               "--label", "io.venv-agents.uid=" + str(user['uid']),
               "--label", "io.venv-agents.gid=" + str(user['gid']),
               "--user", f'{user["uid"]}:{user["gid"]}',
               "--network", policy["network"], "--cap-drop=ALL", "--security-opt=no-new-privileges",
               "--cgroup-parent", policy["cgroup_parent"],
               "--memory", f'{spec["memory_mb"]}m', "--memory-swap", f'{spec["memory_mb"]}m',
               "--cpus", str(spec["cpus"]), "--pids-limit", str(spec["pids"]),
               "--workdir", policy.get("container_workspace", policy['workspace']), "--env", "HOME=" + container_home,
               "--env", "USER=" + account, "--env", "LOGNAME=" + account,
               "--env", "VENV_AGENT_RESOURCES=" + policy['resources'],
               "--mount", f'type=bind,src={source_home},dst={container_home}',
               "--mount", f'type=bind,src={policy["socket"]},dst={policy["socket"]}',
               "--group-add", str(os.stat(policy["socket"]).st_gid),
                "--env", "DOCKER_HOST=unix://" + policy["socket"]]
    for source, destination, writable in shared_mounts(policy):
        command += ['--mount', f'type=bind,src={source},dst={destination}' + ('' if writable else ',readonly')]
    if web:
        command += ['--publish', f'127.0.0.1:{spec["port"]}:{spec["container_port"]}',
                    '--env', 'VENV_AGENT_PORT=' + str(spec['container_port']),
                    '--label', 'io.venv-agents.contract=' + web_contract(policy, harness, account)]
        if harness == 'pi':
            command += ['--env', 'PI_WEB_ALLOWED_HOSTS=' + pi_allowed_hosts(policy)]
        if harness == 't3':
            for key, value in {'T3CODE_UID': user['uid'], 'T3CODE_GID': user['gid'],
                               'T3CODE_PORT': spec['container_port'], 'T3CODE_PROVIDER': 'none'}.items():
                command += ['--env', f'{key}={value}']
    elif tty:
        command += ['--rm']
        command += ["-it"]
    else:
        command += ["--rm", "-i"]
    # Clear inherited image entrypoints. Commands are component-owned image paths,
    # never a host checkout script run by root.
    argv = spec['web' if web else 'cli']
    command += ["--entrypoint", argv[0], spec["image"], *argv[1:], *arguments]
    return command


def shared_mounts(policy: dict) -> list[tuple[str, str, bool]]:
    """Optional schema-2 extension; absent fields retain the exact legacy contract."""
    result = [(policy['workspace'], policy.get('container_workspace', policy['workspace']), True)]
    if 'services_root' in policy:
        result.append((policy['services_root'], policy['services_root'], True))
    if 'legacy_workspace' in policy and not Path(policy['legacy_workspace']).is_relative_to(policy['services_root']):
        result.append((policy['legacy_workspace'], policy['legacy_workspace'], True))
    result.append((policy['resources'], policy['resources'], False))
    return result


def home_mount(policy: dict, harness: str, account: str) -> tuple[str, str]:
    user = policy['accounts'][account]
    if harness == 'pi' and user.get('native_pi_home'):
        source_home = container_home = user['native_pi_home']
    else:
        source_home = str(Path(user['state']) / harness / 'home')
        container_home = policy['harnesses'][harness]['home']
    home = Path(container_home)
    for source in [Path(p) for p, _, _ in shared_mounts(policy)] + [Path(policy['socket'])]:
        require(home != source and home not in source.parents and source not in home.parents,
                'Container HOME must not overlap shared mounts')
    return source_home, container_home


def pi_allowed_hosts(policy: dict) -> str:
    """Exact canonical public hosts; retain Pi's upstream Host/Origin protection."""
    hostname = policy['harnesses']['pi']['hostname']
    return ','.join(dict.fromkeys([hostname, policy.get('web', {}).get('base_hostname', hostname)]))


def web_name(policy: dict, harness: str) -> str:
    if shared_selected(policy, harness):
        return 'agents-runtime-' + hashlib.sha256(policy['target'].encode()).hexdigest()[:16] + '-' + harness + '-web'
    # Dot cannot occur in either target segment, so this encoding is injective.
    return 'venv-agents-' + policy['target'].replace(':', '.') + '-' + harness + '-web'


def web_contract(policy: dict, harness: str, account: str) -> str:
    data = {k: policy[k] for k in ('target', 'workspace', 'resources', 'socket', 'network', 'cgroup_parent')}
    data.update({k: policy[k] for k in ('container_workspace', 'services_root', 'legacy_workspace') if k in policy})
    data.update(spec=policy['harnesses'][harness], account=account, user=policy['accounts'][account])
    if shared_selected(policy, harness):
        data['shared_runtime'] = policy['shared_runtime']['images'][harness][policy['harnesses'][harness]['image']]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def docker_call(policy: dict, arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(['/usr/bin/docker', '--host', 'unix://' + policy['socket'], *arguments],
                          env={'PATH': '/usr/bin:/bin', 'HOME': pwd.getpwuid(os.getuid()).pw_dir},
                          text=True, capture_output=True, timeout=60)


def inspect_web(policy: dict, harness: str) -> dict | None:
    result = docker_call(policy, ['container', 'inspect', web_name(policy, harness)])
    if result.returncode:
        require('No such container:' in result.stderr or 'No such object:' in result.stderr,
                'Cannot inspect local Docker web instance')
        return None
    values = json.loads(result.stdout)
    require(isinstance(values, list) and len(values) == 1, 'Invalid Docker inspection')
    return values[0]


def validate_web_instance(policy: dict, harness: str, instance: dict) -> str:
    if shared_selected(policy, harness):
        return shared_module(policy).inspect_instance(shared_host(), policy, harness, instance)
    labels = instance['Config'].get('Labels') or {}
    owner = labels.get('io.venv-agents.account')
    require(owner in policy['accounts'], 'Foreign web container; no takeover')
    user, spec = policy['accounts'][owner], policy['harnesses'][harness]
    record = pwd.getpwnam(owner)
    require((record.pw_uid, record.pw_gid) == (user['uid'], user['gid']), 'Web owner identity drift')
    if harness == 'pi' and user.get('native_pi_home'):
        require(record.pw_dir == user['native_pi_home'], 'Native Pi web owner HOME drift')
    require(instance['Name'] == '/' + web_name(policy, harness), 'Web container name drift')
    for key, value in {'target': policy['target'], 'harness': harness, 'mode': 'web',
                       'uid': str(user['uid']), 'gid': str(user['gid']),
                        'contract': resource_web_contract(policy, harness, owner, instance['Id'])}.items():
        require(labels.get('io.venv-agents.' + key) == value, 'Web container ownership/policy drift; no takeover')
    config, host = instance['Config'], instance['HostConfig']
    require(config['Image'] == spec['image'] and config['User'] == f'{user["uid"]}:{user["gid"]}'
            and config['WorkingDir'] == policy.get('container_workspace', policy['workspace'])
            and config['Entrypoint'] == spec['web'][:1]
            and (config.get('Cmd') or []) == spec['web'][1:], 'Web image/command drift')
    if spec['image'].startswith('sha256:'):
        require(instance['Image'] == spec['image'], 'Immutable image identity drift')
    require(host['Memory'] == spec['memory_mb'] * 1024**2 and host['MemorySwap'] == host['Memory']
            and host['NanoCpus'] == int(spec['cpus'] * 10**9) and host['PidsLimit'] == spec['pids']
            and host['CgroupParent'] == policy['cgroup_parent'] and host.get('Init') is True
            and not host.get('CapAdd') and 'ALL' in (host.get('CapDrop') or [])
            and any(x in ('no-new-privileges', 'no-new-privileges:true') for x in host.get('SecurityOpt', []))
            and not host.get('Devices') and not host.get('Binds') and not host.get('VolumesFrom'),
            'Web privilege/resource drift')
    require(not host.get('PidMode') and host.get('IpcMode', 'private') == 'private'
            and not host.get('PublishAllPorts') and not host.get('DeviceRequests'),
            'Web foreign Docker options refused')
    require(host['NetworkMode'] == policy['network'] and not host['Privileged']
            and host.get('GroupAdd') == [str(os.stat(policy['socket']).st_gid)]
            and host['PortBindings'] == {f'{spec["container_port"]}/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(spec['port'])}]},
            'Web network/publication drift')
    source, destination = home_mount(policy, harness, owner)
    environment = dict(value.split('=', 1) for value in config.get('Env', []) if '=' in value)
    require(all(environment.get(k) == v for k, v in {
        'HOME': destination, 'USER': owner, 'LOGNAME': owner,
        'VENV_AGENT_RESOURCES': policy['resources'], 'VENV_AGENT_PORT': str(spec['container_port']),
        'DOCKER_HOST': 'unix://' + policy['socket']}.items()), 'Web environment drift')
    if harness == 'pi':
        require(environment.get('PI_WEB_ALLOWED_HOSTS') == pi_allowed_hosts(policy), 'Pi allowed-host environment drift')
    if harness == 't3':
        require(all(environment.get(k) == v for k, v in {
            'T3CODE_UID': str(user['uid']), 'T3CODE_GID': str(user['gid']),
            'T3CODE_PORT': str(spec['container_port']), 'T3CODE_PROVIDER': 'none'}.items()),
            'T3 native environment drift')
    expected = set(shared_mounts(policy)) | {(source, destination, True), (policy['socket'], policy['socket'], True)}
    actual = {(m['Source'], m['Destination'], m['RW']) for m in instance['Mounts'] if m['Type'] == 'bind'}
    require(actual == expected and len(instance['Mounts']) == len(expected), 'Web private/shared mount drift')
    require(re.fullmatch(r'[a-f0-9]{64}', instance['Id']), 'Invalid container identity')
    return owner


def run_web(policy: dict, harness: str, action: str = 'start') -> int:
    validate_policy(policy)
    require(installed(policy, harness), f'{harness} is not installed; run make {harness}')
    require(action in ('start', 'status', 'stop'), 'Invalid web action')
    require(harness in HARNESSES - {'omp'} and (policy['web_ready'] or action != 'start'),
            'Authenticated frontend not enrolled; web blocked')
    account = pwd.getpwuid(os.getuid()).pw_name
    require(os.getuid() > 0 and account in policy['accounts'], 'Enrolled non-root account required')
    user = policy['accounts'][account]
    require((os.getuid(), os.getgid()) == (user['uid'], user['gid']), 'Account identity drift')
    validate_socket(Path(policy['socket']))

    def existing(instance):
        owner = validate_web_instance(policy, harness, instance)
        if action == 'stop':
            require(owner == account, 'Another account owns this web instance; no takeover')
            require(docker_call(policy, ['container', 'stop', '--time', '30', instance['Id']]).returncode == 0,
                    'Web graceful stop failed; container/state preserved')
            require(docker_call(policy, ['container', 'rm', instance['Id']]).returncode == 0,
                    'Web stop failed; state preserved')
            print('Web instance stopped; private state preserved')
        else:
            state = instance['State']['Status']
            require(state in ('running', 'created', 'restarting') or action == 'status',
                    'Web instance is stopped/failed; owner must --web-stop before retry')
            readiness = '' if policy['web_ready'] else '; frontend disabled'
            print(f'https://{policy["harnesses"][harness]["hostname"]}/ ({state}; owner {owner}{readiness})')
        return 0

    instance = inspect_web(policy, harness)
    if instance is not None:
        return existing(instance)
    if action != 'start':
        print('No managed web instance')
        return 0
    require((harness != 'pi' and harness != policy['web']['default_harness']) or account == policy['web']['default_account'],
            'Default Pi web must retain the policy legacy owner; no private-state replacement')
    # No other account's state is read or prepared on the existing-instance path.
    validate_runtime(policy, harness, account, web=True)
    state = Path(user['state']) / harness
    fd = os.open(state / ('.session.lock' if shared_selected(policy, harness) else '.web-start.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_gid == os.getgid()
                and info.st_nlink == 1 and not info.st_mode & 0o077, 'Unsafe web startup lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        instance = inspect_web(policy, harness)
        if instance is not None:
            return existing(instance)
        if shared_selected(policy, harness):
            shared_module(policy).validate_launch(shared_host(), policy, harness, account)
        command = session_command(policy, harness, account, True, [], False)
        created = docker_call(policy, command[3:])
        if created.returncode:
            # Another account may have won Docker's atomic name reservation.
            instance = inspect_web(policy, harness)
            require(instance is not None, 'Web container creation failed; no state changed')
            return existing(instance)
        container_id = created.stdout.strip()
        require(re.fullmatch(r'[a-f0-9]{64}', container_id), 'Invalid created container ID')
        try:
            require(docker_call(policy, ['container', 'start', container_id]).returncode == 0, 'Web container start failed')
            instance = inspect_web(policy, harness)
            require(instance is not None and instance['Id'] == container_id and instance['State']['Running'],
                    'Web container did not remain running')
            return existing(instance)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            # ID-bound cleanup cannot remove a replacement that reused the name.
            docker_call(policy, ['container', 'rm', '--force', container_id])
            raise
    finally:
        os.close(fd)


def validate_socket(socket_path: Path) -> None:
    # /var/run is conventionally a root-owned link to /run. Verify the socket
    # and every canonical ancestor, not arbitrary writable redirected paths.
    socket_info = socket_path.lstat()
    require(stat.S_ISSOCK(socket_info.st_mode) and socket_info.st_uid == 0
            and not socket_info.st_mode & 0o007, "Root-owned private local Docker socket required")
    for parent in set(socket_path.parents) | set(socket_path.resolve(strict=True).parents):
        info = parent.stat()
        require(parent.lstat().st_uid == 0 and info.st_uid == 0 and stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o022,
                "Unsafe Docker socket ancestor")
    require(os.access(socket_path, os.R_OK | os.W_OK), "Account cannot access Docker socket")


def validate_runtime(policy: dict, harness: str, account: str, web: bool = False) -> None:
    """Read-only account-local checks shared by installation and every launch.

    Run as the enrolled account, never root: os.access checks actual ACLs and
    traversal. Do not create state/locks or repair ownership during validation.
    """
    validate_policy(policy)
    require(not web or (policy['web_ready'] and harness != 'omp'), 'Authenticated frontend not enrolled; web blocked')
    require(os.getuid() > 0 and account in policy["accounts"], "Run as an enrolled non-root account")
    require(harness in HARNESSES, "Unknown harness")
    require(installed(policy, harness), f'{harness} is not installed; run make {harness}')
    user = policy["accounts"][account]
    record = pwd.getpwnam(account)
    require((record.pw_uid, record.pw_gid) == (user["uid"], user["gid"]), "Account database identity drift")
    require((os.getuid(), os.getgid()) == (user["uid"], user["gid"]), "Account identity drift")
    home = path_value(record.pw_dir)
    require(stat.S_ISDIR(protected(home, owner=os.getuid()).st_mode), "Account HOME must be a directory")
    if user.get('native_pi_home'):
        require(Path(user['native_pi_home']) == home and home.stat().st_gid == os.getgid(), 'Native Pi HOME identity/path drift')
    account_homes = [path_value(pwd.getpwnam(name).pw_dir) for name in policy['accounts']]
    for key in ("workspace", "resources"):
        path = path_value(policy[key])
        require(path.resolve(strict=True) == path and path.is_dir(), "Existing physical bind directory required")
        require(all(path != h and path not in h.parents for h in account_homes), "Do not mount an account home or its ancestors")
        require(os.access(path, os.R_OK | os.X_OK | (os.W_OK if key == 'workspace' else 0)), "Account cannot access required bind")
    validate_socket(Path(policy['socket']))
    state = Path(user["state"]) / harness
    home_mount(policy, harness, account)
    homes = () if harness == 'pi' and user.get('native_pi_home') else (state / 'home',)
    for path in (Path(user['state']), state, *homes):
        info = protected(path, owner=os.getuid(), private=True)
        require(stat.S_ISDIR(info.st_mode) and info.st_gid == os.getgid(), "Private state/HOME must be matching UID/GID directories")
        require(os.access(path, os.R_OK | os.W_OK | os.X_OK), "Private directory is inaccessible")
    lock = state / ('.web-start.lock' if web and not shared_selected(policy, harness) else '.session.lock')
    if lock.exists() or lock.is_symlink():
        info = protected(lock, owner=os.getuid(), private=True)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_gid == os.getgid(), "Unsafe existing state lock")
        fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)


def run_session(policy: dict, harness: str, web: bool, arguments: list[str]) -> int:
    if web or harness == 't3':
        require(not arguments, 'T3/web entry accepts no app arguments; T3 is web-oriented')
        if harness == 't3' and not web:
            print('T3 is web-oriented; opening its managed web entry, not a conversational CLI.')
        return run_web(policy, harness)
    account = pwd.getpwuid(os.getuid()).pw_name
    validate_runtime(policy, harness, account)
    user = policy['accounts'][account]
    state = Path(user['state']) / harness
    tty = not web and all(os.isatty(fd) for fd in (0, 1, 2)) and (
        not os.environ.get("SSH_CONNECTION") or os.environ.get("VENV_AGENTS_REQUEST") == "shell")
    command = session_command(policy, harness, account, web, arguments, tty)
    fd = os.open(state / ".session.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1 and not info.st_mode & 0o077, "Unsafe state lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Explicit endpoint and minimal environment: no ambient Docker context,
        if shared_selected(policy, harness):
            shared_module(policy).validate_launch(shared_host(), policy, harness, account)
        # remote builder, provider credentials, shell injection or SSH forwarding.
        environment = {"PATH": "/usr/bin:/bin", "HOME": pwd.getpwuid(os.getuid()).pw_dir}
        if tty:
            environment["TERM"] = os.environ.get("TERM", "xterm-256color")
        process = subprocess.Popen(command, env=environment)
        previous = {}
        def forward(signum, frame):
            process.send_signal(signum)
        try:
            for signum in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                previous[signum] = signal.signal(signum, forward)
            return process.wait()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    finally:
        os.close(fd)


def atomic_json(path: Path, value: dict, mode: int = 0o644) -> None:
    """Durable replacement in the protected policy directory; never touch homes."""
    protected(path.parent)
    if path.exists() or path.is_symlink():
        require(stat.S_ISREG(protected(path).st_mode), 'Regular control file required')
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), mode)
            json.dump(value, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def activation_gateway(config: dict, phase: str, transaction: dict, *, lock_fd: int | None = None) -> None:
    require(phase in ('install-prepare', 'install-stage', 'install-check', 'install-commit', 'install-rollback', 'install-finalize'), 'Invalid activation phase')
    gateway = path_value(config['gateway'])
    require(stat.S_ISREG(protected(gateway).st_mode), 'Protected maintained gateway helper required')
    result = subprocess.run(['/usr/bin/python3', '-I', str(gateway), phase, transaction['harness']],
                            input=json.dumps({key: transaction[key] for key in ('previous', 'candidate')}),
                            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root'},
                            text=True, capture_output=True, timeout=180, cwd='/',
                            pass_fds=() if lock_fd is None else (lock_fd,))
    # Never disclose captured gateway output: it may contain private diagnostics.
    require(result.returncode == 0, f'Gateway {phase} failed; see protected service diagnostics')


def run_candidate(harness: str, action: str) -> int:
    """Gateway invokes this as the enrolled owner; candidate stays root-managed."""
    require(harness in HARNESSES and action in ('start', 'status', 'stop'), 'Finite candidate web action required')
    require(os.getuid() > 0, 'Candidate web must run as an enrolled non-root account')
    candidate = load_policy(POLICY.with_name('activation-candidate.json'))
    if 'shared_runtime' in candidate:
        shared_module(candidate).authorize_candidate(shared_host())
    return run_web(candidate, harness, action)


def check_image(policy: dict, harness: str, image: str) -> None:
    if shared_selected(policy, harness):
        return shared_module(policy).check_image(shared_host(), policy, harness, image)
    result = docker_call(policy, ['image', 'inspect', '--format', '{{.Id}}', image])
    require(result.returncode == 0 and result.stdout.strip() == image, 'Exact image must exist in local Docker store')
    user = policy['accounts'][policy['web']['default_account']]
    executable = {'pi': '/opt/pi/runtime/node_modules/.bin/pi', 'omp': '/usr/local/bin/omp',
                  'opencode': '/opt/opencode/component/.runtime/bin/opencode',
                  't3': '/opt/t3/runtime/node_modules/.bin/t3'}[harness]
    result = docker_call(policy, ['create', '--pull=never', '--network', 'none',
                                 '--user', f'{user["uid"]}:{user["gid"]}', '--cap-drop=ALL',
                                 '--security-opt=no-new-privileges', '--read-only', '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m',
                                 '--memory', '512m', '--memory-swap', '512m', '--cpus', '1', '--pids-limit', '64',
                                 '--cgroup-parent', policy['cgroup_parent'],
                                 '--env', 'HOME=/tmp', '--entrypoint', executable, image, '--version'])
    container = result.stdout.strip()
    require(result.returncode == 0 and re.fullmatch(r'[a-f0-9]{64}', container), 'Version-check container creation failed')
    try:
        result = docker_call(policy, ['container', 'start', '--attach', container])
        status = docker_call(policy, ['container', 'inspect', '--format', '{{.State.ExitCode}}', container])
        require(result.returncode == 0 and bool(result.stdout.strip()) and status.returncode == 0
                and status.stdout.strip() == '0', 'Selected image version check failed')
    finally:
        require(docker_call(policy, ['container', 'rm', '--force', container]).returncode == 0,
                'Failed to remove exact version-check container; no activation')


def activate(harness: str, image: str) -> int:
    """Finite root interface. No build code, argv, paths or policy supplied by guest."""
    require(os.getuid() == 0 and os.geteuid() == 0, 'Activation requires the protected sudo interface')
    require(harness in HARNESSES and isinstance(image, str) and re.fullmatch(r'sha256:[a-f0-9]{64}', image),
            'Expected one supported harness and a local sha256 image ID')
    require(stat.S_ISREG(protected(Path(__file__)).st_mode), 'Protected deployed launcher required')
    protected(POLICY.parent)
    require(stat.S_ISREG(protected(ACTIVATION).st_mode), 'Protected activation configuration required')
    config = json.loads(ACTIVATION.read_text())
    require(isinstance(config, dict) and set(config) == {'gateway'}, 'Exact activation configuration required')
    lock = POLICY.with_name('activation.lock')
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and not info.st_mode & 0o077, 'Unsafe activation lock')
        # Bounded refusal rather than a sudo process waiting behind a long build.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        policy = load_policy(POLICY)
        require(policy['schema'] == 2, 'On-demand schema 2 enrollment required')
        account = os.environ.get('SUDO_USER', '')
        require(account in policy['accounts'], 'Enrolled sudo caller required')
        user = policy['accounts'][account]
        record = pwd.getpwnam(account)
        require(os.environ.get('SUDO_UID') == str(user['uid']) and
                (record.pw_uid, record.pw_gid) == (user['uid'], user['gid']), 'Sudo caller identity drift')
        if 'shared_runtime' in policy:
            return shared_module(policy).activate(shared_host(), config, policy, harness, image, fd)
        pending = POLICY.with_name('activation-pending.json')
        candidate_path = POLICY.with_name('activation-candidate.json')
        if pending.exists() or pending.is_symlink():
            require(stat.S_ISREG(protected(pending, private=True).st_mode), 'Private activation journal required')
            transaction = json.loads(pending.read_text())
            require(set(transaction) == {'harness', 'previous', 'candidate'} and transaction['harness'] in HARNESSES,
                    'Invalid activation journal')
            validate_policy(transaction['previous'])
            validate_policy(transaction['candidate'])
            require(policy in (transaction['previous'], transaction['candidate']), 'Policy drift during interrupted activation')
            if policy == transaction['previous']:
                atomic_json(candidate_path, transaction['candidate'])
                activation_gateway(config, 'install-rollback', transaction, lock_fd=fd)
            # A matching candidate policy is the durable commit point. Do not
            # undo it if killed after atomic publication but before journal unlink.
            pending.unlink()
        if candidate_path.exists() or candidate_path.is_symlink():
            require(stat.S_ISREG(protected(candidate_path).st_mode), 'Protected candidate file required')
            candidate_path.unlink()
        if installed(policy, harness):
            require(policy['harnesses'][harness]['image'] == image,
                    'Installed image replacement requires a separate reviewed upgrade; state preserved')
            print(f'{harness} already installed; defaults unchanged')
            return 0
        candidate = copy.deepcopy(policy)
        candidate['harnesses'][harness]['image'] = image
        if policy['default_harness'] in (None, 'native-pi'):
            candidate['default_harness'] = harness
            candidate['web']['default_harness'] = None if harness == 'omp' else harness
        validate_policy(candidate)
        check_image(candidate, harness, image)
        transaction = dict(harness=harness, previous=policy, candidate=candidate)
        atomic_json(pending, transaction, 0o600)
        try:
            atomic_json(candidate_path, candidate)
            activation_gateway(config, 'install-check', transaction, lock_fd=fd)
            activation_gateway(config, 'install-commit', transaction, lock_fd=fd)
            # Gateway work must not have changed policy under this transaction.
            require(load_policy(POLICY) == policy, 'Policy changed during activation')
            atomic_json(POLICY, candidate)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            # Rename may have succeeded before fsync failed: never restore native
            # over a published installed default. Leave journal for retry instead.
            if load_policy(POLICY) == policy:
                activation_gateway(config, 'install-rollback', transaction, lock_fd=fd)
                pending.unlink()
                candidate_path.unlink(missing_ok=True)
            raise
        pending.unlink()
        candidate_path.unlink()
        print(f'{harness} activated; default={candidate["default_harness"]}; web={candidate["web"]["default_harness"]}')
        return 0
    finally:
        os.close(fd)


def _resource_dispatch(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['shared-run']:
        try:
            policy = load_policy(POLICY)
            require('shared_runtime' in policy, 'Shared runtime is not explicitly enrolled')
            return shared_module(policy).run_cli(shared_host(), argv[1:])
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            print(f'venv-agents shared runtime: {error}', file=sys.stderr)
            return 1
    if argv[:1] == ['candidate-web']:
        try:
            require(len(argv) == 3, 'candidate-web requires exactly harness and start|status|stop')
            return run_candidate(argv[1], argv[2])
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            print(f'venv-agents candidate: {error}', file=sys.stderr)
            return 1
    if argv[:1] == ['activate']:
        try:
            require(len(argv) == 3, 'activate requires exactly harness and image ID')
            return activate(argv[1], argv[2])
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            print(f'venv-agents activation: {error}', file=sys.stderr)
            return 1
    if argv in (["validate"], ["validate-runtime"]):
        try:
            policy = json.load(sys.stdin)
            validate_policy(policy)
            if argv == ['validate-runtime']:
                for harness in sorted(HARNESSES):
                    if installed(policy, harness):
                        validate_runtime(policy, harness, pwd.getpwuid(os.getuid()).pw_name)
            return 0
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"venv-agents: {error}", file=sys.stderr)
            return 1
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("harness", choices=['default', *sorted(HARNESSES)])
    parser.add_argument("--web", action="store_true")
    parser.add_argument('--web-status', action='store_true')
    parser.add_argument('--web-stop', action='store_true')
    passthrough = []
    for index, marker in enumerate(argv):
        if marker in ('--args', '--'):
            passthrough, argv = argv[index + 1:], argv[:index]
            break
    parser.add_argument("arguments", nargs="*")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        require(sum((args.web, args.web_status, args.web_stop)) <= 1, 'Select one web action')
        arguments = args.arguments + passthrough
        policy = load_policy(POLICY)
        if args.harness == 'default':
            require(not args.web_status and not args.web_stop, 'Use a named harness for web lifecycle')
            return run_default(policy, args.web, arguments)
        if args.web_status or args.web_stop:
            require(not arguments, 'Web lifecycle accepts no app arguments')
            return run_web(policy, args.harness, 'stop' if args.web_stop else 'status')
        return run_session(policy, args.harness, args.web, arguments)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"venv-agents: {error}", file=sys.stderr)
        return 1


# BEGIN sealed resource runtime extension
from contextlib import contextmanager


@contextmanager
def maintenance_lock(policy_path: Path, *, exclusive: bool = False):
    """Lock the existing protected directory inode; never create a user-owned lock."""
    directory = policy_path.parent
    info = protected(directory)
    require(stat.S_ISDIR(info.st_mode), 'Maintenance directory required')
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        require((opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino), 'Maintenance directory changed')
        fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        yield fd
    finally:
        os.close(fd)


def resource_validate_origins(policy: dict) -> None:
    origins = policy.get('resource_container_origins', {})
    require(isinstance(origins, dict) and set(origins) <= {'pi', 'opencode', 't3'}, 'Invalid resource origin harnesses')
    for harness, origin in origins.items():
        require(isinstance(origin, dict) and set(origin) == {'id', 'limits'}
                and isinstance(origin['id'], str) and re.fullmatch(r'[a-f0-9]{64}', origin['id']), 'Invalid resource origin identity')
        limits = origin['limits']
        require(isinstance(limits, dict) and set(limits) == {'memory_mb', 'cpus', 'pids'}, 'Invalid resource origin limits')
        for key, minimum, maximum in (('memory_mb', 128, 4096), ('cpus', 0, 4), ('pids', 16, 512)):
            value = limits[key]
            require(type(value) in ((int, float) if key == 'cpus' else (int,))
                    and minimum <= value <= maximum and value > 0
                    and value <= policy['harnesses'][harness][key], 'Invalid resource origin bounds')


def resource_web_contract(policy: dict, harness: str, account: str, identity: str) -> str:
    resource_validate_origins(policy)
    origin = policy.get('resource_container_origins', {}).get(harness)
    if origin and origin['id'] == identity:
        policy = copy.deepcopy(policy)
        policy['harnesses'][harness].update(origin['limits'])
    return web_contract(policy, harness, account)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments in (['validate'], ['validate-runtime']) or arguments[:1] == ['activate']:
        return _resource_dispatch(arguments)
    try:
        # Launch/lifecycle entrypoints, including candidate-web, serialize here.
        # Root activation instead holds activation.lock, acquired first by maintenance.
        # Dispatch loads policy only AFTER admission; never use a stale pre-lock copy.
        with maintenance_lock(POLICY):
            require(not POLICY.with_name('shared-runtime-upgrade.json').exists(), 'Protected control upgrade in progress')
            if arguments[:1] != ['candidate-web'] and POLICY.with_name('shared-replacement.json').exists():
                raise ValueError('Shared runtime replacement in progress; retry after recovery')
            require(not POLICY.with_name('resource-update-pending.json').exists()
                    and not POLICY.with_name('resource-update-pending.json').is_symlink(), 'Resource update in progress; retry after operator recovery')
            return _resource_dispatch(arguments)
    except (OSError, ValueError):
        print('venv-agents: resource maintenance admission refused', file=sys.stderr)
        return 1
# END sealed resource runtime extension


if __name__ == "__main__":
    sys.exit(main())
