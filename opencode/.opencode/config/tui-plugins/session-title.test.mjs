import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { test } from "node:test";
import { readFile } from "node:fs/promises";

// Only mock the host-supplied renderer: no OpenTUI installation or live TUI.
const hooks = registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "@opentui/solid/jsx-runtime") {
      return { url: "test:jsx-runtime", shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url === "test:jsx-runtime") {
      return {
        format: "module",
        source: "export function jsx(type, props) { return { type, props }; }",
        shortCircuit: true,
      };
    }
    return nextLoad(url, context);
  },
});
const { default: plugin, formatTitle, titleColorKey } = await import("./session-title.mjs");
hooks.deregister();

test("missing and short titles", () => {
  assert.equal(formatTitle(undefined), "");
  assert.equal(formatTitle("  Short title  "), "Short title");
});

test("35-grapheme limit includes ellipsis", () => {
  assert.equal(formatTitle("a".repeat(35)), "a".repeat(35));
  assert.equal(formatTitle("a".repeat(36)), "a".repeat(34) + "…");
  assert.equal(formatTitle("a".repeat(33) + " " + "long"), "a".repeat(33) + "…");
});

test("does not split combining marks, emoji families, or wide characters", () => {
  for (const part of ["e\u0301", "👨‍👩‍👧‍👦", "界"]) {
    assert.equal(formatTitle(part.repeat(36)), part.repeat(34) + "…");
  }
});

test("sanitizes terminal escapes, whitespace, controls, and bidi overrides", () => {
  assert.equal(formatTitle("\x1b[31mRed\x1b[0m\n\t title\x00"), "Red title");
  assert.equal(formatTitle("a\u202eb\u2069"), "ab");
});

test("color is deterministic, case-insensitive, and ignores leading nonletters", () => {
  assert.equal(titleColorKey("Alpha"), titleColorKey("alpha different title"));
  assert.equal(titleColorKey("123 🚀 Alpha"), titleColorKey("Alpha"));
  assert.equal(titleColorKey("\x1b[31mAlpha\x1b[0m"), titleColorKey("Alpha"));
  assert.notEqual(titleColorKey("Alpha"), titleColorKey("Beta"));
});

test("Unicode letters normalize consistently; no-letter titles fall back", () => {
  assert.equal(titleColorKey("Éclair"), titleColorKey("e\u0301clair"));
  assert.equal(titleColorKey("𐐀 title"), titleColorKey("𐐨 title"));
  assert.equal(titleColorKey("界"), ["primary", "secondary", "accent", "success", "warning", "info"]["界".codePointAt(0) % 6]);
  assert.equal(titleColorKey("123 🚀"), "primary");
  assert.equal(titleColorKey(undefined), "primary");
});

test("module and registration match the V2 CLI-only contract and return cleanup", () => {
  let registration;
  const cleanup = () => {};
  assert.equal(plugin.id, "local.session-title");
  assert.equal("server" in plugin, false);
  assert.equal("tui" in plugin, false);
  assert.equal(plugin.setup({ ui: { slot(value) { registration = value; return cleanup; } } }), cleanup);
  assert.deepEqual(Object.keys(registration), ["append", "render"]);
  assert.equal(registration.append, "prompt.footer.status");
});

function theme(prefix) {
  return {
    hue: { interactive: { 200: `${prefix}-primary` }, accent: { 200: `${prefix}-accent` } },
    categorical: [{ 200: `${prefix}-secondary` }],
    text: { feedback: Object.fromEntries(["success", "warning", "info"].map((key) => [key, { base: `${prefix}-${key}` }])) },
  };
}

test("render getters read current session, slot props, and V2 theme; layout stays bounded", () => {
  let registration;
  const sessions = { one: { title: "Alpha" }, two: { title: "Beta" } };
  const api = {
    ui: { slot(value) { registration = value; } },
    data: { session: { get(id) { assert.equal(typeof id, "string"); return sessions[id]; } } },
    theme: theme("old"),
  };
  plugin.setup(api);
  const props = { sessionID: "one" };
  const view = registration.render(props);
  assert.equal(view.type, "text");
  assert.equal(view.props.content, "Alpha");
  assert.equal(view.props.fg, "old-secondary");
  sessions.one.title = "a".repeat(36);
  assert.equal(view.props.content, "a".repeat(34) + "…");
  props.sessionID = "two";
  assert.equal(view.props.content, "Beta");
  assert.equal(view.props.fg, "old-accent");
  api.theme = theme("new");
  assert.equal(view.props.fg, "new-accent");
  for (const title of ["B", "C", "D", "E", "F", "G"]) {
    sessions.two.title = title;
    assert.equal(view.props.fg, `new-${titleColorKey(title)}`);
  }
  props.sessionID = "missing";
  assert.equal(view.props.content, "");
  props.sessionID = undefined;
  assert.equal(view.props.content, "");
  assert.equal(view.props.fg, "new-primary");
  assert.equal(view.props.maxWidth, 35);
  assert.equal(view.props.minWidth, 0);
  assert.equal(view.props.flexShrink, 1);
  assert.equal(view.props.height, 1);
  assert.equal(view.props.wrapMode, "none");
  assert.equal(view.props.truncate, true);
});

test("cli.json targets a directory with a tui.js entrypoint, not the skipped single file", async () => {
  const config = JSON.parse(await readFile(new URL("../cli.json", import.meta.url), "utf8"));
  assert.equal(config.$schema, "https://opencode.ai/v2/cli.json");
  assert.deepEqual(config.plugins, ["./tui-plugins/session-title"]);
  const entry = new URL(`${config.plugins[0]}/tui.js`, new URL("../", import.meta.url));
  // The module was already loaded with the mock renderer above; the shim adds no imports.
  assert.equal((await import(entry)).default, plugin);
  assert.deepEqual(Object.keys(await import(entry)), ["default"]);
});
