import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import * as entrypoint from "../.opencode/config/plugins/background-subagents.js";

async function host() {
  const hooks = new Map();
  const domain = (prefix) => ({
    async hook(name, callback) {
      const key = `${prefix}.${name}`;
      assert.equal(hooks.has(key), false);
      hooks.set(key, callback);
      return { async dispose() { hooks.delete(key); } };
    },
  });
  // No tool transforms, replacement executors, permission or session APIs are
  // offered: the plugin must only register the two native hooks.
  await entrypoint.default.setup({ tool: domain("tool"), session: domain("session") });
  assert.deepEqual([...hooks.keys()], ["tool.execute.before", "session.context"]);
  return hooks;
}

test("exports only the canonical V2 plugin definition", () => {
  assert.deepEqual(Object.keys(entrypoint), ["default"]);
  assert.equal(entrypoint.default.id, "background-subagents");
  assert.equal(typeof entrypoint.default.setup, "function");
});

for (const agent of ["explore", "system-build"]) {
  test(`defaults fresh and continued ${agent} calls, preserving all other fields`, async () => {
    const hook = (await host()).get("tool.execute.before");
    for (const continuation of [{}, { sessionID: "ses_child" }]) {
      const input = { agent, description: "Bounded task", prompt: "Do the task", ...continuation };
      const original = structuredClone(input);
      const event = { tool: "subagent", input, sessionID: "ses_parent", agent: "system-orchestrator" };
      await hook(event);
      await hook(event);
      assert.equal(event.input, input);
      assert.deepEqual(input, { ...original, background: true });
      assert.equal(event.sessionID, "ses_parent");
    }
  });
}

test("preserves explicit true/false and leaves invalid values for native validation", async () => {
  const hook = (await host()).get("tool.execute.before");
  for (const background of [true, false, null, 0, "false"]) {
    const input = { agent: "system-build", background };
    await hook({ tool: "subagent", input });
    assert.deepEqual(input, { agent: "system-build", background });
  }
  const input = { background: undefined };
  await hook({ tool: "subagent", input });
  assert.equal(input.background, true);
});

test("does not mutate unrelated tools or malformed input", async () => {
  const hook = (await host()).get("tool.execute.before");
  for (const tool of ["shell", "execute", "task", "delegate", "mcp_subagent"]) {
    const input = Object.freeze({ agent: "explore" });
    await hook(Object.freeze({ tool, input }));
    assert.equal(input.background, undefined);
  }
  for (const input of [undefined, null, [], "{}", 1, false]) {
    const event = { tool: "subagent", input };
    await hook(event);
    assert.equal(event.input, input);
  }
});

test("injects a short authoritative SystemPart for every agent without changing tools or messages", async () => {
  const hook = (await host()).get("session.context");
  for (const agent of ["system-orchestrator", "explore", "system-build"]) {
    const original = { type: "text", text: "Existing persona", cache: { type: "ephemeral" } };
    const event = { agent, system: [original], tools: {}, messages: [], options: {} };
    const rest = { tools: event.tools, messages: event.messages, options: event.options };
    await hook(event);
    await hook(event);
    assert.equal(event.system.length, 2);
    assert.equal(event.system[0], original);
    const policy = event.system[1];
    assert.deepEqual(Object.keys(policy), ["type", "text"]);
    assert.equal(policy.type, "text");
    assert.ok(policy.text.length < 1600);
    for (const text of ["overrides portable", "read-only and write-capable", "background:false", "sessionID",
      "permissions", "depth limits", "completion notifications", "wave barrier", "Never sleep, poll", "end the response"]) {
      assert.ok(policy.text.includes(text), text);
    }
    for (const [key, value] of Object.entries(rest)) assert.equal(event[key], value);
  }
});

test("shared instructions keep the native policy conditional on OpenCode V2", async () => {
  const paths = ["system/orchestrator.md", "system/coo.md", "commands/gsd/execute-phase.md",
    "commands/gsd/analyze-codebase.md", "skills/dev/build-feature/SKILL.md"];
  for (const path of paths) {
    const text = await readFile(new URL(`../../agent/${path}`, import.meta.url), "utf8");
    assert.match(text, /\*\*OpenCode V2 only:\*\*/);
    assert.match(text, /background:false/);
    assert.match(text, /Other harnesses/);
  }
});
