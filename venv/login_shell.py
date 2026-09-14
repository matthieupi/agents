#!/usr/bin/python3 -I
"""Restricted SSH alias handoff to the shared agents execution identity."""
import json
import os
from collections.abc import Mapping
from pathlib import Path
import pwd
import re
import stat
import sys


POLICY = Path('/etc/venv-agents/policy.json')


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_policy() -> dict:
    for component in (POLICY.parent, *POLICY.parent.parents):
        info = component.lstat()
        require(not stat.S_ISLNK(info.st_mode) and stat.S_ISDIR(info.st_mode)
                and info.st_uid == 0 and not info.st_mode & 0o022,
                'Unsafe protected handoff policy ancestor')
    descriptor = os.open(POLICY, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and not info.st_mode & 0o022, 'Unsafe protected handoff policy')
        value = json.loads(os.read(descriptor, 1024 * 1024))
        require(os.read(descriptor, 1) == b'', 'Oversized handoff policy')
    finally:
        os.close(descriptor)
    require(isinstance(value, dict) and value.get('schema') == 2, 'Current handoff policy required')
    return value


def handoff(arguments: list[str], environment: Mapping[str, str]) -> tuple[list[str], dict[str, str]]:
    require(not arguments and bool(environment.get('SSH_CONNECTION'))
            and not environment.get('SSH_ORIGINAL_COMMAND'),
            'Only an interactive harness session is supported')
    policy = load_policy()
    alias = pwd.getpwuid(os.getuid()).pw_name
    aliases = policy.get('ssh_aliases')
    account = policy.get('execution_account')
    command = policy.get('command')
    require(isinstance(aliases, dict) and aliases.get(alias) == alias,
            'Login identity is not an enrolled harness alias')
    require(isinstance(account, str) and re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', account) is not None
            and account != alias and account != 'root' and set(policy.get('accounts', {})) == {account},
            'Invalid shared execution identity')
    require(isinstance(command, str) and re.fullmatch(r'/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', command) is not None
            and all(part not in ('.', '..') for part in command.split('/')),
            'Invalid protected launcher path')
    harnesses = policy.get('harnesses')
    require(isinstance(harnesses, dict) and alias in harnesses
            and harnesses[alias].get('account') == account
            and harnesses[alias].get('requested_interfaces') == {'cli': True, 'web': bool(harnesses[alias].get('web'))},
            'Alias does not select an enrolled CLI harness')
    if not isinstance(account, str) or not isinstance(command, str):
        raise ValueError('Invalid protected handoff identity')
    clean = {'PATH': '/usr/bin:/bin', 'HOME': '/', 'USER': alias, 'LOGNAME': alias}
    if environment.get('TERM') and re.fullmatch(r'[A-Za-z0-9_.:+-]{1,64}', environment['TERM']):
        clean['TERM'] = environment['TERM']
    return ['/usr/bin/sudo', '-n', '-H', '-u', account, '--', command, alias], clean


def main() -> None:
    try:
        arguments, environment = handoff(sys.argv[1:], os.environ)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(64)
    os.execve(arguments[0], arguments, environment)


if __name__ == "__main__":
    main()
