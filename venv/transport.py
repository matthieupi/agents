#!/usr/bin/python3 -I
"""Structured OpenSSH transport compiler/verifier. No remote connection or mutation.

Only addresses, account names, ports and local identity/trust paths are accepted.
Never accept SSH option strings, shell snippets, SSH config files or raw proxies.
"""
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys


def hop_arguments(hop: dict) -> list[str]:
    if not isinstance(hop, dict) or set(hop) != {'host', 'port', 'user', 'identity_file', 'known_hosts_file'}:
        raise ValueError('Exact structured hop fields required; raw SSH options are unsupported')
    ipaddress.IPv4Address(hop['host'])
    if type(hop['port']) is not int or not 1 <= hop['port'] <= 65535:
        raise ValueError('Invalid SSH port')
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', hop['user']):
        raise ValueError('Invalid SSH account')
    for key in ('identity_file', 'known_hosts_file'):
        value = hop[key]
        if not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', value):
            raise ValueError('Canonical local file path required; no expansions or shell tokens')
        if any(part in ('.', '..') for part in value.split('/')):
            raise ValueError('Noncanonical path')
    # These become ansible_ssh_args: BEFORE common/extra args, which must be empty.
    return ['-F', 'none', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UserKnownHostsFile=' + hop['known_hosts_file'],
            '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UpdateHostKeys=no',
            '-o', 'VerifyHostKeyDNS=no', '-o', 'ForwardAgent=no',
            '-o', 'ControlMaster=no', '-o', 'ControlPath=none', '-o', 'ControlPersist=no',
            '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
            '-o', 'BatchMode=yes', '-o', 'PasswordAuthentication=no',
            '-o', 'KbdInteractiveAuthentication=no', '-o', 'PreferredAuthentications=publickey',
            '-o', 'ConnectTimeout=5', '-i', hop['identity_file'],
            '-l', hop['user'], '-p', str(hop['port'])]


def build_transport(spec: dict) -> dict:
    if not isinstance(spec, dict) or set(spec) not in ({'target'}, {'target', 'proxy'}):
        raise ValueError('Only structured target and optional proxy are supported')
    target = hop_arguments(spec['target'])
    proxy = None
    if 'proxy' in spec:
        proxy = hop_arguments(spec['proxy']) + ['-o', 'ProxyCommand=none']
        forwarding = ['/usr/bin/ssh', *proxy, '-W', '%h:%p', spec['proxy']['host']]
        target += ['-o', 'ProxyCommand=' + shlex.join(forwarding)]
    else:
        target += ['-o', 'ProxyCommand=none']
    return {'target': target, 'proxy': proxy, 'ssh_args': shlex.join(target)}


def verify_hop(hop: dict, arguments: list[str]) -> None:
    for key in ('identity_file', 'known_hosts_file'):
        path = Path(hop[key])
        info = path.lstat()
        if (path.resolve(strict=True) != path or not stat.S_ISREG(info.st_mode)
                or info.st_uid not in (0, os.getuid()) or info.st_mode & (0o077 if key == 'identity_file' else 0o022)
                or info.st_size == 0):
            raise ValueError('Unsafe or empty local identity/trust file')
        for parent in path.parents:
            ancestor = parent.stat()
            if (ancestor.st_uid not in (0, os.getuid()) or not stat.S_ISDIR(ancestor.st_mode)
                    or ancestor.st_mode & 0o022):
                raise ValueError('Writable or unowned identity/trust ancestor')
    name = hop['host'] if hop['port'] == 22 else f"[{hop['host']}]:{hop['port']}"
    pin = subprocess.run(['/usr/bin/ssh-keygen', '-F', name, '-f', hop['known_hosts_file']],
                         capture_output=True, text=True, timeout=10, check=False)
    if pin.returncode:
        raise ValueError('Exact hop address/port is not pinned')
    result = subprocess.run(['/usr/bin/ssh', '-G', *arguments, hop['host']],
                            capture_output=True, text=True, timeout=10, check=True)
    effective = {}
    for line in result.stdout.splitlines():
        key, value = line.split(' ', 1)
        effective.setdefault(key, []).append(value)
    expected = {'hostname': hop['host'], 'user': hop['user'], 'port': str(hop['port']),
                'stricthostkeychecking': 'true', 'userknownhostsfile': hop['known_hosts_file'],
                'globalknownhostsfile': '/dev/null', 'updatehostkeys': 'false',
                'verifyhostkeydns': 'false', 'forwardagent': 'no', 'controlmaster': 'false',
                'controlpersist': 'no', 'identitiesonly': 'yes', 'identityagent': 'none',
                'batchmode': 'yes', 'passwordauthentication': 'no',
                'kbdinteractiveauthentication': 'no', 'preferredauthentications': 'publickey',
                'identityfile': hop['identity_file']}
    for key, value in expected.items():
        if effective.get(key) != [value]:
            raise ValueError(f'Unexpected effective SSH setting: {key}')
    proxy_command = next(arg.split('=', 1)[1] for arg in arguments if arg.startswith('ProxyCommand='))
    # OpenSSH omits settings whose value is none from -G output.
    if effective.get('proxycommand', ['none']) != [proxy_command]:
        raise ValueError('Unexpected effective SSH proxy')
    if effective.get('controlpath', ['none']) != ['none']:
        raise ValueError('SSH connection sharing must be disabled')


def verify_transport(spec: dict) -> dict:
    result = build_transport(spec)
    if result['proxy'] is not None:
        verify_hop(spec['proxy'], result['proxy'])
    verify_hop(spec['target'], result['target'])
    return result


def main() -> int:
    try:
        print(json.dumps(verify_transport(json.load(sys.stdin))))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        print('venv-agents: structured SSH transport/trust verification failed; no remote connection attempted', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
