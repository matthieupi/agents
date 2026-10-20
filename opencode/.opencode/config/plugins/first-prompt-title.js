// Native title hook: @opencode/plugin promise/session; core session/title.
const LOOKUP_TIMEOUT_MS = 1_000;
const TITLE_TIMEOUT_MS = 3_000;

async function bounded(operation, timeoutMs) {
  const controller = new AbortController();
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(() => operation(controller.signal)),
      new Promise((resolve) => {
        timer = setTimeout(() => {
          controller.abort();
          resolve(undefined);
        }, timeoutMs);
      }),
    ]);
  } catch {
    return undefined;
  } finally {
    clearTimeout(timer);
    controller.abort();
  }
}

function normalizePrompt(text) {
  return text.replace(/\s+/g, " ").trim();
}

function truncateTitle(text, maxLength = 72) {
  if (text.length <= maxLength) return text;

  const truncated = text.slice(0, maxLength + 1);
  const lastSpace = truncated.lastIndexOf(" ");
  const safe = lastSpace >= Math.floor(maxLength * 0.6)
    ? truncated.slice(0, lastSpace)
    : truncated.slice(0, maxLength);

  return safe.trimEnd() + "...";
}

function stopAtFirstLineWithinWindow(text, maxLength = 72) {
  const trimmed = String(text || "").trim();
  const newlineIndex = trimmed.search(/\r?\n/);

  if (newlineIndex === -1 || newlineIndex > maxLength) {
    return trimmed;
  }

  return trimmed.slice(0, newlineIndex);
}

function deriveTitle(parts) {
  const rawPrompt = parts
    .filter((part) => part.type === "text" && !part.synthetic && !part.ignored)
    .map((part) => part.text)
    .join(" ");

  const prompt = normalizePrompt(stopAtFirstLineWithinWindow(rawPrompt));

  if (!prompt) return undefined;

  return truncateTitle(prompt.replace(/[\s.!?;:,]+$/, ""));
}

function sanitizeGeneratedTitle(value) {
  if (typeof value !== "string" || !value) return undefined;

  const firstLine = String(value)
    .trim()
    .split(/\r?\n/)
    .find(Boolean);

  if (!firstLine) return undefined;

  const cleaned = normalizePrompt(
    firstLine
      .replace(/^title\s*[:\-]\s*/i, "")
      .replace(/^['"`]+|['"`]+$/g, "")
      .replace(/[.!?;:,]+$/g, ""),
  );

  if (!cleaned) return undefined;
  return truncateTitle(cleaned, 64);
}

async function generateTitleWithLLM(prompt) {
  const apiKey = process.env.OPENCODE_TITLE_API_KEY || process.env.OPENAI_API_KEY;
  if (!apiKey || !prompt) return undefined;

  return bounded(async (signal) => {
    const url = (
      process.env.OPENCODE_TITLE_BASE_URL ||
      "https://api.openai.com/v1/chat/completions"
    ).replace(/\/$/, "");
    const response = await fetch(url, {
      method: "POST",
      signal,
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: process.env.OPENCODE_TITLE_MODEL || "gpt-4.1-mini",
        temperature: 0.2,
        max_tokens: 64,
        messages: [
          {
            role: "system",
            content:
              "Generate a concise conversation title. Return only the title text, 3 to 6 words, no quotes, no markdown, no trailing punctuation.",
          },
          {
            role: "user",
            content: `First user prompt:\n${prompt}`,
          },
        ],
      }),
    });

    if (!response.ok) return undefined;

    const data = await response.json();
    return sanitizeGeneratedTitle(data?.choices?.[0]?.message?.content);
  }, TITLE_TIMEOUT_MS);
}

function shouldReplaceTitle(session) {
  // Match V2's exact root fallback, never broad prefixes that can be custom titles.
  if (session.title === undefined) return true;
  const created = session.time?.created;
  if (typeof created !== "number" || !Number.isFinite(created)) return false;
  return session.title === `New session - ${new Date(created).toISOString()}`;
}

export default {
  id: "first-prompt-title",
  async setup(ctx) {
    await ctx.session.hook("title", async (event) => {
      try {
        const session = await bounded(
          () => ctx.session.get({ sessionID: event.sessionID }),
          LOOKUP_TIMEOUT_MS,
        );
        if (!session) return;
        if (!shouldReplaceTitle(session)) return;

        // Own only initial titles. An empty result skips generation for an
        // empty first prompt; titled sessions retain native regeneration.
        event.result = "";
        // For untitled sessions V2 supplies Message.user(firstUser.text), not
        // synthetic inputs, assistant content, or the latest turn's transcript.
        const firstUser = event.messages.find((message) => message.role === "user");
        const fallbackTitle = deriveTitle(firstUser?.content ?? []);
        if (!fallbackTitle) return;
        event.result = (await generateTitleWithLLM(fallbackTitle)) || fallbackTitle;
        // The host owns persistence and atomically rejects concurrent renames.
      } catch {
        // Title decoration must never fail the user's session operation.
      }
    });
  },
};
