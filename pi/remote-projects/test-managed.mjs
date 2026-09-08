// Public fake SSH/catalog; real pinned SDK tool factories. Never opens a socket.
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { test } from "node:test";

import { fixture } from "./test-paths.mjs";
const requireFixture = createRequire(path.join(fixture, "package.json"));
const ts = requireFixture("typescript");
const sdk = await import(pathToFileURL(path.join(fixture, "node_modules/@earendil-works/pi-coding-agent/dist/index.js")));
const ai = await import(pathToFileURL(path.join(fixture, "node_modules/@earendil-works/pi-ai/dist/index.js")));
const tui = await import(pathToFileURL(path.join(fixture, "node_modules/@earendil-works/pi-tui/dist/index.js")));
const typebox = await import(pathToFileURL(requireFixture.resolve("typebox")));
assert.equal(JSON.parse(fs.readFileSync(path.join(fixture, "node_modules/@earendil-works/pi-coding-agent/package.json"))).version, "0.85.1");
assert.equal(requireFixture("ssh2/package.json").version, "1.17.0");

const project = (suffix = "a", extra = {}) => ({
  ref: `dev.venv-${suffix}`, label: `Project ${suffix}`, address: `${suffix}.example.test`, port: 2222,
  user: "project", cwd: "/work/project", identity_file: "/dedicated/key",
  host_key_sha256: "ab".repeat(32), environment: "dev", host_key: `venv-${suffix}`, workspace_name: "project", ...extra,
});

function harness(managed = true) {
  const state = { catalog: JSON.stringify({ projects: [project(), project("b")] }), local: [], calls: [], writes: [],
    connections: [], clients: [], files: new Map(), fingerprint: "ab".repeat(32), key: "PRIVATE", fail: "", hold: false,
    cwd: "/work/project", pending: [], storage: new Map(), holdSftp: false, pendingSftp: [], closedSftp: 0 };
  const fakeFs = { ...fs,
    readFileSync(file, encoding) {
      if (file === "/catalog") { if (state.catalog instanceof Error) throw state.catalog; return state.catalog; }
      if (file === "/dedicated/key") return Buffer.from(state.key);
      if (state.storage.has(file)) return state.storage.get(file);
      throw new Error(`ENOENT fake file ${file}`);
    },
    statSync(file) { if (file === "/dedicated/key" && state.key !== "MISSING") return { isFile: () => true, size: 32 }; throw new Error("Missing identity"); },
    mkdirSync(...args) { state.writes.push(args); },
    writeFileSync(...args) { state.writes.push(args); state.storage.set(args[0], args[1]); },
  };
  class Client extends EventEmitter {
    connect(options) {
      this.options = options; state.connections.push(options); state.clients.push(this);
      queueMicrotask(() => {
        if (!options.hostVerifier(state.fingerprint)) this.emit("error", new Error("Host key mismatch"));
        else if (state.fail === "auth") this.emit("error", new Error("authentication failure"));
        else this.emit("ready");
      });
    }
    end() { this.ended = true; this.emit("close"); }
    exec(command, callback) {
      state.calls.push({ host: this.options.host, command });
      if (state.fail === "channel-once") { state.fail = ""; return callback(new Error("ECONNRESET")); }
      if (state.fail === "channel") return callback(new Error("ECONNRESET unknown command result"));
      const stream = new EventEmitter(); stream.stderr = new EventEmitter();
      stream.close = () => stream.emit("close", 1);
      callback(null, stream);
      const finish = () => {
        if (state.fail === "stream") { stream.emit("error", new Error("ECONNRESET stream result unknown")); return; }
        const output = command.includes("pwd -P") ? state.cwd : command.includes("file --mime-type") ? "text/plain" : "remote text\n";
        stream.emit("data", Buffer.from(output));
        stream.emit("close", state.fail === "cwd" ? 1 : 0);
      };
      if (state.hold) state.pending.push(finish); else setImmediate(finish);
    }
    sftp(callback) {
      const host = this.options.host;
      const channel = {
        end() { state.closedSftp++; },
        stat(file, done) { state.calls.push({ host, stat: file }); done(null, {}); },
        readFile(file, done) { state.calls.push({ host, read: file }); done(null, Buffer.from(state.files.get(`${host}:${file}`) ?? "before\n")); },
        writeFile(file, contents, done) {
          state.calls.push({ host, write: file });
          if (state.fail === "write") return done(new Error("ECONNRESET unknown write result"));
          state.files.set(`${host}:${file}`, String(contents)); done(null);
        },
      };
      if (state.holdSftp) state.pendingSftp.push(() => callback(null, channel));
      else callback(null, channel);
    }
  }
  const fakeSsh = { Client, utils: { parseKey(data) {
    if (String(data) !== "PRIVATE") return new Error("encrypted or invalid private key");
    return { isPrivateKey: () => true };
  } } };
  const wrappedSdk = { ...sdk };
  for (const name of ["Read", "Write", "Edit", "Bash"]) {
    wrappedSdk[`create${name}Tool`] = (cwd, options) => {
      const tool = sdk[`create${name}Tool`](cwd, options);
      if (options?.operations) return tool; // Test actual SDK operations/callback contract.
      return { ...tool, execute: async () => { state.local.push({ name, cwd }); return { content: [{ type: "text", text: "LOCAL" }], details: {} }; } };
    };
  }
  const environment = { HOME: "/fake-home", USER: "not-authorized", SSH_AUTH_SOCK: "/never/use/agent", ...(managed ? { PI_PROJECT_CATALOG: "/catalog" } : {}) };
  const sandbox = vm.createContext({ Buffer, console, setTimeout, clearTimeout, setImmediate, queueMicrotask, process: { env: environment },
    __piHpcCredentialCacheV1: { passwords: new Map(), keyPassphrases: new Map(), resume: { command: "ssh attacker@elsewhere", cwd: "/wrong", routeRemoteTools: true } } });
  const modules = new Map();
  function load(file) {
    if (modules.has(file)) return modules.get(file);
    const output = ts.transpileModule(fs.readFileSync(path.join(fixture, file), "utf8"), {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    const require = (name) => {
      if (name === "./managed-projects.js") return load("managed-projects.ts");
      if (name === "ssh2") return fakeSsh;
      if (name === "node:fs") return fakeFs;
      if (name === "@earendil-works/pi-coding-agent") return wrappedSdk;
      if (name === "@earendil-works/pi-ai") return ai;
      if (name === "@earendil-works/pi-tui") return tui;
      if (name === "typebox") return typebox;
      return requireFixture(name);
    };
    vm.runInContext(`(function(require,module,exports){${output}\n})`, sandbox, { filename: file })(require, module, module.exports);
    modules.set(file, module.exports);
    return module.exports;
  }
  const helper = load("managed-projects.ts");
  const extension = load("index.ts").default;
  function session(branch = [], cwd = "/same/local/control") {
    const tools = new Map(), hooks = new Map(), commands = new Map(), notifications = [];
    let choice;
    const ctx = { cwd, sessionManager: { getBranch: () => branch }, ui: {
      setStatus() {}, notify: (...args) => notifications.push(args), theme: { fg: (_color, text) => text },
      select: async (_title, options) => typeof choice === "number" ? options[choice] : choice,
      confirm: async () => { throw new Error("Managed trust must never prompt"); },
      input: async () => { throw new Error("Managed secret must never prompt"); },
    } };
    extension({ registerTool: (tool) => tools.set(tool.name, tool), registerCommand: (name, command) => commands.set(name, command),
      on: (name, callback) => hooks.set(name, callback), appendEntry: (customType, data) => branch.push({ type: "custom", customType, data }) });
    return { ctx, tools, hooks, branch, notifications,
      choose: (value) => { choice = value; },
      start: (reason = "startup") => hooks.get("session_start")({ reason }, ctx),
      shutdown: (reason = "reload") => hooks.get("session_shutdown")({ reason }, ctx),
      call: (name, params = {}) => tools.get(name).execute("id", params, undefined, undefined, ctx),
      command: (input = "") => commands.get("remote").handler(input, ctx),
      bash: () => hooks.get("user_bash")({ command: "pwd", cwd }, ctx),
    };
  }
  return { state, helper, session, catalog: (entries) => { state.catalog = JSON.stringify({ projects: entries }); }, sandbox };
}

async function blocked(session, state) {
  const count = state.local.length;
  for (const [name, params] of [["read", { path: "x" }], ["write", { path: "x", content: "y" }],
    ["edit", { path: "x", edits: [{ oldText: "before", newText: "after" }] }], ["bash", { command: "pwd" }]]) {
    await assert.rejects(session.call(name, params));
  }
  const result = (await session.bash()).result;
  assert.equal(result.exitCode, 1); assert.equal(result.cancelled, false); assert.equal(result.truncated, false);
  assert.equal(typeof result.output, "string"); assert.equal(state.local.length, count);
}

test("catalog validates exact fields, public projection extras, duplicate refs and canonical paths", () => {
  const h = harness();
  assert.equal(h.helper.loadProjectCatalog("/catalog").length, 2);
  const invalid = [{ ref: "dev.venv-a*" }, { address: "host;sh" }, { address: "a..test" }, { address: "a.-test" }, { user: "a b" }, { port: "22" }, { port: 0 },
    { identity_file: "" }, { identity_file: "~/key" }, { cwd: "/work/../project" }, { cwd: "/work/" },
    { label: "bad\nlabel" }, { host_key_sha256: "SHA256:wrong" }, { password: "never" }, { enabled: false }];
  for (const delta of invalid) { h.catalog([project("a", delta)]); assert.throws(() => h.helper.loadProjectCatalog("/catalog")); }
  h.catalog([project(), project()]); assert.throws(() => h.helper.loadProjectCatalog("/catalog"));
  for (const value of ["{}", "null", "{", '{"projects":{}}']) { h.state.catalog = value; assert.throws(() => h.helper.loadProjectCatalog("/catalog")); }
  for (const value of ["", "relative", "/path/../catalog", "/bad\npath"]) assert.throws(() => h.helper.loadProjectCatalog(value));
});

test("helper intent, exact selection, revocation and public metadata changes are per instance", () => {
  const h = harness(), a = new h.helper.ManagedProjects("/catalog"), b = new h.helper.ManagedProjects("/catalog");
  assert.throws(() => a.current()); a.select("dev.venv-a"); b.select("dev.venv-b");
  assert.equal(a.current().ref, "dev.venv-a"); assert.equal(b.current().ref, "dev.venv-b");
  h.catalog([project("b")]); assert.throws(() => a.current()); assert.equal(b.current().ref, "dev.venv-b");
  b.local(); assert.equal(b.remoteIntent, false); assert.throws(() => b.select("dev.venv")); assert.equal(b.remoteIntent, true);
});

test("fresh sessions and cancelled pickers preserve local; remote attempts enable unsupported-tool blocking", async () => {
  const h = harness(), s = h.session();
  assert.equal(new h.helper.ManagedProjects("/catalog").remoteIntent, false);
  await s.start(); await s.command();
  for (const name of ["read", "write", "edit", "bash"]) await s.call(name, {});
  assert.equal(h.state.local.length, 4); assert.equal(await s.bash(), undefined);
  assert.equal(s.hooks.get("tool_call")({ toolName: "ls" }), undefined);
  await s.command("project dev.unknown"); await s.command(); await blocked(s, h.state);
  for (const name of ["grep", "find", "ls", "subagent", "agent-team", "anything"]) {
    assert.equal(s.hooks.get("tool_call")({ toolName: name }).block, true);
  }
  for (const name of ["read", "write", "edit", "bash", "remote"]) assert.equal(s.hooks.get("tool_call")({ toolName: name }), undefined);
  assert.equal(h.state.connections.length, 0);
});

test("two factories same cwd use different targets with actual SDK read/write/edit/bash operations", async () => {
  const h = harness(), a = h.session(), b = h.session(); await a.start(); await b.start();
  await a.command("project dev.venv-a"); b.choose(2); await b.command();
  for (const [s, host] of [[a, "a.example.test"], [b, "b.example.test"]]) {
    const offset = h.state.calls.length;
    await s.call("read", { path: "code.ts" });
    await s.call("write", { path: "code.ts", content: "before\n" });
    await s.call("edit", { path: "code.ts", edits: [{ oldText: "before", newText: "after" }] });
    await s.call("bash", { command: "pwd" });
    const user = await s.bash(); await user.operations.exec("pwd", "/wrong-sdk-cwd", { onData() {} });
    assert.ok(h.state.calls.slice(offset).every((call) => call.host === host));
    assert.equal(h.state.files.get(`${host}:/work/project/code.ts`), "after\n");
    assert.ok(s.branch.every((entry) => !JSON.stringify(entry).includes("identity_file") && !JSON.stringify(entry).includes("ssh ")));
  }
  assert.equal(h.state.local.length, 0); assert.equal(h.state.writes.length, 0);
  for (const options of h.state.connections) {
    assert.equal(options.agent, undefined); assert.equal(options.password, undefined); assert.ok(options.privateKey);
    assert.equal(options.hostHash, "sha256"); assert.equal(options.hostVerifier("ab".repeat(32)), true);
    assert.equal(options.hostVerifier("cd".repeat(32)), false);
  }
  assert.equal(h.sandbox.__piHpcCredentialCacheV1.resume.command, "ssh attacker@elsewhere");
  const prompt = a.hooks.get("before_agent_start")({ systemPrompt: "Base" }).systemPrompt;
  assert.ok(prompt.includes("Managed project dev.venv-a")); assert.equal(h.state.writes.length, 0);
  assert.equal(a.hooks.get("context")({ messages: [] }), undefined);
});

test("unknown/removed projects, malformed catalog and metadata changes block existing connection", async () => {
  for (const change of [[], [project("a", { address: "changed.example.test" })], [project("a", { host_key_sha256: "cd".repeat(32) })],
    [project("a", { identity_file: "/new/key" })], [project("a", { label: "Changed" })], [project("a", { port: 23 })],
    [project("a", { user: "changed" })], [project("a", { cwd: "/new/cwd" })]]) {
    const h = harness(), s = h.session(); await s.start(); await s.command("project dev.venv-a");
    const offset = h.state.calls.length; h.catalog(change); await blocked(s, h.state); assert.equal(h.state.calls.length, offset);
  }
  const h = harness(), s = h.session(); await s.start(); await s.command("project dev.venv-a");
  h.state.catalog = "{"; await blocked(s, h.state);
  h.catalog([project("b")]); await s.command("project dev.venv-a"); await blocked(s, h.state);
  h.state.catalog = new Error("ENOENT catalog removed"); await blocked(s, h.state);
  h.catalog([project("c")]); await s.command("project dev.venv-c"); await s.call("bash", { command: "pwd" });
  assert.equal(h.state.calls.at(-1).host, "c.example.test");
});

test("host trust/auth/key/cwd/connect failures retain intent without prompts, fallback or global writes", async () => {
  for (const delta of [{ fingerprint: "cd".repeat(32) }, { key: "MISSING" }, { key: "ENCRYPTED" },
    { fail: "auth" }, { fail: "cwd" }, { fail: "channel" }, { cwd: "/symlink-resolved-elsewhere" }]) {
    const h = harness(), s = h.session(); await s.start(); Object.assign(h.state, delta);
    await s.command("off"); // A failed explicit remote choice must stop previous local mode.
    await s.command("project dev.venv-a"); await blocked(s, h.state);
    assert.equal(h.state.writes.length, 0); assert.ok(s.notifications.some(([, severity]) => severity === "error"));
  }
});

test("only explicit USER local/off enables local tools; model off/forward/memory/cwd is blocked", async () => {
  const h = harness(), s = h.session(); await s.start(); await s.command("project dev.venv-a");
  for (const action of ["disconnect", "forget", "forward", "unforward", "memory", "note", "chdir", "off"]) {
    await assert.rejects(s.call("remote", { action }));
  }
  for (const command of ["ssh root@elsewhere", "use root@elsewhere", "forward 1:localhost:2", "cd /", "forget"]) await s.command(command);
  s.choose(undefined); await s.command(); await s.call("bash", { command: "pwd" }); assert.equal(h.state.local.length, 0);
  // The old local-memory path is a remote path now, not an escape.
  await s.call("write", { path: "/fake-home/.pi/agent/ssh-remote-memories/cHJvamVjdEBhLmV4YW1wbGUudGVzdA.json", content: "x" });
  assert.equal(h.state.local.length, 0);
  s.choose(0); await s.command(); await s.call("bash", { command: "pwd" }); assert.equal(h.state.local.at(-1).cwd, s.ctx.cwd);
  assert.equal(await s.bash(), undefined); assert.equal(s.hooks.get("tool_call")({ toolName: "ls" }), undefined);
  await s.command("project dev.venv-a"); await s.command("off"); await s.call("read", { path: "x" });
  assert.equal(h.state.local.at(-1).cwd, s.ctx.cwd);
});

test("managed mutation is not replayed on reconnectable errors; connection loss requires explicit reconnect", async () => {
  const h = harness(), s = h.session(); await s.start(); await s.command("project dev.venv-a");
  h.state.fail = "write"; await assert.rejects(s.call("write", { path: "code.ts", content: "x" }));
  assert.equal(h.state.calls.filter((call) => call.write).length, 1); assert.equal(h.state.connections.length, 1);
  h.state.fail = "channel"; const offset = h.state.calls.length;
  await assert.rejects(s.call("bash", { command: "mutate" })); assert.equal(h.state.calls.length, offset + 1);
  h.state.clients[0].emit("close"); await blocked(s, h.state); assert.equal(h.state.connections.length, 1);
  h.state.fail = ""; await s.call("remote", { action: "reconnect" }); assert.equal(h.state.connections.length, 2);
  h.state.fail = "stream"; const streams = h.state.calls.length;
  await assert.rejects(s.call("bash", { command: "mutate" })); assert.equal(h.state.calls.length, streams + 1);
  const user = await s.bash(); await assert.rejects(user.operations.exec("mutate", s.ctx.cwd, { onData() {} }));
  assert.equal(h.state.calls.length, streams + 2); assert.equal(h.state.local.length, 0);
});

test("own-session reload/resume/fork reauthorize; new session never inherits global target", async () => {
  const h = harness(), a = h.session(), b = h.session(); await a.start(); await b.start();
  await a.command("project dev.venv-a"); await b.command("project dev.venv-b"); await a.shutdown();
  for (const reason of ["reload", "resume", "fork"]) {
    const restored = h.session([...a.branch]); await restored.start(reason); await restored.call("bash", { command: "pwd" });
    assert.equal(h.state.calls.at(-1).host, "a.example.test"); await restored.shutdown();
  }
  const fresh = h.session(); await fresh.start("new"); await fresh.call("bash", { command: "pwd" });
  assert.equal(await fresh.bash(), undefined);
  h.catalog([project("b")]); const revoked = h.session([...a.branch]); await revoked.start("resume"); await blocked(revoked, h.state);
  await b.call("bash", { command: "pwd" }); assert.equal(h.state.calls.at(-1).host, "b.example.test");
  const corrupt = h.session([{ type: "custom", customType: "pi-ssh-remote-project", data: { version: 1, local: true, projectRef: "dev.venv-a" } }]);
  await corrupt.start(); await blocked(corrupt, h.state);
  await b.command("off"); const local = h.session([...b.branch]); await local.start("resume"); await local.call("bash", { command: "pwd" });
  assert.equal(h.state.local.length, 2);
});

test("catalog is rechecked between SDK suboperations and before deferred user bash", async () => {
  const h = harness(), s = h.session(); await s.start(); await s.command("project dev.venv-a");
  const user = await s.bash(); h.catalog([]);
  await assert.rejects(user.operations.exec("pwd", s.ctx.cwd, { onData() {} }));
  h.catalog([project()]); h.state.hold = true;
  const write = s.call("write", { path: "code.ts", content: "x" });
  for (let i = 0; !h.state.pending.length && i < 100; i++) await new Promise((done) => setTimeout(done, 5));
  assert.equal(h.state.pending.length, 1); // SDK mutation-queue bookkeeping may await local realpath.
  h.catalog([]); h.state.pending.shift()(); await assert.rejects(write);
  assert.equal(h.state.calls.filter((call) => call.write).length, 0); assert.equal(h.state.local.length, 0);
});

test("same-session concurrent control cannot retarget an in-flight operation", async () => {
  const h = harness(), s = h.session(); await s.start(); await s.command("project dev.venv-a");
  const deferred = await s.bash();
  h.state.hold = true; const work = s.call("bash", { command: "mutate" }); await new Promise(setImmediate);
  await assert.rejects(s.call("remote", { action: "connect", projectRef: "dev.venv-b" }), /in progress/);
  await assert.rejects(s.call("remote", { action: "reconnect", command: "forbidden" }), /in progress/);
  await s.command("off"); h.state.pending.shift()(); await work; h.state.hold = false;
  await s.command("project dev.venv-b");
  await assert.rejects(deferred.operations.exec("pwd", s.ctx.cwd, { onData() {} }), /changed/);
  assert.equal(h.state.local.length, 0);
});

test("catalog absent retains upstream local tools, command input and model disconnect behavior", async () => {
  const h = harness(false), s = h.session([], "/session-not-process-cwd"); await s.start();
  for (const tool of ["read", "write", "edit", "bash"]) await s.call(tool, {});
  assert.equal(h.state.local.length, 4); assert.ok(h.state.local.every((call) => call.cwd === s.ctx.cwd));
  assert.equal(await s.bash(), undefined); assert.equal(s.hooks.get("tool_call")({ toolName: "subagent" }), undefined);
  await s.call("remote", { action: "disconnect" });
  let inputCalled = false; s.ctx.ui.input = async () => { inputCalled = true; return undefined; }; await s.command();
  assert.equal(inputCalled, true);
});

test("unmanaged explicit SSH and automatic reconnect/replay remain upstream behavior", async () => {
  const h = harness(false), s = h.session(); await s.start();
  h.state.storage.set("/fake-home/.pi/agent/ssh-remote-known-hosts.json", JSON.stringify({ "a.example.test:2222": h.state.fingerprint }));
  await s.call("remote", { action: "connect", command: "ssh -i /dedicated/key project@a.example.test -p 2222", cwd: "/work/project" });
  const connections = h.state.connections.length;
  h.state.fail = "channel-once"; await s.call("bash", { command: "pwd" });
  assert.equal(h.state.connections.length, connections + 1);
  assert.equal(h.state.local.length, 0);
  await s.call("write", { path: "unmanaged-file", content: "unchanged SFTP" });
  assert.equal(h.state.files.get("a.example.test:/work/project/unmanaged-file"), "unchanged SFTP");
  await s.call("remote", { action: "disconnect" }); await s.call("bash", { command: "pwd" });
  assert.equal(h.state.local.length, 1);
});

for (const [dispatch, tool, params] of [
  ["write", "write", { path: "file", content: "mutation" }],
  ["read", "edit", { path: "file", edits: [{ oldText: "before", newText: "after" }] }],
  ["stat", "read", { path: "file" }],
]) test(`P1 delayed SFTP ${dispatch} must reauthorize before IO and close the acquired channel`, async () => {
  for (const change of ["revoke", "metadata", "connection", "new-context"]) {
    const h = harness(), s = h.session(); await s.start(); await s.command("project dev.venv-a");
    h.state.holdSftp = true;
    const offset = h.state.calls.length, closed = h.state.closedSftp;
    const outcome = s.call(tool, params).then(() => undefined, (error) => error);
    for (let i = 0; !h.state.pendingSftp.length && i < 100; i++) await new Promise((done) => setTimeout(done, 5));
    assert.equal(h.state.pendingSftp.length, 1, "authenticated SFTP acquisition must be pending");
    if (change === "revoke") h.catalog([]);
    if (change === "metadata") h.catalog([project("a", { host_key_sha256: "cd".repeat(32) })]);
    if (change === "connection") h.state.clients[0].emit("close");
    if (change === "new-context") { s.branch.length = 0; await s.start("new"); }
    h.state.holdSftp = false; h.state.pendingSftp.shift()();
    const error = await outcome;
    assert.equal(h.state.calls.slice(offset).filter((call) => call.read || call.stat || call.write).length, 0,
      `${dispatch} dispatched after ${change}`);
    assert.equal(h.state.closedSftp, closed + 1);
    assert.ok(error, "stale SFTP operation must return an error");
    assert.equal(h.state.local.length, 0);
  }
});

test("P1 idle invalid connect/reconnect from Local records remote intent before validation", async () => {
  for (const params of [{ action: "connect" }, { action: "reconnect" },
    ...["connect", "reconnect"].flatMap((action) => ["command", "cwd", "forwards"].map((field) =>
      ({ action, projectRef: "dev.venv-a", [field]: "forbidden" })))]) {
    const h = harness(), s = h.session(); await s.start(); await s.command("off");
    await assert.rejects(s.call("remote", params)); await blocked(s, h.state);
    assert.equal(s.branch.at(-1).data.local, false);
    assert.equal(h.state.connections.length, 0);
    const restored = h.session([...s.branch]); await restored.start("resume");
    // Unknown/missing ref stays blocked; forbidden-input records must not authorize restore.
    await blocked(restored, h.state);
  }
});

test("P1 catalog errors still offer Local without auto-local on error or cancellation", async () => {
  const h = harness(), s = h.session(); await s.start(); await s.command("project dev.venv-a");
  h.state.catalog = "{";
  const choices = [];
  s.ctx.ui.select = async (_title, options) => { choices.push([...options]); return undefined; };
  await s.command(); assert.deepEqual(choices, [["Local (explicit)"]]); await blocked(s, h.state);
  assert.ok(s.notifications.some(([, severity]) => severity === "error"));
  s.ctx.ui.select = async (_title, options) => options[0];
  await s.command(); await s.call("bash", { command: "pwd" }); assert.equal(h.state.local.length, 1);
});

test("P1 fresh contexts are local but malformed remote records and failed attempts never restore local", async () => {
  for (const reason of ["startup", "new", "resume", "reload", "fork"]) {
    const h = harness(), s = h.session(); await s.start(reason);
    assert.equal(await s.bash(), undefined); await s.call("bash", { command: "pwd" });
    assert.equal(h.state.local.length, 1); assert.equal(h.state.connections.length, 0);
  }
  for (const data of [undefined, null, {}, { version: 1, local: false, projectRef: null }]) {
    const h = harness(), s = h.session([{ type: "custom", customType: "pi-ssh-remote-project", data }]);
    await s.start(); await blocked(s, h.state);
  }
  const legacy = harness(), migrated = legacy.session([{ type: "custom", customType: "pi-ssh-remote-state",
    data: { version: 1, connected: true, command: "ssh untrusted@elsewhere", cwd: "/wrong" } }]);
  await migrated.start("resume"); await blocked(migrated, legacy.state);
  const h = harness(), s = h.session(); await s.start(); await s.command("project dev.venv-a");
  s.branch.length = 0; await s.start("new"); // A new context, not a restore-failure path.
  assert.equal(await s.bash(), undefined); assert.equal(h.state.clients[0].ended, true);
});

test("status errors and rejected model off never change local or remote intent", async () => {
  const h = harness(), s = h.session(); await s.start();
  assert.match((await s.call("remote", { action: "status" })).content[0].text, /Local mode/);
  for (const action of ["off", "disconnect", "forget", "forward"]) await assert.rejects(s.call("remote", { action }));
  assert.equal(s.branch.length, 0); assert.equal(await s.bash(), undefined);
  await s.command("project dev.venv-a"); h.catalog([]);
  const records = s.branch.length;
  await assert.rejects(s.call("remote", { action: "status" }));
  await assert.rejects(s.call("remote", { action: "off" }));
  assert.equal(s.branch.length, records); await blocked(s, h.state);
});
