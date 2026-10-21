# Canonical session title display

The native CLI config `../cli.json` preserves the tracked `opencode` theme and
registers `./tui-plugins/session-title`. Publish this directory together with
`cli.json`, preserving the relative layout. All installation paths use these
same assets; there is no parallel compatibility tree.

```text
cli.json: plugins ["./tui-plugins/session-title"]
  -> session-title/tui.js -> ../session-title.mjs
     -> setup(context) -> ui.slot -> prompt.footer.status
```

The directory entrypoint is required by the native TUI loader. Do not register
the `.mjs` file directly. This remains a display-only plugin. Native V2 owns title
generation through its built-in `title` agent (`openai/gpt-5-mini`) and the server
host owns persistence. The custom `../plugins/first-prompt-title.js` generator is
retired, not this prompt footer; its `OPENCODE_TITLE_*` overrides no longer apply.

## Behavior

- Whitespace is collapsed; terminal escapes, control characters, and bidi
  overrides are removed. Titles are capped at 35 graphemes including ellipsis.
- The first Unicode letter deterministically selects one of six theme colors.
- The additive `prompt.footer.status` slot stays near the prompt without
  replacing the built-in status. Other plugins replacing that slot can hide it.
- The session ID comes from slot props; reactive getters read current title and
  theme. Missing sessions display empty text. No polling or state writes.
- Layout is one line, no wrap, max 35 columns, with renderer truncation and
  shrinking enabled. Wide glyphs/narrow terminals may truncate sooner.

## Publication and preferences

The canonical native `cli.json` explicitly carries all known tracked preferences
(theme and title registration). When publishing into an existing private HOME,
preserve unrelated preferences rather than replacing the private CLI config.
Creating `cli.json` skips upstream's legacy TUI/KV migration, so a private
installation with additional old preferences must use upstream migration first
or deliberately convert those preferences. Docker mounts canonical config
directly; its init does not project or rewrite config files.

Restart the CLI after publication. Check `/plugins` for `local.session-title`
and inspect short/long/renamed titles, theme changes, tabs, and narrow terminals.

## Verification

```sh
node run-tests.mjs
# Optional network smoke with real host/renderer dependencies in a temp HOME:
node run-tests.mjs --runtime
```

The runner copies only owned assets into a disposable HOME/XDG tree and removes
it afterward. Unit tests mock only the host renderer. The optional runtime
contract smoke uses `@opencode/plugin@2.0.32`, `@opentui/solid@0.5.17`, and
`solid-js@1.9.15`; these are test references, not CLI installation pins.

Sources reviewed: the official `v2.0.32` plugin `tui/context.ts`, `host.ts`, TUI
plugin discovery/loader, prompt footer, and CLI config migration code at
<https://github.com/anomalyco/opencode>; CLI schema:
<https://opencode.ai/v2/cli.json>.

Mock tests and import/setup smoke do not establish live rendering, contrast,
Solid scheduling, or supported-engine acceptance for every host version.
