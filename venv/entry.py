#!/usr/bin/python3 -I
"""VM startup and config-only OpenCode seed. No credential copy or repair."""
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def directory(path: Path) -> None:
    require(path.resolve() == path, 'Redirected state directory refused')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and info.st_gid == os.getgid() and not info.st_mode & 0o077,
            'Private directory identity/mode mismatch; no automatic repair')


def reference(destination: Path, source: Path) -> None:
    require(source.exists(), 'Required shared resource is unavailable')
    if destination.exists() or destination.is_symlink():
        # Preserve custom user content, including legacy AGENTS.md; never replace.
        require(not destination.is_symlink() or destination.exists(),
                'Existing resource link is inaccessible; preserve its same-path target')
        return
    try:
        destination.symlink_to(source)
    except FileExistsError:
        pass  # Concurrent publication wins, never replace it.


def public_agents(document: dict, resources: Path) -> dict:
    """Project canonical public metadata only; never copy global policy/providers."""
    require(isinstance(document, dict), 'Canonical config object required')
    agents = document.get('agent')
    require(isinstance(agents, dict) and agents, 'Canonical agent map required')
    result = {}
    for name, agent in agents.items():
        require(re.fullmatch(r'[A-Za-z0-9_-]+', name), 'Invalid public agent name')
        require(isinstance(agent, dict) and not set(agent) - {
            'prompt', 'temperature', 'mode', 'description', 'permission'},
            'Unknown public agent fields refused')
        require(agent.get('mode') in ('all', 'primary', 'subagent'), 'Explicit canonical mode required')
        require(isinstance(agent.get('description'), str), 'Public description required')
        require(isinstance(agent.get('temperature'), (int, float))
                and not isinstance(agent['temperature'], bool)
                and 0 <= agent['temperature'] <= 2, 'Invalid temperature')
        prompt = agent.get('prompt', '')
        absolute_prefix = '{file:' + str(resources) + '/'
        if isinstance(prompt, str) and prompt.startswith(absolute_prefix):
            prompt = '{file:./' + prompt[len(absolute_prefix):]
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
    """Read comments/trailing commas without interpreting strings or substitutions."""
    # Preserve quoted strings verbatim in both passes, including escaped quotes.
    string = r'"(?:[^"\\]|\\.)*"'
    text = re.sub(string + r'|//[^\r\n]*|/\*[\s\S]*?\*/',
                  lambda m: m[0] if m[0].startswith('"') else ' ', text)
    text = re.sub(string + r'|,\s*(?=[}\]])',
                  lambda m: m[0] if m[0].startswith('"') else '', text)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Ambiguous private configuration')
            result[key] = value
        return result
    result = json.loads(text, object_pairs_hook=unique)
    require(isinstance(result, dict), 'Private config object required')
    return result


def first_write(destination: Path, text: str, mode: int = 0o600) -> bool:
    """Publish complete bytes atomically; a concurrent existing file always wins."""
    fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix='.opencode-seed-')
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            return False
        directory_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return True
    finally:
        os.unlink(temporary)


def publish_opencode(resources: Path, document: dict) -> dict:
    """Publish the generated public manifest as its existing directory owner."""
    require(resources.is_absolute() and resources.resolve(strict=True) == resources
            and resources.is_dir() and resources.stat().st_uid == os.getuid(),
            'Physical public resource directory owned by publisher required')
    public_agents(document, resources)
    text = json.dumps({'agent': document['agent']}) + '\n'
    destination = resources / 'opencode-agents.json'
    changed = first_write(destination, text, mode=0o644)
    require(not destination.is_symlink() and destination.is_file()
            and destination.stat().st_nlink == 1
            # Matching public bytes may still await named-reader ACLs. Accept
            # restrictive modes without chmod; the role grants exact-path access.
            and stat.S_IMODE(destination.stat().st_mode) in (0o600, 0o640, 0o644, 0o400, 0o440, 0o444)
            and destination.read_text() == text,
            'Public manifest collision; review explicitly, never overwrite')
    return dict(changed=changed)


def opencode_acl_plan(resources: Path, document: dict) -> list[dict]:
    """List only canonical physical public paths; no filesystem mutations/scans."""
    require(resources.is_absolute() and resources.resolve(strict=True) == resources
            and resources.is_dir() and resources.parent != Path('/'),
            'Physical public resource directory and bounded parent required')
    manifest = resources / 'opencode-agents.json'
    require(manifest.resolve(strict=True) == manifest and manifest.is_file()
            and manifest.stat().st_nlink == 1, 'Physical single-link public manifest required')
    canonical = public_agents(document, resources)
    require(public_agents(json.loads(manifest.read_text()), resources) == canonical,
            'Public manifest differs from canonical projection; no ACL grants')
    targets = {resources.parent: 'x', resources: 'x', manifest: 'r'}
    for agent in canonical['agent'].values():
        prompt = Path(agent['prompt'][6:-1])
        targets[prompt] = 'r'
        parent = prompt.parent
        while parent != resources:
            require(resources in parent.parents, 'External public prompt directory refused')
            targets[parent] = 'x'
            parent = parent.parent
    for path, permission in targets.items():
        require(path.resolve(strict=True) == path, 'Redirected ACL target refused')
        info = path.stat()
        require(stat.S_ISDIR(info.st_mode) if permission == 'x' else
                stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                'Physical directory or single-link public prompt required')
    return [{'path': str(path), 'permission': targets[path]} for path in sorted(targets)]


def check_opencode(resources: Path) -> dict:
    """Prove public discovery access as the caller, without touching private HOME."""
    require(resources.is_absolute(), 'Absolute public resources required')
    manifest = resources / 'opencode-agents.json'
    require(not manifest.is_symlink(), 'Redirected public agent manifest refused')
    document = public_agents(json.loads(manifest.read_text()), resources)
    for agent in document['agent'].values():
        # stat/is_file is not evidence of read permission (including named ACLs).
        with Path(agent['prompt'][6:-1]).open('rb') as stream:
            stream.read(1)
    return {'readable': True}


def seed_opencode(home: Path, resources: Path) -> dict:
    """Atomic first seed, shared by image startup and the maintained Ansible role.

    config.json loads before opencode.json/jsonc in v1.18.29. Never overwrite it.
    Skip global private policy, legacy modes and Markdown discovery: deep-merging
    canonical permissions there could broaden a user's existing restrictions.
    """
    require(home.is_absolute() and home.resolve() == home, 'Physical HOME required')
    require(resources.is_absolute(), 'Absolute public resources required')
    directory(home)
    root = home / '.config/opencode'
    directory(root)
    fd = os.open(root / '.vm-init.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_gid == os.getgid()
                and info.st_nlink == 1 and not info.st_mode & 0o077, 'Unsafe startup lock')
        fcntl.flock(fd, fcntl.LOCK_EX)
        destination = root / 'config.json'
        if destination.exists() or destination.is_symlink():
            return dict(changed=False, skipped='config.json exists; preserved without inspection')
        for name in ('config', 'agent', 'agents', 'mode', 'modes'):
            if (root / name).exists() or (root / name).is_symlink():
                return dict(changed=False, skipped='Existing legacy config or agent discovery; manual merge required')
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
                    return dict(changed=False, skipped='Private policy/legacy configuration; manual merge required')
                overrides = private.get('agent', {})
                require(isinstance(overrides, dict), 'Private agent map required')
                excluded.update(overrides)
            except (ValueError, OSError):
                return dict(changed=False, skipped='Unparseable private config; manual merge required')
        manifest = resources / 'opencode-agents.json'
        require(not manifest.is_symlink(), 'Redirected public agent manifest refused')
        if not manifest.is_file():
            return dict(changed=False, skipped='Public agent manifest absent; run maintained agents reapply')
        document = public_agents(json.loads(manifest.read_text()), resources)
        excluded.intersection_update(document['agent'])
        document['agent'] = {name: agent for name, agent in document['agent'].items() if name not in excluded}
        for agent in document['agent'].values():
            require(Path(agent['prompt'][6:-1]).is_file(), 'Public agent prompt unavailable')
        if not document['agent']:
            return dict(changed=False, skipped='All canonical names have private overrides')
        if not first_write(destination, json.dumps(document, indent=2) + '\n'):
            return dict(changed=False, skipped='Concurrent config.json publication preserved')
        return dict(changed=True, skipped='', excluded=sorted(excluded))
    finally:
        os.close(fd)


def identity(home: Path) -> None:
    """Numeric UID gets matching libc passwd/HOME without root or /etc mutation."""
    require(os.getuid() > 0 and os.geteuid() == os.getuid(), 'Never run harness startup as root')
    name = os.environ.get('USER', '')
    require(re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', name), 'Invalid account name')
    require(home.is_absolute() and home.resolve(strict=True) == home and home.is_dir(), 'Physical HOME required')
    info = home.stat()
    require((info.st_uid, info.st_gid) == (os.getuid(), os.getgid()) and not info.st_mode & 0o022,
            'HOME identity/mode mismatch')
    libraries = list(Path('/usr/lib').glob('*/libnss_wrapper.so'))
    require(len(libraries) == 1, 'Image must provide libnss-wrapper')
    # Container-private /tmp, not persistent HOME and never copied account secrets.
    root = Path(tempfile.mkdtemp(prefix='venv-identity-'))
    passwd, group = root / 'passwd', root / 'group'
    passwd.write_text(f'{name}:x:{os.getuid()}:{os.getgid()}:VM harness:{home}:/bin/bash\n')
    group.write_text(f'{name}:x:{os.getgid()}:\n' + ''.join(
        f'vmgroup{gid}:x:{gid}:{name}\n' for gid in sorted(set(os.getgroups()) - {os.getgid()})))
    os.environ.update(LD_PRELOAD=str(libraries[0]), NSS_WRAPPER_PASSWD=str(passwd), NSS_WRAPPER_GROUP=str(group))


def initialize(harness: str, home: Path, resources: Path) -> None:
    require(resources.is_absolute() and resources.is_dir(), 'Same-path resources required')
    if harness == 't3':
        return  # Component's native initializer owns all T3 private state.
    root = home / {'pi': '.pi/agent', 'omp': '.omp/agent', 'opencode': '.config/opencode'}[harness]
    directory(root)
    fd = os.open(root / '.vm-init.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_gid == os.getgid()
                and info.st_nlink == 1 and not info.st_mode & 0o077, 'Unsafe startup lock')
        # Brief resource publication only; never held for CLI or server lifetime.
        fcntl.flock(fd, fcntl.LOCK_EX)
        if harness == 'pi':
            for name, source in [('agents', resources), ('prompts', resources / 'prompts'), ('skills', resources / 'skills')]:
                reference(root / name, source)
            agents = root / 'AGENTS.md'
            require(not agents.is_symlink() or agents.exists(), 'Legacy Pi AGENTS.md target is inaccessible; no replacement')
        elif harness == 'opencode':
            for name in ('commands', 'skills', 'system', 'gsd'):
                reference(root / name, resources / name)
        else:
            # Native OMP's discovery layout, without its workstation passwd/mount
            # requirements. No upstream application source is copied or modified.
            reference(root / 'SYSTEM.md', resources / 'system/build.md')
            reference(root / 'commands', resources / 'commands')
            directory(root / 'agents')
            for source in sorted((resources / 'system').glob('*.md')):
                require(source.resolve().parent == (resources / 'system').resolve(), 'External system agent refused')
                reference(root / 'agents' / ('system-' + source.name), source)
            directory(root / 'skills')
            for source in sorted([*(resources / 'skills').glob('*/SKILL.md'), *(resources / 'skills').glob('*/*/SKILL.md')]):
                require((resources / 'skills').resolve() in source.resolve().parents, 'External skill refused')
                destination = root / 'skills' / source.parent.name
                if destination.is_symlink():
                    require(destination.resolve() == source.parent.resolve(), 'Duplicate/conflicting skill name')
                reference(destination, source.parent)
    finally:
        os.close(fd)
    if harness == 'opencode':
        plugins = resources / 'opencode-plugins'
        publisher = plugins / 'publish-plugins.mjs'
        if not publisher.is_file():
            plugins = Path('/opt/opencode-defaults').resolve()
            publisher = Path('/opt/opencode-publish-plugins.mjs')
        if publisher.is_file():
            subprocess.run(['node', str(publisher), str(plugins), str(home / '.config/opencode')], check=True)
        result = seed_opencode(home, resources)
        if result['skipped']:
            print('OpenCode agent seed: ' + result['skipped'], file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    os.umask(0o077)
    try:
        if args[:1] == ['--public-opencode-agents']:
            require(len(args) == 2, 'Expected canonical public config')
            # Validate with the same projection used by startup, but retain relative
            # public references in the shared manifest for same-path VM resolution.
            source = json.loads(Path(args[1]).read_text())
            public_agents(source, Path('/public-validation'))
            print(json.dumps({'agent': source['agent']}))
            return 0
        if args[:1] == ['--publish-opencode-agents']:
            require(len(args) == 2, 'Expected public resource directory')
            print(json.dumps(publish_opencode(Path(args[1]), json.load(sys.stdin))))
            return 0
        if args[:1] == ['--check-opencode-agents']:
            require(len(args) == 2, 'Expected public resource directory')
            print(json.dumps(check_opencode(Path(args[1]))))
            return 0
        if args[:1] == ['--opencode-agents-acl-plan']:
            require(len(args) == 2, 'Expected public resource directory')
            print(json.dumps(opencode_acl_plan(Path(args[1]), json.load(sys.stdin))))
            return 0
        if args[:1] == ['--seed-opencode']:
            require(len(args) == 3, 'Expected private HOME and public resources')
            require(os.getuid() > 0 and os.geteuid() == os.getuid(), 'Seed as enrolled user, never root')
            plugins = Path(args[2]) / 'opencode-plugins'
            publisher = plugins / 'publish-plugins.mjs'
            if publisher.is_file():
                subprocess.run(['node', str(publisher), str(plugins), str(Path(args[1]) / '.config/opencode')], check=True)
            print(json.dumps(seed_opencode(Path(args[1]), Path(args[2]))))
            return 0
        require(args and args[0] in ('pi', 'omp', 'opencode', 't3'), 'Expected harness')
        harness, args = args[0], args[1:]
        web = args[:1] == ['--web'] or harness == 't3'
        if args[:1] == ['--web']:
            args = args[1:]
        require(not web or (harness != 'omp' and not args), 'Web arguments are fixed')
        home = Path(os.environ['HOME'])
        identity(home)
        initialize(harness, home, Path(os.environ['VENV_AGENT_RESOURCES']))
        os.environ.update(XDG_CONFIG_HOME=str(home / '.config'), XDG_DATA_HOME=str(home / '.local/share'),
                          XDG_STATE_HOME=str(home / '.local/state'), XDG_CACHE_HOME=str(home / '.cache'))
        if web:
            port = os.environ['VENV_AGENT_PORT']
            require(port.isdecimal() and 1024 <= int(port) <= 65535, 'Invalid web port')
        if harness == 'pi':
            os.environ.update(PI_CODING_AGENT_DIR=str(home / '.pi/agent'), PI_WEB_SKIP_VERSION_CHECK='1')
            command = ['/opt/pi/runtime/node_modules/.bin/pi-web', '--hostname', '0.0.0.0', '--port', port, '--no-open'] if web else ['/opt/pi/runtime/node_modules/.bin/pi', *args]
        elif harness == 'omp':
            command = ['/usr/local/bin/omp', *args]
        elif harness == 'opencode':
            os.environ.update(OPENCODE_CONFIG_DIR=str(home / '.config/opencode'), OPENCODE_DISABLE_AUTOUPDATE='1')
            command = ['/opt/opencode/component/.runtime/bin/opencode', *(['web', '--hostname', '0.0.0.0', '--port', port] if web else args)]
        else:
            command = ['/bin/bash', '/opt/venv/t3-start.sh']
        os.execvpe(command[0], command, os.environ)
    except (OSError, ValueError, KeyError) as error:
        print(f'venv image startup: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
