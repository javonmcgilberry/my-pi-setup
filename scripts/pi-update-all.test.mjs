import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const updater = path.join(repoRoot, "scripts", "pi-update-all");

test("documents the configuration-only update boundary", async () => {
	const { stdout } = await execFileAsync(updater, ["--help"]);
	assert.match(stdout, /never runs product tests or creates Git commits/);
});

test("uses Pi's native all-inclusive updater", async () => {
	const source = await readFile(updater, "utf8");
	assert.match(source, /"\$pi_bin" update --all/);
	assert.doesNotMatch(source, /"\$pi_bin" update --extensions/);
});

test("does not land changes or invoke product validation", async () => {
	const source = await readFile(updater, "utf8");
	assert.doesNotMatch(source, /"\$repo_dir\/scripts\/(?:land|check)\.sh"/);
	assert.match(source, /pull --ff-only/);
	assert.equal(source.match(/repo_dir\/setup\.sh/g)?.length, 2);
});
