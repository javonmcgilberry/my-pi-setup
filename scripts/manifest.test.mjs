import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import { isGitPackageSource, parsePinnedGitSource } from "./check-git-pins.mjs";

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
  sharedSkills: {},
  macosLaunchAgents: {},
  retired: { pi: [], shared: [] },
  externalLinks: [],
  runtimeExclusions: [],
};

describe("managed install manifest", () => {
  it("normalizes the checked-in inventory for every consumer", () => {
    const manifest = loadManifest();
    assert.equal(manifest.version, 1);
    assert.equal(manifest.copied.length, 11);
    assert.equal(manifest.linked.length, 0);
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
      "./extensions/setup-sync.js",
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

  it("keeps every managed npm and Git package source pinned", () => {
    const settings = JSON.parse(readFileSync(`${REPO_ROOT}/settings.json`, "utf8"));
    const exactSemver = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;
    const floating = settings.packages.filter((entry) => {
      if (entry.startsWith("npm:")) {
        const separator = entry.lastIndexOf("@");
        const source = entry.slice(4, separator);
        const version = entry.slice(separator + 1);
        return separator <= 4 || source.endsWith("@") || !exactSemver.test(version);
      }
      if (isGitPackageSource(entry)) return !parsePinnedGitSource(entry);
      return false;
    });
    assert.deepEqual(floating, []);
  });

  it("resolves every supported exact Git source without rewriting its protocol", () => {
    const commit = "a".repeat(40);
    assert.deepEqual(parsePinnedGitSource(`git:github.com/owner/repo@${commit}`), {
      remote: "https://github.com/owner/repo.git",
      ref: commit,
      commit,
    });
    for (const remote of [
      "https://github.com/owner/repo.git",
      "ssh://git@github.com/owner/repo.git",
      "git://github.com/owner/repo.git",
    ]) {
      assert.deepEqual(parsePinnedGitSource(`${remote}@${commit}`), { remote, ref: commit, commit });
    }
    assert.deepEqual(parsePinnedGitSource("https://github.com/owner/repo.git@v1.2.3"), {
      remote: "https://github.com/owner/repo.git",
      ref: "v1.2.3",
      commit: null,
    });
    assert.equal(parsePinnedGitSource("https://github.com/owner/repo.git@main"), null);
    assert.equal(parsePinnedGitSource("npm:example@1.0.0"), null);
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
