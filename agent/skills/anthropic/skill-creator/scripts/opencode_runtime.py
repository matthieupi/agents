"""OpenCode V2 subprocess boundary (local adaptation; see OPENCODE_PORT.md).

Only successful native tool events count. A broken run is never a negative
trigger observation. The CLI event contract is documented in OPENCODE_PORT.md.
"""

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class OpenCodeError(RuntimeError):
    """The run did not produce a complete, usable observation."""


# Cancellation and Popen share this gate. A batch cannot launch a new process
# after cancel_run has set its event, including workers already dequeued.
_LAUNCH_LOCK = threading.Lock()


def cancel_run(cancel_event: threading.Event | None) -> None:
    """Signal cancellation atomically with respect to subprocess launches."""
    if cancel_event is not None:
        with _LAUNCH_LOCK:
            cancel_event.set()


@contextmanager
def isolated_workspace(skill_name: str | None = None, description: str | None = None):
    """Yield (workspace, environment) without modifying live discovery/config.

Keep the normal data directory for V2's credential database; do not copy keys.
Home/config/cache/state and skill discovery are private to each worker. Optional
SKILL_CREATOR_PROVIDER_CONFIG is a JSON file containing only providers/model.
"""
    if sys.platform != 'linux':
        raise OpenCodeError('The isolated evaluation runner supports Linux only')
    if skill_name is not None and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", skill_name):
        raise ValueError("Use a lowercase kebab-case path-derived skill ID")
    # Managed configuration has higher precedence and may start plugins. Do not
    # silently override or bypass it; require an administrator-reviewed runner.
    managed = Path('/etc/opencode')
    if managed.exists() and any(managed.iterdir()):
        raise OpenCodeError("Managed OpenCode configuration requires a separately reviewed eval environment")
    provider_config = {}
    if source := os.environ.get("SKILL_CREATOR_PROVIDER_CONFIG"):
        provider_config = json.loads(Path(source).read_text())
        if not isinstance(provider_config, dict) or set(provider_config) - {"providers", "model"}:
            raise ValueError("Provider config accepts only providers and model")
    data_home = os.environ.get("XDG_DATA_HOME", str(Path.home() / '.local/share'))
    base = Path('/tmp/opencode')
    with tempfile.TemporaryDirectory(prefix='skill-eval-', dir=base if os.access(base, os.W_OK) else None) as tmp:
        root = Path(tmp)
        workspace = root / 'workspace'
        workspace.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith('OPENCODE_')}
        for key, folder in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
                            ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"),
                            ("TMPDIR", "tmp")):
            (root / folder).mkdir()
            env[key] = str(root / folder)
        env['XDG_DATA_HOME'] = data_home
        if 'OPENCODE_DB' in os.environ:
            env['OPENCODE_DB'] = os.environ['OPENCODE_DB']
        env['OPENCODE_CONFIG_DIR'] = str(root / 'config/opencode')
        env['OPENCODE_CONFIG_PROJECT_DISABLE'] = 'true'
        rules = [{"action": "*", "resource": "*", "effect": "deny"}]
        if skill_name:
            rules.append({"action": "skill", "resource": skill_name, "effect": "allow"})
            skill = workspace / '.opencode/skills' / skill_name
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text(
                f'---\nname: {json.dumps(skill_name)}\ndescription: {json.dumps(description)}\n---\n\n'
                'This is a description-discovery evaluation. The skill has loaded. '
                'Respond briefly without executing the task.\n'
            )
        config = {
            "$schema": "https://opencode.ai/config.json",
            **provider_config,
            "snapshots": False,
            "skills": [str(workspace / '.opencode/skills')] if skill_name else [],
            "permissions": rules,
            "agents": {"skill-eval": {
                "description": "Restricted skill description evaluation",
                "mode": "primary",
                "permissions": rules,
            }},
        }
        env['OPENCODE_CONFIG_CONTENT'] = json.dumps(config)
        yield workspace, env


def run_opencode(prompt: str, model: str | None, timeout: int, workspace: Path, env: dict,
                 cancel_event: threading.Event | None = None) -> list[dict]:
    """Drain both pipes with an overall deadline and cooperative cancellation."""
    if sys.platform != 'linux':
        raise OpenCodeError('The isolated evaluation runner supports Linux only')
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    deadline = time.monotonic() + timeout
    cmd = ['opencode', 'run', '--standalone', '--format', 'json', '--agent', 'skill-eval']
    if model:
        if '/' not in model:
            raise ValueError("model must be provider/model or provider/model#variant")
        cmd.extend(['--model', model])
    # V2 consumes non-TTY stdin as the prompt. An unnamed private file avoids
    # both argv leaks and CPython's incomplete-stdin retry behavior after a
    # communicate(input=..., timeout=...) timeout. Only output pipes need draining.
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise OpenCodeError('OpenCode run cancelled')
        with tempfile.TemporaryFile(mode='w+', encoding='utf-8', dir=workspace) as prompt_input:
            prompt_input.write(prompt)
            prompt_input.seek(0)
            with _LAUNCH_LOCK:
                if cancel_event is not None and cancel_event.is_set():
                    raise OpenCodeError('OpenCode run cancelled')
                if time.monotonic() >= deadline:
                    raise OpenCodeError(f'OpenCode timed out after {timeout}s before launch')
                process = subprocess.Popen(cmd, stdin=prompt_input, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True, cwd=workspace,
                                           env=env, start_new_session=True)
    except OSError as exc:
        raise OpenCodeError(f"Cannot start opencode: {exc}") from exc
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise OpenCodeError('OpenCode run cancelled')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(cmd, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(.1, remaining))
                break
            except subprocess.TimeoutExpired:
                # communicate retains both output buffers across retries.
                if process.poll() not in (None, 0):
                    # A failed CLI may leave descendants holding its pipes open.
                    raise OpenCodeError(f'OpenCode exited {process.returncode}')
        if cancel_event is not None and cancel_event.is_set():
            raise OpenCodeError('OpenCode run cancelled')
        if process.returncode:
            raise OpenCodeError(f"OpenCode exited {process.returncode}: {stderr[-2000:]}")
    except BaseException as exc:
        cancel_run(cancel_event)
        # Kill the private server as well as the CLI; reap even on interruption.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        if isinstance(exc, subprocess.TimeoutExpired):
            raise OpenCodeError(f"OpenCode timed out after {timeout}s") from exc
        raise
    events = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OpenCodeError("Invalid OpenCode JSON event stream") from exc
        if not isinstance(event, dict):
            raise OpenCodeError("Invalid OpenCode event")
        if event.get('type') == 'error':
            raise OpenCodeError(f"OpenCode API/runtime error: {event.get('error')}")
        if event.get('type') == 'tool_use' and event.get('part', {}).get('state', {}).get('status') == 'error':
            raise OpenCodeError("OpenCode tool failed; observation is invalid")
        events.append(event)
    finishes = [e.get('part', {}).get('reason') for e in events if e.get('type') == 'step_finish']
    if not finishes or finishes[-1] != 'stop':
        raise OpenCodeError("OpenCode did not complete a normal final step")
    return events
