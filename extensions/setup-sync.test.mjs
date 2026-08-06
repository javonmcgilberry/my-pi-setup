import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { findSetupRoot, summarizeFailure, syncLocalGitCheckouts } from "./setup-sync.js";

const temporaryDirectories = [];

test.after(async () => {
	await Promise.all(temporaryDirectories.map((directory) => rm(directory, { recursive: true, force: true })));
});

test("finds the owning setup repository above the current directory", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "setup-sync-test-"));
	temporaryDirectories.push(root);
	await mkdir(path.join(root, "config"));
	await writeFile(path.join(root, "setup.sh"), "");
	await writeFile(path.join(root, "config", "manifest.json"), "{}");

	assert.equal(findSetupRoot(path.join(root, "nested", "project")), root);
});

test("returns no setup repository when the markers are absent", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "setup-sync-test-"));
	temporaryDirectories.push(root);

	assert.equal(findSetupRoot(root), undefined);
});

test("keeps the failure notification bounded and useful", () => {
	const result = summarizeFailure({
		code: 1,
		stderr: "first\nsecond",
		stdout: "third\nfourth\nfifth\nsixth\nseventh",
	});
	assert.equal(result, "second\nthird\nfourth\nfifth\nsixth\nseventh");
});

test("fast-forwards clean local Git package replacements", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "setup-sync-test-"));
	temporaryDirectories.push(root);
	await writeFile(
		path.join(root, "settings.local.json"),
		JSON.stringify({ packageReplacements: { "git:github.com/example/tool": "/work/tool" } }),
	);
	const calls = [];
	const result = await syncLocalGitCheckouts(root, async (command, args) => {
		calls.push([command, args]);
		return { code: 0, stdout: "", stderr: "" };
	});

	assert.deepEqual(result, { ok: true, synced: ["/work/tool"] });
	assert.deepEqual(calls, [
		["git", ["-C", "/work/tool", "status", "--porcelain"]],
		["git", ["-C", "/work/tool", "pull", "--ff-only"]],
	]);
});

test("refuses to pull a dirty local Git package replacement", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "setup-sync-test-"));
	temporaryDirectories.push(root);
	await writeFile(
		path.join(root, "settings.local.json"),
		JSON.stringify({ packageReplacements: { "git:github.com/example/tool": "/work/tool" } }),
	);
	const calls = [];
	const result = await syncLocalGitCheckouts(root, async (command, args) => {
		calls.push([command, args]);
		return { code: 0, stdout: " M src/index.ts\n", stderr: "" };
	});

	assert.equal(result.ok, false);
	assert.match(result.message, /uncommitted changes/);
	assert.equal(calls.length, 1);
});
