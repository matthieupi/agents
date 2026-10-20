"""V2 readiness and opt-in mount-free disposable image acceptance."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT.parent / 'opencode/.opencode/config'


def canonical_prompts():
    """OpenCode owns system personas; shared agent/ owns GSD prompt resources."""
    canonical = json.loads((CANONICAL / 'opencode.json').read_text())
    result = {}
    for agent in canonical['agents'].values():
        if 'system' not in agent:
            continue
        relative = agent['system'][8:-1]
        owner = CANONICAL if relative.startswith('system/') else ROOT.parent / 'agent'
        result[relative] = (owner / relative).read_text()
    return result


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReadinessTests(unittest.TestCase):
    def test_authenticated_api_info_and_v1_response_rejection(self):
        health, entry = load('opencode_health'), load('entry')
        with patch.dict(sys.modules, entry=entry), patch.object(entry, 'opencode_password', return_value='fixture'), \
                patch.object(health.urllib.request, 'urlopen') as request:
            request.return_value.__enter__.return_value = io.BytesIO(b'{"version":"2.0.32","pid":42}')
            self.assertEqual(health.request_info(Path('/private'), 5102)['pid'], 42)
            sent = request.call_args.args[0]
            self.assertEqual(sent.full_url, 'http://127.0.0.1:5102/api/info')
            self.assertEqual(sent.get_header('Authorization'), 'Basic ' + base64.b64encode(b'opencode:fixture').decode())
            request.return_value.__enter__.return_value = io.BytesIO(b'{"healthy":true,"version":"1.18.29"}')
            with self.assertRaisesRegex(ValueError, 'V2'):
                health.request_info(Path('/private'), 5102)

    def test_canonical_config_projection_preserves_native_metadata(self):
        entry = load('entry')
        canonical = json.loads((ROOT.parent / 'opencode/.opencode/config/opencode.json').read_text())
        projected = entry.public_agents(canonical, Path('/public/resources'))
        self.assertEqual(projected['providers'], canonical['providers'])
        self.assertEqual(projected['permissions'], canonical['permissions'])
        for name, agent in canonical['agents'].items():
            actual = dict(projected['agents'][name])
            if 'system' in agent:
                self.assertTrue(actual['system'].startswith('{file:/public/resources/'))
                actual['system'] = agent['system']
            self.assertEqual(actual, agent)

    def test_image_source_closure_and_enrolled_prompt_resources(self):
        dockerfile = (ROOT / 'Dockerfile.opencode').read_text()
        allowlist = (ROOT / 'Dockerfile.opencode.dockerignore').read_text().splitlines()
        for name in ('opencode.json', 'cli.json', 'plugins/first-prompt-title.js',
                     'plugins/background-subagents.js', 'tui-plugins/session-title.mjs'):
            self.assertTrue((CANONICAL / name).is_file(), name)
            self.assertIn('!opencode/.opencode/config/' + name, allowlist)
            if name.startswith('plugins/'):
                self.assertIn('opencode/.opencode/config/' + name, dockerfile)
        self.assertIn('!opencode/.opencode/config/tui-plugins/session-title/**', allowlist)
        self.assertTrue((CANONICAL / 'tui-plugins/session-title/tui.js').is_file())
        self.assertNotIn('kdco', dockerfile.lower())
        self.assertNotIn('kdco', '\n'.join(allowlist).lower())
        self.assertNotIn('package-lock.json', '\n'.join(allowlist))
        canonical = json.loads((CANONICAL / 'opencode.json').read_text())
        resources = ROOT.parent / 'agent'
        prompts = canonical_prompts()
        for agent in canonical['agents'].values():
            if 'system' not in agent:
                continue
            relative = agent['system'][8:-1]
            source = (resources / relative).resolve(strict=True)
            self.assertTrue(source.is_relative_to(resources.resolve()))
            self.assertTrue(source.is_file())
            self.assertTrue(prompts[relative])
        # Prompts are intentionally supplied by enrollment, never image defaults.
        self.assertNotIn('COPY --chown=node:node agent/', dockerfile)


SMOKE = r'''
import base64, hashlib, json, os, pathlib, secrets, subprocess, sys, tempfile, time, urllib.request, urllib.error
sys.path.insert(0, '/opt/venv')
import entry
public = json.load(sys.stdin)
with tempfile.TemporaryDirectory(prefix='vm-v2-smoke-') as temporary:
    root = pathlib.Path(temporary)
    home, resources = root / 'home', root / 'resources'
    home.mkdir(mode=0o700)
    for name in ('commands', 'skills', 'system', 'gsd'):
        (resources / name).mkdir(parents=True)
    canonical = json.loads(pathlib.Path('/opt/opencode-defaults/opencode.json').read_text())
    assert canonical == public['canonical'], 'image config differs from current canonical source'
    for agent in canonical['agents'].values():
        if 'system' in agent:
            relative = agent['system'][8:-1]
            (resources / relative).write_text(public['prompts'][relative])
    env = dict(os.environ, HOME=str(home), USER='vmfixture', LOGNAME='vmfixture',
                VENV_AGENT_RESOURCES=str(resources), VENV_AGENT_PORT='45123', PYTHONDONTWRITEBYTECODE='1')
    config = home / '.config/opencode'
    previous = public.get('previous')
    private = None
    if previous:
        config.mkdir(mode=0o700, parents=True)
        (config / 'config.json').write_text(previous['config'].replace('/previous/resources', str(resources)))
        for name, encoded in previous['assets'].items():
            destination = config / name
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination.write_bytes(base64.b64decode(encoded))
        (config / 'kdco').symlink_to(resources / 'opencode-plugins/kdco')
        (config / 'plugins/private.js').write_text('export default { id: "private-plugin", setup() {} };')
        private = {'model': 'openai/gpt-6', 'agent': {'build': {'description': 'private existing override'}},
                   'permission': {'edit': 'deny'},
                   'provider': {'openai': {'options': {'apiKey': 'private-key-fixture'}}},
                   'plugin': [['./plugins/private.js', {'keep': True}], './plugins/kdco-worktree.ts']}
        (config / 'opencode.json').write_text(json.dumps(private))
        (config / 'auth.json').write_bytes(b'private-auth-fixture')
        (config / 'private-existing.db').write_bytes(b'private-database-fixture')
        # Private CLI settings are not replaced by canonical defaults.
        (config / 'cli.json').write_text('{"theme":{"name":"private-theme"},"plugins":[]}')
    entry.initialize('opencode', home, resources)
    assert not entry.seed_opencode(home, resources)['changed'], 'migration not idempotent'
    secret = secrets.token_urlsafe(32)
    password = config / 'server-password'
    password.write_text(secret)
    password.chmod(0o600)
    process = subprocess.Popen(['/usr/bin/python3', '-I', '/opt/venv/entry.py', 'opencode', '--web'],
                               env=env, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        url = 'http://127.0.0.1:45123/api/info'
        authorization = 'Basic ' + base64.b64encode(('opencode:' + secret).encode()).decode()
        def api(path):
            with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:45123' + path,
                    headers={'Authorization': authorization}), timeout=10) as response:
                return json.load(response)
        for _ in range(90):
            if process.poll() is not None:
                raise AssertionError('server exited before readiness')
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={'Authorization': authorization}), timeout=1) as response:
                    info = json.load(response)
                assert info['version'].startswith('2.') and type(info['pid']) is int
                break
            except (OSError, urllib.error.URLError):
                time.sleep(1)
        else:
            raise AssertionError('readiness timeout')
        try:
            urllib.request.urlopen(url, timeout=2)
            raise AssertionError('unauthenticated API accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 401
        try:
            bad = 'Basic ' + base64.b64encode(b'opencode:wrong-disposable-password').decode()
            urllib.request.urlopen(urllib.request.Request(url, headers={'Authorization': bad}), timeout=2)
            raise AssertionError('wrong backend password accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 401
        subprocess.run(['/usr/bin/python3', '-I', '/opt/opencode-health.py'], env=env, check=True, timeout=10)
        seeded = json.loads((config / 'opencode.json').read_text())
        if previous:
            for key in ('model', 'agent', 'permission', 'provider'):
                assert seeded[key] == private[key], 'private setting changed'
            assert seeded['plugin'] == [private['plugin'][0], *(str(config / 'plugins' / name)
                                        for name in ('first-prompt-title.js', 'background-subagents.js'))]
            assert (config / 'auth.json').read_bytes() == b'private-auth-fixture'
            assert (config / 'private-existing.db').read_bytes() == b'private-database-fixture'
            assert not (config / 'config.json').exists()
            assert set(seeded['agents']) == {'explore'}
        else:
            assert seeded['providers'] == canonical['providers']
            assert seeded['permissions'] == canonical['permissions']
            assert seeded['plugins'] == [str(config / 'plugins' / name)
                                         for name in ('first-prompt-title.js', 'background-subagents.js')]
        for name, fingerprint in public['assets'].items():
            if previous and name == 'cli.json':
                assert json.loads((config / name).read_text())['theme'] == {'name': 'private-theme'}
                continue
            assert hashlib.sha256((config / name).read_bytes()).hexdigest() == fingerprint, name
        for _ in range(10):
            plugins = api('/api/plugin?directory=' + str(root))['data']
            if {'first-prompt-title', 'background-subagents'} <= {item.get('id') for item in plugins}:
                break
            time.sleep(1)
        else:
            raise AssertionError('canonical plugins missing from native API: ' + json.dumps(plugins))
        for plugin_id in ('first-prompt-title', 'background-subagents'):
            active = next(item for item in plugins if item.get('id') == plugin_id)
            assert active['state'] == {'status': 'active'}, active
        if previous:
            assert next(item for item in plugins if item.get('id') == 'private-plugin')['state'] == {'status': 'active'}
        assert not any('kdco' in json.dumps(item).lower() for item in plugins)
        agents = {item['id']: item for item in api('/api/agent?directory=' + str(root))['data']}
        for name, definition in canonical['agents'].items():
            if previous and name != 'explore':
                continue
            if 'system' not in definition:
                continue
            expected = public['prompts'][definition['system'][8:-1]]
            assert agents[name]['system'].strip() == expected.strip(), name
            assert agents[name]['mode'] == definition['mode'], name
        if previous:
            assert agents['build']['description'] == 'private existing override'
            documents = [item['info'] for item in api('/api/config?directory=' + str(root))
                         if item['type'] == 'document']
            assert any({'action': 'edit', 'resource': '*', 'effect': 'deny'} in doc.get('permissions', [])
                       for doc in documents), 'private legacy policy not loaded by upstream V2'
            assert not any((config / 'plugins' / name).exists() for name in entry.RETIRED)
        # Exercise the exact standalone source's default hooks without a model call.
        hooks = r"""
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const plugin = (await import(pathToFileURL(process.argv[1]))).default;
const registered = {};
await plugin.setup({tool:{hook:async (name, fn) => registered[name] = fn},
                    session:{hook:async (name, fn) => registered[name] = fn}});
const implicit = {tool:'subagent',input:{agent:'explore'}};
registered['execute.before'](implicit);
assert.equal(implicit.input.background, true);
const explicit = {tool:'subagent',input:{background:false}};
registered['execute.before'](explicit);
assert.equal(explicit.input.background, false);
const other = {tool:'shell',input:{}};
registered['execute.before'](other);
assert.equal(other.input.background, undefined);
const event = {system:[]};
registered.context(event);
registered.context(event);
assert.equal(event.system.length, 1);
assert.match(event.system[0].text, /background execution is the default/);
"""
        subprocess.run(['node', '--input-type=module', '-e', hooks,
                        str(config / 'plugins/background-subagents.js')], env=env, check=True, timeout=10)
        assert previous or not (config / 'config.json').exists()
        assert not (config / 'kdco').exists() and not (config / 'kdco').is_symlink()
        assert not pathlib.Path('/opt/opencode-defaults/kdco').exists()
        print('V2 VM entry, canonical seed, explicit password, authenticated /api/info:', info['version'])
    finally:
        process.terminate()
        logs = process.communicate(timeout=15)[0]
        assert secret.encode() not in logs, 'backend password leaked to server output'
'''


class DisposableImageTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('VENV_OPENCODE_TEST_IMAGE'), 'Set disposable VM image ID/tag to run mount-free acceptance')
    def test_vm_entry_and_authenticated_readiness(self):
        self.run_image(previous=False)

    @unittest.skipUnless(os.environ.get('VENV_OPENCODE_TEST_IMAGE'), 'Set disposable VM image to test prior-release HOME migration')
    def test_previous_release_home_migrates_in_place(self):
        self.run_image(previous=True)

    def run_image(self, *, previous: bool):
        canonical = json.loads((CANONICAL / 'opencode.json').read_text())
        prompts = canonical_prompts()
        names = ['cli.json', 'plugins/first-prompt-title.js', 'plugins/background-subagents.js',
                 'tui-plugins/session-title.mjs', 'tui-plugins/session-title/tui.js']
        assets = {name: hashlib.sha256((CANONICAL / name).read_bytes()).hexdigest() for name in names}
        payload = dict(canonical=canonical, prompts=prompts, assets=assets)
        if previous:
            from previous_opencode import previous_home
            payload['previous'] = previous_home(Path('/previous/resources'))
        result = subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'none', '--user', '10001:10001',
                                 '--cap-drop=ALL', '--security-opt=no-new-privileges',
                                 '--entrypoint', '/usr/bin/python3', os.environ['VENV_OPENCODE_TEST_IMAGE'],
                                 '-I', '-c', SMOKE], input=json.dumps(payload),
                                text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('authenticated /api/info:', result.stdout)


if __name__ == '__main__':
    unittest.main()
