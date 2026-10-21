import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";

const POLL_INTERVAL_MS = 1000;
const MAX_POLLS = 300;
const MAX_TITLE_LENGTH = 72;

function normalizeWhitespace(value: string): string {
	return value.replace(/\s+/g, " ").trim();
}

function truncateTitle(value: string, maxLength = MAX_TITLE_LENGTH): string {
	if (value.length <= maxLength) return value;

	const truncated = value.slice(0, maxLength + 1);
	const lastSpace = truncated.lastIndexOf(" ");
	const safe = lastSpace >= Math.floor(maxLength * 0.6)
		? truncated.slice(0, lastSpace)
		: truncated.slice(0, maxLength);

	return `${safe.trimEnd()}...`;
}

function extractTextContent(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";

	return content
		.map((part) => {
			if (!part || typeof part !== "object") return "";
			const candidate = part as { type?: string; text?: unknown };
			return candidate.type === "text" && typeof candidate.text === "string"
				? candidate.text
				: "";
		})
		.filter(Boolean)
		.join(" ");
}

function deriveFirstPromptTitle(ctx: ExtensionContext): string | undefined {
	for (const entry of ctx.sessionManager.getBranch()) {
		if (entry.type !== "message") continue;

		const message = entry.message;
		if (!message || message.role !== "user") continue;

		const text = normalizeWhitespace(extractTextContent(message.content));
		if (!text) continue;

		return truncateTitle(text.replace(/[\s.!?;:,]+$/, ""));
	}

	return undefined;
}

function startTitleWatcher(ctx: ExtensionContext): void {
	if (!ctx.hasUI) return;

	let polls = 0;
	let timer: ReturnType<typeof setInterval> | undefined;
	const tick = (): boolean => {
		polls += 1;

		const title = deriveFirstPromptTitle(ctx);
		if (title) {
			ctx.ui.setTitle(`π - ${title}`);
			if (timer) clearInterval(timer);
			return true;
		}

		if (polls >= MAX_POLLS) {
			if (timer) clearInterval(timer);
		}

		return false;
	};

	if (tick()) return;
	timer = setInterval(tick, POLL_INTERVAL_MS);
}

export default function firstPromptTitle(pi: ExtensionAPI): void {
	pi.on("session_start", async (_event, ctx) => {
		startTitleWatcher(ctx);
	});
}
