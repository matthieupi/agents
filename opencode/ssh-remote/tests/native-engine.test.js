import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { spawn, spawnSync } from 'node:child_process';
import { mkdir, chmod, writeFile, readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fixture } from './fixture.js';

test('positive native 1.18.29 run routes scripted read through SSH, not the local shadow', {
  skip: !process.env.OPENCODE_TEST_BINARY && 'Opt-in positive native engine fixture; npm run test:engine',
  timeout: 45000,
}, async t => {
  const f = await fixture(t);
  const neutral = path.join(f.directory, 'neutral');
  const configHome = path.join(f.directory, 'config');
  const configDir = path.join(configHome, 'opencode');
  await mkdir(neutral);
  await mkdir(configDir, { recursive: true });
  const remoteMarker = 'FIXTURE_REMOTE_CONTENT_83f1';
  const localMarker = 'FIXTURE_LOCAL_SHADOW_MUST_NOT_APPEAR';
  await writeFile(path.join(neutral, 'shadow.txt'), localMarker + '\n');
  await writeFile(path.join(f.target.cwd, 'shadow.txt'), remoteMarker + '\n');

  // One purpose-built OpenAI-compatible chat endpoint, no real keys or providers.
  let readsIssued = 0, mainCalls = 0, streamedMainCalls = 0, toolResult, systemPrompt = '', httpCalls = 0;
  const failures = [];
  const http = createServer(async (req, res) => {
    try {
      if (++httpCalls > 8 || req.method !== 'POST' || req.url !== '/v1/chat/completions')
        throw Error('Unexpected fixture provider request');
      let raw = '';
      for await (const chunk of req) {
        raw += chunk.toString('utf8');
        if (raw.length > 1024 * 1024) throw Error('Fixture provider request exceeds budget');
      }
      const body = JSON.parse(raw);
      const main = body.tools?.some(tool => tool.function?.name === 'read');
      let message = { role: 'assistant', content: 'Fixture auxiliary title' };
      let reason = 'stop';
      if (main) {
        mainCalls++;
        if (body.stream) streamedMainCalls++;
        systemPrompt = body.messages.filter(message => message.role === 'system').map(message => message.content).join('\n');
        const result = body.messages.find(message => message.role === 'tool' && message.tool_call_id === 'fixture_read_call');
        if (result) {
          toolResult = result.content;
          message.content = 'FIXTURE_READ_FINISHED';
        } else {
          if (++readsIssued !== 1) throw Error('Fixture model tried to issue more than one read');
          message = { role: 'assistant', content: null, tool_calls: [{
            id: 'fixture_read_call', type: 'function',
            function: { name: 'read', arguments: JSON.stringify({ filePath: 'shadow.txt' }) },
          }] };
          reason = 'tool_calls';
        }
      }
      const base = { id: 'fixture-chat', created: 1, model: 'fixture-model' };
      if (body.stream) {
        res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
        const delta = message.tool_calls
          ? { role: 'assistant', tool_calls: message.tool_calls.map((call, index) => ({ index, ...call })) }
          : message;
        for (const choice of [{ index: 0, delta, finish_reason: null }, { index: 0, delta: {}, finish_reason: reason }])
          res.write('data: ' + JSON.stringify({ ...base, object: 'chat.completion.chunk', choices: [choice] }) + '\n\n');
        res.end('data: [DONE]\n\n');
      } else {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ ...base, object: 'chat.completion', choices: [{ index: 0, message, finish_reason: reason }],
          usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 } }));
      }
    } catch (error) {
      failures.push(error.message);
      res.writeHead(400).end('Fixture request rejected');
    }
  });
  http.requestTimeout = 5000;
  await new Promise(resolve => http.listen(0, '127.0.0.1', resolve));
  let child, exited, timer, killTimer;
  const kill = signal => {
    if (!child?.pid) return;
    try { process.kill(-child.pid, signal); } catch (error) { if (error.code !== 'ESRCH') throw error; }
  };
  try {
    // Pinned Npm.install skips unwritable directories; do not install outside package.
    await chmod(configDir, 0o500);
    const env = { PATH: '/usr/local/bin:/usr/bin:/bin', HOME: f.directory,
      XDG_CONFIG_HOME: configHome, XDG_DATA_HOME: path.join(f.directory, 'data'),
      XDG_STATE_HOME: path.join(f.directory, 'engine-state'), XDG_CACHE_HOME: path.join(f.directory, 'cache'),
      OPENCODE_DISABLE_AUTOUPDATE: '1', OPENCODE_DISABLE_MODELS_FETCH: '1',
      OPENCODE_DISABLE_DEFAULT_PLUGINS: '1', OPENCODE_DISABLE_PROJECT_CONFIG: '1',
      OPENCODE_DISABLE_EXTERNAL_SKILLS: '1', OPENCODE_DISABLE_CLAUDE_CODE: '1',
      OPENCODE_EXPERIMENTAL_DISABLE_FILEWATCHER: '1' };
    const version = spawnSync(process.env.OPENCODE_TEST_BINARY, ['--version'], { cwd: neutral, env, encoding: 'utf8', timeout: 10000 });
    assert.equal(version.status, 0, version.stderr);
    assert.equal(version.stdout.trim(), '1.18.29');
    const config = { $schema: 'https://opencode.ai/config.json',
      plugin: [[new URL('../index.js', import.meta.url).href, f.options]],
      enabled_providers: ['fixture'], model: 'fixture/fixture-model', small_model: 'fixture/fixture-model',
      provider: { fixture: { npm: '@ai-sdk/openai-compatible', name: 'Loopback fixture only',
        options: { baseURL: `http://127.0.0.1:${http.address().port}/v1` },
        models: { 'fixture-model': { name: 'Scripted fixture', tool_call: true, limit: { context: 32000, output: 1000 } } } } },
      agent: { fixture: { mode: 'primary', model: 'fixture/fixture-model' } },
      permission: { '*': 'deny', read: { [`${f.target.ref}:${f.target.cwd}/shadow.txt`]: 'allow' } },
      snapshot: false, lsp: false, formatter: false, autoupdate: false, share: 'disabled' };
    child = spawn(process.env.OPENCODE_TEST_BINARY,
      ['run', '--format', 'json', '--agent', 'fixture', '--model', 'fixture/fixture-model', 'Read shadow.txt once using read, then stop.'],
      { cwd: neutral, env: { ...env, OPENCODE_CONFIG_CONTENT: JSON.stringify(config) }, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '', stderr = '', bytes = 0, timedOut = false, oversized = false;
    for (const [stream, append] of [[child.stdout, value => { stdout += value; }], [child.stderr, value => { stderr += value; }]])
      stream.on('data', chunk => {
        bytes += chunk.length;
        if (bytes > 1024 * 1024) { oversized = true; kill('SIGKILL'); return; }
        append(chunk.toString('utf8'));
      });
    exited = new Promise((resolve, reject) => { child.once('error', reject); child.once('close', (code, signal) => resolve({ code, signal })); });
    timer = setTimeout(() => { timedOut = true; kill('SIGTERM'); killTimer = setTimeout(() => kill('SIGKILL'), 1000); }, 25000);
    const result = await exited;
    assert.equal(timedOut, false, 'native run timed out');
    assert.equal(oversized, false, 'native output exceeds fixture budget');
    assert.equal(result.code, 0, stderr);
    assert.deepEqual(failures, []);
    assert.equal(readsIssued, 1, 'scripted provider issued one model read');
    assert.equal(mainCalls, 2, 'model received tool result and finished');
    assert.equal(streamedMainCalls, 2, 'real engine consumed scripted SSE tool-call and stop responses');
    assert.match(String(toolResult), new RegExp(remoteMarker), stderr + '\n' + stdout);
    assert.ok(!String(toolResult).includes(localMarker));
    assert.match(systemPrompt, /SSH remote mode: immutable target fake\.project/);
    assert.equal(f.executions(), 1, 'custom read executed the bundled helper over SSH exactly once');
    assert.equal(f.requests[0].operation, 'read');
    assert.equal(f.requests[0].args.filePath, path.join(f.target.cwd, 'shadow.txt'));
    const events = stdout.split('\n').filter(line => line.startsWith('{')).map(line => JSON.parse(line));
    const toolEvent = events.find(event => event.type === 'tool_use' && event.part?.tool === 'read');
    assert.equal(toolEvent?.part.state.status, 'completed', 'native engine accepted custom object-shaped tool result');
    assert.equal(toolEvent.part.state.metadata.target, f.target.ref);
    assert.equal(toolEvent.part.state.title, `[${f.target.ref}] read`);
    assert.match(toolEvent.part.state.output, new RegExp(remoteMarker));
    assert.match(stdout, /FIXTURE_READ_FINISHED/, 'native run delivered the final scripted response');
    const bindings = await readdir(f.options.stateDirectory);
    assert.ok(bindings.length > 0, 'real SDK session lookup established a binding');
    for (const name of bindings) {
      const binding = JSON.parse(await readFile(path.join(f.options.stateDirectory, name), 'utf8'));
      assert.equal(binding.ref, f.target.ref);
      assert.match(binding.fingerprint, /^[a-f0-9]{64}$/);
    }
    // The system hook above only succeeds after real client.mcp.status(); no SDK
    // methods are mocked or replaced in this native process.
    assert.deepEqual(await readdir(configDir), [], 'no config mutation or dependency installation');
    assert.equal(await readFile(path.join(neutral, 'shadow.txt'), 'utf8'), localMarker + '\n');
    t.diagnostic('Native engine: one scripted read, one SSH helper exec, remote tool result and persisted target binding verified.');
  } finally {
    clearTimeout(timer); clearTimeout(killTimer);
    kill('SIGKILL');
    if (exited) await exited.catch(() => {});
    http.closeAllConnections();
    await new Promise(resolve => http.close(resolve));
    await chmod(configDir, 0o700);
  }
});
