const DEFAULT_TITLES = new Set([
  "new session",
  "new chat",
  "untitled",
  "untitled session",
  "conversation",
]);

const DEFAULT_TITLE_PREFIXES = [
  /^new session\b/i,
  /^new chat\b/i,
  /^untitled\b/i,
  /^conversation\b/i,
];

const TITLE_MODEL = process.env.OPENCODE_TITLE_MODEL || "gpt-4.1-mini";
const TITLE_BASE_URL = (
  process.env.OPENCODE_TITLE_BASE_URL ||
  "https://api.openai.com/v1/chat/completions"
).replace(/\/$/, "");
const TITLE_API_KEY = process.env.OPENCODE_TITLE_API_KEY || process.env.OPENAI_API_KEY;

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

function deriveTitle(parts) {
  const prompt = normalizePrompt(
    parts
      .filter((part) => part.type === "text" && !part.synthetic && !part.ignored)
      .map((part) => part.text)
      .join(" "),
  );

  if (!prompt) return undefined;

  return truncateTitle(prompt.replace(/[\s.!?;:,]+$/, ""));
}

function sanitizeGeneratedTitle(value) {
  if (!value) return undefined;

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
  if (!TITLE_API_KEY || !prompt) return undefined;

  const response = await fetch(TITLE_BASE_URL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${TITLE_API_KEY}`,
    },
    body: JSON.stringify({
      model: TITLE_MODEL,
      temperature: 0.2,
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
}

function shouldReplaceTitle(title) {
  if (!title) return true;
  const normalized = title.trim().toLowerCase();
  if (DEFAULT_TITLES.has(normalized)) return true;
  return DEFAULT_TITLE_PREFIXES.some((pattern) => pattern.test(title.trim()));
}

export const FirstPromptTitlePlugin = async ({ client, directory }) => {
  return {
    "chat.message": async (input, output) => {
      const fallbackTitle = deriveTitle(output.parts);
      if (!fallbackTitle) return;

      const [sessionResult, messagesResult] = await Promise.all([
        client.session.get({
          path: { id: input.sessionID },
          query: { directory },
        }),
        client.session.messages({
          path: { id: input.sessionID },
          query: { directory },
        }),
      ]);

      const session = sessionResult.data;
      const messages = messagesResult.data;
      const priorUserMessageCount = messages.filter(
        (message) =>
          message.info.role === "user" && message.info.id !== output.message.id,
      ).length;

      if (priorUserMessageCount > 0) return;
      if (!shouldReplaceTitle(session.title)) return;

      const title =
        (await generateTitleWithLLM(fallbackTitle).catch(() => undefined)) ||
        fallbackTitle;

      await client.session.update({
        path: { id: input.sessionID },
        query: { directory },
        body: { title },
      });
    },
  };
};
