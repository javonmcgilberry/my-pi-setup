import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { listActiveSessionFiles, registerActiveSession, unregisterActiveSession } from "../active-sessions.ts";

test("registers the current process session and removes it on shutdown", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "active-session-marker-"));
	const session = path.join(root, "sessions", "project", "active.jsonl");
	await registerActiveSession(root, session);
	assert.deepEqual([...await listActiveSessionFiles(root)], [session]);
	await unregisterActiveSession(root);
	assert.deepEqual([...await listActiveSessionFiles(root)], []);
	await rm(root, { recursive: true, force: true });
});

test("fails closed when an active-session marker is unreadable", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "active-session-invalid-"));
	const directory = path.join(root, "session-metrics", "active");
	await mkdir(directory, { recursive: true });
	await writeFile(path.join(directory, "broken.json"), "{ incomplete", "utf8");
	await assert.rejects(listActiveSessionFiles(root), /Unreadable active-session marker/);
	await rm(root, { recursive: true, force: true });
});

test("fails closed when a live marker omits its session file", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "active-session-invalid-schema-"));
	const directory = path.join(root, "session-metrics", "active");
	await mkdir(directory, { recursive: true });
	await writeFile(path.join(directory, "invalid.json"), JSON.stringify({ pid: process.pid }), "utf8");
	await assert.rejects(listActiveSessionFiles(root), /Invalid active-session marker/);
	await rm(root, { recursive: true, force: true });
});

test("startup registers its lease but is blocked by the cleanup gate", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "active-session-gate-"));
	const metrics = path.join(root, "session-metrics");
	await mkdir(metrics, { recursive: true });
	await writeFile(path.join(metrics, "maintenance.lock"), JSON.stringify({ pid: 1 }), "utf8");
	const session = path.join(root, "sessions", "project", "active.jsonl");
	await assert.rejects(registerActiveSession(root, session), /startup is blocked/);
	assert.deepEqual([...await listActiveSessionFiles(root)], [session]);
	await unregisterActiveSession(root);
	await rm(root, { recursive: true, force: true });
});

test("in-memory Pi sessions still block destructive maintenance", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "active-session-memory-"));
	await registerActiveSession(root, undefined);
	assert.equal((await listActiveSessionFiles(root)).size, 1);
	await unregisterActiveSession(root);
	await rm(root, { recursive: true, force: true });
});
