import { test } from "node:test";
import assert from "node:assert/strict";

// Explicit opt-in network contract check, not a mocked assertion about the host.
// npm @opencode/cli@2.0.32 is the published binary distribution; its matching
// release tag resolves to this immutable commit. No mutable main/docs contracts.
// Source checkpoints at that commit:
// promise/tool.ts:39-45; promise/session.ts:28,140; promise/adapter.ts:517,594
// core/plugin/hooks.ts:91-94; core/tool.ts:271-280; core/tool/runtime.ts:31-37
// core/tool/plugin/subagent.ts:130-149,200,229-232
// core/session/model-request.ts:296,427
// Run: OPENCODE_VERIFY_V2_SOURCE=1 node --test opencode/tests/background-subagents-source.test.mjs
const commit = "843a6c514e606b436a7fe713422ace0a93ad3d61";
const base = `https://raw.githubusercontent.com/anomalyco/opencode/${commit}/`;
async function get(url, json = false) {
  const response = await fetch(url, { signal: AbortSignal.timeout(30_000) });
  assert.equal(response.ok, true, `${response.status} ${url}`);
  return json ? response.json() : response.text();
}

test("published 2.0.32 release implements mutable native hooks and consumes their results", {
  skip: process.env.OPENCODE_VERIFY_V2_SOURCE !== "1",
}, async () => {
  const [published, tag, toolAPI, sessionAPI, adapter, hooks, tools, runtime, subagent, request, messages] = await Promise.all([
    get("https://registry.npmjs.org/@opencode/cli/2.0.32", true),
    get("https://api.github.com/repos/anomalyco/opencode/git/ref/tags/v2.0.32", true),
    ...["packages/plugin/src/promise/tool.ts", "packages/plugin/src/promise/session.ts",
      "packages/plugin/src/promise/adapter.ts", "packages/core/src/plugin/hooks.ts",
      "packages/core/src/tool.ts", "packages/core/src/tool/runtime.ts",
      "packages/core/src/tool/plugin/subagent.ts", "packages/core/src/session/model-request.ts",
      "packages/ai/src/schema/messages.ts"].map((path) => get(base + path)),
  ]);
  assert.equal(published.version, "2.0.32");
  assert.equal(published.optionalDependencies["@opencode/cli-linux-x64"], "2.0.32");
  assert.equal(tag.object.sha, commit);
  assert.match(toolAPI, /"execute.before":\s*\{\s*tool: string/);
  assert.match(toolAPI, /\n    input: unknown/); // not readonly
  assert.match(sessionAPI, /system: Array<SystemPart>/);
  assert.match(sessionAPI, /readonly context: SessionContext/);
  assert.match(adapter, /host\.tool\.hook\(name, \(event\) => toolHook\[name\]\(\(\) => Promise\.resolve\(callback\(event\)\)\)\)/);
  assert.match(adapter, /host\.session\.hook\(name, \(event\) => Effect\.promise\(\(\) => Promise\.resolve\(callback\(event\)\)\), options\)/);
  assert.match(hooks, /entry\.callback\(event\)[\s\S]*?yield\* result[\s\S]*?return event/);
  // The actual direct-tool pipeline forwards the modified input, not the
  // original call.input. Runtime decoding therefore sees background:true.
  assert.match(tools, /const event = yield\* beforeExecute\(input\.call\.name, input\.call\.input, context\)/);
  assert.match(tools, /if \(tool\) return yield\* executeTool\(tool, name, event\.input, context\)/);
  assert.match(runtime, /const decoded = yield\* decodeInput\(tool, input\)[\s\S]*?tool\.execute\(decoded, context\)/);
  assert.match(subagent, /background: Schema\.optionalKey\(Schema\.Boolean\)/);
  for (const field of ["agent", "description", "prompt", "sessionID"]) assert.ok(subagent.includes(`${field}:`));
  assert.match(subagent, /const background = input\.background === true/);
  assert.match(subagent, /if \(background\) \{\s*yield\* subagents\.background\(recovery\)\s*return backgroundResult\(child\.id\)/);
  assert.match(subagent, /if \(depth >= limit\)/);
  assert.match(subagent, /yield\* permission\s*\.assert\(/);
  assert.match(request, /primary: \(input\) => prepare\("primary", input, agentHook\("context", input\.agent\)\)/);
  assert.match(request, /system: shaped\.system/);
  assert.match(messages, /const makeSystemPart = \(text: string\): SystemPart => \(\{ type: "text", text \}\)/);
});
