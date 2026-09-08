import { tool } from '@opencode-ai/plugin';
import { constants } from 'node:fs';
import { mkdir, lstat, open, link, unlink } from 'node:fs/promises';
import { createHash, randomUUID } from 'node:crypto';
import path from 'node:path';
import os from 'node:os';
import { runRemote, MAX_INPUT, MAX_OUTPUT } from './transport.js';

const z = tool.schema;
const text = z.string();
const positive = z.number().int().positive();
const shapes = {
  read: { filePath: text, offset: positive.optional(), limit: positive.optional() },
  write: { filePath: text, content: text },
  edit: { filePath: text, oldString: text, newString: text, replaceAll: z.boolean().optional() },
  apply_patch: { patchText: text },
  glob: { pattern: text, path: text.optional() },
  grep: { pattern: text, path: text.optional(), include: text.optional() },
  bash: { command: text, workdir: text.optional(), timeout: positive.max(600000).optional(), description: text.optional() },
};
const local = new Set(['question', 'todowrite', 'todoread', 'task', 'plan_exit', 'invalid']);
const blocked = new Set(['skill', 'lsp', 'webfetch', 'websearch', 'list', 'batch', 'execute']);
const digest = value => createHash('sha256').update(value).digest('hex');
const fail = message => { throw new Error(message); };
const projectRef = /^[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9-]*$/;

async function configureRemote(cfg) {
  cfg.snapshot = false; cfg.lsp = false; cfg.formatter = false;
  cfg.watcher = { ...cfg.watcher, ignore: ['**'] };
  cfg.tool_output = { max_lines: 2000, max_bytes: 65536 };
  cfg.skills = { paths: [], urls: [] };
  for (const name of Object.keys(cfg.mcp ?? {})) cfg.mcp[name] = { enabled: false };
  // Preserve all existing permissions, including agent Plan restrictions.
  cfg.tools = { ...cfg.tools, ...Object.fromEntries([...blocked].map(id => [id, false])) };
}

function lockdown() {
  const reject = async () => fail('SSH remote lockdown: initialization failed. Validate the explicit plugin options, catalog and stateDirectory, then restart. No model tools or local shell may run.');
  return {
    config: configureRemote,
    'experimental.chat.system.transform': reject,
    'tool.definition': reject,
    'tool.execute.before': reject,
    'shell.env': reject,
  };
}

function normalize(root, value) {
  if (typeof value !== 'string' || !value || value.includes('\0')) fail('Invalid remote path');
  const result = path.posix.resolve(root, value);
  if (result !== root && !result.startsWith(root === '/' ? '/' : root + '/')) fail('Path is outside remote project');
  return result;
}

async function selected(catalog, ref) {
  const file = await open(catalog, constants.O_RDONLY | constants.O_NONBLOCK);
  let data;
  try {
    if (!(await file.stat()).isFile()) fail('Catalog must be a regular JSON file');
    const buffer = Buffer.alloc(MAX_INPUT + 1);
    const { bytesRead } = await file.read(buffer, 0, buffer.length, 0);
    if (bytesRead > MAX_INPUT) fail('Catalog exceeds size budget');
    try { data = JSON.parse(buffer.subarray(0, bytesRead)); }
    catch { fail('Invalid project catalog JSON'); }
  } finally { await file.close(); }
  if (!Array.isArray(data?.projects)) fail('Invalid project catalog');
  const matches = data.projects.filter(entry => entry?.ref === ref);
  if (!matches || matches.length !== 1) fail('Selected project is missing, revoked or duplicated');
  const p = matches[0];
  const fields = ['ref', 'label', 'address', 'port', 'user', 'cwd', 'identity_file', 'host_key_sha256'];
  const allowed = new Set([...fields, 'environment', 'host_key', 'workspace_name']);
  if (Object.keys(p).some(key => !allowed.has(key))) fail('Unsupported catalog fields');
  for (const key of fields.filter(key => key !== 'port'))
    if (typeof p[key] !== 'string' || !p[key] || /[\x00-\x1f\x7f]/.test(p[key])) fail('Invalid catalog field: ' + key);
  if (p.ref.length > 256 || !projectRef.test(p.ref) || !Number.isInteger(p.port) || p.port < 1 || p.port > 65535 ||
      !path.isAbsolute(p.identity_file) || !path.posix.isAbsolute(p.cwd) || path.posix.normalize(p.cwd) !== p.cwd ||
      !/^[a-f0-9]{64}$/.test(p.host_key_sha256)) fail('Invalid project endpoint');
  return Object.freeze(Object.fromEntries(fields.map(key => [key, p[key]])));
}

export default async function SshRemotePlugin(input, options = {}) {
  // The host catches plugin initialization errors and continues with native tools.
  // Return registered blocking hooks instead; import-time failure is outside this boundary.
  try {
    if (!options || typeof options !== 'object' || Array.isArray(options)) return lockdown();
    const enabled = options.enabled;
    // No config, catalog, key, state or network access in ordinary/default mode.
    if (enabled === undefined || enabled === false) return {};
    if (enabled !== true) return lockdown();
    return await initializeRemote(input, options);
  } catch { return lockdown(); }
}

async function initializeRemote(input, options) {
  if (Object.keys(options).some(key => !['enabled', 'project', 'catalog', 'stateDirectory', 'timeoutMs'].includes(key))) fail('Unknown SSH remote option');
  const { project, catalog, timeoutMs = 120000 } = options;
  if (typeof project !== 'string' || project.length > 256 || !projectRef.test(project) || typeof catalog !== 'string' || !path.isAbsolute(catalog) ||
      !Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 600000) fail('Invalid SSH remote options');
  const target = await selected(catalog, project);
  const fingerprint = digest(JSON.stringify(target));
  const state = options.stateDirectory ?? path.join(process.env.XDG_STATE_HOME || path.join(os.homedir(), '.local/state'), 'opencode-ssh-remote');
  if (typeof state !== 'string' || !path.isAbsolute(state)) fail('stateDirectory must be absolute');
  const hashes = new Map();
  const checkCatalog = async () => {
    if (digest(JSON.stringify(await selected(catalog, project))) !== fingerprint) fail('Selected endpoint changed; restart with a new session');
  };
  const binding = JSON.stringify({ ref: project, fingerprint });
  async function checkMcp() {
    const result = await input.client.mcp.status({ query: { directory: input.directory }, throwOnError: true });
    if (!result.data || typeof result.data !== 'object' || Array.isArray(result.data) ||
        Object.values(result.data).some(server => server?.status !== 'disabled'))
      fail('MCP must be disabled before remote model dispatch');
  }
  async function bind(id, seen = new Set()) {
    if (typeof id !== 'string' || !id || seen.has(id) || seen.size > 64) fail('Invalid session ancestry');
    seen.add(id);
    // PluginInput uses SDK v1, not the v2 sessionID signature.
    const result = await input.client.session.get({ path: { id }, query: { directory: input.directory }, throwOnError: true });
    if (!result.data || result.data.id !== id || (result.data.parentID !== undefined && typeof result.data.parentID !== 'string')) fail('Session parent lookup failed');
    if (result.data.parentID) await bind(result.data.parentID, seen);
    await mkdir(state, { recursive: true, mode: 0o700 });
    const stat = await lstat(state);
    if (!stat.isDirectory() || stat.isSymbolicLink() || (stat.mode & 0o077) || stat.uid !== process.getuid()) fail('Session state must be private and owned by current user');
    const destination = path.join(state, digest(id) + '.json');
    const temporary = path.join(state, '.' + randomUUID());
    // Publish complete immutable bindings atomically; simultaneous launches cannot overwrite.
    const fd = await open(temporary, 'wx', 0o600);
    try { await fd.writeFile(binding); } finally { await fd.close(); }
    try { await link(temporary, destination); } catch (error) { if (error.code !== 'EEXIST') throw error; }
    finally { await unlink(temporary); }
    const saved = await open(destination, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const s = await saved.stat();
      if (!s.isFile() || s.uid !== process.getuid() || (s.mode & 0o077) || s.size > 1024 || await saved.readFile('utf8') !== binding)
        fail('Session target mismatch; start a new session (including child/resumed sessions)');
    } finally { await saved.close(); }
  }
  async function execute(operation, raw, ctx) {
    await checkCatalog();
    const args = z.object(shapes[operation]).strict().parse(raw);
    if (Buffer.byteLength(JSON.stringify(args)) > MAX_INPUT - 65536) fail('Tool input exceeds size budget');
    const paths = [];
    for (const key of ['filePath', 'path', 'workdir']) {
      if (args[key] !== undefined) { args[key] = normalize(target.cwd, args[key]); paths.push(args[key]); }
    }
    if (operation === 'apply_patch') {
      for (const line of args.patchText.split('\n')) {
        const match = /^\*\*\* (?:Add File|Delete File|Update File|Move to): (.+)$/.exec(line);
        if (match) paths.push(normalize(target.cwd, match[1]));
      }
      if (!paths.length) fail('Patch has no supported paths');
    }
    const permission = ['write', 'edit', 'apply_patch'].includes(operation) ? 'edit' : operation;
    const patterns = operation === 'bash'
      ? [`${project}:${encodeURIComponent(args.workdir ?? target.cwd)}:${args.command}`]
      : (paths.length ? paths : [target.cwd]).map(p => `${project}:${p}`);
    await ctx.ask({ permission, patterns,
      always: [], metadata: { target: project, operation, args } });
    await checkCatalog();
    ctx.abort?.throwIfAborted();
    await bind(ctx.sessionID);
    await checkCatalog();
    let expected = hashes.get(ctx.sessionID);
    if (!expected) { expected = new Map(); hashes.set(ctx.sessionID, expected); }
    const checks = Object.fromEntries(paths.map(p => [p, expected.get(p) ?? null]));
    const response = await runRemote(target, { operation, cwd: target.cwd, args, expected: checks,
      timeout_ms: Math.min(timeoutMs, args.timeout ?? timeoutMs), max_output_bytes: MAX_OUTPUT }, { signal: ctx.abort });
    for (const file of response.files) {
      if (!file || normalize(target.cwd, file.path) !== file.path || (file.sha256 !== null && !/^[a-f0-9]{64}$/.test(file.sha256))) fail('Invalid helper file hash');
    }
    // A truncated read must not authorize overwriting content the model did not see.
    const truncated = !!response.truncated || response.output.split('\n').length > 1000;
    for (const file of response.files) {
      if (truncated) expected.delete(file.path);
      else expected.set(file.path, file.sha256);
    }
    // Bound line count below native truncation defaults to avoid local overflow-file references.
    const output = response.output.split('\n').length > 1000 ? response.output.split('\n').slice(0, 1000).join('\n') + '\n[remote output truncated]' : response.output;
    return { title: `[${project}] ${operation}`, output: output + (response.truncated ? '\n[remote output truncated]' : ''),
      metadata: { target: project, exit_code: response.exit_code, truncated } };
  }
  function reviewed(id) {
    if (!Object.hasOwn(shapes, id) && !local.has(id) && !blocked.has(id)) fail('Unreviewed tool blocked in SSH remote mode: ' + id);
  }
  return {
    tool: Object.fromEntries(Object.entries(shapes).map(([operation, args]) => [operation, tool({
      description: `Execute ${operation} only on immutable remote target ${project}. Paths are POSIX, rooted at ${target.cwd}. Existing mutations require a prior read.`,
      args, execute: (args, ctx) => execute(operation, args, ctx),
    })])),
    config: configureRemote,
    'tool.definition': async ({ toolID }, output) => {
      reviewed(toolID);
      if (blocked.has(toolID)) output.description = 'Unavailable in SSH remote mode; execution is blocked.';
    },
    'tool.execute.before': async ({ tool: id, sessionID }) => {
      reviewed(id);
      if (blocked.has(id)) fail('Unsupported tool blocked in SSH remote mode: ' + id);
      await checkCatalog();
      await bind(sessionID);
    },
    'shell.env': async () => fail('Local shell/PTY is disabled in SSH remote mode. Use the remote bash model tool.'),
    'experimental.chat.system.transform': async ({ sessionID }, output) => {
      await checkCatalog();
      await checkMcp();
      if (sessionID) await bind(sessionID);
      output.system.push(`SSH remote mode: immutable target ${project}, root ${target.cwd}. Only read/write/edit/apply_patch/glob/grep/bash model tools are remote. Question/todo/task orchestration remains local; children inherit this target. No local project-tool fallback. Browser files, Git, attachments and internal reads are not remote. This is not a sandbox. Start a new session when switching target or mode.`);
    },
  };
}
