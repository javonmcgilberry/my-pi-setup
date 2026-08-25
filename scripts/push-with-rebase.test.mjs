import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const pushWithRebase = path.join(repoRoot, "scripts", "push-with-rebase.sh");

async function git(cwd, args, options = {}) {
	return execFileAsync("git", args, { cwd, ...options });
}

async function commitFile(repo, name, content, message) {
	await writeFile(path.join(repo, name), content);
	await git(repo, ["add", name]);
	await git(repo, ["commit", "-m", message]);
}

async function createFixture() {
	const root = await mkdtemp(path.join(os.tmpdir(), "push-with-rebase-"));
	const remote = path.join(root, "remote.git");
	const seed = path.join(root, "seed");
	const local = path.join(root, "local");
	const peer = path.join(root, "peer");

	await git(root, ["init", "--bare", "--initial-branch=main", remote]);
	await git(root, ["clone", remote, seed]);
	await git(seed, ["config", "user.name", "Test User"]);
	await git(seed, ["config", "user.email", "test@example.com"]);
	await commitFile(seed, "shared.txt", "base\n", "base");
	await git(seed, ["push", "-u", "origin", "main"]);

	for (const repo of [local, peer]) {
		await git(root, ["clone", remote, repo]);
		await git(repo, ["config", "user.name", "Test User"]);
		await git(repo, ["config", "user.email", "test@example.com"]);
	}

	return { root, remote, local, peer };
}

test("rebases unpublished commits onto an advanced remote before pushing", async (t) => {
	const fixture = await createFixture();
	t.after(() => rm(fixture.root, { recursive: true, force: true }));

	await commitFile(fixture.local, "local.txt", "local\n", "local change");
	await commitFile(fixture.peer, "remote.txt", "remote\n", "remote change");
	await git(fixture.peer, ["push"]);

	const result = await execFileAsync(pushWithRebase, [fixture.local]);
	assert.match(result.stdout, /rebasing unpublished commits/);
	assert.match(result.stdout, /pushed to origin\/main/);
	assert.equal(await readFile(path.join(fixture.local, "local.txt"), "utf8"), "local\n");
	assert.equal(await readFile(path.join(fixture.local, "remote.txt"), "utf8"), "remote\n");

	await git(fixture.local, ["fetch", "origin"]);
	const { stdout: head } = await git(fixture.local, ["rev-parse", "HEAD"]);
	const { stdout: upstream } = await git(fixture.local, ["rev-parse", "origin/main"]);
	assert.equal(head, upstream);
});

test("fast-forwards a clean checkout when only the remote advanced", async (t) => {
	const fixture = await createFixture();
	t.after(() => rm(fixture.root, { recursive: true, force: true }));

	await commitFile(fixture.peer, "remote.txt", "remote\n", "remote change");
	await git(fixture.peer, ["push"]);

	const result = await execFileAsync(pushWithRebase, [fixture.local]);
	assert.match(result.stdout, /rebasing unpublished commits/);
	assert.equal(await readFile(path.join(fixture.local, "remote.txt"), "utf8"), "remote\n");

	const { stdout: head } = await git(fixture.local, ["rev-parse", "HEAD"]);
	const { stdout: upstream } = await git(fixture.local, ["rev-parse", "origin/main"]);
	assert.equal(head, upstream);
});

test("aborts a conflicting rebase and preserves the local commit", async (t) => {
	const fixture = await createFixture();
	t.after(() => rm(fixture.root, { recursive: true, force: true }));

	await commitFile(fixture.local, "shared.txt", "local\n", "local conflict");
	const { stdout: before } = await git(fixture.local, ["rev-parse", "HEAD"]);
	await commitFile(fixture.peer, "shared.txt", "remote\n", "remote conflict");
	await git(fixture.peer, ["push"]);

	await assert.rejects(
		execFileAsync(pushWithRebase, [fixture.local]),
		(error) => {
			assert.match(error.stderr, /automatic rebase conflicted and was aborted/);
			return true;
		},
	);

	const { stdout: after } = await git(fixture.local, ["rev-parse", "HEAD"]);
	assert.equal(after, before);
	assert.equal(await readFile(path.join(fixture.local, "shared.txt"), "utf8"), "local\n");
	await assert.rejects(readFile(path.join(fixture.local, ".git", "rebase-merge", "head-name")));
});
