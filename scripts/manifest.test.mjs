import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  entriesFor,
  loadManifest,
  normalizeManifest,
  REPO_ROOT,
} from "./manifest.mjs";

const base = {
  version: 1,
  rendered: { "settings.json": "settings.json" },
  copied: [],
  linked: {},
  commands: {},
  sharedSkills: {},
  macosLaunchAgents: {},
  retired: { pi: [], shared: [], commands: [] },
  externalLinks: [],
  runtimeExclusions: [],
};

const NPM_SOURCE = /^npm:(?<name>@[^/@]+\/[^/@]+|[^@]+)(?:@(?<version>.+))?$/;

function parseNpmSource(source) {
  const match = NPM_SOURCE.exec(source);
  return match?.groups
    ? { name: match.groups.name, version: match.groups.version }
    : null;
}

describe("managed install manifest", () => {
  it("normalizes the checked-in inventory for every consumer", () => {
    const manifest = loadManifest();
    assert.equal(manifest.version, 1);
    assert.equal(manifest.copied.length, 11);
    assert.equal(manifest.linked.length, 0);
    assert.deepEqual(manifest.commands, [{
      root: "commands",
      source: "scripts/pi-update-all",
      target: "pi-update-all",
      backup: "local-bin-pi-update-all",
    }]);
    assert.equal(manifest.sharedSkills.length, 1);
    assert.equal(manifest.macosLaunchAgents.length, 1);
    assert.deepEqual(manifest.macosLaunchAgents[0], {
      root: "macosLaunchAgents",
      source: "config/com.javonmcgilberry.pi-tmux-gui-server.plist",
      target: "com.javonmcgilberry.pi-tmux-gui-server.plist",
      backup: "macos-launch-agents-com.javonmcgilberry.pi-tmux-gui-server.plist",
    });
    assert.deepEqual(
      entriesFor(manifest, "retired", "pi").map((entry) => entry.target),
      [
        "pi-explore-subagents.json",
        "package.json",
        "package-lock.json",
        "disabled-extensions/clear-status.ts",
        "extensions/herdr-agent-state.ts",
        "extensions/pretty-footer.ts",
        "extensions/session-spend-dashboard",
        "extensions/warp-session-title.ts",
        "packages/context-budget",
        "packages/prewalk",
        "skills/webflow-designer-agent-browser",
      ],
    );
    assert.equal(
      entriesFor(manifest, "shared")[0].backup,
      "external-agents-skills-webflow-designer-agent-browser",
    );
  });

  it("exposes only the intended personal package resources", () => {
    const packageJson = JSON.parse(readFileSync(`${REPO_ROOT}/package.json`, "utf8"));
    assert.equal(packageJson.keywords.includes("pi-package"), true);
    assert.deepEqual(packageJson.pi.extensions, [
      "./extensions/agent-browser-policy.ts",
      "./extensions/herdr-agent-state.ts",
      "./extensions/pretty-footer.ts",
      "./packages/context-budget",
      "./extensions/session-spend-dashboard",
      "./extensions/warp-session-title.ts",
    ]);
    assert.deepEqual(packageJson.dependencies ?? {}, {});
    assert.deepEqual(Object.keys(packageJson.peerDependencies).sort(), [
      "@earendil-works/pi-coding-agent",
      "@earendil-works/pi-tui",
    ]);
    assert.equal(packageJson.files.includes("disabled-extensions/clear-status.ts"), false);
    assert.equal(packageJson.files.some((entry) => entry.includes("webflow-designer-agent-browser")), false);
  });

  it("floats every remote package source", () => {
    const settings = JSON.parse(readFileSync(`${REPO_ROOT}/settings.json`, "utf8"));
    const npmPackages = settings.packages
      .filter((entry) => entry.startsWith("npm:"))
      .map((entry) => {
        const parsed = parseNpmSource(entry);
        assert.ok(parsed, `valid npm package source: ${entry}`);
        return { source: entry, ...parsed };
      });
    for (const pkg of npmPackages) {
      assert.equal(pkg.version, undefined, `${pkg.name} must float`);
    }

    const gitPackages = settings.packages.filter((source) => source.startsWith("git:"));
    assert.ok(gitPackages.length > 0, "the setup includes Git packages");
    for (const source of gitPackages) {
      assert.match(source, /^git:[^@]+$/, `${source} must float`);
    }
  });

  it("rejects traversal and absolute paths", () => {
    assert.throws(
      () => normalizeManifest({ ...base, copied: ["../settings.json"] }),
      /relative path|traversing|malformed/,
    );
    assert.throws(
      () => normalizeManifest({ ...base, externalLinks: ["/tmp/outside"] }),
      /relative path|traversing|malformed/,
    );
    assert.throws(
      () => normalizeManifest({ ...base, externalLinks: ["bad\tpath"] }),
      /relative path|traversing|malformed/,
    );
  });

  it("requires exactly one rendered settings entry in the contract", () => {
    assert.throws(
      () => normalizeManifest({ ...base, rendered: {} }),
      /rendered must contain exactly one/,
    );
    assert.throws(
      () => normalizeManifest({ ...base, rendered: { "settings.json": "settings.json", "other.json": "settings.json" } }),
      /rendered must contain exactly one/,
    );
  });

  it("rejects unknown manifest categories and duplicate local overrides", () => {
    assert.throws(
      () => normalizeManifest({ ...base, unexpected: [] }),
      /unknown manifest keys/,
    );
    assert.throws(
      () => normalizeManifest({ ...base, localOverrides: ["settings.local.json", "settings.local.json"] }),
      /localOverrides contains duplicate paths/,
    );
  });

  it("rejects missing sources before setup can mutate targets", () => {
    assert.throws(
      () => normalizeManifest({ ...base, copied: ["does-not-exist.txt"] }),
      /source does not exist/,
    );
  });

  it("rejects duplicate targets across explicit categories", () => {
    assert.throws(
      () => normalizeManifest({ ...base, copied: ["settings.json"] }),
      /duplicate managed target pi\/settings.json/,
    );
    assert.throws(
      () => normalizeManifest({
        ...base,
        linked: { "settings.json": "settings.json" },
      }),
      /duplicate managed target pi\/settings.json/,
    );
    assert.throws(
      () => normalizeManifest({
        ...base,
        linked: { "extensions": "scripts" },
        sharedSkills: { "foo/bar": "does-not-exist" },
      }),
      /source does not exist/,
    );
    assert.throws(
      () => normalizeManifest({
        ...base,
        linked: { "extensions": "scripts", "extensions/foo": "scripts" },
      }),
      /managed targets overlap/,
    );
  });

  it("rejects shared backup flattening collisions", () => {
    assert.throws(
      () => normalizeManifest({
        ...base,
        sharedSkills: { "foo/bar": "scripts", "foo-bar": "scripts" },
      }),
      /backup path collision/,
    );
  });

  it("rejects external links that claim a managed target", () => {
    assert.throws(
      () => normalizeManifest({ ...base, externalLinks: ["settings.json"] }),
      /external link conflicts/,
    );
    assert.throws(
      () => normalizeManifest({ ...base, externalLinks: ["extensions/warp-gateway.ts", "extensions/warp-gateway.ts"] }),
      /externalLinks contains duplicate paths/,
    );
  });
});
