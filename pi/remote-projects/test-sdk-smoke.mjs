// Real SDK loader + sessions, no model requests or SSH connections.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import net from "node:net";
import tls from "node:tls";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { fixture } from "./test-paths.mjs";

test("Pi 0.85.1 real loader resolves patched TS/helper/TypeBox and binds two isolated sessions", async () => {
  const scratch = fs.mkdtempSync(path.join(fixture, "sdk-smoke-"));
  // All SDK discovery/auth/config locations belong to this new public test run.
  process.env.HOME = scratch;
  process.env.PI_CODING_AGENT_DIR = path.join(scratch, "agent");
  process.env.PI_PROJECT_CATALOG = path.join(scratch, "catalog.json");
  fs.writeFileSync(process.env.PI_PROJECT_CATALOG, '{"projects":[]}\n', { flag: "wx", mode: 0o600 });
  const cwd = path.join(scratch, "control");
  fs.mkdirSync(cwd);
  const requireFixture = createRequire(path.join(fixture, "package.json"));
  const ssh2 = requireFixture("ssh2");
  let networkCalls = 0;
  const denyNetwork = () => { networkCalls++; throw new Error("Smoke must not attempt SSH/provider/network access"); };
  const previous = [net.Socket.prototype.connect, tls.connect, globalThis.fetch, ssh2.Client.prototype.connect];
  net.Socket.prototype.connect = denyNetwork;
  tls.connect = denyNetwork;
  globalThis.fetch = denyNetwork;
  ssh2.Client.prototype.connect = denyNetwork;
  const sessions = [];
  try {
    const sdk = await import(pathToFileURL(path.join(fixture, "node_modules/@earendil-works/pi-coding-agent/dist/index.js")));
    const version = JSON.parse(fs.readFileSync(path.join(fixture, "node_modules/@earendil-works/pi-coding-agent/package.json"))).version;
    assert.equal(version, "0.85.1");
    const errors = [], notifications = [], selections = [];
    async function makeSession() {
      const settingsManager = sdk.SettingsManager.inMemory({ packages: [], extensions: [] });
      const loader = new sdk.DefaultResourceLoader({ cwd, agentDir: process.env.PI_CODING_AGENT_DIR, settingsManager,
        additionalExtensionPaths: [path.join(fixture, "index.ts")], noExtensions: true,
        noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true });
      await loader.reload();
      assert.deepEqual(loader.getExtensions().errors, []);
      assert.equal(loader.getExtensions().extensions.length, 1);
      const manager = sdk.SessionManager.inMemory(cwd);
      const result = await sdk.createAgentSession({ cwd, agentDir: process.env.PI_CODING_AGENT_DIR,
        resourceLoader: loader, settingsManager, sessionManager: manager,
        tools: ["read", "write", "edit", "bash", "remote"] });
      assert.deepEqual(result.extensionsResult.errors, []);
      sessions.push(result.session);
      const runner = result.session.extensionRunner;
      const ui = { ...runner.getUIContext(),
        select: async (title, options) => { selections.push({ title, options }); return undefined; },
        notify: (...args) => notifications.push(args), setStatus() {},
      };
      await result.session.bindExtensions({ uiContext: ui, mode: "rpc", onError: (error) => errors.push(error) });
      assert.ok(runner.getRegisteredCommands().some((command) => command.name === "remote"));
      const tool = runner.getToolDefinition("remote");
      assert.ok(tool.parameters.properties.projectRef); // Real TypeBox schema survived loader resolution.
      const context = runner.createContext();
      assert.equal(context.cwd, cwd);
      return { session: result.session, runner, manager, tool, context };
    }
    const a = await makeSession(), b = await makeSession();
    assert.notEqual(a.runner, b.runner);
    assert.notEqual(a.context.sessionManager, b.context.sessionManager);
    assert.notEqual(a.tool, b.tool);
    // Exercise real session slash-command dispatch; no LLM prompt falls through.
    await a.session.prompt("/remote");
    await b.session.prompt("/remote");
    assert.equal(selections.length, 2);
    assert.deepEqual(selections[0].options, ["Local (explicit)"]);
    const userEvent = { type: "user_bash", command: "DO_NOT_EXECUTE", cwd, excludeFromContext: false };
    for (const s of [a, b]) {
      assert.equal(await s.runner.emitUserBash(userEvent), undefined); // Fresh and cancelled stays Local.
      // An invalid remote attempt, not a cancelled picker, activates remote intent.
      await assert.rejects(s.tool.execute("smoke", { action: "connect" }, undefined, undefined, s.runner.createContext()));
      const result = await s.runner.emitUserBash(userEvent);
      assert.equal(result.result.exitCode, 1);
      assert.equal(result.result.cancelled, false);
      assert.equal(result.result.truncated, false);
      const blocked = await s.runner.emitToolCall({ type: "tool_call", toolName: "ls", toolCallId: "smoke", input: {} });
      assert.equal(blocked.block, true);
    }
    // Explicit local in A must not change B, despite same cwd and imported factory.
    await a.session.prompt("/remote off");
    assert.equal(await a.runner.emitUserBash(userEvent), undefined);
    assert.equal((await b.runner.emitUserBash(userEvent)).result.exitCode, 1);
    const local = await a.tool.execute("smoke", { action: "status" }, undefined, undefined, a.runner.createContext());
    assert.match(local.content[0].text, /Local mode/);
    await assert.rejects(b.tool.execute("smoke", { action: "status" }, undefined, undefined, b.runner.createContext()));
    assert.ok(a.manager.getBranch().some((entry) => entry.customType === "pi-ssh-remote-project"));
    assert.ok(b.manager.getBranch().some((entry) => entry.customType === "pi-ssh-remote-project" && entry.data.local === false));
    assert.deepEqual(errors, []);
    assert.deepEqual(notifications, []);
    assert.equal(networkCalls, 0);
    console.log("SDK smoke: two loaders/sessions, zero load/runtime errors, command/schema/context isolation, zero network attempts");
  } finally {
    for (const session of sessions) session.dispose();
    [net.Socket.prototype.connect, tls.connect, globalThis.fetch, ssh2.Client.prototype.connect] = previous;
  }
});
