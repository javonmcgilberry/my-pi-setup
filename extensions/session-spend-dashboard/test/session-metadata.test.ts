import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { overlaySessionMetadataTitles, readSessionMetadataTitles } from "../session-metadata.ts";
import type { SessionFile } from "../scan.ts";

function session(sessionId: string, name?: string): SessionFile {
	return {
		file: `/sessions/${sessionId}.jsonl`,
		relPath: `${sessionId}.jsonl`,
		sessionId,
		name,
		cwd: "/project",
		startedAt: 1,
		mtimeMs: 2,
		sizeBytes: 3,
		records: [],
		toolCallKeys: [],
		malformedLines: 0,
		truncated: false,
	};
}

test("uses private sidecar titles only when the session log has no newer title", async () => {
	const agentDir = await mkdtemp(path.join(os.tmpdir(), "session-metadata-"));
	const directory = path.join(agentDir, "session-metadata", "summaries");
	await mkdir(directory, { recursive: true });
	await writeFile(
		path.join(directory, "one.json"),
		JSON.stringify({ schemaVersion: 1, sessionId: "one", title: "Backfilled title", summary: "private" }),
	);
	await writeFile(path.join(directory, "broken.json"), "not json");

	const titles = await readSessionMetadataTitles(agentDir);
	const files = overlaySessionMetadataTitles([session("one"), session("two", "Current title")], titles);
	assert.equal(files[0]?.name, "Backfilled title");
	assert.equal(files[1]?.name, "Current title");
	await rm(agentDir, { recursive: true, force: true });
});
