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
  it("adds the local setup package exactly once after its dependencies", async () => {
    const { baseFile } = await fixture({ packages: ["npm:example@1.2.3"] });
    const { stdout } = await execFileAsync(process.execPath, [
      script,
      baseFile,
      "--package-source",
      "/work/my-pi-setup",
    ]);
    const rendered = JSON.parse(stdout);
    assert.deepEqual(rendered.packages, ["npm:example@1.2.3", "/work/my-pi-setup"]);
  });

  it("applies package replacements before adding the local setup package", async () => {
    const source = "git:github.com/example/tool@0123456789012345678901234567890123456789";
    const { baseFile, localFile } = await fixture(
      { packages: [source] },
      { packageReplacements: { [source]: "/work/tool" } },
    );
    const { stdout } = await execFileAsync(process.execPath, [
      script,
      baseFile,
      localFile,
      "--package-source",
      "/work/my-pi-setup",
    ]);
    const rendered = JSON.parse(stdout);
    assert.deepEqual(rendered.packages, ["/work/tool", "/work/my-pi-setup"]);
  });

  it("replaces a pinned package by its stable locator", async () => {
    const { baseFile, localFile } = await fixture(
      { packages: ["git:github.com/example/tool@fedcba98765432100123456789012345678901234"] },
      { packageReplacements: { "git:github.com/example/tool": "/work/tool" } },
    );
    const { stdout } = await execFileAsync(process.execPath, [script, baseFile, localFile]);
    const rendered = JSON.parse(stdout);
    assert.deepEqual(rendered.packages, ["/work/tool"]);
  });

  it("rejects a missing package-source value", async () => {
    const { baseFile } = await fixture({ packages: [] });
    await assert.rejects(
      execFileAsync(process.execPath, [script, baseFile, "--package-source"]),
      /Usage: render-settings\.mjs/,
    );
  });
});
