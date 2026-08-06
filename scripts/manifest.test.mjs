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
  sharedSkills: {},
  retired: { pi: [], shared: [] },
  externalLinks: [],
  runtimeExclusions: [],
};

describe("managed install manifest", () => {
  it("normalizes the checked-in inventory for every consumer", () => {
    const manifest = loadManifest();
    assert.equal(manifest.version, 1);
    assert.equal(manifest.copied.length, 13);
    assert.equal(manifest.linked.length, 5);
    assert.equal(manifest.sharedSkills.length, 1);
    assert.deepEqual(
      entriesFor(manifest, "retired", "pi").map((entry) => entry.target),
      ["pi-explore-subagents.json", "skills/webflow-designer-agent-browser"],
    );
    assert.equal(
      entriesFor(manifest, "shared")[0].backup,
      "external-agents-skills-webflow-designer-agent-browser",
    );
  });

  it("keeps the render-cache runtime pin aligned with package metadata", () => {
    const packageJson = JSON.parse(readFileSync(`${REPO_ROOT}/package.json`, "utf8"));
    const settings = JSON.parse(readFileSync(`${REPO_ROOT}/settings.json`, "utf8"));
    const declared = packageJson.dependencies["pi-render-cache"];
    const version = declared.replace(/^[~^=]/, "");
    assert.equal(settings.packages.filter((entry) => entry.startsWith("npm:pi-render-cache")).length, 1);
    assert.equal(settings.packages.find((entry) => entry.startsWith("npm:pi-render-cache")), `npm:pi-render-cache@${version}`);
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
