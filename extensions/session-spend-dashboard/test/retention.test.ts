import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, stat, utimes, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { planSessionPrune, pruneSessionTrees, withMaintenanceLock } from "../retention.ts";

async function exists(target: string): Promise<boolean> {
	try {
		await stat(target);
		return true;
	} catch {
		return false;
	}
}

test("prunes a root and all nested children only when the whole tree is old", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "session-retention-"));
	const project = path.join(root, "--project--");
	await mkdir(project, { recursive: true });
	const rootFile = path.join(project, "session-a.jsonl");
	const childDirectory = path.join(project, "session-a", "child", "run-0");
	const childFile = path.join(childDirectory, "session.jsonl");
	await mkdir(childDirectory, { recursive: true });
	await writeFile(rootFile, "root\n");
	await writeFile(childFile, "child\n");
	const old = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000);
	await utimes(rootFile, old, old);
	await utimes(childFile, old, old);

	const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
	const plan = await planSessionPrune(root, cutoff);
	assert.equal(plan.eligible.length, 1);
	assert.equal(plan.eligible[0]?.files, 2);
	const removed = await pruneSessionTrees(root, cutoff);
	assert.equal(removed.length, 1);
	assert.equal(await exists(rootFile), false);
	assert.equal(await exists(path.join(project, "session-a")), false);
	await rm(root, { recursive: true, force: true });
});

test("protects active trees and trees with a recently changed child", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "session-retention-active-"));
	const project = path.join(root, "--project--");
	const companion = path.join(project, "session-b", "child");
	await mkdir(companion, { recursive: true });
	const rootFile = path.join(project, "session-b.jsonl");
	const childFile = path.join(companion, "session.jsonl");
	await writeFile(rootFile, "root\n");
	await writeFile(childFile, "child\n");
	const old = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000);
	await utimes(rootFile, old, old);
	await utimes(childFile, old, old);
	const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;

	const active = await planSessionPrune(root, cutoff, new Set([childFile]));
	assert.equal(active.eligible.length, 0);
	assert.equal(active.protected.length, 1);

	await utimes(childFile, new Date(), new Date());
	const recent = await planSessionPrune(root, cutoff);
	assert.equal(recent.eligible.length, 0);
	await rm(root, { recursive: true, force: true });
});

test("maintenance lock rejects overlapping work", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "session-retention-lock-"));
	await withMaintenanceLock(root, async () => {
		await assert.rejects(withMaintenanceLock(root, async () => undefined), /lock already exists/);
	});
	await rm(root, { recursive: true, force: true });
});

test("rechecks active sessions immediately before each tree deletion", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "session-retention-race-"));
	const project = path.join(root, "--project--");
	await mkdir(project, { recursive: true });
	const rootFile = path.join(project, "session-race.jsonl");
	await writeFile(rootFile, "root\n");
	const old = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000);
	await utimes(rootFile, old, old);
	let checks = 0;
	const removed = await pruneSessionTrees(
		root,
		Date.now() - 7 * 24 * 60 * 60 * 1000,
		new Set(),
		async () => (++checks === 1 ? new Set() : new Set([rootFile])),
	);
	assert.equal(removed.length, 0);
	assert.equal(checks, 2);
	assert.equal(await exists(rootFile), true);
	await rm(root, { recursive: true, force: true });
});
