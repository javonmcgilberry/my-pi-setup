/**
 * Pure Git-pin planning for `/sync-me publish`.
 *
 * Routine registry packages float and are updated by `pi update --extensions`.
 * This module handles Prewalk's separate publication boundary: its tracked
 * commit moves only after callers prove the replacement checkout's HEAD exists
 * on a remote branch.
 *
 * No Pi imports: this module is plain data in, plain data out, so it is fully
 * testable without a session.
 */

const GIT_PIN = /^(?<locator>git:.+)@(?<ref>[^@]+)$/;

/** Split an exact Git source into its stable locator and ref. */
export function parseGitPin(source) {
	const git = GIT_PIN.exec(source);
	if (!git?.groups) return null;
	return { locator: git.groups.locator, ref: git.groups.ref };
}

/**
 * Propose a Git pin bump toward `headSha`. Callers must confirm that the commit
 * is pushed first; a pin that exists only locally is not installable.
 */
export function planGitPinUpdate(source, headSha) {
	const pin = parseGitPin(source);
	if (!pin || pin.ref === headSha) return null;
	return {
		source,
		next: `${pin.locator}@${headSha}`,
		name: pin.locator.slice("git:".length),
		from: pin.ref,
		to: headSha,
	};
}

/**
 * Rewrite Git pins by exact string replacement so comments, key order, and
 * formatting survive. Refuses ambiguity rather than guessing which pin to edit.
 */
export function applyGitPinUpdates(settingsText, updates) {
	let text = settingsText;
	for (const update of updates) {
		const needle = `"${update.source}"`;
		const first = text.indexOf(needle);
		if (first === -1 || first !== text.lastIndexOf(needle)) {
			throw new Error(
				`Expected ${update.source} exactly once in settings.json`,
			);
		}
		text = `${text.slice(0, first)}"${update.next}"${text.slice(first + needle.length)}`;
	}
	return text;
}
