import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { afterEach, describe, it } from "node:test";

const execFileAsync = promisify(execFile);
const script = new URL("./render-settings.mjs", import.meta.url).pathname;
const tempDirs = [];

afterEach(async () => {
  await Promise.all(tempDirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

async function fixture(base, local) {
  const dir = await mkdtemp(path.join(os.tmpdir(), "render-settings-"));
  tempDirs.push(dir);
  const baseFile = path.join(dir, "settings.json");
  const localFile = path.join(dir, "settings.local.json");
  await writeFile(baseFile, `${JSON.stringify(base)}\n`);
  if (local !== undefined) await writeFile(localFile, `${JSON.stringify(local)}\n`);
  return { baseFile, localFile };
}

describe("settings renderer", () => {
  it("selects the sole canonical local Prewalk source", async () => {
    const trackedPrewalk = "git:github.com/javonmcgilberry/pi-prewalk";
    const { baseFile } = await fixture({ packages: [trackedPrewalk] });
    const { stdout } = await execFileAsync(process.execPath, [
      script,
      baseFile,
      "--prewalk-source",
      "/home/example/Developer/pi-prewalk",
    ]);
    const rendered = JSON.parse(stdout);
    assert.deepEqual(rendered.packages, ["/home/example/Developer/pi-prewalk"]);
  });

  it("selects canonical local product packages", async () => {
    const personal = "git:git@github.com:javonmcgilberry/javon-pi-extensions.git";
    const webflow = "git:git@github.com:javonmcgilberry/webflow-designer-agent-browser.git";
    const { baseFile } = await fixture({ packages: [personal, webflow] });
    const { stdout } = await execFileAsync(process.execPath, [
      script,
      baseFile,
      "--package-source",
      personal,
      "/home/example/Developer/javon-pi-extensions",
      "--package-source",
      webflow,
      "/home/example/Developer/webflow-designer-agent-browser",
    ]);
    const rendered = JSON.parse(stdout);
    assert.deepEqual(rendered.packages, [
      "/home/example/Developer/javon-pi-extensions",
      "/home/example/Developer/webflow-designer-agent-browser",
    ]);
  });

  it("rejects arbitrary package replacement paths", async () => {
    const source = "git:github.com/javonmcgilberry/pi-prewalk";
    const { baseFile, localFile } = await fixture(
      { packages: [source] },
      { packageReplacements: { [source]: "/work/second-prewalk" } },
    );
    await assert.rejects(
      execFileAsync(process.execPath, [script, baseFile, localFile]),
      /Unknown local settings keys: packageReplacements/,
    );
  });

  it("preserves live Pi preferences while restoring repository-managed settings", async () => {
    const dir = await mkdtemp(path.join(os.tmpdir(), "render-settings-live-"));
    tempDirs.push(dir);
    const baseFile = path.join(dir, "settings.json");
    const localFile = path.join(dir, "settings.local.json");
    const existingFile = path.join(dir, "existing.json");
    await writeFile(baseFile, `${JSON.stringify({
      defaultThinkingLevel: "max",
      compaction: { enabled: true, reserveTokens: 1000 },
      packages: ["npm:managed"],
      subagents: { defaultModel: "managed" },
    })}\n`);
    await writeFile(localFile, `${JSON.stringify({
      settings: { defaultThinkingLevel: "medium" },
    })}\n`);
    await writeFile(existingFile, `${JSON.stringify({
      defaultThinkingLevel: "low",
      compaction: { reserveTokens: 2000 },
      modelThinkingLevels: { "openai/example": "high" },
      packages: ["npm:stale"],
      subagents: { defaultModel: "stale" },
    })}\n`);

    const { stdout } = await execFileAsync(process.execPath, [
      script,
      baseFile,
      localFile,
      "--existing-settings",
      existingFile,
      "--managed-key",
      "packages",
      "--managed-key",
      "subagents",
    ]);
    const rendered = JSON.parse(stdout);
    assert.equal(rendered.defaultThinkingLevel, "low");
    assert.deepEqual(rendered.compaction, { enabled: true, reserveTokens: 2000 });
    assert.deepEqual(rendered.modelThinkingLevels, { "openai/example": "high" });
    assert.deepEqual(rendered.packages, ["npm:managed"]);
    assert.deepEqual(rendered.subagents, { defaultModel: "managed" });
  });

  it("rejects a missing prewalk-source value", async () => {
    const { baseFile } = await fixture({ packages: [] });
    await assert.rejects(
      execFileAsync(process.execPath, [script, baseFile, "--prewalk-source"]),
      /Usage: render-settings\.mjs/,
    );
  });

  it("rejects an incomplete local package replacement", async () => {
    const { baseFile } = await fixture({ packages: [] });
    await assert.rejects(
      execFileAsync(process.execPath, [script, baseFile, "--package-source", "git:example"]),
      /Usage: render-settings\.mjs/,
    );
  });
});
