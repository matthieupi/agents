"""Protected opt-in VM adapter. Only controller-promoted copies may be imported.

No checkout imports, provider-state migration, network resolution or image builds.
The caller supplies the already protected launcher module as ``host``.
"""
import copy
import fcntl
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import signal
import uuid


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def absolute(value):
    require(isinstance(value, str) and re.fullmatch(r'/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', value)
            and '..' not in Path(value).parts, 'Bounded absolute shared-runtime path required')
    return Path(value)


def validate_extension(extension, policy):
    require(isinstance(extension, dict) and set(extension) == {
        'version', 'target', 'controls', 'checkout', 'grants', 'images', 'transitions', 'staging_ports', 'staging_limits', 'enrollment_marker'},
        'Exact shared-runtime extension required')
    require(type(extension['version']) is int and extension['version'] > 0
            and extension['target'] == policy['target'], 'Shared-runtime version/target mismatch')
    absolute(extension['enrollment_marker'])
    controls = extension['controls']
    require(set(controls) == {'adapter', 'runtime', 'catalog'}, 'Complete protected common controls required')
    paths = []
    for key in ('adapter', 'runtime', 'catalog'):
        item = controls[key]
        require(set(item) == {'path', 'sha256'} and re.fullmatch(r'[a-f0-9]{64}', item['sha256']), 'Control digest required')
        paths.append(absolute(item['path']))
    require(len(set(paths)) == 3 and len({p.parent for p in paths}) == 1
            and paths[0].name == 'shared.py' and paths[1].name == 'runtime.py'
            and paths[2].name == 'harnesses.json', 'Separate protected sibling controls required')
    checkout = extension['checkout']
    require(set(checkout) == {'path', 'owner', 'origin', 'revision', 'public_paths'}
            and checkout['owner'] in policy['accounts'], 'Explicit enrolled checkout owner required')
    source = absolute(checkout['path'])
    require(not any(source == p or source in p.parents or p in source.parents for p in paths),
            'Editable checkout must be separate from protected controls')
    workspace = absolute(policy['workspace'])
    require(source != workspace and source not in workspace.parents and workspace not in source.parents,
            'Editable checkout must not be exposed wholesale by the workspace mount')
    require(isinstance(checkout['origin'], str) and checkout['origin'].startswith(('https://', 'ssh://', 'git@'))
            and not any(c.isspace() for c in checkout['origin']), 'Explicit checkout origin required')
    require(re.fullmatch(r'https://[A-Za-z0-9.-]+/[A-Za-z0-9_./-]+|ssh://(?:[a-z0-9_-]+@)?[A-Za-z0-9.-]+(?::[0-9]+)?/[A-Za-z0-9_./-]+|git@[A-Za-z0-9.-]+:[A-Za-z0-9_./-]+', checkout['origin']),
            'Checkout origin must be a credential-free repository reference')
    require(re.fullmatch(r'[a-f0-9]{40}', checkout['revision']), 'Reviewed checkout commit required')
    require(checkout['public_paths'] == ['runtime/entry.py', 'runtime/harnesses.json'],
            'Only reviewed public startup files may be exposed; no broad checkout mount')
    grants = extension['grants']
    require(set(grants) == {'docker_socket', 'root_user', 'checkout_write', 'cap_add'}
            and all(type(grants[k]) is bool for k in ('docker_socket', 'root_user', 'checkout_write')),
            'Explicit independent capability policy required')
    require(isinstance(grants['cap_add'], list) and len(set(grants['cap_add'])) == len(grants['cap_add'])
            and set(grants['cap_add']) <= {'NET_BIND_SERVICE'}, 'Unsupported VM capability allowance')
    require(isinstance(extension['images'], dict) and set(extension['images']) <= {'pi', 'omp', 'opencode', 't3'},
            'VM harness allowlist excludes Claude')
    for harness, images in extension['images'].items():
        require(isinstance(images, dict) and images, 'Explicit reviewed image receipts required')
        for image, receipt in images.items():
            require(re.fullmatch(r'sha256:[a-f0-9]{64}', image) and set(receipt) == {
                'harness', 'platform', 'resolution_sha256', 'source_sha256', 'source_revision', 'contract'},
                'Exact image receipt projection required')
            require(receipt['harness'] == harness and receipt['contract'] == 1
                    and receipt['platform'] in (['linux/amd64'] if harness == 'omp' else ['linux/amd64', 'linux/arm64']),
                    'Unsupported image contract/platform')
            require(all(re.fullmatch(r'[a-f0-9]{64}', receipt[k]) for k in ('resolution_sha256', 'source_sha256'))
                    and re.fullmatch(r'[a-f0-9]{40}', receipt['source_revision']), 'Immutable build/source evidence required')
    ports = extension['staging_ports']
    require(set(ports) == set(extension['images']) - {'omp'}
            and all(type(port) is int and 1024 <= port <= 65535 for port in ports.values())
            and len(set(ports.values())) == len(ports), 'Finite independent staging ports required')
    require(not set(ports.values()) & {s['port'] for s in policy['harnesses'].values() if 'port' in s},
            'Staging must not use real-state service ports')
    limits = extension['staging_limits']
    require(set(limits) == {'memory_mb', 'cpus', 'pids'} and type(limits['memory_mb']) is int
            and 128 <= limits['memory_mb'] <= 1024 and type(limits['cpus']) in (int, float)
            and 0 < limits['cpus'] <= 1 and type(limits['pids']) is int and 16 <= limits['pids'] <= 128,
            'Bounded canonical staging resources required')
    require(isinstance(extension['transitions'], list), 'Explicit transition list required')
    pairs = set()
    for transition in extension['transitions']:
        require(set(transition) == {'harness', 'from', 'to', 'state', 'evidence'}, 'Exact reviewed state transition required')
        h = transition['harness']
        require(h in extension['images'] and transition['to'] in extension['images'][h]
                and (transition['from'] is None or re.fullmatch(r'sha256:[a-f0-9]{64}', transition['from'])),
                'Transition must bind exact previous/candidate image IDs')
        require(transition['state'] == 'backward-compatible'
                and isinstance(transition['evidence'], str) and 16 <= len(transition['evidence']) <= 1024,
                'Reviewed backward-compatible real-state evidence required; unknown/backup-only transitions refused')
        pair = (h, transition['from'], transition['to'])
        require(pair not in pairs, 'Ambiguous compatibility transition')
        pairs.add(pair)


def transition(previous, candidate, harness):
    extension = candidate.get('shared_runtime')
    validate_extension(extension, candidate)
    require(previous['target'] == candidate['target'] and previous.get('shared_runtime') == extension,
            'Replacement cannot change target or protected compatibility authority')
    expected = copy.deepcopy(previous)
    image = candidate['harnesses'][harness]['image']
    expected['harnesses'][harness]['image'] = image
    if previous['default_harness'] in (None, 'native-pi'):
        expected['default_harness'] = harness
        expected['web']['default_harness'] = None if harness == 'omp' else harness
    require(expected == candidate, 'Only selected image and first-install defaults may change')
    pair = (harness, previous['harnesses'][harness]['image'], image)
    require(any((t['harness'], t['from'], t['to']) == pair for t in extension['transitions']),
            'Unknown real-state downgrade/upgrade; promote exact reviewed compatibility evidence first')


def selected(policy, harness):
    return policy['harnesses'][harness]['image'] in policy.get('shared_runtime', {}).get('images', {}).get(harness, {})


def common(host, policy):
    controls = policy['shared_runtime']['controls']
    for item in controls.values():
        path = Path(item['path'])
        require(stat.S_ISREG(host.protected(path).st_mode)
                and hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], 'Protected runtime control drift')
    path = controls['runtime']['path']
    spec = importlib.util.spec_from_file_location('protected_agents_runtime', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract(host, policy, harness, account, *, web, name=None, requests=None):
    validate_extension(policy['shared_runtime'], policy)
    require(selected(policy, harness) and account in policy['accounts'], 'Reviewed image/account required')
    spec, user = policy['harnesses'][harness], policy['accounts'][account]
    receipt = policy['shared_runtime']['images'][harness][spec['image']]
    home, _ = host.home_mount(policy, harness, account)
    requests = requests or dict(root_user=False, docker_socket=False, cap_add=[], checkout_write=False, live_source=False)
    require(set(requests) == {'root_user', 'docker_socket', 'cap_add', 'checkout_write', 'live_source'}, 'Unknown VM privilege/source request')
    allowance = policy['shared_runtime']['grants']
    for key in ('root_user', 'docker_socket', 'checkout_write', 'live_source'):
        require(type(requests[key]) is bool, 'Boolean VM privilege requests required')
        if key != 'live_source':
            require(not requests[key] or allowance[key], 'VM capability request exceeds protected target allowance')
    require(isinstance(requests['cap_add'], list) and set(requests['cap_add']) <= set(allowance['cap_add']), 'VM capability not allowed')
    require(not requests['root_user'] or not requests['live_source'], 'Root cannot execute mutable checkout startup')
    require(not web or not any(requests.values()), 'Managed VM web always uses the baked default capability contract')
    source = dict(mode='baked', path=None, sha256=receipt['source_sha256'], revision=receipt['source_revision'])
    if requests['live_source']:
        require(os.getuid() > 0, 'Only ordinary users may select checkout execution')
        checkout = policy['shared_runtime']['checkout']
        hashes = {}
        for relative in checkout['public_paths']:
            path = Path(checkout['path']) / relative
            info = host.protected(path, owner=policy['accounts'][checkout['owner']]['uid'])
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and info.st_uid == policy['accounts'][checkout['owner']]['uid'] and not info.st_mode & 0o022,
                    'Public startup custody mismatch')
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        result = host.subprocess.run(['git', '-C', checkout['path'], 'rev-parse', 'HEAD'], text=True, capture_output=True,
            check=True, env={'PATH': '/usr/bin:/bin', 'HOME': host.pwd.getpwuid(os.getuid()).pw_dir})
        source = dict(mode='live', path=str(Path(checkout['path']) / 'runtime'), sha256=digest(hashes), revision=result.stdout.strip())
    socket = None
    if requests['docker_socket']:
        host.validate_socket(Path(policy['socket']))
        socket = dict(path=policy['socket'], gid=os.stat(policy['socket']).st_gid)
    return dict(schema=1, harness=harness, mode='web' if web else 'cli', image=spec['image'],
                platform=receipt['platform'], uid=user['uid'], gid=user['gid'],
                name=name or ('agents-runtime-' + hashlib.sha256(policy['target'].encode()).hexdigest()[:16]
                              + '-' + harness + ('-web' if web else '-' + uuid.uuid4().hex)),
                workspace=policy['workspace'], home=home, resources=None if requests['root_user'] else policy['resources'],
                source=source, grants=dict(root_user=requests['root_user'], docker_socket=socket,
                                          cap_add=requests['cap_add'], checkout_write=requests['checkout_write']),
                limits={k: spec[k] for k in ('memory_mb', 'cpus', 'pids')},
                port=spec.get('container_port') if web else None, endpoint='unix://' + policy['socket'], receipt=digest(receipt))


def session_command(host, policy, harness, account, web, arguments, tty, requests=None, *, launch_contract=None):
    module = common(host, policy)
    c = launch_contract or contract(host, policy, harness, account, web=web, requests=requests)
    require(not web or policy['harnesses'][harness]['port'] == c['port'], 'Same-path VM port contract required')
    argv = module.command(c, arguments, tty=tty)
    argv[argv.index('--network') + 1] = policy['network']
    insertion = ['--cgroup-parent', policy['cgroup_parent']]
    for key, value in dict(target=policy['target'], harness=harness, account=account,
                           mode='web' if web else 'cli', uid=str(c['uid']), gid=str(c['gid']),
                           contract=host.web_contract(policy, harness, account)).items():
        insertion += ['--label', 'io.venv-agents.' + key + '=' + value]
    if harness == 'pi' and web:
        insertion += ['--env', 'PI_WEB_ALLOWED_HOSTS=' + host.pi_allowed_hosts(policy)]
    argv[4:4] = insertion
    if c['source']['mode'] == 'live':
        value = 'type=bind,src=' + c['source']['path'] + ',dst=' + c['source']['path'] + ('' if c['grants']['checkout_write'] else ',readonly')
        index = argv.index(value)
        narrow = []
        for relative in policy['shared_runtime']['checkout']['public_paths']:
            path = str(Path(policy['shared_runtime']['checkout']['path']) / relative)
            narrow += ['--mount', 'type=bind,src=' + path + ',dst=' + path + ('' if c['grants']['checkout_write'] else ',readonly')]
        argv[index - 1:index + 1] = narrow
    if web:
        argv[3] = 'create'
        argv.remove('--rm')
        argv.remove('-i')
    return argv


def run_cli(host, argv):
    """Explicit ordinary-user opt-in entry; requests can only narrow protected allowances."""
    parser = argparse.ArgumentParser(prog='venv-agents shared-run')
    parser.add_argument('harness', choices=('pi', 'omp', 'opencode'))
    for flag in ('docker-socket', 'root-user', 'checkout-write', 'live-source'):
        parser.add_argument('--' + flag, action='store_true')
    parser.add_argument('--cap-add', action='append', default=[])
    split = argv.index('--') if '--' in argv else len(argv)
    args = parser.parse_args(argv[:split])
    arguments = argv[split + 1:]
    policy = host.load_policy(host.POLICY)
    require(os.getuid() > 0, 'Shared VM execution requires the enrolled ordinary caller')
    account = host.pwd.getpwuid(os.getuid()).pw_name
    host.validate_runtime(policy, args.harness, account)
    requests = {key: getattr(args, key) for key in ('docker_socket', 'root_user', 'checkout_write', 'live_source', 'cap_add')}
    c = contract(host, policy, args.harness, account, web=False, requests=requests)
    command = session_command(host, policy, args.harness, account, False, arguments,
                              all(os.isatty(fd) for fd in (0, 1, 2)), launch_contract=c)
    state = Path(policy['accounts'][account]['state']) / args.harness
    lock = os.open(state / '.session.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
                and not info.st_mode & 0o077, 'Unsafe selected writer lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        validate_launch(host, policy, args.harness, account)
        path = state / ('.shared-launch-' + uuid.uuid4().hex + '.json')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(c, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        process = host.subprocess.Popen(command, env={'PATH': '/usr/bin:/bin', 'HOME': host.pwd.getpwuid(os.getuid()).pw_dir})
        handlers = {}
        try:
            for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                handlers[sig] = signal.signal(sig, lambda signum, frame: process.send_signal(signum))
            return process.wait()
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
    finally:
        os.close(lock)


def inspect_instance(host, policy, harness, instance):
    owner = instance['Config'].get('Labels', {}).get('io.venv-agents.account')
    require(owner in policy['accounts'], 'Foreign shared-runtime owner')
    user = policy['accounts'][owner]
    record = host.pwd.getpwnam(owner)
    require((record.pw_uid, record.pw_gid) == (user['uid'], user['gid']), 'Shared-runtime NSS identity drift')
    c = contract(host, policy, harness, owner, web=True)
    labels = instance['Config']['Labels']
    for key, value in dict(target=policy['target'], harness=harness, account=owner, mode='web',
                           uid=str(user['uid']), gid=str(user['gid']), contract=host.web_contract(policy, harness, owner)).items():
        require(labels.get('io.venv-agents.' + key) == value, 'Shared VM ownership/target drift')
    require(instance['HostConfig']['NetworkMode'] == policy['network']
            and instance['HostConfig']['CgroupParent'] == policy['cgroup_parent']
            and instance['HostConfig'].get('Init') is True
            and not instance['HostConfig'].get('Binds'), 'VM bridge/cgroup/init drift')
    normalized = copy.deepcopy(instance)
    normalized['HostConfig']['NetworkMode'] = 'bridge'
    common(host, policy).inspect_contract(c, normalized)
    require(re.fullmatch(r'[a-f0-9]{64}', instance['Id']), 'Exact local container ID required')
    return owner


def validate_recovery_journal(host, policy, journal):
    require(set(journal) == {'token', 'harness', 'previous', 'candidate', 'old', 'signature', 'rollback_name', 'stage_name'},
            'Exact protected replacement journal required')
    require(isinstance(journal['token'], str) and re.fullmatch(r'[a-f0-9]{32}', journal['token'])
            and journal['harness'] in ('pi', 'omp', 'opencode', 't3'), 'Invalid recovery token/harness')
    previous, candidate, harness = journal['previous'], journal['candidate'], journal['harness']
    require(isinstance(previous, dict) and isinstance(candidate, dict)
            and previous.get('target') == candidate.get('target') == policy['target']
            and previous.get('shared_runtime') == candidate.get('shared_runtime') == policy['shared_runtime'],
            'Recovery cannot introduce alternate target or executable control paths')
    host.validate_policy(previous)
    host.validate_policy(candidate)
    transition(previous, candidate, harness)
    require(policy in (previous, candidate) and policy['target'] == previous['target']
            and journal['signature'] == digest(dict(previous=previous, candidate=candidate)), 'Recovery policy/signature mismatch')
    require(journal['stage_name'] == 'agents-runtime-stage-' + journal['token']
            and journal['rollback_name'] == host.web_name(previous, harness) + '-rollback-' + journal['token'],
            'Recovery identities must be derived from the protected transaction')
    if previous['harnesses'][harness]['image'] is None or harness == 'omp':
        require(journal['old'] is None, 'Unexpected retained container in first-install/CLI journal')


def validate_native_retirement(host, policy, record, journal, profile):
    """One narrowly recorded missing control, never blanket missing-file admission."""
    require(journal is not None, 'Missing native profile requires exact protected recovery evidence')
    validate_recovery_journal(host, policy, journal)
    previous, candidate, harness = journal['previous'], journal['candidate'], journal['harness']
    require(policy == previous and previous['default_harness'] == 'native-pi'
            and previous['harnesses'][harness]['image'] is None and candidate['default_harness'] == harness,
            'Missing native profile is not part of this first-install transition')
    config_path = host.POLICY.with_name('gateway.json')
    info = host.protected(config_path, private=True)
    require(stat.S_ISREG(info.st_mode) and hashlib.sha256(config_path.read_bytes()).hexdigest()
            == dict(record['files'], **record['shared_runtime_seal']['files']).get(str(config_path)), 'Unsealed native recovery configuration')
    config = json.loads(config_path.read_text())
    require(config['target'] == policy['target'] and config.get('native_profile') == str(profile)
            and config['activation_lock'] == str(host.POLICY.with_name('activation.lock')), 'Native recovery target/path mismatch')
    path = Path(config['web']['paths']['recovery_dir']) / ('install-' + harness + '.json')
    info = host.protected(path, private=True)
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'Protected first-install gateway journal required')
    snapshot = json.loads(path.read_text())
    require(snapshot['transaction'] == journal['signature'] and snapshot['native_active'] is True
            and snapshot['native_enabled'] is True and isinstance(snapshot.get('profile'), dict), 'Native retirement journal mismatch')
    saved = snapshot['profile']
    require(set(saved) == {'content', 'mode'} and isinstance(saved['content'], str)
            and hashlib.sha256(saved['content'].encode()).hexdigest() == record['files'][str(profile)]
            and type(saved['mode']) is int and 0 <= saved['mode'] <= 0o777 and not saved['mode'] & 0o022,
            'Native recovery bytes must match the original enrollment seal')


def validate_seal(host, policy, *, recovery=None):
    marker = absolute(policy['shared_runtime']['enrollment_marker'])
    host.protected(marker, private=True)
    record = json.loads(marker.read_text())
    require(record['target'] == policy['target'] and record['shared_runtime_seal']['extension'] == policy['shared_runtime'],
            'Runtime opt-in must match the exact promoted enrollment seal')
    def shape(value):
        value = copy.deepcopy(value)
        value.pop('shared_runtime', None)
        value.pop('default_harness')
        value['web'].pop('default_harness')
        for item in value['harnesses'].values():
            item['image'] = None
        return value
    require(shape(policy) == shape(record['bootstrap_policy']), 'Immutable enrolled policy drift')
    missing_profile = None
    for name, expected in dict(record['files'], **record['shared_runtime_seal']['files']).items():
        path = Path(name)
        if path == host.POLICY:
            continue  # Runtime owns selected IDs/defaults, never its static shape.
        if name == record.get('retired_profile') and not path.exists() and not path.is_symlink() and policy['default_harness'] not in (None, 'native-pi'):
            continue
        if name == record.get('retired_profile') and not path.exists() and not path.is_symlink() and recovery is not None:
            missing_profile = path
            continue
        info = host.protected(path)
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'Enrollment control drift before replacement')
        metadata = record['shared_runtime_seal'].get('metadata', {}).get(name)
        if metadata:
            require((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (metadata['uid'], metadata['gid'], metadata['mode']),
                    'Promoted control metadata drift before activation')
    if missing_profile is not None:
        validate_native_retirement(host, policy, record, recovery, missing_profile)


def validate_state_layout(host, policy, harness):
    """No implicit legacy HOME conversion. Inspect directory metadata, not secrets.

    The old entrypoint writes absolute resource links and a different Pi agents
    root. Until a reviewed layout migration exists, only absent/empty managed
    roots can enter the new contract. Check every identity affected by the image
    pointer, including CLI-only OMP accounts.
    """
    if selected(policy, harness):
        return
    relative = {'pi': '.pi/agent', 'omp': '.omp/agent', 'opencode': '.config/opencode', 't3': 'base'}[harness]
    for account, user in policy['accounts'].items():
        home = Path(host.home_mount(policy, harness, account)[0])
        info = host.protected(home, owner=user['uid'], private=True)
        require(stat.S_ISDIR(info.st_mode) and info.st_gid == user['gid'], 'Private HOME layout custody mismatch')
        current = home
        for part in Path(relative).parts:
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                break
            require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), 'Redirected legacy state layout refused; no repair')
            require((info.st_uid, info.st_gid) == (user['uid'], user['gid']) and not info.st_mode & 0o022
                    and info.st_mode & 0o200, 'Legacy state layout directory custody/permissions mismatch')
        else:
            require(not any(current.iterdir()), 'Populated legacy state layout requires an explicit migration; state preserved')


def check_image(host, policy, harness, image):
    receipt = policy['shared_runtime']['images'][harness][image]
    actual = host.docker_call(policy, ['image', 'inspect', image])
    require(actual.returncode == 0, 'Reviewed local image is unavailable; never pull during activation')
    value = json.loads(actual.stdout)[0]
    require(value['Id'] == image and value['Os'] + '/' + value['Architecture'] == receipt['platform'], 'Image/platform drift')
    native = {'x86_64': 'linux/amd64', 'aarch64': 'linux/arm64'}.get(os.uname().machine)
    require(native == receipt['platform'], 'Host platform check retained; no implicit emulation')
    if harness == 'omp':
        flags = [line.split(':', 1)[1].split() for line in Path('/proc/cpuinfo').read_text().splitlines()
                 if ':' in line and line.split(':', 1)[0].strip() == 'flags']
        require(flags and all('sse4_2' in row for row in flags), 'OMP requires SSE4.2 on every host CPU')
    config = value['Config']
    labels = config.get('Labels') or {}
    require(labels.get('io.agents-runtime.harness') == harness and labels.get('io.agents-runtime.contract') == '1'
            and labels.get('io.agents-runtime.resolution') == receipt['resolution_sha256']
            and not config.get('Volumes'), 'Reviewed image receipt/volume mismatch')
    forbidden = {'DOCKER_HOST', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'BASH_ENV', 'ENV'}
    require(not any(item.split('=', 1)[0] in forbidden for item in config.get('Env') or []), 'Image execution override refused')
    user = policy['accounts'][policy['web']['default_account']]
    executable = '/opt/agents-runtime/packages/node_modules/.bin/' + {'pi': 'pi', 'omp': 'omp', 'opencode': 'opencode', 't3': 't3'}[harness]
    created = host.docker_call(policy, ['create', '--pull=never', '--network', 'none', '--read-only',
        '--user', f'{user["uid"]}:{user["gid"]}', '--cap-drop=ALL', '--security-opt=no-new-privileges',
        '--memory', '512m', '--memory-swap', '512m', '--cpus', '1', '--pids-limit', '64',
        '--cgroup-parent', policy['cgroup_parent'], '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m',
        '--env', 'HOME=/tmp', '--env', 'OPENCODE_DISABLE_AUTOUPDATE=1', '--env', 'DISABLE_AUTOUPDATER=1',
        '--entrypoint', executable, image, '--version'])
    identity = created.stdout.strip()
    require(created.returncode == 0 and re.fullmatch(r'[a-f0-9]{64}', identity), 'Mountless version probe creation failed')
    try:
        started = host.docker_call(policy, ['container', 'start', '--attach', identity])
        status = host.docker_call(policy, ['container', 'inspect', '--format', '{{.State.ExitCode}}', identity])
        require(started.returncode == 0 and started.stdout.strip() and status.returncode == 0
                and status.stdout.strip() == '0', 'Reviewed image version probe failed')
    finally:
        require(host.docker_call(policy, ['container', 'rm', '--force', identity]).returncode == 0, 'Version probe cleanup failed')


def inspect(host, policy, identity):
    result = host.docker_call(policy, ['container', 'inspect', identity])
    if result.returncode:
        require('No such container:' in result.stderr or 'No such object:' in result.stderr, 'Docker inspection failure is not absence')
        return None
    values = json.loads(result.stdout)
    require(isinstance(values, list) and len(values) == 1, 'Ambiguous local container inspection')
    return values[0]


def mutate(host, policy, argv):
    result = host.docker_call(policy, argv)
    require(result.returncode == 0, 'Selected container operation failed; retain recovery journal')
    return result.stdout.strip()


def stage_contract(host, journal):
    candidate, harness = journal['candidate'], journal['harness']
    c = contract(host, candidate, harness, candidate['web']['default_account'], web=True, name=journal['stage_name'])
    c.update(home='/disposable-home', workspace='/tmp', resources=None, port=candidate['shared_runtime']['staging_ports'][harness])
    c['limits'] = candidate['shared_runtime']['staging_limits']
    return c


def stage_instance(host, journal, value):
    c = stage_contract(host, journal)
    require(value['Name'] == '/' + journal['stage_name'] and value['Image'] == c['image']
            and value['Config'].get('Labels', {}).get('io.venv-agents.transaction') == journal['token']
            and value['Config']['Labels'].get('io.agents-runtime.contract') == common(host, journal['candidate']).fingerprint(c),
            'Foreign staging container; no cleanup')
    config, options = value['Config'], value['HostConfig']
    require(config['User'] == f'{c["uid"]}:{c["gid"]}' and config['Entrypoint'] == ['/usr/bin/python3']
            and config['Cmd'] == ['-I', '/opt/agents-runtime/entry.py', c['harness'], '--web', '--port', str(c['port']), '--'],
            'Staging executable/identity drift')
    require(not options.get('Privileged') and options.get('ReadonlyRootfs') is True
            and set(options.get('CapDrop') or []) == {'ALL'} and not options.get('CapAdd') and not options.get('GroupAdd')
            and set(options.get('SecurityOpt') or []) in ({'no-new-privileges'}, {'no-new-privileges=true'})
            and not options.get('Binds') and not options.get('Devices') and not options.get('DeviceRequests')
            and not options.get('VolumesFrom') and not options.get('PidMode') and options.get('IpcMode', 'private') == 'private',
            'Unsafe staging authority')
    require(all(m['Type'] == 'tmpfs' for m in value['Mounts'])
            and options['NetworkMode'] == journal['candidate']['network']
            and options['CgroupParent'] == journal['candidate']['cgroup_parent']
            and options['PortBindings'] == {str(c['port']) + '/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(c['port'])}]},
            'Staging must be disposable, mountless and on its finite loopback port')
    require(options['Memory'] == c['limits']['memory_mb'] * 1024**2 and options['MemorySwap'] == options['Memory']
            and options['NanoCpus'] == int(c['limits']['cpus'] * 10**9) and options['PidsLimit'] == c['limits']['pids'],
            'Staging resource drift')
    require(options.get('Tmpfs') == {'/tmp': 'rw,nosuid,nodev,size=256m',
            '/home/agent': f'rw,nosuid,nodev,mode=0700,uid={c["uid"]},gid={c["gid"]},size=256m'}, 'Unknown staging tmpfs')
    environment = dict(item.split('=', 1) for item in config.get('Env') or [])
    require(environment.get('HOME') == '/home/agent' and 'DOCKER_HOST' not in environment
            and 'AGENTS_RUNTIME_RESOURCES' not in environment, 'Staging must not expose providers/resources')


def remove_stage(host, journal):
    if journal['harness'] == 'omp':
        return
    value = inspect(host, journal['candidate'], journal['stage_name'])
    if value is not None:
        stage_instance(host, journal, value)
        mutate(host, journal['candidate'], ['container', 'rm', '--force', value['Id']])


def stage(host, config, journal, lock_fd):
    candidate, h = journal['candidate'], journal['harness']
    if h == 'omp':
        return  # Exact numeric-user mountless --version already succeeded.
    c = stage_contract(host, journal)
    module = common(host, candidate)
    argv = module.command(c, [], tty=False)[3:]
    argv[0] = 'create'
    argv.remove('--rm')
    argv.remove('-i')
    while '--mount' in argv:
        index = argv.index('--mount')
        del argv[index:index + 2]
    argv[argv.index('--network') + 1] = candidate['network']
    argv[1:1] = ['--cgroup-parent', candidate['cgroup_parent'], '--label', 'io.venv-agents.transaction=' + journal['token'],
                 '--tmpfs', f'/home/agent:rw,nosuid,nodev,mode=0700,uid={c["uid"]},gid={c["gid"]},size=256m']
    if h == 'pi':
        argv[1:1] = ['--env', 'PI_WEB_ALLOWED_HOSTS=' + host.pi_allowed_hosts(candidate)]
    require(inspect(host, candidate, journal['stage_name']) is None, 'Staging identity already exists')
    identity = mutate(host, candidate, argv)
    require(re.fullmatch(r'[a-f0-9]{64}', identity), 'Staging creation returned invalid identity')
    mutate(host, candidate, ['container', 'start', identity])
    value = inspect(host, candidate, identity)
    require(value is not None and value['State']['Running'], 'Staging did not remain running')
    stage_instance(host, journal, value)
    host.activation_gateway(config, 'install-stage', journal, lock_fd=lock_fd)
    remove_stage(host, journal)


def quiet_writers(host, policy, harness, old):
    result = host.docker_call(policy, ['container', 'ls', '--quiet', '--no-trunc'])
    require(result.returncode == 0, 'Cannot inspect active writers')
    homes = [Path(host.home_mount(policy, harness, account)[0]) for account in policy['accounts']]
    for identity in result.stdout.split():
        require(re.fullmatch(r'[a-f0-9]{64}', identity), 'Unknown active container identity')
        if old and identity == old['Id']:
            continue
        value = inspect(host, policy, identity)
        require(value is not None, 'Container changed while inspecting writers; retry')
        for mount in value['Mounts']:
            if mount.get('Type') == 'bind' and mount.get('RW'):
                source = Path(mount['Source'])
                require(not any(source == home or source in home.parents or home in source.parents for home in homes),
                        'Active CLI/foreign writer uses selected private state; quiesce it explicitly')


def stage_budget(host, policy):
    budget = policy.get('resource_budget', {}).get('memory_max_mb', sum(s['memory_mb'] for s in policy['harnesses'].values()))
    used = 0
    result = host.docker_call(policy, ['container', 'ls', '--quiet', '--no-trunc'])
    require(result.returncode == 0, 'Cannot prove available staging resource headroom')
    for identity in result.stdout.split():
        require(re.fullmatch(r'[a-f0-9]{64}', identity), 'Invalid workload identity during capacity check')
        value = inspect(host, policy, identity)
        require(value is not None, 'Workload changed during staging capacity check')
        if value['HostConfig'].get('CgroupParent') == policy['cgroup_parent']:
            memory = value['HostConfig'].get('Memory', 0)
            require(type(memory) is int and memory > 0, 'Unbounded shared-cgroup writer blocks staging')
            used += memory
    require(used + policy['shared_runtime']['staging_limits']['memory_mb'] * 1024**2 <= budget * 1024**2,
            'Insufficient bounded staging headroom; quiesce workloads, never risk OOM of retained services')


def validate_launch(host, policy, harness, account):
    """Under the selected ordinary-account session lock, refuse a second HOME writer."""
    require(not (harness == 'pi' and policy['accounts'][account].get('native_pi_home')),
            'Native Pi HOME cannot start a shared writer without supported quiescence')
    selected_policy = copy.deepcopy(policy)
    selected_policy['accounts'] = {account: policy['accounts'][account]}
    quiet_writers(host, selected_policy, harness, None)


def authorize_candidate(host):
    lock = host.POLICY.with_name('activation.lock')
    info = host.protected(lock, private=True)
    found = False
    for path in Path('/proc/self/fd').iterdir():
        try:
            opened = os.fstat(int(path.name))
        except (OSError, ValueError):
            continue
        if (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino):
            fcntl.flock(int(path.name), fcntl.LOCK_EX | fcntl.LOCK_NB)
            found = True
    require(found, 'Shared candidate lifecycle requires inherited protected activation authority')


def old_instance(host, journal):
    original = journal['old']
    if original is None:
        return None
    value = inspect(host, journal['previous'], original['Id'])
    require(value is not None and value['Name'] in (original['Name'], '/' + journal['rollback_name']), 'Retained original container identity missing/drifted')
    normalized = copy.deepcopy(value)
    normalized['Name'] = original['Name']
    host.validate_web_instance(journal['previous'], journal['harness'], normalized)
    for key in ('Config', 'HostConfig', 'Mounts', 'Image', 'Id'):
        require(normalized[key] == original[key], 'Retained previous container contract drift')
    require(normalized.get('GraphDriver') == original.get('GraphDriver'), 'Retained writable-layer identity drift')
    return value


def candidate_instance(host, journal):
    if journal['harness'] == 'omp':
        return None
    value = inspect(host, journal['candidate'], host.web_name(journal['candidate'], journal['harness']))
    if value is not None and journal['old'] and value['Id'] == journal['old']['Id']:
        return None  # Before rename: canonical name still belongs to exact original.
    if value is not None:
        host.validate_web_instance(journal['candidate'], journal['harness'], value)
        require(value['Config']['Labels'].get('io.venv-agents.transaction') == journal['token'], 'Candidate lacks transaction ownership')
    return value


def recover_replacement(host, config, journal, lock_fd):
    previous, candidate, h = journal['previous'], journal['candidate'], journal['harness']
    transition(previous, candidate, h)
    current = host.load_policy(host.POLICY)
    require(current in (previous, candidate) and journal['signature'] == digest({'previous': previous, 'candidate': candidate}),
            'Unknown policy state during replacement recovery')
    require(journal['stage_name'] == 'agents-runtime-stage-' + journal['token']
            and journal['rollback_name'] == host.web_name(previous, h) + '-rollback-' + journal['token'],
            'Recovery identities must be transaction-bound, never caller paths')
    candidate_file = host.POLICY.with_name('activation-candidate.json')
    host.protected(candidate_file)
    require(json.loads(candidate_file.read_text()) == candidate, 'Candidate control drift during recovery')
    remove_stage(host, journal)
    value = candidate_instance(host, journal)
    committed = current == candidate
    if committed:
        require(h == 'omp' or value is not None and value['State']['Running'], 'Published candidate is unavailable; retain journal, never resurrect old state')
        host.activation_gateway(config, 'install-finalize', journal, lock_fd=lock_fd)
    else:
        if value is not None:
            mutate(host, candidate, ['container', 'rm', '--force', value['Id']])
        old = old_instance(host, journal)
        if old is not None:
            original = journal['old']
            if old['Name'] != original['Name']:
                require(inspect(host, previous, original['Name'][1:]) is None, 'Original name occupied; no foreign takeover')
                mutate(host, previous, ['container', 'rename', old['Id'], original['Name'][1:]])
            if old['State']['Running'] != original['State']['Running']:
                mutate(host, previous, ['container', 'start' if original['State']['Running'] else 'stop', old['Id']])
            restored = old_instance(host, journal)
            require(restored['State']['Running'] == original['State']['Running'], 'Original running/stopped state not restored')
        host.activation_gateway(config, 'install-rollback', journal, lock_fd=lock_fd)
    pending = host.POLICY.with_name('shared-replacement.json')
    host.protected(pending, private=True)
    require(json.loads(pending.read_text()) == journal and json.loads(candidate_file.read_text()) == candidate,
            'Replacement controls changed during finalization; retain the admission journal')
    archive = pending.with_name('shared-replacement-' + journal['token'] + ('-committed.json' if committed else '-restored.json'))
    candidate_file.unlink()
    if archive.exists():
        host.protected(archive, private=True)
        require(archive.read_bytes() == pending.read_bytes(), 'Replacement archive collision')
        pending.unlink()
    else:
        os.replace(pending, archive)
    directory = os.open(pending.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def activate(host, config, policy, harness, image, lock_fd):
    """Existing activation lock is held. Policy publication is the image commit point."""
    pending = host.POLICY.with_name('shared-replacement.json')
    candidate_file = host.POLICY.with_name('activation-candidate.json')
    if pending.exists() or pending.is_symlink():
        info = host.protected(pending, private=True)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'Private regular replacement journal required')
        journal = json.loads(pending.read_text())
        validate_recovery_journal(host, policy, journal)
        validate_seal(host, policy, recovery=journal)
        # A crash can precede candidate-file publication; reconstruct only exact recorded bytes.
        if candidate_file.exists():
            host.protected(candidate_file)
            require(json.loads(candidate_file.read_text()) == journal['candidate'], 'Interrupted candidate drift')
        else:
            host.atomic_json(candidate_file, journal['candidate'])
        recover_replacement(host, config, journal, lock_fd)
        policy = host.load_policy(host.POLICY)
    validate_seal(host, policy)
    if policy['harnesses'][harness]['image'] == image:
        return 0
    require(policy['default_harness'] != 'native-pi'
            and not (harness == 'pi' and any(u.get('native_pi_home') for u in policy['accounts'].values())),
            'Native-to-shared admission is blocked until exact native quiescence and HOME migration are supported')
    candidate = copy.deepcopy(policy)
    candidate['harnesses'][harness]['image'] = image
    if policy['default_harness'] in (None, 'native-pi'):
        candidate['default_harness'] = harness
        candidate['web']['default_harness'] = None if harness == 'omp' else harness
    transition(policy, candidate, harness)  # Before image execution or HOME access.
    host.validate_policy(candidate)
    check_image(host, candidate, harness, image)
    with host.maintenance_lock(host.POLICY, exclusive=True):
        require(not host.POLICY.with_name('activation-pending.json').exists(), 'Legacy activation pending')
        old = None if harness == 'omp' else host.inspect_web(policy, harness)
        if old is not None:
            require(host.validate_web_instance(policy, harness, old) == policy['web']['default_account'],
                    'Replacement must retain the configured private-state owner')
            require(old['HostConfig'].get('RestartPolicy', {}).get('Name', '') in ('', 'no'), 'Unknown container restart authority')
            require(not old['State'].get('Paused') and not old['State'].get('Restarting')
                    and old['State']['Status'] in ('running', 'exited', 'created'), 'Unstable old container; preserve for explicit recovery')
        quiet_writers(host, policy, harness, old)
        validate_state_layout(host, policy, harness)
        if harness != 'omp':
            stage_budget(host, policy)
        owner = policy['web']['default_account']
        user = policy['accounts'][owner]
        home = Path(host.home_mount(policy, harness, owner)[0])
        info = host.protected(home, owner=user['uid'], private=True)
        require(stat.S_ISDIR(info.st_mode) and info.st_gid == user['gid'], 'Physical private HOME with exact owner/group required; no repair')
        token = uuid.uuid4().hex
        journal = dict(token=token, harness=harness, previous=policy, candidate=candidate, old=old,
                       signature=digest({'previous': policy, 'candidate': candidate}),
                       rollback_name=host.web_name(policy, harness) + '-rollback-' + token,
                       stage_name='agents-runtime-stage-' + token)
        if candidate_file.exists():
            host.protected(candidate_file)
            require(json.loads(candidate_file.read_text()) == policy, 'Unknown stale candidate file; preserve for review')
            candidate_file.unlink()
        host.atomic_json(pending, journal, 0o600)  # Closes normal launch admission before maintenance release.
    try:
        host.atomic_json(candidate_file, candidate)
        stage(host, config, journal, lock_fd)
        host.activation_gateway(config, 'install-prepare', journal, lock_fd=lock_fd)
        quiet_writers(host, policy, harness, old)
        if old is not None:
            current = old_instance(host, journal)
            require(inspect(host, policy, journal['rollback_name']) is None, 'Rollback namespace collision')
            if current['State']['Running']:
                mutate(host, policy, ['container', 'stop', '--time', '30', old['Id']])
            require(not old_instance(host, journal)['State']['Running'], 'Old selected writer did not quiesce')
            mutate(host, policy, ['container', 'rename', old['Id'], journal['rollback_name']])
        validate_state_layout(host, policy, harness)  # Recheck after old writers are quiesced, also for OMP.
        if harness != 'omp':
            require(inspect(host, candidate, host.web_name(candidate, harness)) is None, 'Candidate name occupied; no adoption')
            argv = session_command(host, candidate, harness, policy['web']['default_account'], True, [], False)[3:]
            argv[1:1] = ['--label', 'io.venv-agents.transaction=' + token]
            identity = mutate(host, candidate, argv)
            require(re.fullmatch(r'[a-f0-9]{64}', identity), 'Invalid canonical candidate identity')
            mutate(host, candidate, ['container', 'start', identity])
            value = candidate_instance(host, journal)
            require(value is not None and value['State']['Running'], 'Real-state candidate failed startup')
        host.activation_gateway(config, 'install-check', journal, lock_fd=lock_fd)
        host.activation_gateway(config, 'install-commit', journal, lock_fd=lock_fd)
        require(host.load_policy(host.POLICY) == policy, 'Policy changed before publication')
        host.atomic_json(host.POLICY, candidate)
        recover_replacement(host, config, journal, lock_fd)
    except Exception:
        if pending.exists():
            if not candidate_file.exists():
                host.atomic_json(candidate_file, candidate)
            recover_replacement(host, config, journal, lock_fd)
        raise
    return 0
