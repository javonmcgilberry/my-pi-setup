import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

import type { SessionFile } from "./scan.ts";

const MAX_METADATA_FILES = 10_000;

interface SessionMetadata {
	schemaVersion: 1;
	sessionId: string;
	title: string;
}

function parseMetadata(value: unknown): SessionMetadata | undefined {
	if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
	const record = value as Record<string, unknown>;
	if (record.schemaVersion !== 1) return undefined;
	if (typeof record.sessionId !== "string" || !record.sessionId.trim()) return undefined;
	if (typeof record.title !== "string" || !record.title.trim()) return undefined;
	return {
		schemaVersion: 1,
		sessionId: record.sessionId,
		title: record.title.replace(/[\r\n]+/g, " ").trim(),
	};
}

export async function readSessionMetadataTitles(agentDir: string): Promise<ReadonlyMap<string, string>> {
	const directory = path.join(agentDir, "session-metadata", "summaries");
	let names: string[];
	try {
		const entries = await readdir(directory);
		names = entries.filter((name) => name.endsWith(".json")).sort((a, b) => a.localeCompare(b));
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return new Map();
		throw error;
	}
	if (names.length > MAX_METADATA_FILES) {
		throw new Error(`Session metadata scan exceeds the ${MAX_METADATA_FILES}-file safety limit`);
	}

	const titles = new Map<string, string>();
	for (const name of names) {
		try {
			const metadata = parseMetadata(JSON.parse(await readFile(path.join(directory, name), "utf8")));
			if (metadata) titles.set(metadata.sessionId, metadata.title);
		} catch {
			// One malformed private sidecar must not take down the spend dashboard.
		}
	}
	return titles;
}

export function overlaySessionMetadataTitles(
	files: readonly SessionFile[],
	titles: ReadonlyMap<string, string>,
): SessionFile[] {
	return files.map((file) => ({ ...file, name: file.name ?? titles.get(file.sessionId) }));
}
