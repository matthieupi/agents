import ssh2 from 'ssh2';
import { createHash } from 'node:crypto';
import { mkdtemp, writeFile, rm, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
const { Server, utils } = ssh2;

export async function fixture(t, mode = 'helper') {
  const directory = await mkdtemp(path.join(tmpdir(), 'opencode-ssh-test-'));
  const key = utils.generateKeyPairSync('ed25519');
  const hostKey = utils.generateKeyPairSync('ed25519');
  const identity = path.join(directory, 'fixture-key');
  await writeFile(identity, key.private, { mode: 0o600 });
  const cwd = path.join(directory, "project 'quoted ;$(not-a-command)");
  await mkdir(cwd);
  const sockets = new Set(), children = new Set();
  let connections = 0, executions = 0, requests = [];
  const server = new Server({ hostKeys: [hostKey.private] }, client => {
    connections++;
    sockets.add(client);
    client.on('error', () => {});
    client.on('close', () => sockets.delete(client));
    client.on('authentication', ctx => {
      if (mode === 'auth-timeout') return;
      if (mode === 'auth-fail' || ctx.method !== 'publickey' || !ctx.key.data.equals(utils.parseKey(key.public).getPublicSSH())) return ctx.reject();
      ctx.accept();
    });
    client.on('ready', () => client.on('session', accept => {
      const session = accept();
      session.on('exec', (accept, reject, info) => {
        executions++;
        const channel = accept();
        channel.on('error', () => {});
        if (mode !== 'helper') {
          channel.once('data', raw => {
            requests.push(JSON.parse(raw));
            if (mode === 'hang') return;
            if (mode === 'stderr') { channel.stderr.write(Buffer.alloc(40000, 120)); channel.exit(1); channel.end(); return; }
            if (mode === 'stdout') { channel.write(Buffer.alloc(400000, 120)); channel.exit(1); channel.end(); return; }
            channel.end(JSON.stringify({ ok: true, output: 'fixture', files: [] }));
          });
          return;
        }
        // Localhost fixture only: emulate sshd's command execution, not production fallback.
        let requestLine = '';
        channel.on('data', raw => {
          if (requestLine === null) return;
          requestLine += raw.toString('utf8');
          if (requestLine.length > 1024 * 1024) { channel.close(); requestLine = null; return; }
          if (requestLine.includes('\n')) {
            requests.push(JSON.parse(requestLine.slice(0, requestLine.indexOf('\n'))));
            requestLine = null;
          }
        });
        const child = spawn('/bin/sh', ['-c', info.command], { stdio: ['pipe', 'pipe', 'pipe'] });
        children.add(child);
        child.stdin.on('error', () => {});
        channel.pipe(child.stdin);
        child.stdout.pipe(channel, { end: false });
        child.stderr.pipe(channel.stderr, { end: false });
        channel.on('close', () => child.stdin.end());
        child.on('close', code => { children.delete(child); channel.exit(code ?? 1); channel.end(); });
      });
    }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => {
    for (const client of sockets) client.end();
    for (const child of children) child.stdin.end();
    await new Promise(resolve => server.close(resolve));
    const deadline = Date.now() + 4000;
    while (children.size && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 20));
    if (children.size) { for (const child of children) child.kill('SIGKILL'); throw new Error('Fixture helper leaked'); }
    await rm(directory, { recursive: true, force: true });
  });
  const target = { ref: 'fake.project', label: 'Fake fixture', address: '127.0.0.1', port: server.address().port,
    user: 'fixture', cwd, identity_file: identity,
    host_key_sha256: createHash('sha256').update(utils.parseKey(hostKey.private).getPublicSSH()).digest('hex') };
  const catalog = path.join(directory, 'catalog.json');
  const save = projects => writeFile(catalog, JSON.stringify({ projects }));
  await save([target]);
  const options = { enabled: true, project: target.ref, catalog, stateDirectory: path.join(directory, 'state'), timeoutMs: 5000 };
  const parents = new Map();
  const input = { directory, client: {
    session: { get: async ({ path: { id } }) => ({ data: { id, parentID: parents.get(id) } }) },
    mcp: { status: async () => ({ data: {} }) },
  } };
  const permissions = [];
  const ctx = (sessionID = 'session-1', ask = async request => { permissions.push(request); }) => ({ sessionID, ask, abort: new AbortController().signal, metadata() {} });
  return { target, directory, catalog, options, input, ctx, save, parents, permissions, requests,
    connections: () => connections, executions: () => executions };
}
