import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { test } from "node:test";

import { aggregate } from "../aggregate.ts";
import { MetricsLedger } from "../ledger.ts";
import { SessionScanner } from "../scan.ts";

const PRIVATE_TEXT = "do-not-store-this-private-prompt";
const PRIVATE_NAME = "do-not-store-this-private-session-name";

function header(id: string, startedAt: number): string {
	return JSON.stringify({ type: "session", version: 3, id, cwd: "/project/example", timestamp: new Date(startedAt).toISOString() });
}

function assistant(id: string, timestamp: number, cost: number, toolCallId?: string): string {
	return JSON.stringify({
		type: "message",
		id,
		timestamp: new Date(timestamp).toISOString(),
		message: {
			role: "assistant",
			provider: "anthropic",
			model: "claude-test",
			content: toolCallId
				? [{ type: "text", text: PRIVATE_TEXT }, { type: "toolCall", id: toolCallId, name: "private-tool", arguments: { prompt: PRIVATE_TEXT } }]
				: [{ type: "text", text: PRIVATE_TEXT }],
			usage: {
				input: 100,
				output: 20,
				cacheRead: 5,
				cacheWrite: 2,
				reasoning: 3,
				totalTokens: 127,
				cost: { total: cost },
			},
			timestamp,
		},
	});
}

test("keeps deduplicated usage and tool counts after source transcripts are deleted", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "spend-ledger-"));
	const sessionsRoot = path.join(root, "sessions");
	const project = path.join(sessionsRoot, "--project-example--");
	await mkdir(project, { recursive: true });
	const started = Date.now() - 60_000;
	const shared = assistant("shared", started + 1, 0.75, "tool-call-shared");
	const origin = path.join(project, "2026-01-01T00-00-00-000Z_origin.jsonl");
	const fork = path.join(project, "2026-01-02T00-00-00-000Z_fork.jsonl");
	await writeFile(origin, `${header("origin", started)}\n${JSON.stringify({ type: "session_info", name: PRIVATE_NAME })}\n${shared}\n`, "utf8");
	await writeFile(fork, `${header("fork", started + 1000)}\n${shared}\n${assistant("new", started + 1001, 0.25, "tool-call-new")}\n`, "utf8");

	const liveFiles = await new SessionScanner(sessionsRoot).scan();
	const databasePath = path.join(root, "metrics.sqlite");
	const ledger = new MetricsLedger(databasePath);
	const first = ledger.ingest(liveFiles);
	assert.equal(first.usageRecords, 2);
	assert.equal(first.toolCalls, 2);
	assert.equal(ledger.ingest(liveFiles).usageRecords, 0);

	const before = aggregate(ledger.readSessions(), { sessionsRoot, now: Date.now(), scanDurationMs: 1 });
	assert.equal(before.totals.cost, 1);
	assert.equal(before.totals.calls, 2);
	assert.equal(before.totals.toolCalls, 2);
	assert.equal(before.sessions.find((session) => session.sessionId === "fork")?.inheritedCost, 0.75);

	await rm(sessionsRoot, { recursive: true, force: true });
	const after = aggregate(ledger.readSessions(), { sessionsRoot, now: Date.now(), scanDurationMs: 1 });
	assert.equal(after.totals.cost, before.totals.cost);
	assert.equal(after.totals.totalTokens, before.totals.totalTokens);
	assert.equal(after.totals.toolCalls, before.totals.toolCalls);
	ledger.close();

	const bytes = await readFile(databasePath);
	assert.equal(bytes.includes(Buffer.from(PRIVATE_TEXT)), false);
	assert.equal(bytes.includes(Buffer.from("private-tool")), false);
	assert.equal(bytes.includes(Buffer.from(PRIVATE_NAME)), false);
	await rm(root, { recursive: true, force: true });
});

test("expires content-free metrics by their session update time", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "spend-ledger-retention-"));
	const sessionsRoot = path.join(root, "sessions");
	const project = path.join(sessionsRoot, "--project--");
	await mkdir(project, { recursive: true });
	const old = Date.now() - 400 * 24 * 60 * 60 * 1000;
	const file = path.join(project, "old.jsonl");
	await writeFile(file, `${header("old", old)}\n${assistant("old-call", old + 1, 1)}\n`, "utf8");
	const files = await new SessionScanner(sessionsRoot).scan();
	files[0]!.mtimeMs = old + 1;
	const ledger = new MetricsLedger(path.join(root, "metrics.sqlite"));
	ledger.ingest(files);
	assert.equal(ledger.pruneMetricsBefore(Date.now() - 365 * 24 * 60 * 60 * 1000), 1);
	assert.equal(ledger.readSessions().length, 0);
	ledger.close();
	await rm(root, { recursive: true, force: true });
});

test("migrates the version-one ledger and preserves canonical usage", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "spend-ledger-v1-"));
	const databasePath = path.join(root, "metrics.sqlite");
	const legacy = new DatabaseSync(databasePath);
	legacy.exec(`
		CREATE TABLE source_files (
			rel_path TEXT PRIMARY KEY, file_path TEXT NOT NULL, session_id TEXT NOT NULL,
			name TEXT, cwd TEXT NOT NULL, started_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
			mtime_ms INTEGER NOT NULL, size_bytes INTEGER NOT NULL, parent_session_id TEXT,
			malformed_lines INTEGER NOT NULL, truncated INTEGER NOT NULL
		);
		CREATE TABLE usage_records (
			dedupe_key TEXT PRIMARY KEY, origin_rel_path TEXT NOT NULL REFERENCES source_files(rel_path) ON DELETE CASCADE,
			timestamp INTEGER NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, usage_type TEXT NOT NULL,
			input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cache_read_tokens INTEGER NOT NULL,
			cache_write_tokens INTEGER NOT NULL, reasoning_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL,
			cost REAL NOT NULL, cost_reported INTEGER NOT NULL
		);
		CREATE TABLE tool_calls (
			dedupe_key TEXT PRIMARY KEY, origin_rel_path TEXT NOT NULL REFERENCES source_files(rel_path) ON DELETE CASCADE
		);
		INSERT INTO source_files VALUES ('project/old.jsonl', '/tmp/old.jsonl', 'old', NULL, '/project', 1, 2, 2, 3, NULL, 0, 0);
		INSERT INTO usage_records VALUES ('usage-1', 'project/old.jsonl', 2, 'provider', 'model', 'assistant', 1, 2, 3, 4, 5, 15, 0.25, 1);
		INSERT INTO tool_calls VALUES ('tool-1', 'project/old.jsonl');
		PRAGMA user_version = 1;
	`);
	legacy.close();

	const ledger = new MetricsLedger(databasePath);
	const sessions = ledger.readSessions();
	assert.equal(sessions.length, 1);
	assert.equal(sessions[0]?.records[0]?.cost, 0.25);
	assert.deepEqual(sessions[0]?.toolCallKeys, ["tool-1"]);
	ledger.close();
	await rm(root, { recursive: true, force: true });
});

test("reassigns canonical records before an older origin session expires", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "spend-ledger-origin-"));
	const sessionsRoot = path.join(root, "sessions");
	const project = path.join(sessionsRoot, "--project--");
	await mkdir(project, { recursive: true });
	const now = Date.now();
	const old = now - 400 * 24 * 60 * 60 * 1000;
	const shared = assistant("shared-old", old, 0.5, "shared-tool");
	const origin = path.join(project, "origin.jsonl");
	const fork = path.join(project, "fork.jsonl");
	await writeFile(origin, `${header("origin", old)}\n${shared}\n`, "utf8");
	await writeFile(fork, `${header("fork", now - 1000)}\n${shared}\n${assistant("new", now - 500, 0.25)}\n`, "utf8");
	const files = await new SessionScanner(sessionsRoot).scan();
	files.find((file) => file.sessionId === "origin")!.mtimeMs = old;
	const ledger = new MetricsLedger(path.join(root, "metrics.sqlite"));
	ledger.ingest(files);
	assert.equal(ledger.pruneMetricsBefore(now - 365 * 24 * 60 * 60 * 1000), 1);
	const remaining = aggregate(ledger.readSessions(), { sessionsRoot, now, scanDurationMs: 1 });
	assert.equal(remaining.totals.cost, 0.75);
	assert.equal(remaining.totals.toolCalls, 1);
	assert.equal(remaining.sessions.length, 1);
	ledger.close();
	await rm(root, { recursive: true, force: true });
});
