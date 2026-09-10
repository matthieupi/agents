#!/usr/bin/env python3
"""Baked common startup for the explicitly selected runtime, not legacy init."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

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
    agents = document.get('agent')
    require(isinstance(agents, dict) and agents, 'Canonical agent map required')
    result = {}
    for name, agent in agents.items():
        require(re.fullmatch(r'[A-Za-z0-9_-]+', name), 'Invalid public agent name')
        require(isinstance(agent, dict) and not set(agent) - {
            'prompt', 'temperature', 'mode', 'description', 'permission'}, 'Unknown public agent fields refused')
        require(agent.get('mode') in ('all', 'primary', 'subagent'), 'Explicit canonical mode required')
        require(isinstance(agent.get('description'), str), 'Public description required')
        temperature = agent.get('temperature')
        require(isinstance(temperature, (int, float)) and not isinstance(temperature, bool)
                and 0 <= temperature <= 2, 'Invalid temperature')
        prompt = agent.get('prompt', '')
        prefix = '{file:' + str(resources) + '/'
        if isinstance(prompt, str) and prompt.startswith(prefix):
            prompt = '{file:./' + prompt[len(prefix):]
        require(isinstance(prompt, str) and re.fullmatch(
            r'\{file:\./(?:system|gsd)/[A-Za-z0-9_-]+\.md\}', prompt), 'Public prompt reference required')
        if 'permission' in agent:
            permission = agent['permission']
            require(isinstance(permission, dict) and not set(permission) - {
                'read', 'glob', 'grep', 'list', 'bash', 'task', 'webfetch', 'edit',
                'question', 'todowrite', 'skill'}, 'Unknown public permission fields refused')
            require(all(action in ('allow', 'ask', 'deny') for action in permission.values()),
                    'Public permission action required')
        result[name] = dict(agent, prompt='{file:' + str(resources / prompt[8:-1]) + '}')
    return {'$schema': 'https://opencode.ai/config.json', 'agent': result}


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
    """Config-only first seed, matching legacy VM policy preservation rules.

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
    destination = root / 'config.json'
    if destination.exists() or destination.is_symlink():
        return dict(changed=False, skipped='config.json exists; preserved without inspection')
    for name in ('config', 'agent', 'agents', 'mode', 'modes'):
        if (root / name).exists() or (root / name).is_symlink():
            return dict(changed=False, skipped='Existing legacy discovery; manual merge required')
    excluded = set()
    for name in ('opencode.json', 'opencode.jsonc'):
        path = root / name
        if path.is_symlink():
            return dict(changed=False, skipped='Redirected private config; manual merge required')
        if not path.exists():
            continue
        if not path.is_file():
            return dict(changed=False, skipped='Non-file private config; manual merge required')
        try:
            private = read_jsonc(path.read_text())
            if set(private) & {'permission', 'tools', 'mode', 'version'}:
                return dict(changed=False, skipped='Private policy/legacy config; manual merge required')
            overrides = private.get('agent', {})
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
    excluded.intersection_update(document['agent'])
    document['agent'] = {name: agent for name, agent in document['agent'].items() if name not in excluded}
    for agent in document['agent'].values():
        prompt = Path(agent['prompt'][6:-1])
        require(prompt.resolve(strict=True) == prompt and prompt.is_file(), 'Physical public prompt required')
        with prompt.open('rb') as stream:
            stream.read(1)
    if not document['agent']:
        return dict(changed=False, skipped='All canonical names have private overrides')
    if not first_write(destination, json.dumps(document, indent=2) + '\n'):
        return dict(changed=False, skipped='Concurrent config.json publication preserved')
    return dict(changed=True, skipped='', excluded=sorted(excluded))


def initialize(harness: str, home: Path, resources: Path | None) -> None:
    require(harness in MODES, 'Unsupported harness')
    directory(home)
    root = home / {'pi': '.pi/agent', 'omp': '.omp/agent', 'opencode': '.config/opencode',
                   'claude': '.claude', 't3': 'base'}[harness]
    directory(root)
    if harness == 'opencode':
        # Baked package + dependencies stay visible even when private HOME is bound.
        plugins = resources / 'opencode-plugins' if resources else Path('/opt/opencode-defaults')
        publisher = plugins / 'publish-plugins.mjs'
        if not publisher.is_file():
            plugins = Path('/opt/opencode-defaults')
            publisher = Path('/opt/opencode-publish-plugins.mjs')
        if publisher.is_file():
            subprocess.run(['node', str(publisher), str(plugins), str(root)], check=True)
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
    if harness == 'opencode':
        result = seed_opencode(home, resources)
        if result['skipped']:
            print('OpenCode agent seed: ' + result['skipped'], file=sys.stderr)


def command(harness: str, arguments: list[str], *, web: bool, port: int | None) -> list[str]:
    require(harness in MODES and ('web' if web else 'cli') in MODES[harness], 'Unsupported harness mode')
    require(all(isinstance(arg, str) and '\x00' not in arg for arg in arguments), 'Invalid arguments')
    require(not web or not arguments, 'Web startup arguments are fixed')
    if web:
        require(type(port) is int and 1024 <= port <= 65535, 'Explicit unprivileged web port required')
        if harness == 'pi':
            return [BIN + 'pi-web', '--hostname', '0.0.0.0', '--port', str(port), '--no-open']
        if harness == 'opencode':
            return [BIN + 'opencode', 'web', '--hostname', '0.0.0.0', '--port', str(port)]
        return [BIN + 't3', 'serve', '--host', '0.0.0.0', '--port', str(port),
                '--base-dir', str(Path(os.environ['HOME']) / 'base'), os.getcwd()]
    require(not (harness == 'opencode' and any(arg in ('web', 'serve', 'upgrade') for arg in arguments)),
            'Use managed web; runtime self-upgrade forbidden')
    return [BIN + CATALOG['harnesses'][harness]['cli'], *arguments]


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
        os.execvpe(selected[0], selected, os.environ)
    except (OSError, ValueError, KeyError) as error:
        print('agents-runtime startup: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
