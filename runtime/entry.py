#!/usr/bin/env python3
"""Baked common startup for the explicitly selected runtime, not legacy init."""
import argparse
import base64
import fcntl
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import time

BIN = '/opt/agents-runtime/packages/node_modules/.bin/'
CATALOG = json.loads(Path(__file__).with_name('harnesses.json').read_text())
MODES = {name: spec['modes'] for name, spec in CATALOG['harnesses'].items()}


def require(value, message):
    if not value:
        raise ValueError(message)


def directory(path):
    require(path.is_absolute() and path.resolve() == path, 'Redirected private directory refused')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) and (info.st_uid, info.st_gid) == (os.getuid(), os.getgid())
            and not info.st_mode & 0o077,
            'Private directory ownership/mode mismatch; no repair')


def link(destination, source):
    require(source.exists(), 'Public resource missing')
    if destination.exists() or destination.is_symlink():
        require(not destination.is_symlink() or destination.resolve() == source.resolve(), 'Resource link conflict; preserve for manual review')
        return
    try:
        destination.symlink_to(source)
    except FileExistsError:
        # A concurrent initializer may publish the same link; never replace it.
        require(not destination.is_symlink() or destination.resolve() == source.resolve(),
                'Resource link conflict; preserve for manual review')


def public_agents(document: dict, resources: Path) -> dict:
    """Project public agent metadata only, never providers or global policy."""
    require(isinstance(document, dict), 'Canonical config object required')
    agents = document.get('agents')
    require(isinstance(agents, dict) and agents, 'Canonical agent map required')
    result = {}
    for name, agent in agents.items():
        require(re.fullmatch(r'[A-Za-z0-9_ -]+', name), 'Invalid public agent name')
        require(isinstance(agent, dict) and not set(agent) - {
            'system', 'request', 'model', 'hidden', 'mode', 'description', 'permissions'}, 'Unknown public agent fields refused')
        if name == 'title' and set(agent) == {'model'}:
            result[name] = dict(agent)
            continue
        require(agent.get('mode') in ('all', 'primary', 'subagent'), 'Explicit canonical mode required')
        require(isinstance(agent.get('description'), str), 'Public description required')
        prompt = agent.get('system', '')
        prefix = '{file:' + str(resources) + '/'
        if isinstance(prompt, str) and prompt.startswith(prefix):
            prompt = '{file:./' + prompt[len(prefix):]
        require(isinstance(prompt, str) and re.fullmatch(
            r'\{file:\./(?:system|gsd)/[A-Za-z0-9_-]+\.md\}', prompt), 'Public prompt reference required')
        if 'permissions' in agent:
            require(isinstance(agent['permissions'], list) and all(
                isinstance(rule, dict) and set(rule) == {'action', 'resource', 'effect'}
                and rule['effect'] in ('allow', 'ask', 'deny')
                and isinstance(rule['action'], str) and isinstance(rule['resource'], str)
                for rule in agent['permissions']), 'Public permission rules required')
        result[name] = dict(agent, system='{file:' + str(resources / prompt[8:-1]) + '}')
    return {'$schema': 'https://opencode.ai/config.json', 'agents': result}


def read_jsonc(text: str) -> dict:
    """Comments/trailing commas are allowed; duplicate keys are ambiguous."""
    string = r'"(?:[^"\\]|\\.)*"'
    text = re.sub(string + r'|//[^\r\n]*|/\*[\s\S]*?\*/',
                  lambda m: m[0] if m[0].startswith('"') else ' ', text)
    text = re.sub(string + r'|,\s*(?=[}\]])',
                  lambda m: m[0] if m[0].startswith('"') else '', text)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Ambiguous configuration')
            result[key] = value
        return result

    result = json.loads(text, object_pairs_hook=unique)
    require(isinstance(result, dict), 'Config object required')
    return result


def first_write(destination: Path, text: str) -> bool:
    """Publish complete private bytes exclusively; existing content always wins."""
    fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix='.opencode-seed-')
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            return False
        fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return True
    finally:
        os.unlink(temporary)


def seed_opencode(home: Path, resources: Path) -> dict:
    """Optional public V2 agent-only seed; canonical runtime uses baked config.

    Deliberately self-contained: baked startup must not import legacy/mutable code.
    """
    directory(home)
    root = home / '.config/opencode'
    directory(root)
    fd = os.open(root / '.runtime-init.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and (info.st_uid, info.st_gid) == (os.getuid(), os.getgid())
                and info.st_nlink == 1 and not info.st_mode & 0o077, 'Unsafe startup lock')
        fcntl.flock(fd, fcntl.LOCK_EX)
        return _seed_opencode(root, resources)
    finally:
        os.close(fd)


def _seed_opencode(root: Path, resources: Path) -> dict:
    destination = root / 'opencode.json'
    if destination.exists() or destination.is_symlink():
        return dict(changed=False, skipped='opencode.json exists; preserved without inspection')
    excluded = set()
    for name in ('opencode.jsonc',):
        path = root / name
        if path.is_symlink():
            return dict(changed=False, skipped='Redirected private config; manual merge required')
        if not path.exists():
            continue
        if not path.is_file():
            return dict(changed=False, skipped='Non-file private config; manual merge required')
        try:
            private = read_jsonc(path.read_text())
            if set(private) & {'agent', 'permission', 'tools', 'mode', 'version'}:
                return dict(changed=False, skipped='V1 private config; clean V2 config required')
            overrides = private.get('agents', {})
            require(isinstance(overrides, dict), 'Private agent map required')
            excluded.update(overrides)
        except (ValueError, OSError):
            return dict(changed=False, skipped='Unparseable private config; manual merge required')
    require(resources.is_absolute() and resources.resolve(strict=True) == resources,
            'Physical public resources required')
    manifest = resources / 'opencode-agents.json'
    require(not manifest.is_symlink(), 'Redirected public agent manifest refused')
    if not manifest.is_file():
        return dict(changed=False, skipped='Public agent manifest absent; publish reviewed resources')
    document = public_agents(read_jsonc(manifest.read_text()), resources)
    excluded.intersection_update(document['agents'])
    document['agents'] = {name: agent for name, agent in document['agents'].items() if name not in excluded}
    for agent in document['agents'].values():
        if 'system' not in agent:
            continue
        prompt = Path(agent['system'][6:-1])
        require(prompt.resolve(strict=True) == prompt and prompt.is_file(), 'Physical public prompt required')
        with prompt.open('rb') as stream:
            stream.read(1)
    if not document['agents']:
        return dict(changed=False, skipped='All canonical names have private overrides')
    if not first_write(destination, json.dumps(document, indent=2) + '\n'):
        return dict(changed=False, skipped='Concurrent opencode.json publication preserved')
    return dict(changed=True, skipped='', excluded=sorted(excluded))


def migrate_opencode_config(root: Path) -> None:
    """Retire only the old runtime filename; preserve syntax, bytes and file mode."""
    legacy, destination = root / 'config.json', root / 'opencode.json'
    if not legacy.exists() and not legacy.is_symlink():
        return
    fd = os.open(legacy, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and (info.st_uid, info.st_gid) == (os.getuid(), os.getgid()),
                'Unsafe legacy config.json; preserved for manual review')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            read_jsonc(stream.read().decode())  # Validate without reserializing private settings.
        native = [root / name for name in ('opencode.json', 'opencode.jsonc')
                  if (root / name).exists() or (root / name).is_symlink()]
        if native:
            # Recover only a publication-before-retirement interruption of this
            # exact move, not merely equivalent documents with unknown precedence.
            require(native == [destination] and not destination.is_symlink()
                    and info.st_nlink == 2 and destination.stat().st_ino == info.st_ino
                    and destination.stat().st_dev == info.st_dev,
                    'Legacy config.json and native config coexist; reconcile precedence explicitly')
        else:
            require(info.st_nlink == 1, 'Hardlinked legacy config.json; preserved for manual review')
            os.link(legacy, destination, follow_symlinks=False)  # Atomic, exclusive publication; never replace native files.
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
            legacy.unlink()
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        os.close(fd)


def publish_opencode_plugins(root: Path, defaults: Path) -> None:
    """Publish exact managed files, never hide private plugins behind a directory link."""
    files = ('plugins/first-prompt-title.js', 'plugins/background-subagents.js',
             'tui-plugins/session-title.mjs', 'tui-plugins/session-title/tui.js')
    directories = ('plugins', 'tui-plugins', 'tui-plugins/session-title')
    reset = []
    retired = []
    # Validate everything before changing anything. Children of a replaced public
    # directory link are image files, not private paths to inspect or unlink.
    for relative in directories:
        destination = root / relative
        if any(parent in destination.parents for parent in reset):
            continue
        if destination.is_symlink():
            require(os.readlink(destination) in (str(defaults / relative),
                    '/opt/agent/opencode-plugins/' + relative), 'Unknown plugin directory link; manual review required')
            reset.append(destination)
        elif destination.exists():
            info = destination.stat()
            require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                    and not info.st_mode & 0o022, 'Unsafe private plugin directory')
    for relative in files:
        source, destination = defaults / relative, root / relative
        require(source.resolve(strict=True) == source and source.is_file(), 'Physical canonical plugin required')
        if any(parent in destination.parents for parent in reset):
            continue
        if destination.exists() or destination.is_symlink():
            require(destination.is_symlink() and os.readlink(destination) == str(source),
                    'Canonical plugin name conflict; preserve for manual review')
    for name in ('background-agents', 'worktree', 'notify'):
        relative = 'plugins/kdco-' + name + '.ts'
        destination = root / relative
        if any(parent in destination.parents for parent in reset):
            continue
        if destination.exists() or destination.is_symlink():
            require(destination.is_symlink() and os.readlink(destination) in (
                str(defaults / relative), '/opt/agent/opencode-plugins/' + relative),
                'Unrecognized retired KDCO wrapper; remove explicitly after review')
            retired.append(destination)
    for destination in reset:
        destination.unlink()  # Only the exact known public link, never its target.
    for relative in directories:
        (root / relative).mkdir(mode=0o700, exist_ok=True)
    for destination in retired:
        destination.unlink()
    for relative in files:
        destination = root / relative
        if not destination.is_symlink():
            destination.symlink_to(defaults / relative)


def initialize(harness: str, home: Path, resources: Path | None) -> None:
    require(harness in MODES, 'Unsupported harness')
    directory(home)
    root = home / {'pi': '.pi/agent', 'omp': '.omp/agent', 'opencode': '.config/opencode',
                   'claude': '.claude', 't3': 'base'}[harness]
    directory(root)
    if harness == 'opencode':
        defaults = Path('/opt/opencode-defaults')
        migrate_opencode_config(root)
        native = [root / name for name in ('opencode.json', 'opencode.jsonc')]
        require(not any(path.is_symlink() for path in native), 'Redirected private config refused')
        if not any(path.exists() for path in native):
            first_write(root / 'opencode.json', (defaults / 'opencode.json').read_text())
        require(not (root / 'cli.json').is_symlink(), 'Redirected private config refused')
        first_write(root / 'cli.json', (defaults / 'cli.json').read_text())
        publish_opencode_plugins(root, defaults)
        if resources is None:
            for name in ('system', 'gsd'):
                link(root / name, defaults / name)
    if harness == 't3':
        directory(home / 'logs')
        for name in ('userdata', 'worktrees', 'caches'):
            path = root / name
            if path.exists() or path.is_symlink():
                directory(path)  # Inspect existing roots only, never traverse/repair.
        return
    if resources is None:
        return
    require(resources.is_absolute() and resources.resolve(strict=True) == resources and resources.is_dir(),
            'Physical reviewed public resources required')
    names = {'pi': ('skills', 'prompts'), 'omp': ('commands',),
             'opencode': ('skills', 'commands', 'system', 'gsd'), 'claude': ('skills', 'commands')}[harness]
    for name in names:
        link(root / name, resources / name)
    if harness == 'omp':
        link(root / 'SYSTEM.md', resources / 'system/build.md')
        directory(root / 'skills')
        for source in sorted([*(resources / 'skills').glob('*/SKILL.md'), *(resources / 'skills').glob('*/*/SKILL.md')]):
            require(resources / 'skills' in source.resolve().parents, 'External skill refused')
            link(root / 'skills' / source.parent.name, source.parent)
    if harness in ('pi', 'omp'):
        directory(root / 'agents')
        for source in sorted((resources / 'system').glob('*.md')):
            require(source.resolve().parent == resources / 'system', 'External agent source refused')
            link(root / 'agents' / ('system-' + source.name), source)


def command(harness: str, arguments: list[str], *, web: bool, port: int | None) -> list[str]:
    require(harness in MODES and ('web' if web else 'cli') in MODES[harness], 'Unsupported harness mode')
    require(all(isinstance(arg, str) and '\x00' not in arg for arg in arguments), 'Invalid arguments')
    require(not web or not arguments, 'Web startup arguments are fixed')
    if web:
        require(type(port) is int and 1024 <= port <= 65535, 'Explicit unprivileged web port required')
        if harness == 'pi':
            return [BIN + 'pi-web', '--hostname', '0.0.0.0', '--port', str(port), '--no-open']
        if harness == 'opencode':
            return [BIN + 'opencode', 'serve', '--hostname', '0.0.0.0', '--port', str(port)]
        return [BIN + 't3', 'serve', '--host', '0.0.0.0', '--port', str(port),
                '--base-dir', str(Path(os.environ['HOME']) / 'base'), os.getcwd()]
    require(not (harness == 'opencode' and any(arg in ('web', 'serve', 'upgrade') for arg in arguments)),
            'Use managed web; runtime self-upgrade forbidden')
    if harness == 'opencode':
        require(not any(arg == '--server' or arg.startswith('--server=') for arg in arguments),
                'Runtime owns the server endpoint')
        return [BIN + 'opencode', '--server', 'http://127.0.0.1:4096', *arguments]
    return [BIN + CATALOG['harnesses'][harness]['cli'], *arguments]


def opencode_password(home: Path) -> str:
    """One random credential per isolated HOME; never put it in launch records."""
    destination = home / '.opencode-runtime-password'
    first_write(destination, secrets.token_urlsafe(32) + '\n')
    fd = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and (info.st_uid, info.st_gid) == (os.getuid(), os.getgid())
                and not info.st_mode & 0o077, 'Unsafe runtime credential file')
        password = os.read(fd, 256).decode().strip()
        require(re.fullmatch(r'[A-Za-z0-9_-]{32,128}', password), 'Invalid runtime credential file')
        return password
    finally:
        os.close(fd)


def opencode_info(port: int, password: str) -> dict:
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    try:
        authorization = base64.b64encode(('opencode:' + password).encode()).decode()
        connection.request('GET', '/api/info', headers={'Authorization': 'Basic ' + authorization})
        response = connection.getresponse()
        body = response.read(1024 * 1024 + 1)
        require(response.status == 200 and len(body) <= 1024 * 1024, 'OpenCode API unavailable')
        info = json.loads(body)
        require(isinstance(info, dict) and str(info.get('version', '')).startswith('2.')
                and type(info.get('pid')) is int, 'OpenCode V2 API required')
        return info
    finally:
        connection.close()


def run_opencode(arguments: list[str], home: Path) -> int:
    """Server owns execution; the attached CLI is only a client. Reap both children."""
    log = os.open(home / '.opencode-server.log', os.O_WRONLY | os.O_CREAT | os.O_APPEND
                  | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    server = client = None
    previous = {}
    def forward(signum, frame):
        for process in (client, server):
            if process is not None and process.poll() is None:
                process.send_signal(signum)
    try:
        info = os.fstat(log)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and (info.st_uid, info.st_gid) == (os.getuid(), os.getgid())
                and not info.st_mode & 0o077, 'Unsafe runtime server log')
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, forward)
        server = subprocess.Popen([BIN + 'opencode', 'serve', '--hostname', '127.0.0.1', '--port', '4096'],
                                  stdout=log, stderr=log)
        deadline = time.monotonic() + 60
        while True:
            require(server.poll() is None, 'OpenCode server exited before readiness')
            require(time.monotonic() < deadline, 'OpenCode server readiness timed out')
            try:
                info = opencode_info(4096, os.environ['OPENCODE_PASSWORD'])
            except (OSError, ValueError, http.client.HTTPException):
                time.sleep(0.25)
                continue
            require(info['pid'] == server.pid, 'OpenCode endpoint belongs to another process')
            break
        client = subprocess.Popen(arguments)
        while client.poll() is None:
            require(server.poll() is None, 'OpenCode server exited during client session')
            time.sleep(0.1)
        return 128 - client.returncode if client.returncode < 0 else client.returncode
    finally:
        for process in (client, server):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        os.close(log)
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('harness', choices=MODES)
    parser.add_argument('--web', action='store_true')
    parser.add_argument('--port', type=int)
    raw = list(sys.argv[1:] if argv is None else argv)
    split = raw.index('--') if '--' in raw else len(raw)
    args = parser.parse_args(raw[:split])
    arguments = raw[split + 1:]
    try:
        os.umask(0o077)
        if os.getuid() == 0:
            require(Path(__file__).resolve() == Path('/opt/agents-runtime/entry.py')
                    and os.environ.get('AGENTS_RUNTIME_SOURCE_MODE') == 'baked', 'Root requires baked immutable startup')
        home = Path(os.environ['HOME'])
        if os.getuid() > 0:
            libraries = list(Path('/usr/lib').glob('*/libnss_wrapper.so'))
            require(len(libraries) == 1, 'Image must supply immutable libnss-wrapper')
            identity = Path(tempfile.mkdtemp(prefix='agents-identity-'))
            (identity / 'passwd').write_text(f'agent:x:{os.getuid()}:{os.getgid()}:Runtime:{home}:/bin/bash\n')
            (identity / 'group').write_text(f'agent:x:{os.getgid()}:\n')
            os.environ.update(LD_PRELOAD=str(libraries[0]), NSS_WRAPPER_PASSWD=str(identity / 'passwd'),
                              NSS_WRAPPER_GROUP=str(identity / 'group'))
        initialize(args.harness, home, Path(os.environ['AGENTS_RUNTIME_RESOURCES'])
                   if os.environ.get('AGENTS_RUNTIME_RESOURCES') else None)
        os.environ.update(OPENCODE_DISABLE_AUTOUPDATE='1', PI_WEB_SKIP_VERSION_CHECK='1', PI_SKIP_VERSION_CHECK='1',
                          DISABLE_AUTOUPDATER='1', DISABLE_INSTALLATION_CHECKS='1',
                          XDG_CONFIG_HOME=str(home / '.config'), XDG_DATA_HOME=str(home / '.local/share'),
                          XDG_STATE_HOME=str(home / '.local/state'), XDG_CACHE_HOME=str(home / '.cache'),
                          PI_CODING_AGENT_DIR=str(home / '.pi/agent'), OPENCODE_CONFIG_DIR=str(home / '.config/opencode'))
        # An image-level lock also guards T3 if called without the host adapter.
        # Keep the fd across exec; never acquire by following an existing symlink.
        if args.harness == 't3':
            fd = os.open(home / '.server.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and (info.st_uid, info.st_gid) == (os.getuid(), os.getgid())
                    and not info.st_mode & 0o077, 'Unsafe T3 writer lock')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.set_inheritable(fd, True)
            log = os.open(home / 'logs/server.log', os.O_WRONLY | os.O_CREAT | os.O_APPEND
                          | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            info = os.fstat(log)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and (info.st_uid, info.st_gid) == (os.getuid(), os.getgid())
                    and not info.st_mode & 0o077, 'Unsafe private T3 log')
            os.dup2(log, 1)
            os.dup2(log, 2)
            os.close(log)
        selected = command(args.harness, arguments, web=args.web, port=args.port)
        if args.harness == 'opencode':
            os.environ['OPENCODE_PASSWORD'] = opencode_password(home)
            if not args.web:
                return run_opencode(selected, home)
        os.execvpe(selected[0], selected, os.environ)
    except (OSError, ValueError, KeyError) as error:
        print('agents-runtime startup: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
