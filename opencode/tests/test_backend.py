"""Workstation backend probes and command contracts; no Docker or real servers."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HEALTH = ROOT / 'opencode/backend-health.mjs'


class BackendHealth(unittest.TestCase):
    def probe(self, body, *, wait=False, password='', username=''):
        # Exercise the actual Node helper, replacing only its HTTP boundary.
        script = '''
import assert from 'node:assert/strict';
let attempts = 0;
globalThis.fetch = async (url, options) => {
  assert.equal(url, 'http://127.0.0.1:4096/global/health');
  const password = process.env.OPENCODE_SERVER_PASSWORD;
  assert.deepEqual(options.headers, password ? {
    Authorization: 'Basic ' + Buffer.from((process.env.OPENCODE_SERVER_USERNAME || 'opencode') + ':' + password).toString('base64')
  } : {});
  assert.ok(options.signal instanceof AbortSignal);
  attempts++;
  BODY
};
await import(HELPER);
'''.replace('BODY', body).replace('HELPER', json.dumps(HEALTH.as_uri()))
        return subprocess.run(
            ['node', '--input-type=module', '-e', script, *(['--', '--wait'] if wait else [])],
            env=dict(os.environ, OPENCODE_SERVER_PASSWORD=password, OPENCODE_SERVER_USERNAME=username),
            capture_output=True, text=True, timeout=6)

    def test_healthy_authenticated_and_anonymous(self):
        for password, username in [('', ''), ('secret:with spaces', 'alice'), ('secret', '')]:
            result = self.probe('return {ok: true, json: async () => ({healthy: true})};',
                                password=password, username=username)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout + result.stderr, '')

    def test_http_failure_invalid_body_and_connection_failure(self):
        for body in [
            'return {ok: false, json: async () => ({healthy: true})};',
            'return {ok: true, json: async () => ({healthy: false})};',
            'return {ok: true, json: async () => ({})};',
            'return {ok: true, json: async () => {throw Error("not JSON")}};',
            'throw Error("connection refused")',
        ]:
            with self.subTest(body=body):
                result = self.probe(body, password='do-not-print')
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout + result.stderr, '')

    def test_wait_retries_transient_startup(self):
        result = self.probe('return {ok: true, json: async () => ({healthy: attempts >= 2})};', wait=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_hung_http_body_has_hard_deadline(self):
        result = self.probe('return {ok: true, json: () => new Promise(() => {})};')
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_cpu_gpu_startup_and_health_match(self):
        for name in ('Dockerfile', 'Dockerfile.gpu'):
            text = (ROOT / 'opencode' / name).read_text()
            self.assertIn('npm install -g opencode-ai@latest', text)
            self.assertIn('COPY init.sh backend-health.mjs /opt/harness/', text)
            self.assertIn('CMD node /opt/harness/backend-health.mjs', text)
            self.assertIn('--start-period=120s', text)
            self.assertIn('exec opencode web --hostname 0.0.0.0 --port 4096 --mdns false', text)
            self.assertNotIn('CMD ["opencode"]', text)


class BackendStartup(unittest.TestCase):
    def test_init_once_then_foreground_exec_and_init_failure_blocks_backend(self):
        dockerfile = (ROOT / 'opencode/Dockerfile').read_text()
        command = json.loads(next(line[4:] for line in dockerfile.splitlines() if line.startswith('CMD [')))[-1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init = root / 'init.sh'
            init.write_text('#!/bin/bash\nprintf "init\\n" >> "$CALLS"\nexit "$INIT_STATUS"\n')
            init.chmod(0o755)
            backend = root / 'opencode'
            backend.write_text('#!/bin/bash\nprintf "backend:%s:%s\\n" "$$" "$*" >> "$CALLS"\n')
            backend.chmod(0o755)
            command = command.replace('/opt/harness/init.sh', str(init)).replace('exec opencode ', f'exec {backend} ')
            for status in ('0', '42'):
                calls = root / 'calls'
                calls.unlink(missing_ok=True)
                process = subprocess.Popen(['/bin/bash', '-c', command],
                                           env=dict(os.environ, CALLS=str(calls), INIT_STATUS=status),
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, int(status), stdout + stderr)
                expected = ['init']
                if status == '0':
                    expected.append(f'backend:{process.pid}:web --hostname 0.0.0.0 --port 4096 --mdns false')
                self.assertEqual(calls.read_text().splitlines(), expected)


if __name__ == '__main__':
    unittest.main()
