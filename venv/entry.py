#!/usr/bin/python3 -I
"""VM startup and config-only OpenCode seed. No credential copy or repair."""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


SERVER_PLUGINS = ('first-prompt-title.js', 'background-subagents.js')
RETIRED = ('kdco-background-agents.ts', 'kdco-worktree.ts', 'kdco-notify.ts')


def legacy_evidence() -> dict:
    # Loaded only by OpenCode migration; other harnesses need no legacy metadata.
    return json.loads(Path(__file__).with_name('opencode_legacy.json').read_text())


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
    """Native V2 public config, with bounded same-path prompt references."""
    require(isinstance(document, dict), 'Canonical config object required')
    require(not set(document) & {'agent', 'provider', 'permission', 'plugin', 'autoupdate'},
            'V1 configuration refused; publish canonical V2 resources')
    agents = document.get('agents')
    require(isinstance(agents, dict) and agents, 'Canonical agent map required')
    assert isinstance(agents, dict)
    allowed = {'$schema', 'model', 'default_agent', 'update', 'compaction', 'lsp',
               'agents', 'providers', 'permissions', 'plugins'}
    require(not set(document) - allowed, 'Unknown public configuration fields refused')
    result = copy.deepcopy(document)
    # Public resources must never become a credential distribution mechanism.
    def public_value(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if re.search(r'key|token|password|secret|authorization|headers', key, re.I):
                    require(isinstance(item, str) and re.fullmatch(r'\{env:[A-Z][A-Z0-9_]*\}', item),
                            'Only environment references permitted for public credentials')
                public_value(item)
        elif isinstance(value, list):
            for item in value:
                public_value(item)
    public_value(document)
    for name, agent in agents.items():
        require(re.fullmatch(r'[A-Za-z0-9_ -]+', name), 'Invalid public agent name')
        require(isinstance(agent, dict) and not set(agent) - {
            'system', 'request', 'mode', 'description', 'permissions', 'model',
            'hidden', 'color', 'steps', 'disabled'},
            'Unknown public agent fields refused')
        if 'mode' in agent:
            require(agent['mode'] in ('all', 'primary', 'subagent'), 'Invalid canonical mode')
        if 'system' not in agent:
            continue  # Built-in overrides such as title may only select a model.
        prompt = agent['system']
        absolute_prefix = '{file:' + str(resources) + '/'
        if isinstance(prompt, str) and prompt.startswith(absolute_prefix):
            prompt = '{file:./' + prompt[len(absolute_prefix):]
        require(isinstance(prompt, str) and re.fullmatch(
            r'\{file:\./(?:system|gsd)/[A-Za-z0-9_-]+\.md\}', prompt), 'Public prompt reference required')
        result['agents'][name]['system'] = '{file:' + str(resources / prompt[8:-1]) + '}'
    for rules in [document.get('permissions', []), *(a.get('permissions', []) for a in agents.values())]:
        require(isinstance(rules, list) and all(isinstance(rule, dict)
                and set(rule) == {'action', 'resource', 'effect'}
                and isinstance(rule['action'], str) and isinstance(rule['resource'], str)
                and rule['effect'] in ('allow', 'ask', 'deny') for rule in rules),
                'Native V2 ordered permission rules required')
    result['$schema'] = 'https://opencode.ai/config.json'
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


def read_jsonc(text: str) -> dict:
    """Read upstream-compatible JSONC, refusing ambiguous duplicate keys."""
    string = r'"(?:[^"\\]|\\.)*"'
    text = re.sub(string + r'|//[^\r\n]*|/\*[\s\S]*?\*/',
                  lambda m: m[0] if m[0].startswith('"') else ' ', text)
    text = re.sub(string + r'|,\s*(?=[}\]])',
                  lambda m: m[0] if m[0].startswith('"') else '', text)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Ambiguous private configuration; preserved')
            result[key] = value
        return result
    document = json.loads(text, object_pairs_hook=unique)
    require(isinstance(document, dict), 'Private config object required; preserved')
    return document


def owned_bytes(path: Path) -> bytes:
    require(path.resolve() == path, 'Redirected private file refused; preserved')
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and info.st_gid == os.getgid() and info.st_nlink == 1 and not info.st_mode & 0o022,
            'Unsafe private file custody; preserved')
    return path.read_bytes()


def replace_owned(path: Path, before: bytes, after: bytes) -> None:
    """Atomic same-file update, with drift check and existing mode retained."""
    require(owned_bytes(path) == before, 'Private file changed during migration; retry while idle')
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.opencode-migrate-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        require(owned_bytes(path) == before, 'Private file changed during migration; retry while idle')
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def managed_legacy_agents(document: dict, resources: Path) -> bool:
    """Recognize only exact historical seeder output (including excluded subsets)."""
    if set(document) != {'$schema', 'agent'} or document['$schema'] != 'https://opencode.ai/config.json':
        return False
    agents = document['agent']
    if not isinstance(agents, dict) or not agents:
        return False
    evidence = legacy_evidence()
    for name, value in agents.items():
        if not isinstance(value, dict) or not isinstance(value.get('prompt'), str):
            return False
        agent = dict(value)
        prefix = '{file:' + str(resources) + '/'
        if not agent['prompt'].startswith(prefix):
            return False
        agent['prompt'] = '{file:./' + agent['prompt'][len(prefix):]
        fingerprint = hashlib.sha256(json.dumps(agent, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if evidence['agent_sha256'].get(name) != fingerprint:
            return False
    return True


def retired_reference(value: str, root: Path, resources: Path) -> bool:
    paths = {str(parent / 'plugins' / name)
             for parent in (root, resources / 'opencode-plugins', Path('/opt/opencode-defaults'),
                            Path('/opt/opencode/component/.opencode/config')) for name in RETIRED} | {
                                './plugins/' + name for name in RETIRED}
    return value in paths or value.startswith('file://') and value[7:] in paths


def reconcile_plugins(document: dict, root: Path, resources: Path, *, required: bool) -> bool:
    """Touch plugin registrations only; upstream owns legacy schema normalization."""
    before = copy.deepcopy(document)
    for key in ('plugin', 'plugins'):
        if key not in document:
            continue
        require(isinstance(document[key], list), 'Invalid private plugin list; preserved')
        retained = []
        for item in document[key]:
            spec = item if isinstance(item, str) else item[0] if isinstance(item, list) and item else None
            if isinstance(spec, str) and retired_reference(spec, root, resources):
                continue
            require(not isinstance(spec, str) or not re.search(r'(?:^|[/@])kdco(?:[-/]|$)', spec),
                    'Unknown active KDCO registration; preserved for manual review')
            for name in SERVER_PLUGINS:
                absolute = str(root / 'plugins' / name)
                if spec in ('./plugins/' + name, absolute):
                    item = [absolute, *item[1:]] if isinstance(item, list) else absolute
                    break
            retained.append(item)
        document[key] = retained
    if required:
        # Keep the existing syntax so upstream preserves legacy package tuples/options.
        key = 'plugins' if 'plugins' in document or 'plugin' not in document else 'plugin'
        entries = document.setdefault(key, [])
        for name in SERVER_PLUGINS:
            path = str(root / 'plugins' / name)
            if not any((item if isinstance(item, str) else item[0] if isinstance(item, list) and item else None) == path
                       for item in entries):
                entries.append(path)
    return document != before


def publish_opencode(resources: Path, document: dict) -> dict:
    """Publish the generated public manifest as its existing directory owner."""
    require(resources.is_absolute() and resources.resolve(strict=True) == resources
            and resources.is_dir() and resources.stat().st_uid == os.getuid(),
            'Physical public resource directory owned by publisher required')
    text = json.dumps(public_agents(document, resources)) + '\n'
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
    for agent in canonical['agents'].values():
        if 'system' not in agent:
            continue
        prompt = Path(agent['system'][6:-1])
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
    for agent in document['agents'].values():
        if 'system' not in agent:
            continue
        # stat/is_file is not evidence of read permission (including named ACLs).
        with Path(agent['system'][6:-1]).open('rb') as stream:
            stream.read(1)
    return {'readable': True}


def seed_opencode(home: Path, resources: Path) -> dict:
    """Reconcile managed defaults in-place; leave private schema normalization upstream."""
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
        manifest = resources / 'opencode-agents.json'
        require(not manifest.is_symlink(), 'Redirected public agent manifest refused')
        if not manifest.is_file():
            manifest = Path('/opt/opencode-defaults/opencode.json')
        require(manifest.is_file(), 'Canonical V2 public config unavailable; reapply resources or rebuild image')
        document = public_agents(json.loads(manifest.read_text()), resources)
        for agent in document['agents'].values():
            if 'system' in agent:
                require(Path(agent['system'][6:-1]).is_file(), 'Public agent prompt unavailable')
        existing, legacy_seed = [], None
        for name in ('config.json', 'opencode.json', 'opencode.jsonc'):
            path = root / name
            if path.exists() or path.is_symlink():
                before = owned_bytes(path)
                private = read_jsonc(before.decode())
                if name == 'config.json' and managed_legacy_agents(private, resources):
                    require(set(private['agent']) <= set(document['agents']),
                            'Historical managed agents missing from authoritative public V2 manifest')
                    legacy_seed = (path, before, set(private['agent']))
                    continue
                existing.append((path, before, private))
        moved_private = None
        if existing and existing[0][0].name == 'config.json':
            if len(existing) == 1:
                # Upstream accepts the syntax but not this old VM filename. Move
                # every private setting without conversion or a precedence guess.
                moved_private = existing.pop()
                existing.append((root / 'opencode.json', None, moved_private[2]))
            else:
                # Recover publication-before-retirement interruption only when
                # the complete native document is exactly the intended result.
                expected = copy.deepcopy(existing[0][2])
                reconcile_plugins(expected, root, resources, required=True)
                require(len(existing) == 2 and existing[1][0].name == 'opencode.json'
                        and existing[1][2] == expected,
                        'Unknown private config.json and native configs both exist; reconcile precedence explicitly')
                moved_private = existing.pop(0)
        if legacy_seed:
            excluded = set()
            for _, _, private in existing:
                for key in ('agent', 'agents'):
                    mapping = private.get(key, {})
                    require(isinstance(mapping, dict), 'Ambiguous private agent settings; preserved')
                    excluded.update(mapping)
            managed = {name: document['agents'][name] for name in sorted(legacy_seed[2]) if name not in excluded}
            if not existing:
                existing.append((root / 'opencode.json', None, {'$schema': document['$schema'], 'agents': managed}))
            else:
                existing[0][2].setdefault('agents', {}).update(managed)
        if not existing:
            discovery = any((root / name).exists() or (root / name).is_symlink()
                            for name in ('config', 'agent', 'agents', 'mode', 'modes'))
            # Existing discovery is private policy, not a genuinely fresh HOME.
            # Let upstream load it; do not introduce canonical global defaults.
            initial = {'$schema': document['$schema']} if discovery else document
            existing.append((root / 'opencode.json', None, initial))
        updates = []
        for index, (path, before, private) in enumerate(existing):
            reconcile_plugins(private, root, resources, required=index == len(existing) - 1)
            if before is None or private != read_jsonc(before.decode()):
                updates.append((path, before, (json.dumps(private, indent=2) + '\n').encode()))
        # Validate private configs before changing any managed assets. Assets also
        # preflight their complete narrow set before applying mutations.
        assets_changed = publish_opencode_assets(home, resources)
        for path, before, after in updates:
            if before is None:
                origin = moved_private or legacy_seed
                mode = stat.S_IMODE(origin[0].stat().st_mode) if origin else 0o600
                require(first_write(path, after.decode(), mode=mode),
                        'Concurrent private config publication; retry while idle')
            else:
                replace_owned(path, before, after)
        for retired_config in (legacy_seed, moved_private):
            if retired_config:
                path, before = retired_config[:2]
                require(owned_bytes(path) == before, 'Old config changed during migration; preserved')
                path.unlink()
                directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        return dict(changed=bool(updates or legacy_seed or moved_private) or assets_changed, skipped='')
    finally:
        os.close(fd)


def publish_opencode_assets(home: Path, resources: Path) -> bool:
    """Publish canonical standalone plugins and CLI assets, without dependencies."""
    root = home / '.config/opencode'
    directory(root)
    source = resources / 'opencode-config'
    if not source.is_dir():
        source = Path('/opt/opencode-defaults')
    changes, retired = [], []
    old_sources = (resources / 'opencode-plugins', Path('/opt/opencode-defaults'),
                   Path('/opt/opencode/component/.opencode/config'))
    for name in ('kdco', *('plugins/' + name for name in RETIRED)):
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink():
            require(path.readlink() in {parent / name for parent in old_sources},
                    'Unknown retired KDCO link; preserved for manual review')
        else:
            # The publisher's exact re-export bytes are the only removable files.
            module = {'kdco-background-agents.ts': 'background-agents',
                      'kdco-worktree.ts': 'worktree', 'kdco-notify.ts': 'notify'}.get(path.name)
            require(module is not None and owned_bytes(path) ==
                    ('export { default } from "../kdco/' + module + '"\n').encode(),
                    'Unknown retired KDCO content; preserved for manual review')
        retired.append(path)
    for name in ('plugins/first-prompt-title.js', 'plugins/background-subagents.js',
                 'tui-plugins/session-title.mjs', 'tui-plugins/session-title'):
        destination, original = root / name, source / name
        require(original.exists(), 'Canonical V2 plugin/CLI asset unavailable')
        directory(destination.parent)
        if destination.is_symlink() and destination.resolve() == original.resolve():
            continue
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink():
                require(destination.readlink() in {parent / name for parent in old_sources},
                        'Conflicting plugin/CLI link preserved; manual review required')
            else:
                data = owned_bytes(destination)
                require(data == original.read_bytes() or hashlib.sha256(data).hexdigest() ==
                        legacy_evidence()['asset_sha256'].get(name),
                        'Conflicting plugin/CLI asset preserved; manual review required')
        changes.append((destination, original))
    # Validate existing CLI preferences before removing any old server plugins.
    cli = root / 'cli.json'
    cli_before = owned_bytes(cli) if cli.exists() or cli.is_symlink() else None
    cli_document = read_jsonc(cli_before.decode()) if cli_before is not None else read_jsonc((source / 'cli.json').read_text())
    cli_plugins = cli_document.setdefault('plugins', [])
    require(isinstance(cli_plugins, list), 'Invalid private CLI plugins; preserved')
    if './tui-plugins/session-title' not in cli_plugins:
        cli_plugins.append('./tui-plugins/session-title')
    cli_after = (json.dumps(cli_document, indent=2) + '\n').encode()
    if cli_before is None and cli_document == read_jsonc((source / 'cli.json').read_text()):
        cli_after = (source / 'cli.json').read_bytes()
    cli_changed = cli_before is None or read_jsonc(cli_before.decode()) != cli_document
    for destination, original in changes:
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        destination.symlink_to(original)
    for path in retired:
        path.unlink()  # Never traverse/delete the shared package or copy archives.
    if cli_before is None:
        require(first_write(cli, cli_after.decode()), 'Concurrent CLI publication; retry while idle')
    elif cli_changed:
        replace_owned(cli, cli_before, cli_after)
    return bool(changes or retired or cli_changed)


def opencode_password(home: Path) -> str:
    """Use the infrastructure-provisioned backend secret; never generate/log it."""
    path = home / '.config/opencode/server-password'
    require(path.resolve() == path, 'Physical OpenCode password file required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_gid == os.getgid() and info.st_nlink == 1
                and stat.S_IMODE(info.st_mode) == 0o600 and 0 < info.st_size <= 4096,
                'OpenCode password requires an account-owned single-link 0600 file')
        password = os.read(fd, 4097).decode().removesuffix('\n')
        require(bool(password) and not any(c in password for c in '\r\n\x00'),
                'Invalid OpenCode backend password')
        return password
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
            print(json.dumps(source))
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
        port = ''
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
            if web or '--server' in args or any(a.startswith('--server=') for a in args):
                os.environ['OPENCODE_PASSWORD'] = opencode_password(home)
            command = ['/opt/opencode/component/.runtime/bin/opencode', *(['serve', '--hostname', '0.0.0.0', '--port', port] if web else args)]
        else:
            command = ['/bin/bash', '/opt/venv/t3-start.sh']
        os.execvpe(command[0], command, os.environ)
    except (OSError, ValueError, KeyError) as error:
        print(f'venv image startup: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
