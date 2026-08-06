import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { access, lstat, mkdir, mkdtemp, readFile, readdir, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { afterEach, describe, it } from "node:test";

const execFileAsync = promisify(execFile);
const repoRoot = path.resolve(new URL("..", import.meta.url).pathname);
const setupScript = path.join(repoRoot, "setup.sh");
const driftScript = path.join(repoRoot, "scripts/drift.sh");
const restoreScript = path.join(repoRoot, "scripts/restore.sh");
const tempDirs = [];

afterEach(async () => {
  await Promise.all(tempDirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

async function tempTarget() {
  const root = await mkdtemp(path.join(os.tmpdir(), "my-pi-setup-"));
  tempDirs.push(root);
  return {
    root,
    agentDir: path.join(root, "agent"),
    skillsDir: path.join(root, "skills"),
  };
}

function run(script, args, target) {
  return execFileAsync(script, args, {
    cwd: repoRoot,
    env: {
      ...process.env,
      PI_AGENT_DIR: target.agentDir,
      AGENTS_SKILLS_DIR: target.skillsDir,
    },
  });
}

async function exists(file) {
  try {
    await access(file);
    return true;
  } catch {
    return false;
  }
}

describe("setup bootstrap", () => {
  it("is idempotent and produces a clean drift result", async () => {
    const target = await tempTarget();
    await run(setupScript, [], target);
    const second = await run(setupScript, [], target);
    const drift = await run(driftScript, [], target);

    assert.match(second.stdout, /unchanged: settings\.json/);
    assert.match(drift.stdout, /No managed file drift detected\./);

    const settings = JSON.parse(await readFile(path.join(target.agentDir, "settings.json"), "utf8"));
    assert.equal(settings.packages[0], repoRoot);
    assert.equal(settings.packages.filter((source) => source === repoRoot).length, 1);
    assert.equal(await exists(path.join(target.agentDir, "extensions/pretty-footer.ts")), false);
    assert.equal(await exists(path.join(target.agentDir, "packages/prewalk")), false);

    const sharedSkill = path.join(target.skillsDir, "webflow-designer-agent-browser");
    assert.equal((await lstat(sharedSkill)).isSymbolicLink(), true);
  });

  it("backs up retired paths and restores them", async () => {
    const target = await tempTarget();
    const oldExtension = path.join(target.agentDir, "extensions/warp-session-title.ts");
    const oldPrewalk = path.join(target.agentDir, "packages/prewalk/marker.txt");
    await mkdir(path.dirname(oldExtension), { recursive: true });
    await mkdir(path.dirname(oldPrewalk), { recursive: true });
    await writeFile(oldExtension, "old extension\n");
    await writeFile(oldPrewalk, "old prewalk\n");

    await run(setupScript, [], target);
    assert.equal(await exists(oldExtension), false);
    assert.equal(await exists(oldPrewalk), false);

    const backupsRoot = path.join(target.agentDir, "backups");
    const backups = await readdir(backupsRoot);
    assert.equal(backups.length, 1);
    const backupDir = path.join(backupsRoot, backups[0]);
    assert.equal(await readFile(path.join(backupDir, "extensions/warp-session-title.ts"), "utf8"), "old extension\n");
    assert.equal(await readFile(path.join(backupDir, "packages/prewalk/marker.txt"), "utf8"), "old prewalk\n");

    await run(restoreScript, [backupDir], target);
    assert.equal(await readFile(oldExtension, "utf8"), "old extension\n");
    assert.equal(await readFile(oldPrewalk, "utf8"), "old prewalk\n");
  });

  it("refuses a symlinked target root", async () => {
    const target = await tempTarget();
    const realAgent = path.join(target.root, "real-agent");
    await mkdir(realAgent);
    await symlink(realAgent, target.agentDir);

    await assert.rejects(
      run(setupScript, [], target),
      (error) => {
        assert.match(error.stderr, /Refusing symlinked target root/);
        return true;
      },
    );
    await assert.rejects(
      run(driftScript, [], target),
      (error) => {
        assert.match(error.stderr, /Refusing symlinked comparison root/);
        return true;
      },
    );
  });

  it("refuses a symlinked managed target parent", async () => {
    const target = await tempTarget();
    const outside = path.join(target.root, "outside");
    await mkdir(target.agentDir, { recursive: true });
    await mkdir(outside);
    await symlink(outside, path.join(target.agentDir, "extensions"));

    await assert.rejects(
      run(setupScript, [], target),
      (error) => {
        assert.match(error.stderr, /Refusing symlinked target parent/);
        return true;
      },
    );
    await assert.rejects(
      run(driftScript, [], target),
      (error) => {
        assert.match(error.stderr, /Refusing symlinked comparison target parent/);
        return true;
      },
    );
  });

  it("keeps dry-run side effect free", async () => {
    const target = await tempTarget();
    const result = await run(setupScript, ["--dry-run"], target);
    assert.match(result.stdout, /would render: settings\.json/);
    assert.equal(await exists(target.agentDir), false);
    assert.equal(await exists(target.skillsDir), false);
  });
});
