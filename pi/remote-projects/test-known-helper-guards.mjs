// Source-only: no child processes, network, real home writes, or SDK imports.
// Uses the existing remote-projects scratch TypeScript compiler read-only.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import vm from 'node:vm';
import { EventEmitter } from 'node:events';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const ts = require('./.scratch/node_modules/typescript');
const helperPath = path.join(root, '.pi/agent/extension-library/remote-project-mode.ts');
function load(file, mocks = {}, globals = {}) {
  const source = readFileSync(file, 'utf8').replaceAll('import.meta.url', JSON.stringify(`file://${file}`));
  const { outputText, diagnostics } = ts.transpileModule(source, {
    fileName: file, reportDiagnostics: true,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  assert.equal(diagnostics.length, 0);
  const exports = {};
  vm.runInNewContext(outputText, {
    exports, ...globals,
    require(name) {
      if (name.endsWith('/remote-project-mode.ts')) return helper;
      if (Object.hasOwn(mocks, name)) return mocks[name];
      throw new Error(`Unexpected dependency: ${name}`);
    },
  }, { filename: file });
  return exports;
}
const helper = load(helperPath);
const local = { type: 'custom', customType: 'pi-ssh-remote-project', data: { version: 1, local: true, projectRef: null } };
const remote = { type: 'custom', customType: 'pi-ssh-remote-project', data: { version: 1, local: false, projectRef: 'SECRET-REF' } };
const legacy = { type: 'custom', customType: 'pi-ssh-remote-state', data: { connected: false, secret: 'SECRET-LEGACY' } };
const malformed = [null, {}, { version: 2, local: true, projectRef: null }, { version: 1, local: true },
  { version: 1, local: true, projectRef: 'SECRET-REF' }, { version: 1, local: false }]
  .map(data => ({ ...remote, data }));
const branches = [[], [local], [remote], [legacy], ...malformed.map(e => [e]),
  [remote, local], [local, remote], [local, legacy], [legacy, local],
  [remote, { type: 'message', content: 'SECRET-MESSAGE' }]];

test('pure parser agrees with actual patched extension restore decision', async () => {
  const patch = readFileSync(path.join(root, 'remote-projects/apply-upstream.py'), 'utf8');
  const start = patch.indexOf('      const record = [...ctx.sessionManager.getBranch()]');
  const end = patch.indexOf('      status(ctx);', start);
  assert.ok(start > 0 && end > start);
  for (const branch of branches) {
    let mode = 'local';
    // Execute the actual restore statements, not a second hand-written parser.
    const restore = ts.transpileModule(`(async () => { ${patch.slice(start, end)} })`, {
      compilerOptions: { target: ts.ScriptTarget.ES2022 },
    }).outputText;
    const run = vm.runInNewContext(restore, {
      ctx: { sessionManager: { getBranch: () => branch }, ui: { notify() {} } },
      managedEntry: 'pi-ssh-remote-project', SESSION_STATE_ENTRY_TYPE: 'pi-ssh-remote-state',
      managed: { begin() { mode = 'remote'; }, local() { mode = 'local'; } },
      managedExclusive: f => f(), connectProject() {},
    });
    await run();
    assert.equal(helper.remoteProjectMode(branch), mode);
  }
});

test('guard fails closed for missing/unreadable context without leaking data', () => {
  for (const ctx of [undefined, {}, { sessionManager: {} },
    { sessionManager: { getBranch: () => null } },
    { sessionManager: { getBranch() { throw new Error('SECRET-EXCEPTION'); } } }]) {
    assert.throws(() => helper.requireLocalProjectExecution(ctx, 'Known helper'), error => {
      assert.match(error.message, /cannot verify/);
      assert.doesNotMatch(error.message, /SECRET/);
      return true;
    });
  }
});

test('pure helper ignores unrelated unknown entries; current branch is read at every launch', () => {
  assert.equal(helper.remoteProjectMode([null, 4, {}, { type: 'message' }]), 'local');
  assert.equal(helper.remoteProjectMode([remote, null, 4, {}]), 'remote');
  let children = 0, current = [];
  const notices = [];
  const ctx = { sessionManager: { getBranch: () => current }, ui: { notify: text => notices.push(text) } };
  const spawn = () => { children++; };
  const launch = () => { helper.requireLocalProjectExecution(ctx, 'Known helper'); spawn(); };
  launch();
  for (const entry of [remote, legacy, ...malformed]) {
    current = [entry];
    assert.throws(launch, /unsupported.*remote/);
    assert.equal(children, 1);
  }
  current = [remote, local];
  launch();
  assert.equal(children, 2);
  assert.doesNotMatch(notices.join('\n'), /SECRET/);
});

async function harness(relative, branch = [], closeAutomatically = true) {
  const commands = new Map(), tools = new Map(), hooks = new Map();
  const calls = [], notices = [], children = [], timers = new Set();
  let current = branch, onClose = () => {};
  const ctx = {
    cwd: '/fake-project', model: { provider: 'test', id: 'model' },
    sessionManager: { getBranch: () => current },
    ui: { notify: (text, level) => notices.push({ text, level }), setWidget() {}, setStatus() {}, setFooter() {},
      select: async (_title, choices) => choices[0] },
  };
  const fakeFs = {
    existsSync: p => !p.endsWith('.json'), mkdirSync() {}, unlinkSync() {},
    readdirSync: p => p.endsWith('agent-sessions') ? [] : ['worker.md'],
    readFileSync: p => p.endsWith('teams.yaml') ? 'team:\n  - worker\n'
      : p.endsWith('agent-chain.yaml') ? 'chain:\n  steps:\n    - agent: worker\n      prompt: $INPUT\n    - agent: worker\n      prompt: $INPUT\n'
      : '---\nname: worker\ndescription: fixture\ntools: read,bash\n---\nFixture system prompt',
  };
  const spawn = (command, args, options) => {
    calls.push({ command, args, options });
    const child = new EventEmitter();
    child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
    child.stdout.setEncoding = child.stderr.setEncoding = () => {};
    child.kill = () => { child.killed = true; };
    children.push(child);
    if (closeAutomatically) queueMicrotask(() => { onClose(); child.emit('close', 0); });
    return child;
  };
  const extension = load(path.join(root, relative), {
    child_process: { spawn }, fs: fakeFs, os: { homedir: () => '/fake-home' }, path,
    './themeMap.ts': { applyExtensionDefaults() {} },
    '@sinclair/typebox': { Type: new Proxy({}, { get: () => () => ({}) }) },
    '@mariozechner/pi-coding-agent': {}, '@mariozechner/pi-tui': {},
  }, {
    process: { env: { FIXTURE: 'preserved' } },
    setInterval: () => { const id = {}; timers.add(id); return id; },
    clearInterval: id => timers.delete(id),
  });
  extension.default({
    registerCommand: (name, value) => commands.set(name, value),
    registerTool: tool => tools.set(tool.name, tool), on: (name, fn) => hooks.set(name, fn),
    sendMessage() {}, setActiveTools() {},
  });
  await hooks.get('session_start')?.({}, ctx);
  notices.length = 0;
  return { ctx, calls, notices, children, timers, tools,
    branch: value => { current = value; }, onClose: fn => { onClose = fn; },
    command: (name, args = '') => commands.get(name).handler(args, ctx),
    execute: (name, params) => tools.get(name).execute('test', params, undefined, undefined, ctx),
  };
}
async function blocked(h, action) {
  const count = h.calls.length;
  const timerCount = h.timers.size;
  let result;
  try { result = await action(); } catch (error) { result = error.message; }
  await Promise.resolve();
  assert.equal(h.calls.length, count, 'remote helper must create zero children');
  const errors = h.notices.filter(n => n.level === 'error');
  assert.ok(errors.some(n => /unsupported.*remote|cannot verify/.test(n.text)), 'visible guard error');
  assert.doesNotMatch(JSON.stringify(errors), /SECRET/);
  assert.doesNotMatch(JSON.stringify(result), /SECRET/);
  assert.equal(h.timers.size, timerCount, 'blocked launches must not leak or cancel timers');
  h.notices.length = 0;
}
const subFiles = ['.pi/agent/extensions/subagent-widget.ts', '.pi/agent/extension-library/pi-vs-claude-code/subagent-widget.ts'];
for (const file of subFiles) {
  test(`${file}: direct /sub, /subcont and tool paths; local round-trip`, async () => {
    const h = await harness(file, [remote]);
    await blocked(h, () => h.command('sub', 'SECRET-PROMPT'));
    await blocked(h, () => h.execute('subagent_create', { task: 'SECRET-PROMPT' }));
    for (const record of [legacy, ...malformed]) {
      h.branch([record]);
      await blocked(h, () => h.command('sub', 'SECRET-PROMPT'));
    }
    const manager = h.ctx.sessionManager;
    h.ctx.sessionManager = { getBranch() { throw new Error('SECRET-CONTEXT'); } };
    await blocked(h, () => h.command('sub', 'SECRET-PROMPT'));
    h.ctx.sessionManager = manager;
    h.branch([]);
    await h.command('sub', 'local task');
    assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].command, 'pi');
    assert.ok(h.calls[0].args.includes('--no-extensions'));
    assert.equal(h.calls[0].args.at(-1), 'local task');
    assert.equal(h.calls[0].options.env.FIXTURE, 'preserved');
    const session = h.calls[0].args[h.calls[0].args.indexOf('--session') + 1];
    h.branch([remote]);
    await blocked(h, () => h.command('sub', '1 SECRET-PROMPT'));
    await blocked(h, () => h.command('subcont', '1 SECRET-PROMPT'));
    await blocked(h, () => h.execute('subagent_continue', { id: 1, prompt: 'SECRET-PROMPT' }));
    const list = await h.execute('subagent_list', {});
    assert.match(list.content[0].text, /DONE/);
    assert.ok(h.children.every(c => !c.killed));
    h.branch([remote, local]);
    await h.command('subcont', '1 local continuation');
    assert.equal(h.calls.length, 2);
    assert.ok(h.calls[1].args.includes(session));
    assert.equal(h.calls[1].args.at(-1), 'local continuation');
    await h.command('subrm', '1');
    await h.command('subclear');
  });
}

for (const [file, tool, params, count, commands] of [
  ['agent-team.ts', 'dispatch_agent', { agent: 'worker', task: 'local task' }, 1, ['agents-team', 'agents-list', 'agents-grid']],
  ['agent-chain.ts', 'run_chain', { task: 'local task' }, 2, ['chain', 'chain-list']],
  ['pi-pi.ts', 'query_experts', { queries: [{ expert: 'worker', question: 'local task' }] }, 1, ['experts', 'experts-grid']],
]) {
  test(`${file}: local argv preserved, remote/legacy/malformed zero spawn; administrative commands safe`, async () => {
    const h = await harness(`.pi/agent/extension-library/pi-vs-claude-code/${file}`);
    await h.execute(tool, params);
    assert.equal(h.calls.length, count);
    for (const call of h.calls) {
      assert.equal(call.command, 'pi');
      assert.ok(call.args.includes('--no-extensions'));
      assert.ok(call.args.includes('test/model'));
      assert.ok(call.args.includes('read,bash'));
      assert.equal(call.options.env.FIXTURE, 'preserved');
    }
    for (const record of [remote, legacy, ...malformed]) {
      h.branch([record]);
      await blocked(h, () => h.execute(tool, params));
    }
    const manager = h.ctx.sessionManager;
    h.ctx.sessionManager = { getBranch() { throw new Error('SECRET-CONTEXT'); } };
    await blocked(h, () => h.execute(tool, params));
    h.ctx.sessionManager = manager;
    for (const command of commands) await h.command(command, '2');
    assert.equal(h.calls.length, count);
    h.branch([remote, local]);
    await h.execute(tool, params);
    assert.equal(h.calls.length, count * 2);
    assert.equal(h.timers.size, 0);
  });
}

test('chain rechecks after async child completion without killing the already-started job', async () => {
  const h = await harness('.pi/agent/extension-library/pi-vs-claude-code/agent-chain.ts');
  h.onClose(() => h.branch([remote]));
  await assert.rejects(h.execute('run_chain', { task: 'local task' }), /unsupported.*remote/);
  assert.equal(h.calls.length, 1);
  assert.ok(h.children.every(c => !c.killed));
  assert.equal(h.timers.size, 0);
});

test('independent parent branches do not share mode even with identical cwd', async () => {
  const a = await harness(subFiles[0], [remote]);
  const b = await harness(subFiles[0], []);
  await blocked(a, () => a.command('sub', 'SECRET-PROMPT'));
  await b.command('sub', 'local task');
  assert.equal(b.calls.length, 1);
  assert.equal(a.calls.length, 0);
});

test('switching to remote and rejecting a new launch leaves an existing local job running', async () => {
  const h = await harness(subFiles[0], [], false);
  await h.command('sub', 'existing local job');
  h.branch([remote]);
  await blocked(h, () => h.command('sub', 'SECRET-PROMPT'));
  assert.equal(h.children[0].killed, undefined);
  assert.equal(h.timers.size, 1);
  const result = await h.execute('subagent_list', {});
  assert.match(result.content[0].text, /RUNNING/);
  h.children[0].emit('close', 0);
  assert.equal(h.timers.size, 0);
});
