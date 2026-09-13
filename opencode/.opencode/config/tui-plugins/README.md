# Session title in the prompt metadata row

✅ `session-title.mjs` adds the current session title to `session_prompt_right`.
It is explicitly loaded by the global `../tui.json` as `local.session-title`.
It does not replace the prompt or change stored titles. The separate server
plugin `../plugins/first-prompt-title.js` remains responsible for title generation.

- Display: whitespace collapsed, terminal escapes/control characters and bidi
  overrides removed; at most 35 graphemes including `…` when shortened.
- Layout: at most 35 terminal columns, one line, no wrapping, renderer truncation
  enabled. Wide glyphs can therefore truncate earlier than 35 graphemes. Very
  narrow terminals or other prompt-right plugins may further constrain space.
- Color: NFC-normalized first Unicode letter, lowercased, code point modulo six:
  `primary`, `secondary`, `accent`, `success`, `warning`, `info`. No letters means
  `primary`. Collisions are intentional; themes may also reuse accent colors.
- Session/title and theme changes are read through reactive getters. No polling,
  network requests, stored state, custom subscriptions, or installed dependencies.

## Verification and activation

Verified against OpenCode **1.18.29**, its local plugin declarations (1.15.7),
and the version-matched OpenTUI **0.4.5** runtime. References:

- [TUI plugin specification](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/specs/tui-plugins.md)
- [TUI loader and runtime imports](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/plugin/tui/runtime.ts)
- [Session/theme adapters](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/tui/src/plugin/adapters.tsx)
- [Prompt metadata layout](https://github.com/anomalyco/opencode/blob/v1.18.29/packages/tui/src/component/prompt/index.tsx)
- [JSX runtime](https://unpkg.com/@opentui/solid@0.4.5/jsx-runtime.js)

Run with Node 22.15+ (tested with 22.23.2):

```sh
node --check ~/.config/opencode/tui-plugins/session-title.mjs
node --test ~/.config/opencode/tui-plugins/session-title.test.mjs
```

The eight tests validate formatting, color mapping, module/slot registration,
fresh getter reads, and layout properties with a mocked JSX renderer. They do
**not** verify live TUI loading, Solid scheduling, terminal layout, or contrast.

When convenient, quit and restart OpenCode normally, then resume a session.
Existing running sessions are not restarted or hot-patched. Do not use `--pure`
when checking this plugin. In the command palette's **Plugins** view, check that
`local.session-title` is active. Inspect short/long titles, a renamed session,
theme changes, and a narrow terminal. Runtime imports are supplied by OpenCode;
standalone Node cannot render this plugin without the host or the test mock.

To disable, toggle `local.session-title` off in **Plugins**, or remove only its
entry from `../tui.json` and restart. A persisted Plugins disable overrides the
config on subsequent starts; toggle it on again there when re-enabling.
