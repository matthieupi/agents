import { beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import * as entrypoint from "../.opencode/config/plugins/first-prompt-title.js";

// Exact contract references, pinned rather than the generic (V1) plugins page:
// https://github.com/anomalyco/opencode/blob/v2.0.32/packages/plugin/src/promise/session.ts
// https://github.com/anomalyco/opencode/blob/v2.0.32/packages/core/src/session/title.ts
// https://github.com/anomalyco/opencode/blob/v2.0.32/packages/core/src/plugin/module.ts
// https://github.com/anomalyco/opencode/blob/v2.0.32/packages/ai/src/schema/messages.ts
const created = Date.parse("2026-10-20T12:00:00.000Z");
const timestampTitle = `New session - ${new Date(created).toISOString()}`;
const user = (text) => ({ type: "user", text });

beforeEach((t) => {
  const keys = ["OPENCODE_TITLE_API_KEY", "OPENAI_API_KEY", "OPENCODE_TITLE_MODEL", "OPENCODE_TITLE_BASE_URL"];
  const saved = keys.map((key) => [key, process.env[key]]);
  for (const key of keys) delete process.env[key];
  t.after(() => {
    for (const [key, value] of saved) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  });
  t.mock.method(globalThis, "fetch", async () => {
    assert.fail("Unexpected network request");
  });
});

async function host(t, { title, history = [user("Fix the login bug.")], get } = {}) {
  const session = { id: "ses_test", title, time: { created } };
  const hooks = new Map();
  const lookups = [];
  const ctx = {
    session: {
      async hook(name, callback) {
        assert.equal(name, "title");
        assert.equal(hooks.has(name), false);
        hooks.set(name, callback);
        return { async dispose() { hooks.delete(name); } };
      },
      async get(input) {
        assert.deepEqual(input, { sessionID: "ses_test" });
        lookups.push(input);
        return get ? get(input) : structuredClone(session);
      },
      async update() { assert.fail("Plugin must let the native title host persist its result"); },
    },
  };
  assert.equal(await entrypoint.default.setup(ctx), undefined);
  const titleHook = hooks.get("title");
  assert.equal(typeof titleHook, "function");
  let nativeRequests = 0;
  let renames = 0;
  // Mirrors the relevant host behavior: first persisted user (not synthetic),
  // initial scheduling only for untitled sessions, explicit regeneration even
  // for titled sessions, result short-circuit, and concurrent-title guard.
  // This is a contract harness, not a real CLI/database integration test.
  async function generate({ regenerate = false } = {}) {
    if (!regenerate && session.title !== undefined && session.title !== timestampTitle) return;
    const first = history.find((message) => message.type === "user");
    if (!first) return;
    const initialTitle = session.title;
    const event = {
      sessionID: session.id,
      model: { providerID: "test", id: "test-model" },
      system: [],
      messages: [{ role: "user", content: [{ type: "text", text: first.text }] }],
      options: {},
    };
    await titleHook(event);
    let title = event.result;
    if (title === undefined) {
      nativeRequests++;
      title = "Native regenerated title";
    }
    const result = title.length > 100 ? `${title.slice(0, 97)}...` : title;
    if (result && session.title === initialTitle && session.title !== result) {
      session.title = result;
      renames++;
    }
    return event;
  }
  return { session, history, lookups, titleHook, generate,
    counts: () => ({ nativeRequests, renames }) };
}

test("exports a default V2 definition, not a V1 factory", () => {
  assert.deepEqual(Object.keys(entrypoint), ["default"]);
  assert.equal(entrypoint.default.id, "first-prompt-title");
  assert.equal(typeof entrypoint.default.setup, "function");
});

test("derives the first real user prompt only, ignoring synthetic and later turns", async (t) => {
  const h = await host(t, { history: [
    { type: "synthetic", text: "Ignore this background notification" },
    { type: "assistant", text: "Ignore assistant output" },
    user("  Fix   the login bug!\nImplementation details follow"),
    user("Different later topic"),
  ] });
  await h.generate();
  assert.equal(h.session.title, "Fix the login bug");
  await h.generate();
  assert.deepEqual(h.counts(), { nativeRequests: 0, renames: 1 });
});

test("recognizes only the exact timestamped root fallback", async (t) => {
  const h = await host(t, { title: timestampTitle });
  await h.generate();
  assert.equal(h.session.title, "Fix the login bug");
});

test("ordinary native initial scheduling preserves custom titles without invoking the hook", async (t) => {
  process.env.OPENCODE_TITLE_API_KEY = "test-only-key";
  for (const title of ["My custom title", "New session architecture", "New chat protocol", "Untitled", "Conversation", "", "A custom title longer than the host title generation limit ".repeat(4), "New session - 2026-10-19T12:00:00.000Z"]) {
    const h = await host(t, { title });
    const event = await h.generate();
    assert.equal(event, undefined);
    assert.equal(h.lookups.length, 0);
    assert.equal(h.session.title, title);
    assert.deepEqual(h.counts(), { nativeRequests: 0, renames: 0 });
  }
});

test("explicit regeneration of existing titles falls through to native generation", async (t) => {
  process.env.OPENCODE_TITLE_API_KEY = "test-only-key";
  for (const title of ["Custom title", "New session architecture", "A long custom title ".repeat(10), ""]) {
    const h = await host(t, { title });
    const event = await h.generate({ regenerate: true });
    assert.equal(event.result, undefined);
    assert.equal(Object.hasOwn(event, "result"), false);
    assert.equal(h.session.title, "Native regenerated title");
    assert.deepEqual(h.counts(), { nativeRequests: 1, renames: 1 });
  }
});

test("declining an existing title leaves another hook's result untouched", async (t) => {
  const h = await host(t, { title: "Custom title" });
  const event = { sessionID: "ses_test", result: "Another plugin's title" };
  await h.titleHook(event);
  assert.equal(event.result, "Another plugin's title");
});

test("no synthetic-only session or empty first prompt title; never uses a later prompt", async (t) => {
  for (const history of [[], [{ type: "synthetic", text: "Notification" }], [user("  \n "), user("Later text")], [user("!!!")]]) {
    const h = await host(t, { history });
    await h.generate();
    assert.equal(h.session.title, undefined);
    assert.deepEqual(h.counts(), { nativeRequests: 0, renames: 0 });
  }
});

test("keeps multiline and word-aware truncation fallback behavior", async (t) => {
  const h = await host(t, { history: [user("Investigate " + "longword ".repeat(20) + "\nmore details")] });
  await h.generate();
  assert.ok(h.session.title.startsWith("Investigate longword"));
  assert.ok(h.session.title.endsWith("..."));
  assert.ok(h.session.title.length <= 75);
  assert.ok(!h.session.title.includes("\n"));
});

test("optional LLM uses existing environment settings and sanitizes output", async (t) => {
  process.env.OPENCODE_TITLE_API_KEY = "title-key";
  process.env.OPENAI_API_KEY = "other-key";
  process.env.OPENCODE_TITLE_BASE_URL = "https://example.invalid/title/";
  process.env.OPENCODE_TITLE_MODEL = "title-model";
  let calls = 0;
  globalThis.fetch = async (url, init) => {
    calls++;
    assert.equal(url, "https://example.invalid/title");
    assert.equal(init.headers.authorization, "Bearer title-key");
    assert.equal(init.method, "POST");
    assert.ok(init.signal instanceof AbortSignal);
    const body = JSON.parse(init.body);
    assert.equal(body.model, "title-model");
    assert.equal(body.max_tokens, 64);
    assert.equal(body.messages[1].content, "First user prompt:\nFix the login bug");
    return { ok: true, json: async () => ({ choices: [{ message: { content: '\nTitle: "Repair Login Flow!"\nDo not use this line' } }] }) };
  };
  const h = await host(t);
  await h.generate();
  await h.generate();
  assert.equal(h.session.title, "Repair Login Flow");
  assert.equal(calls, 1);
});

test("LLM HTTP, transport, JSON and malformed output failures use fallback", async (t) => {
  process.env.OPENAI_API_KEY = "test-key";
  for (const response of [
    async () => { throw new Error("offline"); },
    async () => ({ ok: false }),
    async () => ({ ok: true, json: async () => { throw new Error("invalid JSON"); } }),
    async () => ({ ok: true, json: async () => ({}) }),
    async () => ({ ok: true, json: async () => ({ choices: [{ message: { content: "Title: ..." } }] }) }),
    async () => ({ ok: true, json: async () => ({ choices: [{ message: { content: { unexpected: "object" } } }] }) }),
    async () => ({ ok: true, json: async () => ({ choices: [{ message: { content: 123 } }] }) }),
  ]) {
    globalThis.fetch = response;
    const h = await host(t);
    await h.generate();
    assert.equal(h.session.title, "Fix the login bug");
    assert.deepEqual(h.counts(), { nativeRequests: 0, renames: 1 });
  }
});

test("lookup failures leave the result untouched and allow native fallback", async (t) => {
  for (const get of [async () => { throw new Error("missing session"); }, async () => undefined]) {
    const h = await host(t, { get });
    const event = await h.generate();
    assert.equal(Object.hasOwn(event, "result"), false);
    assert.equal(h.session.title, "Native regenerated title");
    assert.equal(h.counts().nativeRequests, 1);
    const existing = { sessionID: "ses_test", result: "Existing hook result" };
    await h.titleHook(existing);
    assert.equal(existing.result, "Existing hook result");
  }
});

test("malformed hook input does not throw; ambiguous titles are not owned", async (t) => {
  const h = await host(t);
  const event = { sessionID: "ses_test" };
  await assert.doesNotReject(h.titleHook(event));
  assert.equal(event.result, "");
  const historical = await host(t, { title: timestampTitle,
    get: async () => ({ title: timestampTitle, time: { created: "invalid" } }) });
  const ambiguous = { sessionID: "ses_test" };
  await historical.titleHook(ambiguous);
  assert.equal(Object.hasOwn(ambiguous, "result"), false);
  assert.equal(historical.session.title, timestampTitle);
});

test("lookup has a bounded wait and a late completion cannot mutate result", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let resolve;
  const h = await host(t, { get: () => new Promise((done) => { resolve = done; }) });
  const pending = h.generate();
  await Promise.resolve();
  t.mock.timers.tick(1_000);
  const event = await pending;
  assert.equal(Object.hasOwn(event, "result"), false);
  resolve({ title: undefined });
  await Promise.resolve();
  assert.equal(Object.hasOwn(event, "result"), false);
});

test("LLM deadline covers both fetch and response parsing, even when abort is ignored", async (t) => {
  process.env.OPENAI_API_KEY = "test-key";
  t.mock.timers.enable({ apis: ["setTimeout"] });
  for (const phase of ["fetch", "json"]) {
    let resolve;
    let signal;
    globalThis.fetch = (_url, init) => {
      signal = init.signal;
      const stuck = new Promise((done) => { resolve = done; });
      return phase === "fetch" ? stuck : Promise.resolve({ ok: true, json: () => stuck });
    };
    const h = await host(t);
    const pending = h.generate();
    // Drain lookup/race microtasks until the request has started.
    for (let i = 0; i < 20; i++) await Promise.resolve();
    assert.ok(signal);
    t.mock.timers.tick(3_000);
    const event = await pending;
    assert.equal(signal.aborted, true);
    assert.equal(event.result, "Fix the login bug");
    resolve(phase === "fetch" ? { ok: false } : { choices: [{ message: { content: "Late title" } }] });
    for (let i = 0; i < 5; i++) await Promise.resolve();
    assert.equal(event.result, "Fix the login bug");
  }
});

test("native host guard preserves a user rename during optional generation", async (t) => {
  process.env.OPENAI_API_KEY = "test-key";
  const h = await host(t);
  globalThis.fetch = async () => {
    h.session.title = "User renamed this while waiting";
    return { ok: true, json: async () => ({ choices: [{ message: { content: "Generated title" } }] }) };
  };
  await h.generate();
  assert.equal(h.session.title, "User renamed this while waiting");
  assert.equal(h.counts().renames, 0);
});

test("concurrent title attempts cannot overwrite the first committed title", async (t) => {
  const h = await host(t);
  await Promise.all([h.generate(), h.generate()]);
  assert.equal(h.session.title, "Fix the login bug");
  assert.deepEqual(h.counts(), { nativeRequests: 0, renames: 1 });
});
