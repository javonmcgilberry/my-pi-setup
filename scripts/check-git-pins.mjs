import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const gitProtocolPattern = /^(?:https?|ssh|git):\/\//;
const exactGitRef = /^(?:[0-9a-f]{40}|v?\d+(?:\.\d+){0,2}(?:-[0-9A-Za-z.-]+)?)$/;

export function isGitPackageSource(source) {
  return source.startsWith("git:") || gitProtocolPattern.test(source);
}

export function parsePinnedGitSource(source) {
  if (!isGitPackageSource(source)) return null;
  const separator = source.lastIndexOf("@");
  const locator = source.slice(0, separator);
  const ref = source.slice(separator + 1);
  if (separator < source.indexOf(":") + 2 || !exactGitRef.test(ref)) return null;

  const shorthand = locator.startsWith("git:") && !locator.startsWith("git://");
  const remote = shorthand ? `https://${locator.slice(4)}.git` : locator;
  return { remote, ref, commit: /^[0-9a-f]{40}$/.test(ref) ? ref : null };
}

export async function verifyGitPins(settingsPath) {
  const settings = JSON.parse(await readFile(settingsPath, "utf8"));
  const gitSources = settings.packages.filter(isGitPackageSource);

  for (const source of gitSources) {
    const parsed = parsePinnedGitSource(source);
    assert.ok(parsed, `Git package must use an exact commit or tag: ${source}`);
    const { remote, ref, commit } = parsed;
    const checkout = await mkdtemp(path.join(os.tmpdir(), "my-pi-git-pin-"));
    try {
      await execFileAsync("git", ["-C", checkout, "init", "--quiet"]);
      await execFileAsync("git", ["-C", checkout, "fetch", "--quiet", "--depth=1", remote, ref], {
        env: { ...process.env, GIT_TERMINAL_PROMPT: "0" },
      });
      const { stdout } = await execFileAsync("git", ["-C", checkout, "rev-parse", "FETCH_HEAD"]);
      if (commit) assert.equal(stdout.trim(), commit, `Fetched the wrong commit for ${source}`);
    } catch (error) {
      const detail = error.stderr?.trim() || error.message;
      throw new Error(`Pinned Git package is not fetchable: ${source}\n${detail}`, { cause: error });
    } finally {
      await rm(checkout, { recursive: true, force: true });
    }
  }

  console.log(`Verified ${gitSources.length} pinned Git package refs.`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const repoRoot = fileURLToPath(new URL("..", import.meta.url));
  await verifyGitPins(path.join(repoRoot, "settings.json"));
}
