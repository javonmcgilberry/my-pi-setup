import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const land = path.join(repoRoot, "scripts", "land.sh");

/**
 * Only non-mutating invocations belong here. Every case below either short
 * circuits before staging or exits on argument validation, so the suite can
 * never create a commit in the repository it is running inside.
 */
async function run(args) {
	try {
		const { stdout, stderr } = await execFileAsync(land, args, {
			cwd: repoRoot,
		});
		return { code: 0, stdout, stderr };
	} catch (error) {
		return {
			code: error.code ?? 1,
			stdout: error.stdout ?? "",
			stderr: error.stderr ?? "",
		};
	}
}

test("succeeds and stages nothing when the pathspec has no changes", async () => {
	const result = await run(["--path", "package.json"]);
	assert.equal(result.code, 0);
	assert.match(result.stdout, /nothing to commit/);
});

test("does not require a message when there is nothing to commit", async () => {
	const result = await run(["--path", "package.json"]);
	assert.equal(result.code, 0, "a clean pathspec must not demand a message");
	assert.match(result.stdout, /nothing to commit/);
});

// No test passes --push: this suite runs inside the real repository, so a case
// that reached the push step would publish. The push branch is covered by
// reading the script, not by executing it here.

test("rejects an unknown flag instead of guessing", async () => {
	const result = await run(["--bogus"]);
	assert.equal(result.code, 2);
	assert.match(result.stderr, /usage: scripts\/land\.sh/);
});

test("rejects a message flag with no value", async () => {
	const result = await run(["--message"]);
	assert.equal(result.code, 2);
	assert.match(result.stderr, /usage: scripts\/land\.sh/);
});

test("rejects a path flag with no value", async () => {
	const result = await run(["--path"]);
	assert.equal(result.code, 2);
	assert.match(result.stderr, /usage: scripts\/land\.sh/);
});

test("documents every supported flag in its usage text", async () => {
	const { stderr } = await run(["--bogus"]);
	for (const flag of ["--message", "--path", "--push", "--full"]) {
		assert.match(
			stderr,
			new RegExp(flag.replace(/-/g, "\\-")),
			`usage should mention ${flag}`,
		);
	}
});
