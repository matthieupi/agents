import test from 'node:test';
import assert from 'node:assert/strict';
import { runRemote, MAX_OUTPUT, MAX_INPUT } from '../transport.js';
import { fixture } from './fixture.js';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const request = (f, timeout_ms = 5000) => ({ operation: 'bash', cwd: f.target.cwd, args: { command: 'printf ok' }, expected: {}, timeout_ms, max_output_bytes: MAX_OUTPUT });

test('host pin mismatch and auth rejection fail closed', async t => {
  const f = await fixture(t, 'auth-fail');
  await assert.rejects(runRemote({ ...f.target, host_key_sha256: '0'.repeat(64) }, request(f)), /SSH/);
  await assert.rejects(runRemote(f.target, request(f)), /SSH/);
});

for (const mode of ['auth-timeout', 'hang', 'stderr', 'stdout']) {
  test(`bounded transport: ${mode}`, async t => {
    const f = await fixture(t, mode);
    await assert.rejects(runRemote(f.target, request(f, mode.includes('timeout') || mode === 'hang' ? 300 : 5000)), /timed out|budget|SSH/);
  });
}

test('abort closes connection; preabort and oversized input perform no connection', async t => {
  const f = await fixture(t, 'hang');
  const controller = new AbortController();
  const promise = runRemote(f.target, request(f), { signal: controller.signal });
  const timer = setTimeout(() => controller.abort(), 200);
  try { await assert.rejects(promise, /cancelled/); } finally { clearTimeout(timer); }
  const count = f.connections();
  await assert.rejects(runRemote(f.target, request(f), { signal: controller.signal }), /cancelled/);
  const huge = request(f); huge.args.command = 'x'.repeat(MAX_INPUT);
  await assert.rejects(runRemote(f.target, huge), /input budget/);
  assert.equal(f.connections(), count);
});

test('real helper output is explicitly truncated and deadline/cancellation clean up', async t => {
  const f = await fixture(t);
  const large = request(f); large.args.command = "python3 -c 'print(\"x\" * 100000)'";
  const result = await runRemote(f.target, large);
  assert.equal(result.truncated, true);
  assert.ok(Buffer.byteLength(result.output) <= MAX_OUTPUT);
  const slow = request(f, 500); slow.args.command = 'sleep 30';
  await assert.rejects(runRemote(f.target, slow), /timed out/);
  const controller = new AbortController();
  slow.timeout_ms = 5000;
  slow.args.command = "printf '%s' $$ > fixture-process.pid; exec sleep 30";
  const pending = runRemote(f.target, slow, { signal: controller.signal });
  let pid;
  const deadline = Date.now() + 3000;
  while (!pid && Date.now() < deadline) {
    try { pid = Number(await readFile(path.join(f.target.cwd, 'fixture-process.pid'), 'utf8')); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (!pid) await new Promise(resolve => setTimeout(resolve, 20));
  }
  controller.abort();
  await assert.rejects(pending, /cancelled/);
  assert.ok(pid > 0, 'remote command actually started before cancellation');
  let alive = true;
  for (let i = 0; i < 100 && alive; i++) {
    try { process.kill(pid, 0); await new Promise(resolve => setTimeout(resolve, 20)); }
    catch (error) { if (error.code !== 'ESRCH') throw error; alive = false; }
  }
  assert.equal(alive, false, 'helper reaped the cancelled command');
});
