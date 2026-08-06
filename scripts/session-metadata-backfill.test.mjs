import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { applyBackfill, prepareBackfill } from "./session-metadata-backfill.mjs";

test("prepares redacted dialogue and applies stable private metadata to inactive sessions", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "session-backfill-test-"));
	const agentDir = path.join(root, "agent");
	const sessionsRoot = path.join(agentDir, "sessions");
	const project = path.join(sessionsRoot, "--project--");
	const output = path.join(root, "prepared");
	await mkdir(project, { recursive: true });
	const sessionFile = path.join(project, "one.jsonl");
	await writeFile(
		sessionFile,
		`${[
			JSON.stringify({ type: "session", id: "one", cwd: "/project", timestamp: "2026-01-01T00:00:00.000Z" }),
			JSON.stringify({ type: "message", id: "u1", message: { role: "user", content: "Fix auth TOKEN=very-secret-value" } }),
			JSON.stringify({ type: "message", id: "a1", message: { role: "assistant", content: [{ type: "text", text: "Implemented auth checks" }, { type: "toolCall", id: "call", name: "private", arguments: { secret: "do-not-copy" } }] } }),
		].join("\n")}\n`,
	);

	const prepared = await prepareBackfill({ agentDir, sessionsRoot, output });
	assert.equal(prepared.manifest.items.length, 1);
	const transcript = await readFile(prepared.manifest.items[0].transcriptFile, "utf8");
	assert.match(transcript, /TOKEN=\[REDACTED\]/);
	assert.doesNotMatch(transcript, /very-secret-value|do-not-copy|toolCall/);

	const resultsFile = path.join(root, "results.json");
	await writeFile(resultsFile, JSON.stringify({ sessions: [{ sessionId: "one", title: "Fix Authentication", summary: "Implemented and verified authentication checks." }] }));
	const result = await applyBackfill({ manifestFile: prepared.manifestFile, resultsFile });
	assert.deepEqual(result, { applied: ["one"], skipped: [] });

	const updated = (await readFile(sessionFile, "utf8")).trim().split("\n").map(JSON.parse);
	assert.equal(updated.at(-2).type, "session_info");
	assert.equal(updated.at(-2).name, "Fix Authentication");
	assert.equal(updated.at(-1).customType, "pi-autoname-state");
	assert.equal(updated.at(-1).data.event, "user_rename");
	const metadata = JSON.parse(await readFile(path.join(agentDir, "session-metadata", "summaries", "one.json"), "utf8"));
	assert.equal(metadata.title, "Fix Authentication");
	assert.equal(metadata.summary, "Implemented and verified authentication checks.");
	await rm(root, { recursive: true, force: true });
});

test("skips a session that changed after preparation", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "session-backfill-race-"));
	const agentDir = path.join(root, "agent");
	const sessionsRoot = path.join(agentDir, "sessions");
	const project = path.join(sessionsRoot, "--project--");
	await mkdir(project, { recursive: true });
	const sessionFile = path.join(project, "one.jsonl");
	await writeFile(sessionFile, `${JSON.stringify({ type: "session", id: "one", cwd: "/project" })}\n${JSON.stringify({ type: "message", id: "u1", message: { role: "user", content: "hello" } })}\n`);
	const prepared = await prepareBackfill({ agentDir, sessionsRoot, output: path.join(root, "prepared") });
	await writeFile(sessionFile, `${await readFile(sessionFile, "utf8")}${JSON.stringify({ type: "message", id: "u2", message: { role: "user", content: "changed" } })}\n`);
	const resultsFile = path.join(root, "results.json");
	await writeFile(resultsFile, JSON.stringify([{ sessionId: "one", title: "Greeting Session", summary: "A short greeting conversation that later changed." }]));
	const result = await applyBackfill({ manifestFile: prepared.manifestFile, resultsFile });
	assert.deepEqual(result.applied, []);
	assert.deepEqual(result.skipped, [{ sessionId: "one", reason: "changed" }]);
	await rm(root, { recursive: true, force: true });
});
