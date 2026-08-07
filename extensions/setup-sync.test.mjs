import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
	APPLY_SCRIPT,
	CHECK_COMMAND,
	applyLogPath,
	defaultCommitMessage,
	describeUpdates,
	fetchLatestVersions,
	findSetupRoot,
	readyCheckoutForPinning,
	summarizeFailure,
	syncLocalGitCheckouts,
	trackedPinFor,
} from "./setup-sync.js";

/** Fake git: keyed by the git subcommand, recording every invocation. */
function fakeGit(responses) {
	const calls = [];
	const exec = async (_command, args) => {
		// args are ["GIT_TERMINAL_PROMPT=0", "git", "-C", checkout, ...gitArgs]
		const gitArgs = args.slice(4);
		calls.push(gitArgs.join(" "));
		const key = Object.keys(responses).find((prefix) =>
			gitArgs.join(" ").startsWith(prefix),
		);
		return responses[key] ?? { code: 0, stdout: "", stderr: "" };
	};
	return { exec, calls };
}

function fakeUi({ input, confirm } = {}) {
	return {
		ui: {
			input: async () => input,
			confirm: async () => confirm ?? false,
			notify: () => {},
		},
	};
}

const temporaryDirectories = [];

test.after(async () => {
	await Promise.all(
		temporaryDirectories.map((directory) =>
			rm(directory, { recursive: true, force: true }),
		),
	);
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
		JSON.stringify({
			packageReplacements: { "git:github.com/example/tool": "/work/tool" },
		}),
	);
	const calls = [];
	const result = await syncLocalGitCheckouts(root, async (command, args) => {
		calls.push([command, args]);
		return { code: 0, stdout: "", stderr: "" };
	});

	assert.deepEqual(result, { ok: true, synced: ["/work/tool"] });
	assert.deepEqual(calls, [
		[
			"env",
			[
				"GIT_TERMINAL_PROMPT=0",
				"git",
				"-C",
				"/work/tool",
				"status",
				"--porcelain",
			],
		],
		[
			"env",
			["GIT_TERMINAL_PROMPT=0", "git", "-C", "/work/tool", "pull", "--ff-only"],
		],
	]);
});

test("gates shutdown on the fast checks only", () => {
	assert.match(CHECK_COMMAND, /check\.sh --fast/);
	assert.match(CHECK_COMMAND, /npm pack --dry-run/);
});

test("runs the full checks in the detached helper before applying setup", () => {
	const fullChecks = APPLY_SCRIPT.indexOf("./scripts/check.sh;");
	const setup = APPLY_SCRIPT.indexOf("./setup.sh");
	const drift = APPLY_SCRIPT.indexOf("./scripts/drift.sh");
	assert.ok(fullChecks > 0, "helper runs the full checks");
	assert.ok(
		fullChecks < setup && setup < drift,
		"checks run before setup, setup before drift",
	);
	assert.match(APPLY_SCRIPT, /Setup was NOT applied/);
	assert.match(APPLY_SCRIPT, /Waiting for these Pi processes to exit/);
});

test("matches a local checkout to the tracked git pin it replaces", () => {
	const packages = [
		"npm:pi-lens@3.8.74",
		"git:github.com/javonmcgilberry/pi-prewalk@c22cf7e9",
		"git:github.com/other/tool@abc1234",
	];
	assert.equal(
		trackedPinFor(packages, "git:github.com/javonmcgilberry/pi-prewalk"),
		"git:github.com/javonmcgilberry/pi-prewalk@c22cf7e9",
	);
	assert.equal(
		trackedPinFor(packages, "git:github.com/absent/tool"),
		undefined,
	);
});

test("collects registry versions and tolerates lookup failures", async () => {
	const latest = await fetchLatestVersions(
		["pi-lens", "pi-fzf"],
		async (url) => (url.includes("pi-lens") ? "3.9.0" : undefined),
	);
	assert.deepEqual([...latest], [["pi-lens", "3.9.0"]]);
});

test("renders an update table the user can actually read", () => {
	assert.equal(
		describeUpdates([
			{ name: "pi-lens", from: "3.8.74", to: "3.9.0" },
			{
				name: "github.com/javonmcgilberry/pi-prewalk",
				from: "c22cf7e",
				to: "a0b2a8e",
			},
		]),
		"  pi-lens  3.8.74 \u2192 3.9.0\n  github.com/javonmcgilberry/pi-prewalk  c22cf7e \u2192 a0b2a8e",
	);
});

test("never writes to a dirty checkout when no commit message is given", async () => {
	const { exec, calls } = fakeGit({
		status: { code: 0, stdout: " M src/core.ts\n", stderr: "" },
	});
	const result = await readyCheckoutForPinning(
		"/work/prewalk",
		exec,
		fakeUi({ input: "  " }),
	);

	assert.equal(result.ok, false);
	assert.match(result.message, /nothing was committed/);
	assert.deepEqual(calls, ["status --porcelain"]);
});

test("never writes to a dirty checkout when the confirmation is declined", async () => {
	const { exec, calls } = fakeGit({
		status: { code: 0, stdout: " M src/core.ts\n", stderr: "" },
	});
	const result = await readyCheckoutForPinning(
		"/work/prewalk",
		exec,
		fakeUi({ input: "fix: something", confirm: false }),
	);

	assert.equal(result.ok, false);
	assert.match(result.message, /cancelled/);
	assert.deepEqual(calls, ["status --porcelain"]);
});

test("does not push a clean checkout whose HEAD is already published", async () => {
	const head = "a0b2a8e4d02bb38f43a64d6ff49e96cfea9e2ce4";
	const { exec, calls } = fakeGit({
		"branch -r": { code: 0, stdout: "  origin/main\n", stderr: "" },
		"rev-parse": { code: 0, stdout: `${head}\n`, stderr: "" },
	});
	const result = await readyCheckoutForPinning("/work/prewalk", exec, fakeUi());

	assert.deepEqual(result, { ok: true, head });
	assert.ok(!calls.includes("push"), "an already-published HEAD needs no push");
});

test("commits, pushes, and reports HEAD once the user confirms", async () => {
	const head = "beef1234beef1234beef1234beef1234beef1234";
	let published = false;
	const calls = [];
	const exec = async (_command, args) => {
		const gitArgs = args.slice(4).join(" ");
		calls.push(gitArgs);
		if (gitArgs.startsWith("status"))
			return { code: 0, stdout: " M src/core.ts\n", stderr: "" };
		if (gitArgs.startsWith("push")) {
			published = true;
			return { code: 0, stdout: "", stderr: "" };
		}
		if (gitArgs.startsWith("branch -r")) {
			return {
				code: 0,
				stdout: published ? "  origin/main\n" : "",
				stderr: "",
			};
		}
		if (gitArgs.startsWith("rev-parse"))
			return { code: 0, stdout: `${head}\n`, stderr: "" };
		return { code: 0, stdout: "", stderr: "" };
	};

	const result = await readyCheckoutForPinning(
		"/work/prewalk",
		exec,
		fakeUi({ input: "fix: real work", confirm: true }),
	);

	assert.deepEqual(result, { ok: true, head });
	assert.ok(calls.includes("add -A"));
	assert.ok(calls.includes("commit -m fix: real work"));
	assert.ok(calls.includes("push"));
});

test("refuses to pin a HEAD that never reaches a remote branch", async () => {
	const { exec } = fakeGit({
		"branch -r": { code: 0, stdout: "", stderr: "" },
	});
	const result = await readyCheckoutForPinning("/work/prewalk", exec, fakeUi());

	assert.equal(result.ok, false);
	assert.match(result.message, /not on any remote branch/);
});

test("suggests a commit message that names what moved", () => {
	assert.equal(
		defaultCommitMessage([{ name: "pi-lens", from: "3.8.74", to: "3.9.0" }]),
		"chore: update 1 tracked pin\n\npi-lens 3.8.74 -> 3.9.0\n",
	);
	assert.equal(
		defaultCommitMessage([
			{ name: "pi-lens", from: "3.8.74", to: "3.9.0" },
			{ name: "pi-fzf", from: "0.9.0", to: "0.9.1" },
		]),
		"chore: update 2 tracked pins\n\npi-lens 3.8.74 -> 3.9.0\npi-fzf 0.9.0 -> 0.9.1\n",
	);
});

test("logs the apply to a stable path that follows PI_AGENT_DIR", () => {
	assert.equal(
		applyLogPath({ PI_AGENT_DIR: "/tmp/agent" }),
		"/tmp/agent/sync-me.log",
	);
	assert.equal(
		applyLogPath({}, "/Users/example"),
		"/Users/example/.pi/agent/sync-me.log",
	);
});

test("refuses to pull a dirty local Git package replacement", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "setup-sync-test-"));
	temporaryDirectories.push(root);
	await writeFile(
		path.join(root, "settings.local.json"),
		JSON.stringify({
			packageReplacements: { "git:github.com/example/tool": "/work/tool" },
		}),
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
