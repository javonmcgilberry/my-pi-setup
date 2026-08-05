import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdir, mkdtemp, rm, stat, utimes, writeFile } from "node:fs/promises";
import { promisify } from "node:util";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { runMaintenance } from "../maintenance.ts";
import { registerActiveSession, unregisterActiveSession } from "../active-sessions.ts";

const execFileAsync = promisify(execFile);

async function exists(target: string): Promise<boolean> {
	try {
		await stat(target);
		return true;
	} catch {
		return false;
	}
}

test("imports metrics before pruning an eligible transcript", async () => {
	const agentDir = await mkdtemp(path.join(os.tmpdir(), "session-maintenance-"));
	const sessionsRoot = path.join(agentDir, "sessions");
	const project = path.join(sessionsRoot, "--project--");
	await mkdir(project, { recursive: true });
	await writeFile(path.join(agentDir, "session-spend-dashboard.json"), JSON.stringify({ chatRetentionDays: 7, metricsRetentionDays: 365 }));
	const session = path.join(project, "old.jsonl");
	const timestamp = Date.now() - 10 * 24 * 60 * 60 * 1000;
	await writeFile(
		session,
		`${JSON.stringify({ type: "session", version: 3, id: "old", cwd: "/project", timestamp: new Date(timestamp).toISOString() })}\n${JSON.stringify({
			type: "message",
			id: "assistant-entry",
			message: {
				role: "assistant",
				provider: "anthropic",
				model: "claude-test",
				content: [{ type: "toolCall", id: "tool-1", name: "not-stored", arguments: { secret: "not-stored" } }],
				usage: { input: 10, output: 5, cacheRead: 0, cacheWrite: 0, totalTokens: 15, cost: { total: 0.5 } },
				timestamp,
			},
		})}\n`,
		"utf8",
	);
	const old = new Date(timestamp);
	await utimes(session, old, old);
	const databasePath = path.join(agentDir, "session-metrics", "test.sqlite");

	const preview = await runMaintenance({ sessionsRoot, now: Date.now(), dryRun: true, databasePath });
	assert.equal(preview.eligibleTrees, 1);
	assert.equal(preview.removedTrees, 0);
	assert.equal(preview.archivedUsageRecords, 1);
	assert.equal(preview.archivedToolCalls, 1);
	assert.equal(await exists(session), true);

	const applied = await runMaintenance({ sessionsRoot, now: Date.now(), dryRun: false, databasePath });
	assert.equal(applied.removedTrees, 1);
	assert.equal(await exists(session), false);
	assert.equal(applied.archivedUsageRecords, 1);
	assert.equal(applied.archivedToolCalls, 1);
	await rm(agentDir, { recursive: true, force: true });
});

test("refuses destructive cleanup while a Pi session is active", async () => {
	const agentDir = await mkdtemp(path.join(os.tmpdir(), "session-maintenance-active-"));
	const sessionsRoot = path.join(agentDir, "sessions");
	await mkdir(sessionsRoot, { recursive: true });
	await registerActiveSession(agentDir, path.join(sessionsRoot, "active.jsonl"));
	await assert.rejects(
		runMaintenance({ sessionsRoot, dryRun: false, databasePath: path.join(agentDir, "test.sqlite") }),
		/Close every Pi session/,
	);
	await unregisterActiveSession(agentDir);
	await rm(agentDir, { recursive: true, force: true });
});

test("standalone maintenance honors the custom session directory", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "session-maintenance-cli-"));
	const home = path.join(root, "home");
	const agentDir = path.join(home, ".pi", "agent");
	const sessionsRoot = path.join(root, "custom-sessions");
	const project = path.join(sessionsRoot, "--project--");
	await mkdir(project, { recursive: true });
	await mkdir(agentDir, { recursive: true });
	await writeFile(path.join(project, "one.jsonl"), `${JSON.stringify({ type: "session", id: "one", cwd: "/project", timestamp: new Date().toISOString() })}\n`);
	const script = path.resolve(import.meta.dirname, "../../../scripts/session-maintenance.mjs");
	const env = { ...process.env, HOME: home, PI_CODING_AGENT_SESSION_DIR: sessionsRoot };
	delete env.PI_AGENT_DIR;
	delete env.PI_CODING_AGENT_DIR;
	const { stdout } = await execFileAsync(process.execPath, [script], {
		env,
	});
	assert.equal(JSON.parse(stdout).scannedSessions, 1);
	assert.equal(await exists(path.join(agentDir, "session-metrics", "metrics.sqlite")), true);
	await rm(root, { recursive: true, force: true });
});

test("refuses cleanup when scanner limits omit or truncate a transcript", async () => {
	const agentDir = await mkdtemp(path.join(os.tmpdir(), "session-maintenance-limits-"));
	const sessionsRoot = path.join(agentDir, "sessions");
	const project = path.join(sessionsRoot, "--project--");
	await mkdir(project, { recursive: true });
	for (const name of ["one.jsonl", "two.jsonl"]) {
		await writeFile(path.join(project, name), `${JSON.stringify({ type: "session", id: name, cwd: "/project", timestamp: new Date().toISOString() })}\n`);
	}
	await assert.rejects(
		runMaintenance({
			sessionsRoot,
			dryRun: false,
			databasePath: path.join(agentDir, "limit.sqlite"),
			scanLimits: { maxFiles: 1, maxBytesPerFile: 1024 },
		}),
		/coverage is incomplete/,
	);
	await assert.rejects(
		runMaintenance({
			sessionsRoot,
			dryRun: false,
			databasePath: path.join(agentDir, "truncated.sqlite"),
			scanLimits: { maxFiles: 10, maxBytesPerFile: 1 },
		}),
		/coverage is incomplete/,
	);
	await rm(agentDir, { recursive: true, force: true });
});
