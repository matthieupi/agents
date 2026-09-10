#!/usr/bin/python3 -I
"""Named SSH account shell adapter; sysops never uses this shell."""
import os
import sys


def shell_invocation(arguments: list[str], environment: dict) -> tuple[list[str], dict]:
    environment = dict(environment)
    for key in ("BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "VENV_AGENTS_STARTED", "VENV_AGENTS_REQUEST"):
        environment.pop(key, None)
    if len(arguments) == 2 and arguments[0] == "-c":
        environment["VENV_AGENTS_REQUEST"] = "command"
        return ["/bin/bash", "--noprofile", "--norc", "-c", arguments[1]], environment
    if not arguments:
        environment["VENV_AGENTS_REQUEST"] = "shell" if environment.get("SSH_CONNECTION") else "local"
        return ["/bin/bash", "--login"], environment
    raise ValueError("Unsupported login shell invocation")


def main() -> None:
    try:
        arguments, environment = shell_invocation(sys.argv[1:], os.environ)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(64)
    os.execve(arguments[0], arguments, environment)


if __name__ == "__main__":
    main()
