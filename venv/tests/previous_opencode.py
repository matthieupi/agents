"""Immutable prior-release HOME fixture; never reads mutable working-tree assets.

The two-agent config is emitted by the *actual* historical public_agents helper.
This reproduces a valid subset left after the prior seeder excluded private names,
not an invented whole-config default. Asset bytes come from pinned Git objects.
The fixture requires this repository's history on the test controller; disposable
image tests receive these public bytes via stdin, without Git or user mounts.
"""
import base64
import json
from pathlib import Path
import subprocess

COMMIT = 'c8567a4f48a3b86a807aec28b474cca7b7bbb16c'
REPO = Path(__file__).resolve().parents[2]


def historical(path: str) -> bytes:
    return subprocess.check_output(['git', 'show', COMMIT + ':' + path], cwd=REPO)


def previous_home(resources: Path) -> dict:
    namespace: dict = {'__name__': 'historical_fixture'}
    exec(compile(historical('venv/entry.py'), '<immutable previous VM seeder>', 'exec'), namespace)
    config = json.loads(historical('opencode/.opencode/config/opencode.json'))
    selected = {'agent': {name: config['agent'][name] for name in ('explore', 'build')}}
    projected = namespace['public_agents'](selected, resources)
    assets = {name: base64.b64encode(historical('opencode/.opencode/config/' + name)).decode()
              for name in ('plugins/first-prompt-title.js', 'tui-plugins/session-title.mjs',
                           'plugins/kdco-worktree.ts', 'plugins/kdco-notify.ts', 'plugins/kdco-background-agents.ts')}
    return {'config': json.dumps(projected, indent=2) + '\n', 'assets': assets, 'commit': COMMIT}
