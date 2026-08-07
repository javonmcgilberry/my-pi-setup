/**
 * Pure pin-planning logic for `/sync-me update`.
 *
 * The tracked `settings.json` in this repository is the only source of truth for
 * package versions. `pi update` and the extension manager write to the live
 * `~/.pi/agent/settings.json`, which `setup.sh` regenerates from this file, so
 * their updates are lost on the next apply. Everything here rewrites the tracked
 * file instead, leaving the apply path untouched.
 *
 * No Pi imports: this module is plain data in, plain data out, so it is fully
 * testable without a session.
 */

const NPM_PIN = /^npm:(?<name>@[^/@]+\/[^/@]+|[^@]+)@(?<version>.+)$/;
const GIT_PIN = /^(?<locator>git:.+)@(?<ref>[^@]+)$/;

/** Split a pinned package source into its parts. Returns null when unpinned. */
export function parsePackagePin(source) {
	const npm = NPM_PIN.exec(source);
	if (npm?.groups) {
		return { kind: "npm", name: npm.groups.name, version: npm.groups.version };
	}
	const git = GIT_PIN.exec(source);
	if (git?.groups) {
		return { kind: "git", locator: git.groups.locator, ref: git.groups.ref };
	}
	return null;
}

export function registryUrl(name) {
	// A scoped name carries a slash that must not read as a path separator.
	return `https://registry.npmjs.org/${name.replace("/", "%2F")}/latest`;
}

function releaseParts(version) {
	const [release, prerelease] = version.split("-", 2);
	return {
		numbers: release.split(".").map((part) => Number.parseInt(part, 10) || 0),
		prerelease,
	};
}

/** Compare two semver-ish versions numerically. A prerelease sorts below its release. */
export function compareVersions(left, right) {
	const a = releaseParts(left);
	const b = releaseParts(right);
	const length = Math.max(a.numbers.length, b.numbers.length);
	for (let index = 0; index < length; index += 1) {
		const difference = (a.numbers[index] ?? 0) - (b.numbers[index] ?? 0);
		if (difference !== 0) return difference < 0 ? -1 : 1;
	}
	if (a.prerelease === b.prerelease) return 0;
	if (a.prerelease === undefined) return 1;
	if (b.prerelease === undefined) return -1;
	return a.prerelease < b.prerelease ? -1 : 1;
}

/** Propose npm pin bumps for packages whose registry version is genuinely newer. */
export function planNpmUpdates(packages, latestByName) {
	const updates = [];
	for (const source of packages) {
		const pin = parsePackagePin(source);
		if (pin?.kind !== "npm") continue;
		const latest = latestByName.get(pin.name);
		if (!latest || compareVersions(latest, pin.version) <= 0) continue;
		updates.push({
			source,
			next: `npm:${pin.name}@${latest}`,
			name: pin.name,
			from: pin.version,
			to: latest,
		});
	}
	return updates;
}

/**
 * Propose a git pin bump toward `headSha`. Callers must confirm that the commit
 * is pushed first; a pin that only exists locally is not installable.
 */
export function planGitPinUpdate(source, headSha) {
	const pin = parsePackagePin(source);
	if (pin?.kind !== "git" || pin.ref === headSha) return null;
	return {
		source,
		next: `${pin.locator}@${headSha}`,
		name: pin.locator.slice("git:".length),
		from: pin.ref,
		to: headSha,
	};
}

/**
 * Rewrite pins by exact string replacement so comments, key order, and
 * formatting survive. Refuses ambiguity rather than guessing which pin to edit.
 */
export function applyPinUpdates(settingsText, updates) {
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
