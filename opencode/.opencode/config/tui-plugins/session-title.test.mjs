import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import { test } from "node:test";

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

test("module and registration match the TUI-only contract", async () => {
  let registration;
  assert.equal(plugin.id, "local.session-title");
  assert.equal("server" in plugin, false);
  await plugin.tui({ slots: { register(value) { registration = value; } } });
  assert.deepEqual(Object.keys(registration.slots), ["session_prompt_right"]);
  assert.equal("id" in registration, false);
});

test("render getters read current session, route props, and theme; layout stays bounded", async () => {
  let registration;
  const sessions = { one: { title: "Alpha" }, two: { title: "Beta" } };
  const api = {
    slots: { register(value) { registration = value; } },
    state: { session: { get(id) { return sessions[id]; } } },
    theme: { current: { secondary: "old-secondary", accent: "old-accent" } },
  };
  await plugin.tui(api);
  const props = { session_id: "one" };
  const view = registration.slots.session_prompt_right({}, props);
  assert.equal(view.type, "text");
  assert.equal(view.props.content, "Alpha");
  assert.equal(view.props.fg, "old-secondary");
  sessions.one.title = "a".repeat(36);
  assert.equal(view.props.content, "a".repeat(34) + "…");
  props.session_id = "two";
  assert.equal(view.props.content, "Beta");
  assert.equal(view.props.fg, "old-accent");
  api.theme.current = { accent: "new-accent" };
  assert.equal(view.props.fg, "new-accent");
  props.session_id = "missing";
  assert.equal(view.props.content, "");
  assert.equal(view.props.maxWidth, 35);
  assert.equal(view.props.minWidth, 0);
  assert.equal(view.props.height, 1);
  assert.equal(view.props.wrapMode, "none");
  assert.equal(view.props.truncate, true);
});
