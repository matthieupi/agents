import { stripVTControlCharacters } from "node:util";
import { jsx } from "@opentui/solid/jsx-runtime";

const LIMIT = 35;
const ACCENTS = ["primary", "secondary", "accent", "success", "warning", "info"];
const graphemes = new Intl.Segmenter(undefined, { granularity: "grapheme" });

/** Display only: never changes the stored session title. */
export function formatTitle(title) {
  const text = stripVTControlCharacters(title ?? "")
    .replace(/[\s\p{Cc}]+/gu, " ")
    .replace(/[\u200e\u200f\u202a-\u202e\u2066-\u2069]/gu, "")
    .trim();
  const parts = Array.from(graphemes.segment(text), (part) => part.segment);
  return parts.length <= LIMIT ? text : parts.slice(0, LIMIT - 1).join("").trimEnd() + "…";
}

export function titleColorKey(title) {
  const letter = stripVTControlCharacters(title ?? "").normalize("NFC").match(/\p{L}/u)?.[0];
  return letter ? ACCENTS[letter.toLowerCase().codePointAt(0) % ACCENTS.length] : ACCENTS[0];
}

export default {
  id: "local.session-title",
  /** @param {import("@opencode/plugin/tui/context").Context} context */
  setup(context) {
    return context.ui.slot({
      append: "prompt.footer.status",
      render(props) {
        const title = () => props.sessionID ? context.data.session.get(props.sessionID)?.title : undefined;
        // jsx/spread tracks these getters against the host's Solid state/theme.
        return jsx("text", {
          get content() { return formatTitle(title()); },
          get fg() {
            const theme = context.theme;
            return {
              primary: theme.hue.interactive[200],
              secondary: theme.categorical[0][200],
              accent: theme.hue.accent[200],
              success: theme.text.feedback.success.base,
              warning: theme.text.feedback.warning.base,
              info: theme.text.feedback.info.base,
            }[titleColorKey(title())];
          },
          maxWidth: LIMIT,
          minWidth: 0,
          flexShrink: 1,
          height: 1,
          wrapMode: "none",
          truncate: true,
        });
      },
    });
  },
};
