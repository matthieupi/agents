import assert from "node:assert/strict";
import { test } from "node:test";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { join } from "node:path";
import { mkdtempSync, writeFileSync } from "node:fs";

// run.py sets cwd, HOME and SDK agentDir to the isolated public build fixture.
const cwd = process.cwd();
const require = createRequire(join(cwd, "package.json"));
const { createJiti } = require("jiti");
const jiti = createJiti(join(cwd, "package.json"), { fsCache: false, tsconfigPaths: true, jsx: { runtime: "automatic" } });
const sdk = await import(pathToFileURL(join(cwd, "node_modules/@earendil-works/pi-coding-agent/dist/index.js")));
const { AgentSessionWrapper, getRpcSession } = await jiti.import(join(cwd, "lib/rpc-manager.ts"));
const { sessionProjectMode, rejectRemoteProjectRequest } = await jiti.import(join(cwd, "lib/session-project-mode.ts"));
const { projectRequestUrl } = await jiti.import(join(cwd, "lib/project-request.ts"));
const remote = { version: 1, local: false, projectRef: "pending-invalid" };
const local = { version: 1, local: true, projectRef: null };

async function setup(t, handler) {
  const settingsManager = sdk.SettingsManager.inMemory({ packages: [], extensions: [] });
  const resourceLoader = new sdk.DefaultResourceLoader({ cwd, agentDir: process.env.PI_CODING_AGENT_DIR,
    settingsManager, noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true,
    noContextFiles: true, extensionFactories: handler ? [(pi) => pi.on("user_bash", handler)] : [],
  });
  await resourceLoader.reload();
  const manager = sdk.SessionManager.inMemory(cwd);
  const { session } = await sdk.createAgentSession({ cwd, agentDir: process.env.PI_CODING_AGENT_DIR,
    settingsManager, resourceLoader, sessionManager: manager, tools: [] });
  const wrapper = new AgentSessionWrapper(session);
  await session.bindExtensions({ uiContext: wrapper.createExtensionUiContext(), mode: "rpc" });
  getRpcSession("initialize-registry");
  globalThis.__piSessions.set(session.sessionId, wrapper);
  t.after(() => { globalThis.__piSessions.delete(session.sessionId); wrapper.destroy(); });
  return { wrapper, session, manager };
}

test("real SDK operations route browser ! and !! and preserve history", async (t) => {
  const events = [], calls = [];
  const { wrapper, manager, session } = await setup(t, (event) => {
    events.push(event);
    return { operations: { exec: async (command, dir, { onData }) => {
      calls.push({ command, dir }); onData(Buffer.from("remote fixture output\n")); return { exitCode: 0 };
    } } };
  });
  manager.appendCustomEntry("pi-ssh-remote-project", remote);
  for (const excludeFromContext of [false, true]) {
    const result = await wrapper.send({ type: "bash", command: "REMOTE_ONLY_NOT_A_LOCAL_COMMAND", excludeFromContext });
    assert.equal(result.output, "remote fixture output\n");
  }
  assert.equal(calls.length, 2);
  assert.equal(events[1].excludeFromContext, true);
  assert.equal(events[0].cwd, cwd);
  assert.equal(session.messages.filter((message) => message.role === "bashExecution").length, 2);
});

test("SDK replacement result records history without executeBash", async (t) => {
  const supplied = { output: "blocked by extension", exitCode: 1, cancelled: false, truncated: false };
  const { wrapper, manager, session } = await setup(t, () => ({ result: supplied }));
  manager.appendCustomEntry("pi-ssh-remote-project", remote);
  session.executeBash = () => assert.fail("must not execute");
  assert.deepEqual(await wrapper.send({ type: "bash", command: "never" }), supplied);
  assert.equal(session.messages.at(-1).output, supplied.output);
});

for (const kind of ["missing", "undefined", "throws", "empty"]) {
  test(`remote ${kind} hook never reaches local execution`, async (t) => {
    const handler = kind === "missing" ? undefined : () => {
      if (kind === "throws") throw new Error("hook failure");
      return kind === "empty" ? {} : undefined;
    };
    const { wrapper, manager, session } = await setup(t, handler);
    manager.appendCustomEntry("pi-ssh-remote-project", remote);
    session.executeBash = () => assert.fail("local execution reached");
    await assert.rejects(wrapper.send({ type: "bash", command: "never" }), /hook/i);
  });
}

test("Local default still executes sanitized local bash; explicit Local restores it", async (t) => {
  const { wrapper, manager } = await setup(t);
  assert.match((await wrapper.send({ type: "bash", command: "printf local-fixture" })).output, /local-fixture/);
  manager.appendCustomEntry("pi-ssh-remote-project", remote);
  manager.appendCustomEntry("pi-ssh-remote-project", local);
  assert.match((await wrapper.send({ type: "bash", command: "printf explicit-local" })).output, /explicit-local/);
});

test("awaited hook preserves busy exclusion and abort before execution", async (t) => {
  let release;
  const { wrapper, manager, session } = await setup(t, () => new Promise((resolve) => { release = resolve; }));
  manager.appendCustomEntry("pi-ssh-remote-project", remote);
  session.executeBash = () => assert.fail("aborted hook must not execute");
  const pending = wrapper.send({ type: "bash", command: "never" });
  await new Promise(setImmediate);
  await assert.rejects(wrapper.send({ type: "bash", command: "never" }), /busy/);
  await wrapper.send({ type: "abort_bash" });
  release({ operations: {} });
  await assert.rejects(pending, /aborted/);
});

test("live and persisted SDK branches are authority; unknown/empty context rejects", async (t) => {
  const a = await setup(t), b = await setup(t);
  a.manager.appendCustomEntry("pi-ssh-remote-project", remote);
  assert.equal(await sessionProjectMode(a.session.sessionId), "remote");
  assert.equal(await sessionProjectMode(b.session.sessionId), "local");
  const url = "http://localhost/api/git/status";
  for (const id of [a.session.sessionId, "unknown", ""]) {
    assert.equal((await rejectRemoteProjectRequest(new Request(projectRequestUrl(url, id).replace(/^\//, "http://localhost/")))).status, 409);
  }
  assert.equal(await rejectRemoteProjectRequest(new Request(url)), undefined);
  const manager = sdk.SessionManager.create(cwd, join(process.env.HOME, "persisted"));
  manager.appendCustomEntry("pi-ssh-remote-project", remote);
  manager.appendMessage({ role: "assistant", content: [], api: "openai-completions", provider: "fixture", model: "fixture",
    usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: "stop", timestamp: Date.now() });
  const { cacheSessionPath } = await jiti.import(join(cwd, "lib/session-reader.ts"));
  cacheSessionPath(manager.getSessionId(), manager.getSessionFile());
  assert.equal(await sessionProjectMode(manager.getSessionId()), "remote");
});

test("actual HTTP handlers reject remote/unknown before native file/Git/PTY work", async (t) => {
  const { wrapper, manager } = await setup(t);
  manager.appendCustomEntry("pi-ssh-remote-project", remote);
  const { NextRequest } = require("next/server");
  const routes = {
    "files/[...path]": ["GET", "POST"], "file-index": ["GET"],
    "git/status": ["GET"], "git/diff": ["GET"], "worktrees": ["GET", "POST", "DELETE"],
    "terminal": ["POST"], "terminal/[id]": ["GET", "POST", "DELETE"], "terminal/[id]/events": ["GET"],
  };
  for (const [route, methods] of Object.entries(routes)) {
    const module = await jiti.import(join(cwd, `app/api/${route}/route.ts`));
    for (const method of methods) for (const id of [wrapper.sessionId, "unknown", ""]) {
      const request = new NextRequest(`http://localhost/api/${route}?sessionId=${id}`, { method });
      const response = await module[method](request, { params: Promise.resolve({ id: "no-terminal", path: ["no-file"] }) });
      assert.equal(response.status, 409, `${method} ${route} ${id}`);
    }
  }
  // Real local files handler succeeds under existing allowed-root protection.
  const dir = mkdtempSync(join(process.env.HOME, "files-"));
  writeFileSync(join(dir, "visible.txt"), "local contents");
  const { allowFileRoot } = await jiti.import(join(cwd, "lib/file-access.ts"));
  allowFileRoot(dir);
  manager.appendCustomEntry("pi-ssh-remote-project", local);
  const files = await jiti.import(join(cwd, "app/api/files/[...path]/route.ts"));
  const response = await files.GET(new NextRequest(`http://localhost/api/files/x?type=list&sessionId=${wrapper.sessionId}`),
    { params: Promise.resolve({ path: dir.split("/").filter(Boolean) }) });
  assert.equal(response.status, 200);
  assert.ok((await response.json()).entries.some((entry) => entry.name === "visible.txt"));
});

test("React Local-only boundary renders Local features and hides unknown bound panels", async () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const { ProjectModeProvider, LocalOnly } = await jiti.import(join(cwd, "components/ProjectMode.tsx"));
  const render = (sessionId) => renderToStaticMarkup(React.createElement(ProjectModeProvider, { sessionId },
    React.createElement(LocalOnly, null, React.createElement("div", null, "LOCAL_PANEL_CONTENT"))));
  assert.match(render(null), /LOCAL_PANEL_CONTENT/);
  assert.doesNotMatch(render("bound"), /LOCAL_PANEL_CONTENT/);
  assert.match(render("bound"), /available in Local mode/);
});

test("canonical copied helper treats pending, malformed and legacy intent as remote", async () => {
  const { remoteProjectMode } = await jiti.import(join(cwd, "lib/remote-project-mode.ts"));
  const entry = (data) => ({ type: "custom", customType: "pi-ssh-remote-project", data });
  assert.equal(remoteProjectMode([]), "local");
  for (const data of [null, {}, remote, { version: 1, local: true, projectRef: "invalid" }]) {
    assert.equal(remoteProjectMode([entry(data)]), "remote");
  }
  const legacy = { type: "custom", customType: "pi-ssh-remote-state", data: { connected: false } };
  assert.equal(remoteProjectMode([legacy]), "remote");
  assert.equal(remoteProjectMode([legacy, entry(local)]), "local");
  assert.equal(remoteProjectMode([entry(local), legacy]), "remote");
});

test("missing SDK hook method or missing SDK session context never falls back", async (t) => {
  const { wrapper, manager, session } = await setup(t);
  manager.appendCustomEntry("pi-ssh-remote-project", remote);
  session.executeBash = () => assert.fail("local execution reached");
  session.extensionRunner.emitUserBash = undefined;
  await assert.rejects(wrapper.send({ type: "bash", command: "never" }), /hook unavailable/);
  manager.getBranch = () => { throw new Error("context unavailable"); };
  await assert.rejects(wrapper.send({ type: "bash", command: "never" }), /context unavailable/);
});

test("real SDK abort reaches extension operations without local execution", async (t) => {
  let started;
  const ready = new Promise((resolve) => { started = resolve; });
  const { wrapper, manager } = await setup(t, () => ({ operations: { exec: async (_command, _cwd, { signal, onData }) => {
    onData(Buffer.from("partial remote output"));
    started();
    await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true }));
    throw new Error("aborted");
  } } }));
  manager.appendCustomEntry("pi-ssh-remote-project", remote);
  const pending = wrapper.send({ type: "bash", command: "never-local" });
  await ready;
  await wrapper.send({ type: "abort_bash" });
  const result = await pending;
  assert.equal(result.cancelled, true);
  assert.match(result.output, /partial remote output/);
});
