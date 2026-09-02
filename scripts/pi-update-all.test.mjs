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

test("documents that the updater refreshes Pi and its packages", async () => {
	const { stdout } = await execFileAsync(updater, ["--help"]);
	assert.match(stdout, /updates the live setup, Pi itself, and every/);
});

test("uses Pi's native all-inclusive updater", async () => {
	const source = await readFile(updater, "utf8");
	assert.match(source, /"\$pi_bin" update --all/);
	assert.doesNotMatch(source, /"\$pi_bin" update --extensions/);
});

test("uses the normal bounded landing checks", async () => {
	const source = await readFile(updater, "utf8");
	assert.match(source, /land_args=\(--push\)/);
	assert.doesNotMatch(source, /land\.sh" --full|land_args=.*--full/);
});
