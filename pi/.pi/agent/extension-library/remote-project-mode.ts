/** Canonical session-branch mode parser; deliberately has no SDK/package imports.
 * Browser builds may copy this file verbatim. Keep semantics aligned with the
 * managed pi-ssh-remote restore path, including unmigrated legacy records.
 */
export function remoteProjectMode(entries: readonly unknown[]): 'local'|'remote' {
	for (let i = entries.length - 1; i >= 0; i--) {
		const entry = entries[i] as any;
		if (entry?.type !== "custom") continue;
		if (entry.customType === "pi-ssh-remote-state") return "remote";
		if (entry.customType !== "pi-ssh-remote-project") continue;
		const saved = entry.data;
		return saved?.version === 1 && saved.local === true && saved.projectRef === null
			? "local" : "remote";
	}
	return "local";
}

/** Call synchronously at the local launch boundary, after any UI awaits.
 * operation must be a static source label, never prompt/branch/user content.
 * No mode cache: forks, resumes and explicit Local use the current branch.
 */
export function requireLocalProjectExecution(ctx: any, operation: string): void {
	let mode: 'local'|'remote';
	try {
		const entries = ctx.sessionManager.getBranch();
		if (!Array.isArray(entries)) throw new Error();
		mode = remoteProjectMode(entries);
	} catch {
		const message = `${operation}: cannot verify session project mode; local execution blocked.`;
		ctx?.ui?.notify?.(message, "error");
		throw new Error(message);
	}
	if (mode === "remote") {
		const message = `${operation}: local child execution is unsupported in managed remote mode. Select Local explicitly to run locally.`;
		ctx?.ui?.notify?.(message, "error");
		throw new Error(message);
	}
}
