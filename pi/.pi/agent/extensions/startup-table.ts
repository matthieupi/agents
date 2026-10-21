import type { ExtensionAPI, ExtensionContext, Theme } from "@mariozechner/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@mariozechner/pi-tui";
import { homedir } from "node:os";
import { basename, dirname, relative, resolve, sep } from "node:path";
import { access, readFile } from "node:fs/promises";

type ResourceRow = {
	category: string;
	name: string;
	desc: string;
	path: string;
};

type DiagnosticRow = {
	resource: string;
	issue: string;
};

const home = homedir();

function normalizeWhitespace(value: string | undefined): string {
	return (value ?? "").replace(/\s+/g, " ").trim();
}

function stripQuotes(value: string): string {
	const trimmed = value.trim();
	if (
		(trimmed.startsWith('"') && trimmed.endsWith('"')) ||
		(trimmed.startsWith("'") && trimmed.endsWith("'"))
	) {
		return trimmed.slice(1, -1);
	}
	return trimmed;
}

function parseFrontmatter(text: string): Record<string, string> {
	const match = text.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
	if (!match) return {};

	const fields: Record<string, string> = {};
	for (const line of match[1].split(/\r?\n/)) {
		const parsed = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
		if (!parsed) continue;
		fields[parsed[1]!.toLowerCase()] = stripQuotes(parsed[2] ?? "");
	}
	return fields;
}

async function pathExists(path: string): Promise<boolean> {
	try {
		await access(path);
		return true;
	} catch {
		return false;
	}
}

async function readText(path: string): Promise<string> {
	try {
		return await readFile(path, "utf8");
	} catch {
		return "";
	}
}

function inferCategory(filePath: string, rootName: "skills" | "prompts"): string {
	const parts = resolve(filePath).split(sep);
	const idx = parts.lastIndexOf(rootName);
	if (idx === -1) return "";

	const remainder = parts.slice(idx + 1, -1);
	if (remainder.length <= 1) return "";
	return remainder.slice(0, -1).join("/");
}

function displayPath(filePath: string, cwd: string): string {
	const resolved = resolve(filePath);
	if (resolved === cwd) return ".";
	if (resolved.startsWith(`${cwd}${sep}`)) return `./${relative(cwd, resolved)}`;
	if (resolved.startsWith(`${home}${sep}`)) return `~/${relative(home, resolved)}`;
	return resolved;
}

function pad(text: string, width: number): string {
	const fitted = truncateToWidth(text || "—", width, "…");
	const diff = Math.max(0, width - visibleWidth(fitted));
	return fitted + " ".repeat(diff);
}

function sortResources(rows: ResourceRow[]): ResourceRow[] {
	return [...rows].sort((a, b) => `${a.category}\u0000${a.name}`.localeCompare(`${b.category}\u0000${b.name}`));
}

function sortDiagnostics(rows: DiagnosticRow[]): DiagnosticRow[] {
	return [...rows].sort((a, b) => `${a.resource}\u0000${a.issue}`.localeCompare(`${b.resource}\u0000${b.issue}`));
}

async function buildSkillDiagnostics(pi: ExtensionAPI, cwd: string): Promise<DiagnosticRow[]> {
	const rows: DiagnosticRow[] = [];
	const skillPaths = Array.from(
		new Set(
			pi
				.getCommands()
				.filter((command) => command.source === "skill")
				.map((command) => resolve(command.sourceInfo.path)),
		),
	);

	for (const filePath of skillPaths) {
		if (!(await pathExists(filePath))) continue;
		const text = await readText(filePath);
		const frontmatter = parseFrontmatter(text);
		const description = normalizeWhitespace(frontmatter.description);
		if (!description) {
			rows.push({
				resource: displayPath(filePath, cwd),
				issue: "description is required",
			});
		}

		if (basename(filePath).toLowerCase() === "skill.md") {
			const name = normalizeWhitespace(frontmatter.name);
			const parentDir = basename(dirname(filePath));
			if (name && name !== parentDir) {
				rows.push({
					resource: displayPath(filePath, cwd),
					issue: `name \"${name}\" does not match parent directory \"${parentDir}\"`,
				});
			}
		}
	}

	return sortDiagnostics(rows);
}

function buildSkillRows(pi: ExtensionAPI): ResourceRow[] {
	const rows = pi
		.getCommands()
		.filter((command) => command.source === "skill")
		.map((command) => ({
			category: inferCategory(command.sourceInfo.path, "skills"),
			name: command.name.replace(/^skill:/, ""),
			desc: normalizeWhitespace(command.description) || "—",
			path: command.sourceInfo.path,
		}));

	return sortResources(rows);
}

function buildPromptRows(pi: ExtensionAPI): ResourceRow[] {
	const rows = pi
		.getCommands()
		.filter((command) => command.source === "prompt")
		.map((command) => ({
			category: inferCategory(command.sourceInfo.path, "prompts"),
			name: command.name,
			desc: normalizeWhitespace(command.description) || "—",
			path: command.sourceInfo.path,
		}));

	return sortResources(rows);
}

function sectionTitle(theme: Theme, title: string, count: number): string {
	return theme.fg("accent", theme.bold(`[${title}]`)) + theme.fg("dim", ` (${count})`);
}

function renderResourceTable(theme: Theme, width: number, rows: ResourceRow[]): string[] {
	const innerWidth = Math.max(30, width - 2);
	const separators = 6;
	const categoryWidth = 16;
	const nameWidth = 22;
	const descWidth = Math.max(16, innerWidth - separators - categoryWidth - nameWidth);
	const minTotal = separators + categoryWidth + nameWidth + 16;

	if (innerWidth < minTotal) {
		return rows.map((row) => {
			const prefix = row.category ? `${row.category} / ` : "";
			return truncateToWidth(`  ${prefix}${row.name} — ${row.desc}`, width);
		});
	}

	const header = [
		theme.fg("muted", pad("category", categoryWidth)),
		theme.fg("muted", pad("name", nameWidth)),
		theme.fg("muted", pad("description", descWidth)),
	].join(theme.fg("borderMuted", " │ "));

	const divider = theme.fg("borderMuted", truncateToWidth(`  ${"─".repeat(Math.max(0, innerWidth))}`, width));
	const lines = [truncateToWidth(`  ${header}`, width), divider];

	for (const row of rows) {
		const line = [
			theme.fg("muted", pad(row.category || "—", categoryWidth)),
			theme.fg("text", pad(row.name, nameWidth)),
			theme.fg("dim", pad(row.desc || "—", descWidth)),
		].join(theme.fg("borderMuted", " │ "));
		lines.push(truncateToWidth(`  ${line}`, width));
	}

	return lines;
}

function renderDiagnostics(theme: Theme, width: number, rows: DiagnosticRow[]): string[] {
	const lines = [sectionTitle(theme, "Skill diagnostics", rows.length)];
	if (rows.length === 0) {
		lines.push(theme.fg("dim", "  none"));
		return lines;
	}

	const innerWidth = Math.max(30, width - 2);
	const separators = 3;
	const resourceWidth = Math.max(18, Math.floor(innerWidth * 0.48));
	const issueWidth = Math.max(16, innerWidth - separators - resourceWidth);
	const minTotal = separators + resourceWidth + 16;

	if (innerWidth < minTotal) {
		return [
			...lines,
			...rows.map((row) => truncateToWidth(`  ${row.resource} — ${row.issue}`, width)),
		];
	}

	const header = [
		theme.fg("muted", pad("resource", resourceWidth)),
		theme.fg("muted", pad("issue", issueWidth)),
	].join(theme.fg("borderMuted", " │ "));
	const divider = theme.fg("borderMuted", truncateToWidth(`  ${"─".repeat(Math.max(0, innerWidth))}`, width));
	const body = [truncateToWidth(`  ${header}`, width), divider];

	for (const row of rows) {
		const line = [
			theme.fg("text", pad(row.resource, resourceWidth)),
			theme.fg("warning", pad(row.issue, issueWidth)),
		].join(theme.fg("borderMuted", " │ "));
		body.push(truncateToWidth(`  ${line}`, width));
	}

	return [...lines, ...body];
}

function buildHeaderLines(
	theme: Theme,
	width: number,
	skills: ResourceRow[],
	prompts: ResourceRow[],
	diagnostics: DiagnosticRow[],
): string[] {
	const lines: string[] = [];
	lines.push(theme.fg("accent", theme.bold("Pi resources")) + theme.fg("dim", "  category | name | description"));
	lines.push(theme.fg("dim", "Commands: /startup-table-refresh, /startup-table-off, /builtin-header"));
	lines.push("");
	lines.push(sectionTitle(theme, "Skills", skills.length));
	if (skills.length === 0) {
		lines.push(theme.fg("dim", "  none"));
	} else {
		lines.push(...renderResourceTable(theme, width, skills));
	}
	lines.push("");
	lines.push(sectionTitle(theme, "Prompts", prompts.length));
	if (prompts.length === 0) {
		lines.push(theme.fg("dim", "  none"));
	} else {
		lines.push(...renderResourceTable(theme, width, prompts));
	}

	if (diagnostics.length > 0) {
		lines.push("");
		lines.push(...renderDiagnostics(theme, width, diagnostics));
	}

	return lines.map((line) => truncateToWidth(line, width));
}

export default function startupTable(pi: ExtensionAPI) {
	let diagnostics: DiagnosticRow[] = [];

	async function refresh(ctx: ExtensionContext): Promise<void> {
		diagnostics = await buildSkillDiagnostics(pi, ctx.cwd);
	}

	function applyHeader(ctx: ExtensionContext): void {
		if (!ctx.hasUI) return;
		ctx.ui.setHeader((_tui, theme) => ({
			invalidate() {},
			render(width: number): string[] {
				return buildHeaderLines(theme, width, buildSkillRows(pi), buildPromptRows(pi), diagnostics);
			},
		}));
	}

	async function enableHeader(ctx: ExtensionContext, notify = false): Promise<void> {
		await refresh(ctx);
		applyHeader(ctx);
		if (notify && ctx.hasUI) ctx.ui.notify("Startup resource tables refreshed", "info");
	}

	pi.on("session_start", async (_event, ctx) => {
		await enableHeader(ctx);
	});

	pi.registerCommand("startup-table-refresh", {
		description: "Refresh the startup skills and prompts tables",
		handler: async (_args, ctx) => {
			await enableHeader(ctx, true);
		},
	});

	pi.registerCommand("startup-table-on", {
		description: "Enable the startup skills and prompts tables",
		handler: async (_args, ctx) => {
			await enableHeader(ctx, true);
		},
	});

	pi.registerCommand("startup-table-off", {
		description: "Restore the built-in startup header",
		handler: async (_args, ctx) => {
			if (ctx.hasUI) {
				ctx.ui.setHeader(undefined);
				ctx.ui.notify("Built-in header restored", "info");
			}
		},
	});

	pi.registerCommand("builtin-header", {
		description: "Restore the built-in startup header",
		handler: async (_args, ctx) => {
			if (ctx.hasUI) {
				ctx.ui.setHeader(undefined);
				ctx.ui.notify("Built-in header restored", "info");
			}
		},
	});
}
