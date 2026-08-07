import assert from "node:assert/strict";
import test from "node:test";

import {
	applyPinUpdates,
	compareVersions,
	parsePackagePin,
	planGitPinUpdate,
	planNpmUpdates,
	registryUrl,
} from "./setup-update.js";

test("parses npm pins, including scoped names", () => {
	assert.deepEqual(parsePackagePin("npm:pi-lens@3.8.74"), {
		kind: "npm",
		name: "pi-lens",
		version: "3.8.74",
	});
	assert.deepEqual(parsePackagePin("npm:@howaboua/pi-auto-trees@0.1.11"), {
		kind: "npm",
		name: "@howaboua/pi-auto-trees",
		version: "0.1.11",
	});
});

test("parses git pins into locator and ref", () => {
	assert.deepEqual(
		parsePackagePin("git:github.com/javonmcgilberry/pi-prewalk@c22cf7e9"),
		{
			kind: "git",
			locator: "git:github.com/javonmcgilberry/pi-prewalk",
			ref: "c22cf7e9",
		},
	);
});

test("ignores sources that are not pinned packages", () => {
	assert.equal(parsePackagePin("npm:pi-lens"), null);
	assert.equal(parsePackagePin("./local/path"), null);
});

test("builds registry URLs that survive scoped names", () => {
	assert.equal(
		registryUrl("pi-lens"),
		"https://registry.npmjs.org/pi-lens/latest",
	);
	assert.equal(
		registryUrl("@howaboua/pi-auto-trees"),
		"https://registry.npmjs.org/@howaboua%2Fpi-auto-trees/latest",
	);
});

test("orders versions numerically, not lexically", () => {
	assert.ok(compareVersions("3.8.74", "3.8.9") > 0);
	assert.ok(compareVersions("0.2.0", "0.1.62") > 0);
	assert.ok(compareVersions("1.0.0", "1.0.0") === 0);
	assert.ok(compareVersions("1.2.0", "1.10.0") < 0);
});

test("treats a prerelease as older than its release", () => {
	assert.ok(compareVersions("1.0.0", "1.0.0-beta.1") > 0);
	assert.ok(compareVersions("1.0.0-beta.1", "1.0.0") < 0);
});

test("plans only genuine npm upgrades", () => {
	const packages = [
		"npm:pi-lens@3.8.74",
		"npm:pi-fzf@0.9.0",
		"npm:pi-render-cache@1.1.0",
		"git:github.com/example/tool@abc",
	];
	const latest = new Map([
		["pi-lens", "3.9.0"],
		["pi-fzf", "0.9.0"],
		["pi-render-cache", "1.0.9"],
	]);

	assert.deepEqual(planNpmUpdates(packages, latest), [
		{
			source: "npm:pi-lens@3.8.74",
			next: "npm:pi-lens@3.9.0",
			name: "pi-lens",
			from: "3.8.74",
			to: "3.9.0",
		},
	]);
});

test("skips npm packages whose latest version could not be resolved", () => {
	assert.deepEqual(planNpmUpdates(["npm:pi-lens@3.8.74"], new Map()), []);
});

test("plans a git pin bump toward an already-pushed head", () => {
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

test("plans no git bump when the pin already matches head", () => {
	const head = "a0b2a8e4d02bb38f43a64d6ff49e96cfea9e2ce4";
	assert.equal(
		planGitPinUpdate(`git:github.com/example/tool@${head}`, head),
		null,
	);
});

test("rewrites pins without reformatting the rest of settings.json", () => {
	const original = `{
  "theme": "dark",
  "packages": [
    "npm:pi-lens@3.8.74",
    "npm:pi-fzf@0.9.0"
  ]
}
`;
	const updated = applyPinUpdates(original, [
		{ source: "npm:pi-lens@3.8.74", next: "npm:pi-lens@3.9.0" },
	]);

	assert.equal(
		updated,
		`{
  "theme": "dark",
  "packages": [
    "npm:pi-lens@3.9.0",
    "npm:pi-fzf@0.9.0"
  ]
}
`,
	);
});

test("refuses to rewrite a pin that is not present exactly once", () => {
	const settings = `{ "packages": ["npm:pi-lens@3.8.74", "npm:pi-lens@3.8.74"] }`;
	assert.throws(
		() =>
			applyPinUpdates(settings, [
				{ source: "npm:pi-lens@3.8.74", next: "npm:pi-lens@3.9.0" },
			]),
		/exactly once/,
	);
	assert.throws(
		() =>
			applyPinUpdates(`{ "packages": [] }`, [
				{ source: "npm:missing@1.0.0", next: "npm:missing@2.0.0" },
			]),
		/exactly once/,
	);
});

test("applies every planned update in one pass", () => {
	const original = `["npm:a@1.0.0","npm:b@2.0.0"]`;
	const updated = applyPinUpdates(original, [
		{ source: "npm:a@1.0.0", next: "npm:a@1.1.0" },
		{ source: "npm:b@2.0.0", next: "npm:b@2.1.0" },
	]);
	assert.equal(updated, `["npm:a@1.1.0","npm:b@2.1.0"]`);
});
