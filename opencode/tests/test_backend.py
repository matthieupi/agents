"""Workstation backend probes and command contracts; no Docker or real servers."""
import json
import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
HEALTH = ROOT / 'opencode/backend-health.mjs'


class BackendHealth(unittest.TestCase):
    def probe(self, body, *, wait=False, password='', username='', port=None):
        # Exercise the actual Node helper, replacing only its HTTP boundary.
        script = '''
import assert from 'node:assert/strict';
let attempts = 0;
globalThis.fetch = async (url, options) => {
  assert.equal(url, EXPECTED_URL);
  const password = process.env.OPENCODE_PASSWORD ?? process.env.OPENCODE_SERVER_PASSWORD;
  assert.deepEqual(options.headers, password ? {
    Authorization: 'Basic ' + Buffer.from('opencode:' + password).toString('base64')
  } : {});
  assert.ok(options.signal instanceof AbortSignal);
  attempts++;
  BODY
};
await import(HELPER);
'''.replace('BODY', body).replace('HELPER', json.dumps(HEALTH.as_uri())).replace(
            'EXPECTED_URL', json.dumps(f'http://127.0.0.1:{port or 4096}/api/info'))
        return subprocess.run(
            ['node', '--input-type=module', '-e', script, '--', 'backend-health.mjs', *([str(port)] if port else []), *(['--wait'] if wait else [])],
             env=dict(os.environ, OPENCODE_PASSWORD=password, OPENCODE_SERVER_PASSWORD='ignored-legacy', OPENCODE_SERVER_USERNAME=username),
            capture_output=True, text=True, timeout=6)

    def test_healthy_authenticated_and_anonymous(self):
        for password, username in [('', ''), ('secret:with spaces', 'alice'), ('secret', '')]:
            result = self.probe('return {ok: true, json: async () => ({version: "2.0.32"})};',
                                password=password, username=username)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout + result.stderr, '')

    def test_http_failure_invalid_body_and_connection_failure(self):
        for body in [
            'return {ok: false, json: async () => ({version: "2.0.32"})};',
            'return {ok: true, json: async () => ({version: "1.0.0"})};',
            'return {ok: true, json: async () => ({})};',
            'return {ok: true, json: async () => {throw Error("not JSON")}};',
            'throw Error("connection refused")',
        ]:
            with self.subTest(body=body):
                result = self.probe(body, password='do-not-print')
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stdout + result.stderr, '')

    def test_wait_retries_transient_startup(self):
        result = self.probe('return {ok: attempts >= 2, json: async () => ({version: "2.0.32"})};', wait=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_service_template_port_argument(self):
        result = self.probe('return {ok: true, json: async () => ({version: "2.1.1"})};', port=4196, password='disposable')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_hung_http_body_has_hard_deadline(self):
        result = self.probe('return {ok: true, json: () => new Promise(() => {})};')
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_vm_image_uses_shared_v2_installer_without_baked_config_or_kdco(self):
        text = (ROOT / 'opencode/Dockerfile.service').read_text()
        self.assertIn('USER node\nRUN /bin/bash', text)
        self.assertIn('; install_runtime', text)
        self.assertIn('USER agent', text)
        self.assertNotIn('OPENCODE_VERSION', text)
        self.assertNotIn('kdco', text.lower())
        self.assertNotIn('COPY .opencode', text)
        ignore = (ROOT / 'opencode/Dockerfile.service.dockerignore').read_text()
        self.assertTrue(ignore.startswith('**\n'))
        self.assertNotIn('!.opencode', ignore)

    def test_installer_checks_v2_package_and_binary_before_and_after_promotion(self):
        text = (ROOT / 'opencode/scripts/entrypoint.sh').read_text()
        self.assertIn('"@opencode/cli@latest"', text)
        self.assertIn('node_modules/@opencode/cli/package.json', text)
        self.assertIn('Number(p.version.split(".")[0])<2', text)
        self.assertIn('verify_runtime "$stage/runtime" "$stage/home"', text)
        self.assertIn('verify_runtime "$OPENCODE_PREFIX" "$stage/home" "$resolved"', text)
        self.assertIn('previous runtime restored', text)
        self.assertIn('never root', text)
        self.assertNotIn('kdco', text.lower())


if __name__ == '__main__':
    unittest.main()
