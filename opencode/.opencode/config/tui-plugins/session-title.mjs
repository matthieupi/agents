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

/** @param {import("@opencode-ai/plugin/tui").TuiPluginApi} api */
async function tui(api) {
  api.slots.register({
    slots: {
      session_prompt_right(_context, props) {
        const title = () => api.state.session.get(props.session_id)?.title;
        // jsx/spread tracks these getters against the host's Solid state/theme.
        return jsx("text", {
          get content() { return formatTitle(title()); },
          get fg() { return api.theme.current[titleColorKey(title())]; },
          maxWidth: LIMIT,
          minWidth: 0,
          height: 1,
          wrapMode: "none",
          truncate: true,
        });
      },
    },
  });
}

export default { id: "local.session-title", tui };
