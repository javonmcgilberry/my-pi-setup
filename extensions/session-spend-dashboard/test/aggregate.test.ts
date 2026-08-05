import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";

import { aggregate } from "../aggregate.ts";
import { emptyRunSnapshot, type RunSnapshot } from "../runs.ts";
import { SessionScanner, parseSessionFile } from "../scan.ts";

let root = "";

function usage(cost: number, tokens = 100) {
	return {
		input: tokens,
		output: 10,
		cacheRead: 5,
		cacheWrite: 1,
		reasoning: 2,
		totalTokens: tokens + 16,
		cost: { input: cost, output: 0, cacheRead: 0, cacheWrite: 0, total: cost },
	};
}

function assistant(id: string, cost: number, opts: { model?: string; provider?: string; timestamp?: number } = {}) {
	return JSON.stringify({
		type: "message",
		id,
		timestamp: new Date(opts.timestamp ?? 1_700_000_000_000).toISOString(),
		message: {
			role: "assistant",
			provider: opts.provider ?? "anthropic",
			model: opts.model ?? "claude-x",
			usage: usage(cost),
			stopReason: "stop",
			timestamp: opts.timestamp ?? 1_700_000_000_000,
		},
	});
}

function header(id: string, cwd: string, startedAt: number) {
	return JSON.stringify({ type: "session", version: 3, id, cwd, timestamp: new Date(startedAt).toISOString() });
}

async function writeSession(relPath: string, lines: string[]) {
	const full = path.join(root, relPath);
	await mkdir(path.dirname(full), { recursive: true });
	await writeFile(full, `${lines.join("\n")}\n`, "utf8");
	return full;
}

before(async () => {
	root = await mkdtemp(path.join(os.tmpdir(), "spend-dash-test-"));
});

after(async () => {
	await rm(root, { recursive: true, force: true });
});

test("parses assistant usage and preserves provider-reported cost", async () => {
	const file = await writeSession("--proj-a--/2024-01-01T00-00-00-000Z_s1.jsonl", [
		header("s1", "/proj/a", 1_700_000_000_000),
		assistant("e1", 0.25),
		assistant("e2", 0.5),
	]);

	const parsed = await parseSessionFile(file);
	assert.equal(parsed.sessionId, "s1");
	assert.equal(parsed.cwd, "/proj/a");
	assert.equal(parsed.records.length, 2);
	assert.equal(parsed.records[0]?.cost, 0.25);
	assert.equal(parsed.records[0]?.costReported, true);
	assert.equal(parsed.records[0]?.model, "claude-x");
	assert.equal(parsed.malformedLines, 0);
});

test("tolerates malformed, blank, and non-object lines without losing valid records", async () => {
	const file = await writeSession("--proj-b--/2024-01-01T00-00-00-000Z_s2.jsonl", [
		header("s2", "/proj/b", 1_700_000_000_000),
		"{ not json",
		"",
		"   ",
		"[1,2,3]",
		'"a string"',
		assistant("e3", 1.5),
		'{"type":"message","id":"e4","message":{"role":"assistant"}}',
	]);

	const parsed = await parseSessionFile(file);
	assert.equal(parsed.records.length, 1);
	assert.equal(parsed.records[0]?.cost, 1.5);
	assert.equal(parsed.malformedLines, 3);
});

test("never invents a price when cost is absent", async () => {
	const file = await writeSession("--proj-c--/2024-01-01T00-00-00-000Z_s3.jsonl", [
		header("s3", "/proj/c", 1_700_000_000_000),
		'{"type":"message","id":"e5","message":{"role":"assistant","model":"m","provider":"p","usage":{"input":10,"output":2,"totalTokens":12}}}',
	]);

	const parsed = await parseSessionFile(file);
	assert.equal(parsed.records.length, 1);
	assert.equal(parsed.records[0]?.cost, 0);
	assert.equal(parsed.records[0]?.costReported, false);
	assert.equal(parsed.records[0]?.totalTokens, 12);
});

test("ignores toolResult usage that restates nested subagent spend", async () => {
	const file = await writeSession("--proj-d--/2024-01-01T00-00-00-000Z_s4.jsonl", [
		header("s4", "/proj/d", 1_700_000_000_000),
		assistant("e6", 1),
		JSON.stringify({
			type: "message",
			id: "e7",
			message: { role: "toolResult", toolName: "subagent", toolCallId: "t1", isError: false, content: [], usage: usage(99) },
		}),
	]);

	const parsed = await parseSessionFile(file);
	assert.equal(parsed.records.length, 1);
	assert.equal(parsed.records[0]?.cost, 1);
});

test("counts compaction and branch_summary usage", async () => {
	const file = await writeSession("--proj-e--/2024-01-01T00-00-00-000Z_s5.jsonl", [
		header("s5", "/proj/e", 1_700_000_000_000),
		JSON.stringify({ type: "compaction", id: "c1", timestamp: "2024-01-01T00:00:00.000Z", summary: "s", usage: usage(2) }),
		JSON.stringify({ type: "branch_summary", id: "b1", timestamp: "2024-01-01T00:00:00.000Z", summary: "s", usage: usage(3) }),
		JSON.stringify({ type: "compaction", id: "c2", timestamp: "2024-01-01T00:00:00.000Z", summary: "no usage" }),
	]);

	const parsed = await parseSessionFile(file);
	assert.equal(parsed.records.length, 2);
	assert.equal(parsed.records.reduce((sum, r) => sum + r.cost, 0), 5);
});

test("attributes a replayed call to the earliest session and reports the rest as inherited", async () => {
	const scanRoot = await mkdtemp(path.join(os.tmpdir(), "spend-dash-fork-"));
	const shared = assistant("shared", 4, { timestamp: 1_700_000_100_000 });
	await writeFile(
		path.join(await mkdirp(scanRoot, "--proj-f--"), "2024-01-01T00-00-00-000Z_origin.jsonl"),
		`${[header("origin", "/proj/f", 1_700_000_000_000), shared].join("\n")}\n`,
		"utf8",
	);
	await writeFile(
		path.join(await mkdirp(scanRoot, "--proj-f--"), "2024-01-02T00-00-00-000Z_fork.jsonl"),
		`${[header("fork", "/proj/f", 1_700_000_500_000), shared, assistant("newwork", 1, { timestamp: 1_700_000_600_000 })].join("\n")}\n`,
		"utf8",
	);

	const files = await new SessionScanner(scanRoot).scan();
	const snapshot = aggregate(files, { sessionsRoot: scanRoot, now: 1_700_000_700_000, scanDurationMs: 1 });

	assert.equal(snapshot.totals.cost, 5);
	const origin = snapshot.sessions.find((s) => s.sessionId === "origin");
	const fork = snapshot.sessions.find((s) => s.sessionId === "fork");
	assert.equal(origin?.cost, 4);
	assert.equal(origin?.inheritedCost, 0);
	assert.equal(fork?.cost, 1);
	assert.equal(fork?.inheritedCost, 4);

	await rm(scanRoot, { recursive: true, force: true });
});

test("every rollup sums to the same grand total", async () => {
	const scanRoot = await mkdtemp(path.join(os.tmpdir(), "spend-dash-rollup-"));
	await writeFile(
		path.join(await mkdirp(scanRoot, "--proj-g--"), "2024-01-01T00-00-00-000Z_g1.jsonl"),
		`${[
			header("g1", "/proj/g", 1_700_000_000_000),
			assistant("g-a", 1.25, { model: "m1", provider: "p1", timestamp: 1_700_000_000_000 }),
			assistant("g-b", 2.5, { model: "m2", provider: "p2", timestamp: 1_700_200_000_000 }),
		].join("\n")}\n`,
		"utf8",
	);
	await writeFile(
		path.join(await mkdirp(scanRoot, "--proj-h--"), "2024-01-01T00-00-00-000Z_h1.jsonl"),
		`${[header("h1", "/proj/h", 1_700_000_000_000), assistant("h-a", 0.75, { model: "m1", provider: "p1" })].join("\n")}\n`,
		"utf8",
	);

	const files = await new SessionScanner(scanRoot).scan();
	const snapshot = aggregate(files, { sessionsRoot: scanRoot, now: 1_700_300_000_000, scanDurationMs: 1 });
	const round = (n: number) => Math.round(n * 1e6) / 1e6;

	assert.equal(round(snapshot.totals.cost), 4.5);
	assert.equal(round(snapshot.byProject.reduce((a, b) => a + b.cost, 0)), 4.5);
	assert.equal(round(snapshot.byModel.reduce((a, b) => a + b.cost, 0)), 4.5);
	assert.equal(round(snapshot.byProvider.reduce((a, b) => a + b.cost, 0)), 4.5);
	assert.equal(round(snapshot.byDay.reduce((a, b) => a + b.cost, 0)), 4.5);
	assert.equal(snapshot.totals.projects, 2);
	assert.equal(snapshot.byDay.length, 2);

	await rm(scanRoot, { recursive: true, force: true });
});

test("marks nested run files as subagent sessions of their parent", async () => {
	const scanRoot = await mkdtemp(path.join(os.tmpdir(), "spend-dash-nested-"));
	const nested = await mkdirp(scanRoot, "--proj-i--/2024-01-01T00-00-00-000Z_parent/abc123/run-0");
	await writeFile(
		path.join(await mkdirp(scanRoot, "--proj-i--"), "2024-01-01T00-00-00-000Z_parent.jsonl"),
		`${[header("parent", "/proj/i", 1_700_000_000_000), assistant("p-a", 1)].join("\n")}\n`,
		"utf8",
	);
	await writeFile(
		path.join(nested, "session.jsonl"),
		`${[header("child", "/proj/i", 1_700_000_100_000), assistant("c-a", 2)].join("\n")}\n`,
		"utf8",
	);

	const files = await new SessionScanner(scanRoot).scan();
	const snapshot = aggregate(files, { sessionsRoot: scanRoot, now: 1_700_000_200_000, scanDurationMs: 1 });
	const child = snapshot.sessions.find((s) => s.sessionId === "child");
	const parent = snapshot.sessions.find((s) => s.sessionId === "parent");

	assert.equal(child?.isSubagent, true);
	assert.equal(child?.parentSessionId, "parent");
	assert.equal(parent?.isSubagent, false);
	assert.equal(snapshot.totals.cost, 3);

	await rm(scanRoot, { recursive: true, force: true });
});

test("derives activity from write age and promotes sessions with a running subagent run", async () => {
	const scanRoot = await mkdtemp(path.join(os.tmpdir(), "spend-dash-activity-"));
	const file = path.join(await mkdirp(scanRoot, "--proj-j--"), "2024-01-01T00-00-00-000Z_j1.jsonl");
	await writeFile(file, `${[header("j1", "/proj/j", 1_700_000_000_000), assistant("j-a", 1)].join("\n")}\n`, "utf8");

	const files = await new SessionScanner(scanRoot).scan();
	const stale = files[0]?.mtimeMs ?? 0;

	const dormant = aggregate(files, { sessionsRoot: scanRoot, now: stale + 48 * 3600_000, scanDurationMs: 1 });
	assert.equal(dormant.sessions[0]?.activity, "dormant");

	const idle = aggregate(files, { sessionsRoot: scanRoot, now: stale + 3600_000, scanDurationMs: 1 });
	assert.equal(idle.sessions[0]?.activity, "idle");

	const active = aggregate(files, { sessionsRoot: scanRoot, now: stale + 1000, scanDurationMs: 1 });
	assert.equal(active.sessions[0]?.activity, "active");

	const runs: RunSnapshot = {
		available: true,
		activeRuns: 1,
		bySessionFile: new Map([[file, { runId: "r1", state: "running", agent: "worker", currentTool: "read" }]]),
	};
	const live = aggregate(files, { sessionsRoot: scanRoot, now: stale + 48 * 3600_000, scanDurationMs: 1, runs });
	assert.equal(live.sessions[0]?.activity, "live");
	assert.equal(live.sessions[0]?.runAgent, "worker");
	assert.equal(live.runs.activeRuns, 1);

	await rm(scanRoot, { recursive: true, force: true });
});

test("degrades cleanly when no subagent run artifacts exist", () => {
	const snapshot = aggregate([], { sessionsRoot: root, now: 1, scanDurationMs: 0, runs: emptyRunSnapshot() });
	assert.equal(snapshot.runs.available, false);
	assert.equal(snapshot.totals.cost, 0);
	assert.equal(snapshot.sessions.length, 0);
	assert.deepEqual(snapshot.byModel, []);
});

test("reuses cached parses until a session file changes", async () => {
	const scanRoot = await mkdtemp(path.join(os.tmpdir(), "spend-dash-cache-"));
	const file = path.join(await mkdirp(scanRoot, "--proj-k--"), "2024-01-01T00-00-00-000Z_k1.jsonl");
	await writeFile(file, `${[header("k1", "/proj/k", 1_700_000_000_000), assistant("k-a", 1)].join("\n")}\n`, "utf8");

	const scanner = new SessionScanner(scanRoot);
	const first = await scanner.scan();
	assert.equal(first[0]?.records.length, 1);
	assert.equal(scanner.cachedFileCount, 1);

	const second = await scanner.scan();
	assert.equal(second[0]?.records, first[0]?.records);

	await writeFile(file, `${[header("k1", "/proj/k", 1_700_000_000_000), assistant("k-a", 1), assistant("k-b", 2)].join("\n")}\n`, "utf8");
	const third = await scanner.scan();
	assert.equal(third[0]?.records.length, 2);

	await rm(file, { force: true });
	const fourth = await scanner.scan();
	assert.equal(fourth.length, 0);
	assert.equal(scanner.cachedFileCount, 0);

	await rm(scanRoot, { recursive: true, force: true });
});

async function mkdirp(base: string, rel: string): Promise<string> {
	const full = path.join(base, rel);
	await mkdir(full, { recursive: true });
	return full;
}
