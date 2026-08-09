import assert from "node:assert/strict";
import test from "node:test";

import {
	applyGitPinUpdates,
	parseGitPin,
	planGitPinUpdate,
} from "./setup-update.js";

test("parses exact Git sources into locator and ref", () => {
	assert.deepEqual(
		parseGitPin("git:github.com/javonmcgilberry/pi-prewalk@c22cf7e9"),
		{
			locator: "git:github.com/javonmcgilberry/pi-prewalk",
			ref: "c22cf7e9",
		},
	);
});

test("ignores registry, local, and floating Git sources", () => {
	assert.equal(parseGitPin("npm:pi-lens"), null);
	assert.equal(parseGitPin("npm:pi-subagents@0.43.0"), null);
	assert.equal(parseGitPin("git:github.com/example/tool"), null);
	assert.equal(parseGitPin("./local/path"), null);
});

test("plans a Git pin bump toward an already-pushed head", () => {
	const head = "a0b2a8e4d02bb38f43a64d6ff49e96cfea9e2ce4";
	assert.deepEqual(
		planGitPinUpdate(
			"git:github.com/javonmcgilberry/pi-prewalk@c22cf7e927b3d67d28d12a4ea9f74afbdb8b94dc",
			head,
		),
		{
			source:
				"git:github.com/javonmcgilberry/pi-prewalk@c22cf7e927b3d67d28d12a4ea9f74afbdb8b94dc",
			next: `git:github.com/javonmcgilberry/pi-prewalk@${head}`,
			name: "github.com/javonmcgilberry/pi-prewalk",
			from: "c22cf7e927b3d67d28d12a4ea9f74afbdb8b94dc",
			to: head,
		},
	);
});

test("plans no change for a matching head or a non-Git source", () => {
	const head = "a0b2a8e4d02bb38f43a64d6ff49e96cfea9e2ce4";
	assert.equal(
		planGitPinUpdate(`git:github.com/example/tool@${head}`, head),
		null,
	);
	assert.equal(planGitPinUpdate("npm:pi-intercom", head), null);
});

test("rewrites Git pins without touching floating npm locators or formatting", () => {
	const original = `{
  "theme": "dark",
  "packages": [
    "npm:pi-intercom",
    "git:github.com/example/tool@old-head"
  ]
}
`;
	const updated = applyGitPinUpdates(original, [
		{
			source: "git:github.com/example/tool@old-head",
			next: "git:github.com/example/tool@new-head",
		},
	]);

	assert.equal(
		updated,
		`{
  "theme": "dark",
  "packages": [
    "npm:pi-intercom",
    "git:github.com/example/tool@new-head"
  ]
}
`,
	);
});

test("refuses to rewrite a Git pin that is missing or duplicated", () => {
	const duplicate =
		`{ "packages": [` +
		`"git:github.com/example/tool@old",` +
		`"git:github.com/example/tool@old"] }`;
	assert.throws(
		() =>
			applyGitPinUpdates(duplicate, [
				{
					source: "git:github.com/example/tool@old",
					next: "git:github.com/example/tool@new",
				},
			]),
		/exactly once/,
	);
	assert.throws(
		() =>
			applyGitPinUpdates(`{ "packages": [] }`, [
				{
					source: "git:github.com/example/missing@old",
					next: "git:github.com/example/missing@new",
				},
			]),
		/exactly once/,
	);
});

test("applies every planned Git pin in one pass", () => {
	const original =
		`["git:github.com/example/a@old-a",` +
		`"git:github.com/example/b@old-b"]`;
	const updated = applyGitPinUpdates(original, [
		{
			source: "git:github.com/example/a@old-a",
			next: "git:github.com/example/a@new-a",
		},
		{
			source: "git:github.com/example/b@old-b",
			next: "git:github.com/example/b@new-b",
		},
	]);
	assert.equal(
		updated,
		`["git:github.com/example/a@new-a",` +
			`"git:github.com/example/b@new-b"]`,
	);
});
