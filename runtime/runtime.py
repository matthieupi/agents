#!/usr/bin/env python3
"""Opt-in foreground runtime and pure contract builder. No legacy adoption."""
import argparse
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
IMAGE = re.compile(r'sha256:[a-f0-9]{64}')
CATALOG = json.loads((ROOT / 'harnesses.json').read_text())
CAPABILITIES = set(CATALOG['capabilities'])
MODES = {name: set(spec['modes']) for name, spec in CATALOG['harnesses'].items()}
KEYS = {'schema', 'harness', 'mode', 'image', 'platform', 'uid', 'gid', 'name', 'workspace',
        'home', 'resources', 'source', 'grants', 'limits', 'port', 'endpoint', 'receipt'}


def require(value, message):
    if not value:
        raise ValueError(message)


def path(value):
    require(isinstance(value, str) and value.startswith('/') and value != '/'
            and not any(c in value for c in (',', '\x00', '\n', '\r'))
            and str(Path(value)) == value and '..' not in Path(value).parts, 'Canonical bounded absolute path required')
    return Path(value)


def overlap(a, b):
    a, b = Path(a), Path(b)
    return a == b or a in b.parents or b in a.parents


def fingerprint(contract):
    return hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_contract(contract: dict) -> None:
    require(isinstance(contract, dict) and set(contract) == KEYS and contract['schema'] == 1, 'Exact runtime schema required')
    c = contract
    require(c['harness'] in MODES and c['mode'] in MODES[c['harness']], 'Unsupported harness mode')
    require(c['platform'] in CATALOG['harnesses'][c['harness']]['platforms'], 'Unsupported platform')
    require(isinstance(c['image'], str) and IMAGE.fullmatch(c['image']), 'Local immutable image ID required')
    require(isinstance(c['receipt'], str) and re.fullmatch(r'[a-f0-9]{64}', c['receipt']), 'Bound receipt digest required')
    require(all(type(c[key]) is int and 0 < c[key] < 2**32 - 1 for key in ('uid', 'gid')), 'Numeric ordinary owner required')
    require(re.fullmatch(r'agents-runtime-[a-z0-9-]{1,100}', c['name']), 'Isolated runtime namespace required')
    workspace, home = path(c['workspace']), path(c['home'])
    require(not overlap(workspace, home), 'Workspace/private HOME overlap refused')
    require(not overlap(workspace, '/opt') and not overlap(workspace, '/home/agent')
            and not overlap(workspace, '/usr') and not overlap(workspace, '/etc')
            and not overlap(workspace, '/proc') and not overlap(workspace, '/sys')
            and not overlap(workspace, '/dev'), 'Workspace cannot shadow image controls or private HOME')
    if c['resources'] is not None:
        resources = path(c['resources'])
        require(not overlap(resources, workspace) and not overlap(resources, home), 'Public resource/private mount overlap')
    require(set(c['source']) == {'mode', 'path', 'sha256', 'revision'}, 'Exact source mode required')
    source = c['source']
    require(source['mode'] in ('baked', 'live'), 'Unsupported source mode')
    require(re.fullmatch(r'[a-f0-9]{64}', source['sha256']) and re.fullmatch(r'[a-f0-9]{40,64}', source['revision']), 'Source evidence required')
    require(set(c['grants']) == {'root_user', 'docker_socket', 'cap_add', 'checkout_write'}, 'Independent grants required')
    grants = c['grants']
    require(type(grants['root_user']) is bool and type(grants['checkout_write']) is bool, 'Boolean grants required')
    caps = grants['cap_add']
    require(isinstance(caps, list) and len(set(caps)) == len(caps) and set(caps) <= CAPABILITIES, 'Capability not allowlisted')
    if grants['docker_socket'] is not None:
        socket = grants['docker_socket']
        require(set(socket) == {'path', 'gid'} and type(socket['gid']) is int and socket['gid'] >= 0,
                'Exact socket/group grant required')
        path(socket['path'])
        require('unix://' + socket['path'] == c['endpoint'], 'Socket grant must match selected local endpoint')
    require(isinstance(c['endpoint'], str) and c['endpoint'].startswith('unix://'), 'Explicit local Docker endpoint required')
    path(c['endpoint'][7:])
    if source['mode'] == 'live':
        public = path(source['path'])
        require(not grants['root_user'], 'Root cannot execute mutable checkout startup')
        require(not overlap(public, home) and not overlap(public, workspace)
                and (c['resources'] is None or not overlap(public, c['resources'])), 'Executable source must be a narrow separate public bind')
        require(not any(overlap(public, reserved) for reserved in ('/opt', '/usr', '/etc', '/home/agent', '/proc', '/sys', '/dev')),
                'Public startup bind cannot shadow image controls')
    else:
        require(source['path'] is None and not grants['checkout_write'], 'Baked startup has no editable checkout mount')
    if grants['root_user']:
        require(c['resources'] is None, 'Root mode refuses mutable resource/skill binds')
    limits = c['limits']
    require(set(limits) == {'memory_mb', 'cpus', 'pids'}, 'Explicit bounded resources required')
    require(type(limits['memory_mb']) is int and 128 <= limits['memory_mb'] <= 4096
            and type(limits['cpus']) in (int, float) and 0 < limits['cpus'] <= 4
            and type(limits['pids']) is int and 16 <= limits['pids'] <= 512, 'Resource bounds exceeded')
    require((c['mode'] == 'cli' and c['port'] is None) or
            (c['mode'] == 'web' and type(c['port']) is int and 1024 <= c['port'] <= 65535), 'Mode/loopback port mismatch')


def mounts(c):
    result = [(c['workspace'], c['workspace'], not c['grants']['root_user'])]
    if not c['grants']['root_user']:
        result.append((c['home'], '/home/agent', True))
    if c['resources']:
        result.append((c['resources'], '/opt/agent', False))
    if c['source']['mode'] == 'live':
        result.append((c['source']['path'], c['source']['path'], c['grants']['checkout_write']))
    if c['grants']['docker_socket']:
        socket = c['grants']['docker_socket']['path']
        result.append((socket, socket, True))
    return result


def environment(c):
    result = {'HOME': '/home/agent', 'USER': 'agent', 'LOGNAME': 'agent',
              'AGENTS_RUNTIME_SOURCE_MODE': c['source']['mode'],
              'OPENCODE_DISABLE_AUTOUPDATE': '1', 'PI_WEB_SKIP_VERSION_CHECK': '1',
              'DISABLE_AUTOUPDATER': '1', 'DISABLE_INSTALLATION_CHECKS': '1'}
    if c['resources']:
        result['AGENTS_RUNTIME_RESOURCES'] = '/opt/agent'
    if c['grants']['docker_socket']:
        result['DOCKER_HOST'] = c['endpoint']
    return result


def command(contract: dict, arguments: list[str], *, tty: bool) -> list[str]:
    validate_contract(contract)
    c = contract
    require(isinstance(arguments, list) and all(isinstance(a, str) and '\x00' not in a for a in arguments), 'Invalid argv')
    require(not (c['mode'] == 'web' and arguments), 'Web arguments are fixed')
    require(not any(a in ('--gpu', '-gpu', '--gpus', '--privileged') for a in arguments), 'Unsupported GPU/privileged request')
    root = c['grants']['root_user']
    result = ['/usr/bin/docker', '--host', c['endpoint'], 'run', '--rm', '--init', '--pull=never',
              '--name', c['name'], '--platform', c['platform'], '--user', '0:0' if root else f'{c["uid"]}:{c["gid"]}',
              '--cap-drop=ALL', '--security-opt=no-new-privileges', '--network', 'bridge', '--read-only',
              '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m',
              '--memory', str(c['limits']['memory_mb']) + 'm', '--memory-swap', str(c['limits']['memory_mb']) + 'm',
              '--cpus', str(c['limits']['cpus']), '--pids-limit', str(c['limits']['pids']),
              '--workdir', c['workspace'], '--label', 'io.agents-runtime.contract=' + fingerprint(c),
              '--label', 'io.agents-runtime.home=' + hashlib.sha256(c['home'].encode()).hexdigest()]
    if root:
        result += ['--tmpfs', '/home/agent:rw,nosuid,nodev,mode=0700,size=256m']
    for cap in c['grants']['cap_add']:
        result += ['--cap-add', cap]
    if c['grants']['docker_socket']:
        result += ['--group-add', str(c['grants']['docker_socket']['gid'])]
    for source, destination, writable in mounts(c):
        result += ['--mount', f'type=bind,src={source},dst={destination}' + ('' if writable else ',readonly')]
    for key, value in environment(c).items():
        result += ['--env', key + '=' + value]
    if c['mode'] == 'web':
        result += ['--publish', f'127.0.0.1:{c["port"]}:{c["port"]}']
    result += ['-it' if tty else '-i', '--entrypoint', '/usr/bin/python3', c['image'], '-I',
               '/opt/agents-runtime/entry.py' if c['source']['mode'] == 'baked' else c['source']['path'] + '/entry.py', c['harness']]
    if c['mode'] == 'web':
        result += ['--web', '--port', str(c['port'])]
    return [*result, '--', *arguments]


def inspect_contract(contract: dict, instance: dict) -> None:
    """No label-only reuse. Reject all extra mounts and authority, not just missing flags."""
    validate_contract(contract)
    c, i = contract, instance
    config, host = i['Config'], i['HostConfig']
    require(i['Image'] == c['image'] and i['Name'] == '/' + c['name'], 'Container identity mismatch')
    require(config.get('Labels', {}).get('io.agents-runtime.contract') == fingerprint(c), 'Contract fingerprint mismatch')
    require(config['User'] == ('0:0' if c['grants']['root_user'] else f'{c["uid"]}:{c["gid"]}'), 'Container user mismatch')
    require(host.get('Privileged') is False and host.get('ReadonlyRootfs') is True
            and set(host.get('CapDrop') or []) == {'ALL'}
            and set(host.get('CapAdd') or []) == set(c['grants']['cap_add'])
            and set(host.get('SecurityOpt') or []) in ({'no-new-privileges'}, {'no-new-privileges=true'}), 'Container privilege drift')
    require(host.get('NetworkMode') == 'bridge' and host.get('PidMode', '') == ''
            and host.get('IpcMode') in ('private', '') and not host.get('Devices')
            and not host.get('DeviceRequests') and not host.get('VolumesFrom'), 'Host namespace/device grant refused')
    require((host.get('GroupAdd') or []) == ([str(c['grants']['docker_socket']['gid'])] if c['grants']['docker_socket'] else []),
            'Supplementary group drift')
    expected = sorted(mounts(c))
    actual = sorted((m['Source'], m['Destination'], m['RW']) for m in i['Mounts'] if m['Type'] == 'bind')
    require(actual == expected and all(m['Type'] in ('bind', 'tmpfs') for m in i['Mounts']), 'Container mount drift')
    require(host['Memory'] == c['limits']['memory_mb'] * 1024**2 and host['MemorySwap'] == host['Memory']
            and host['NanoCpus'] == int(c['limits']['cpus'] * 10**9) and host['PidsLimit'] == c['limits']['pids'], 'Resource drift')
    env = dict(item.split('=', 1) for item in config['Env'])
    require(all(env.get(k) == v for k, v in environment(c).items()), 'Startup environment drift')
    require(c['grants']['docker_socket'] is not None or 'DOCKER_HOST' not in env, 'Ambient Docker authority refused')
    require(config['WorkingDir'] == c['workspace'] and config['Entrypoint'] == ['/usr/bin/python3'], 'Startup executable drift')
    expected_command = command(c, [], tty=False)
    expected_command = expected_command[expected_command.index(c['image']) + 1:]
    require(config['Cmd'][:len(expected_command)] == expected_command
            and (c['mode'] != 'web' or config['Cmd'] == expected_command), 'Startup command drift')
    tmpfs = {'/tmp': 'rw,nosuid,nodev,size=256m'}
    if c['grants']['root_user']:
        tmpfs['/home/agent'] = 'rw,nosuid,nodev,mode=0700,size=256m'
    require(host.get('Tmpfs') == tmpfs, 'Unexpected writable tmpfs')
    bindings = {str(c['port']) + '/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(c['port'])}]} if c['mode'] == 'web' else {}
    require((host.get('PortBindings') or {}) == bindings and not host.get('PublishAllPorts'), 'Unexpected port publication')


def public_source(root):
    """A live mount exposes ONLY a dedicated two-file public startup directory."""
    require(root.resolve(strict=True) == root and root.is_dir(), 'Physical public startup directory required')
    require({p.name for p in root.iterdir()} == {'entry.py', 'harnesses.json'}, 'Live startup must be a narrow two-file public bundle')
    hashes = {}
    for child in root.iterdir():
        info = child.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid(), 'Owned physical public source required')
        hashes[child.name] = hashlib.sha256(child.read_bytes()).hexdigest()
    return fingerprint(hashes)


def web_instance(c: dict) -> dict:
    """Revalidate full ownership/authority, never act on a name or label alone."""
    result = subprocess.run(['/usr/bin/docker', '--host', c['endpoint'], 'container', 'inspect', c['name']],
                            env={'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())},
                            text=True, capture_output=True, check=True, timeout=5)
    values = json.loads(result.stdout)
    require(isinstance(values, list) and len(values) == 1, 'Unique web instance required')
    value = values[0]
    inspect_contract(c, value)
    require(isinstance(value.get('Id'), str) and re.fullmatch(r'[a-f0-9]{64}', value['Id']), 'Exact web container ID required')
    return value


def web_request(c: dict, route: str, *, upgrade: bool = False) -> tuple[int, bytes]:
    # http.client does not follow redirects or use ambient proxy/credential config.
    connection = http.client.HTTPConnection('127.0.0.1', c['port'], timeout=2)
    try:
        headers = {'Connection': 'close'}
        if upgrade:
            headers = {'Connection': 'Upgrade', 'Upgrade': 'websocket', 'Sec-WebSocket-Version': '13',
                       'Sec-WebSocket-Key': 'YWdlbnRzLXJ1bnRpbWUxMg=='}
        connection.request('GET', route, headers=headers)
        response = connection.getresponse()
        body = response.read(1024 * 1024 + 1)
        require(len(body) <= 1024 * 1024, 'Oversized readiness response refused')
        return response.status, body
    finally:
        connection.close()


def web_ready(c: dict) -> None:
    require(web_request(c, '/')[0] == 200, 'Application HTTP unavailable')
    if c['harness'] == 't3':
        require(web_request(c, '/api/orchestration/snapshot')[0] == 401, 'T3 unpaired API gate missing')
        require(web_request(c, '/ws', upgrade=True)[0] == 401, 'T3 unpaired WS gate missing')
    else:
        route = '/api/sessions' if c['harness'] == 'pi' else '/global/health'
        status, body = web_request(c, route)
        require(status == 200, 'Application API unavailable')
        value = json.loads(body)
        require(isinstance(value, (dict, list)), 'Application JSON response required')
        if c['harness'] == 'opencode':
            require(isinstance(value, dict) and value.get('healthy') is True, 'OpenCode API unhealthy')


def wait_web(c: dict, process, *, timeout: float = 60) -> None:
    validate_contract(c)
    require(c['mode'] == 'web', 'Web readiness requires web mode')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        require(process.poll() is None, 'Web process exited before readiness')
        try:
            value = web_instance(c)
        except subprocess.SubprocessError:
            # Docker run may not yet have created the container. Contract drift
            # (ValueError) is never retried as mere startup unavailability.
            time.sleep(0.25)
            continue
        if not value.get('State', {}).get('Running'):
            time.sleep(0.25)
            continue
        try:
            web_ready(c)
        except (OSError, ValueError, http.client.HTTPException):
            time.sleep(0.25)
            continue
        current = web_instance(c)
        require(current['Id'] == value['Id'] and current.get('State', {}).get('Running')
                and process.poll() is None, 'Web instance changed during readiness')
        require(time.monotonic() < deadline, 'Web startup readiness timed out')
        print(f'agents-runtime: ready http://127.0.0.1:{c["port"]} (local startup only)', file=sys.stderr)
        return
    raise ValueError('Web startup readiness timed out; no provider/browser acceptance implied')


def supervise_web(c: dict, process) -> int:
    try:
        wait_web(c, process)
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException, subprocess.SubprocessError):
        try:
            value = web_instance(c)
            subprocess.run(['/usr/bin/docker', '--host', c['endpoint'], 'container', 'stop', '--time', '10', value['Id']],
                           env={'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())},
                           check=True, capture_output=True, timeout=20)
        finally:
            # SIGTERM to docker can proxy into an unverified container. Kill only
            # the local attached client after cleanup/refusal; retain unknown state.
            if process.poll() is None:
                process.kill()
            process.wait(timeout=15)
        raise
    return process.wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run',))
    parser.add_argument('harness', choices=MODES)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--state-slot', default='default', help='Independent private HOME; existing state never migrates implicitly')
    parser.add_argument('--web', action='store_true')
    parser.add_argument('--port', type=int, default=4096)
    parser.add_argument('--resources')
    parser.add_argument('--live-source')
    parser.add_argument('--checkout-write', action='store_true')
    parser.add_argument('--root-user', action='store_true')
    parser.add_argument('--docker-socket', action='store_true')
    parser.add_argument('--cap-add', action='append', default=[])
    raw = list(sys.argv[1:] if argv is None else argv)
    split = raw.index('--') if '--' in raw else len(raw)
    args = parser.parse_args(raw[:split])
    arguments = raw[split + 1:]
    try:
        # Import only in ordinary-user entry. Protected consumers use the pure
        # contract functions, never this checkout-dependent CLI.
        require(os.getuid() > 0 and os.getuid() == os.geteuid(), 'Runtime must be invoked as ordinary user')
        import install
        os.umask(0o077)
        root = install.state_root()
        receipt = json.loads(install.private(root / (args.harness + '-selected.json')).read_text())
        require(receipt['harness'] == args.harness and receipt['contract'] == 1, 'Selected receipt mismatch')
        install.prerequisites(args.harness, receipt['platform'])
        require(re.fullmatch(r'[a-z0-9][a-z0-9-]{0,40}', args.state_slot), 'Bounded private state slot required')
        home = root / (args.harness + '-' + args.state_slot + '-home')
        home.mkdir(mode=0o700, exist_ok=True)
        install.private(home, directory=True)
        workspace = Path(args.workspace).resolve(strict=True)
        require(workspace.is_dir(), 'Existing workspace required')
        resources = str(Path(args.resources).resolve(strict=True)) if args.resources else None
        source = dict(mode='baked', path=None, sha256=receipt['resolution']['source']['public_sha256'],
                      revision=receipt['resolution']['source']['revision'])
        if args.live_source:
            public = Path(args.live_source).absolute()
            source = dict(mode='live', path=str(public), sha256=public_source(public),
                          revision=subprocess.run(['git', '-C', str(public), 'rev-parse', 'HEAD'], text=True,
                                                  capture_output=True, check=True).stdout.strip())
        socket = None
        if args.docker_socket:
            info = Path('/var/run/docker.sock').stat()
            require(stat.S_ISSOCK(info.st_mode), 'Real Docker socket required')
            socket = dict(path='/var/run/docker.sock', gid=info.st_gid)
        c = dict(schema=1, harness=args.harness, mode='web' if args.web else 'cli', image=receipt['image'],
                 platform=receipt['platform'], uid=os.getuid(), gid=os.getgid(),
                 name=f'agents-runtime-{os.getuid()}-{args.harness}-{uuid.uuid4().hex}', workspace=str(workspace),
                 home=str(home), resources=resources, source=source, receipt=install.digest(install.encoded(receipt)),
                 grants=dict(root_user=args.root_user, docker_socket=socket, cap_add=args.cap_add, checkout_write=args.checkout_write),
                 limits=dict(memory_mb=2048, cpus=2, pids=256), port=args.port if args.web else None,
                 endpoint='unix:///var/run/docker.sock')
        selected = command(c, arguments, tty=all(os.isatty(fd) for fd in (0, 1, 2)))
        lock_path = root / (args.harness + '-' + args.state_slot + '.writer.lock')
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            install.private(lock_path)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # A killed adapter may leave a live container after releasing flock.
            # Never start a second writer merely because the host lock is free.
            existing = install.docker(['container', 'ls', '--all', '--quiet', '--filter',
                                       'label=io.agents-runtime.home=' + hashlib.sha256(c['home'].encode()).hexdigest()])
            require(not existing.stdout.strip(), 'Prior runtime container still owns HOME; inspect/recover it explicitly')
            inspected = json.loads(install.docker(['image', 'inspect', c['image']]).stdout)[0]
            install.verify_image(receipt, inspected)
            # Image rollback cannot reverse databases/provider-state writes. Until
            # a reviewed state migration policy exists, image changes use a new
            # explicit slot rather than silently opening an older private HOME.
            if not args.root_user:
                install.bind_home(home, c['image'])
            install.atomic(root / (c['name'] + '.json'), c)
            process = subprocess.Popen(selected, env={'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())})
            handlers = {}
            try:
                for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                    handlers[sig] = signal.signal(sig, lambda signum, frame: process.send_signal(signum))
                if args.web:
                    return supervise_web(c, process)
                return process.wait()
            finally:
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)
        finally:
            os.close(fd)
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException, subprocess.SubprocessError) as error:
        print('agents-runtime: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
