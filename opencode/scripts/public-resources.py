#!/usr/bin/env python3
"""Publish config-only public resources for the opt-in workstation runtime."""
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


def public_agents(document: dict, resources: Path) -> dict:
    """Project public agent metadata only, never global policy or providers."""
    if not isinstance(document, dict) or not isinstance(document.get('agent'), dict) or not document['agent']:
        raise ValueError('Canonical agent map required')
    result = {}
    for name, agent in document['agent'].items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('Invalid public agent name')
        if not isinstance(agent, dict) or set(agent) - {'prompt', 'temperature', 'mode', 'description', 'permission'}:
            raise ValueError('Unknown public agent fields refused')
        if agent.get('mode') not in ('all', 'primary', 'subagent') or not isinstance(agent.get('description'), str):
            raise ValueError('Explicit canonical mode and description required')
        temperature = agent.get('temperature')
        if not isinstance(temperature, (int, float)) or isinstance(temperature, bool) or not 0 <= temperature <= 2:
            raise ValueError('Invalid temperature')
        prompt = agent.get('prompt', '')
        prefix = '{file:' + str(resources) + '/'
        if isinstance(prompt, str) and prompt.startswith(prefix):
            prompt = '{file:./' + prompt[len(prefix):]
        if not isinstance(prompt, str) or not re.fullmatch(r'\{file:\./(?:system|gsd)/[A-Za-z0-9_-]+\.md\}', prompt):
            raise ValueError('Public prompt reference required')
        if 'permission' in agent:
            permission = agent['permission']
            if not isinstance(permission, dict) or set(permission) - {
                'read', 'glob', 'grep', 'list', 'bash', 'task', 'webfetch', 'edit',
                'question', 'todowrite', 'skill'} or not all(value in ('allow', 'ask', 'deny') for value in permission.values()):
                raise ValueError('Invalid public permissions')
        result[name] = dict(agent, prompt='{file:' + str(resources / prompt[8:-1]) + '}')
    return {'$schema': 'https://opencode.ai/config.json', 'agent': result}


def first_write(destination: Path, text: str, mode: int = 0o600) -> bool:
    """Publish complete bytes exclusively; never replace existing content."""
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
    if not (resources.is_absolute() and resources.resolve(strict=True) == resources
            and resources.is_dir() and resources.stat().st_uid == os.getuid()):
        raise ValueError('Physical public resource directory owned by publisher required')
    public_agents(document, resources)
    text = json.dumps({'agent': document['agent']}) + '\n'
    destination = resources / 'opencode-agents.json'
    changed = first_write(destination, text, mode=0o644)
    if not (not destination.is_symlink() and destination.is_file()
            and destination.stat().st_nlink == 1
            and stat.S_IMODE(destination.stat().st_mode) in (0o600, 0o640, 0o644, 0o400, 0o440, 0o444)
            and destination.read_text() == text):
        raise ValueError('Public manifest collision; review explicitly, never overwrite')
    return {'changed': changed}


def validate_resources(resources: Path, document: dict) -> None:
    """Retain exact physical-path validation, without an unused VM ACL plan."""
    if not (resources.is_absolute() and resources.resolve(strict=True) == resources
            and resources.is_dir() and resources.parent != Path('/')):
        raise ValueError('Physical public resource directory and bounded parent required')
    manifest = resources / 'opencode-agents.json'
    canonical = public_agents(document, resources)
    if public_agents(json.loads(manifest.read_text()), resources) != canonical:
        raise ValueError('Public manifest differs from canonical projection')
    directories = {resources.parent, resources}
    files = {manifest}
    for agent in canonical['agent'].values():
        prompt = Path(agent['prompt'][6:-1])
        files.add(prompt)
        parent = prompt.parent
        while parent != resources:
            if resources not in parent.parents:
                raise ValueError('External public prompt directory refused')
            directories.add(parent)
            parent = parent.parent
    for path in directories | files:
        if path.resolve(strict=True) != path:
            raise ValueError('Redirected public path refused')
        info = path.stat()
        if not (stat.S_ISDIR(info.st_mode) if path in directories else
                stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
            raise ValueError('Physical directory or single-link public prompt required')


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    os.umask(0o077)
    try:
        if len(args) != 2:
            raise ValueError('Expected canonical config and public resource directory')
        document = json.loads(Path(args[0]).read_text())
        # Preserve the former Make projection's relative public-prompt contract.
        public_agents(document, Path('/public-validation'))
        resources = Path(args[1])
        result = publish_opencode(resources, document)
        validate_resources(resources, document)
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'opencode public resources: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
