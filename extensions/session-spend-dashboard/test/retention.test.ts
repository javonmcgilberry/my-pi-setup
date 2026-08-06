import assert from "node:assert/strict";
import { mkdir, mkdtemp, readdir, rename as fsRename, rm, stat, utimes, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { planSessionPrune, pruneSessionTrees, type RetentionFileOperations, withMaintenanceLock } from "../retention.ts";

async function exists(target: string): Promise<boolean> {
	try {
		await stat(target);
		return true;
	} catch {
		return false;
	}
}

async function createOldTree(root: string, stem: string): Promise<{
	project: string;
	rootFile: string;
	companionDirectory: string;
	cutoffMs: number;
}> {
	const project = path.join(root, "--project--");
	const rootFile = path.join(project, `${stem}.jsonl`);
	const companionDirectory = path.join(project, stem, "child");
	await mkdir(companionDirectory, { recursive: true });
	const childFile = path.join(companionDirectory, "session.jsonl");
	await writeFile(rootFile, "root\n");
	await writeFile(childFile, "child\n");
	const old = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000);
	await utimes(rootFile, old, old);
	await utimes(childFile, old, old);
	return {
		project,
		rootFile,
		companionDirectory: path.join(project, stem),
		cutoffMs: Date.now() - 7 * 24 * 60 * 60 * 1000,
	};
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

test("restores a staged tree when companion staging fails", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "session-retention-rollback-"));
	const tree = await createOldTree(root, "session-staging-failure");
	let calls = 0;
	const fileOperations: RetentionFileOperations = {
		mkdir,
		rm,
		rename: async (from, to) => {
			calls++;
			if (calls === 2) throw new Error("injected staging failure");
			return fsRename(from, to);
		},
	};

	await assert.rejects(
		pruneSessionTrees(root, tree.cutoffMs, new Set(), undefined, fileOperations),
		/injected staging failure/,
	);
	assert.equal(await exists(tree.rootFile), true);
	assert.equal(await exists(tree.companionDirectory), true);
	assert.equal(
		(await readdir(tree.project)).some((name) => name.startsWith(".session-retention-quarantine-")),
		false,
	);
	await rm(root, { recursive: true, force: true });
});

test("preserves quarantine when rollback also fails", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "session-retention-quarantine-"));
	const tree = await createOldTree(root, "session-rollback-failure");
	let calls = 0;
	const fileOperations: RetentionFileOperations = {
		mkdir,
		rm,
		rename: async (from, to) => {
			calls++;
			if (calls === 2) throw new Error("injected staging failure");
			if (calls === 3) throw new Error("injected rollback failure");
			return fsRename(from, to);
		},
	};

	await assert.rejects(
		pruneSessionTrees(root, tree.cutoffMs, new Set(), undefined, fileOperations),
		(error: unknown) => error instanceof AggregateError && /preserved quarantine/.test(error.message),
	);
	assert.equal(await exists(tree.rootFile), false);
	const quarantine = (await readdir(tree.project)).find((name) => name.startsWith(".session-retention-quarantine-"));
	assert.ok(quarantine);
	assert.equal(await exists(path.join(tree.project, quarantine, path.basename(tree.rootFile))), true);
	await rm(root, { recursive: true, force: true });
});
