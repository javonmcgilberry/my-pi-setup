import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { access, chmod, lstat, mkdir, mkdtemp, readFile, readlink, readdir, rm, symlink, writeFile } from "node:fs/promises";
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
    commandsDir: path.join(root, "bin"),
  };
}

function run(script, args, target) {
  return execFileAsync(script, args, {
    cwd: repoRoot,
    env: {
      ...process.env,
      HOME: target.root,
      PI_AGENT_DIR: target.agentDir,
      PI_CODING_AGENT_DIR: target.agentDir,
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

async function installWebflowFixture(target) {
  const skill = path.join(
    target.agentDir,
    "git/github.com/javonmcgilberry/webflow-designer-agent-browser/skills/webflow-designer-agent-browser",
  );
  const launcher = path.join(skill, "scripts/designer-code-mode.py");
  await mkdir(path.dirname(launcher), { recursive: true });
  await writeFile(launcher, '#!/usr/bin/env bash\nprintf \'{"operation":"help"}\\n\'\n');
  await chmod(launcher, 0o755);
  return skill;
}

async function installLocalPackageFixtures(target) {
  const developer = path.join(target.root, "Developer");
  const personal = path.join(developer, "javon-pi-extensions");
  const webflow = path.join(developer, "webflow-designer-agent-browser");
  for (const checkout of [personal, webflow]) {
    await mkdir(checkout, { recursive: true });
    await execFileAsync("git", ["init", "-q", checkout]);
  }
  await mkdir(path.join(webflow, "skills/webflow-designer-agent-browser"), { recursive: true });
  return { personal, webflow };
}

describe("setup bootstrap", () => {
  it("is idempotent and produces a clean drift result", async () => {
    const target = await tempTarget();
    const webflowSkill = await installWebflowFixture(target);
    await run(setupScript, [], target);
    const second = await run(setupScript, [], target);
    const drift = await run(driftScript, [], target);

    assert.match(second.stdout, /unchanged: settings\.json/);
    assert.match(drift.stdout, /No managed file drift detected\./);

    const settings = JSON.parse(await readFile(path.join(target.agentDir, "settings.json"), "utf8"));
    assert.equal(settings.packages.includes(repoRoot), false);
    assert.equal(settings.packages.includes("git:git@github.com:javonmcgilberry/javon-pi-extensions.git"), true);
    assert.equal(settings.packages.includes("git:git@github.com:javonmcgilberry/webflow-designer-agent-browser.git"), true);
    assert.equal(
      settings.packages.includes("git:github.com/javonmcgilberry/pi-prewalk"),
      true,
    );
    assert.equal(await exists(path.join(target.agentDir, "extensions/pretty-footer.ts")), false);
    assert.equal(await exists(path.join(target.agentDir, "packages/prewalk")), false);

    const tuiSkill = path.join(target.skillsDir, "tui-cli-design");
    assert.equal((await lstat(tuiSkill)).isSymbolicLink(), true);
    assert.equal(await readlink(tuiSkill), path.join(repoRoot, "skills/tui-cli-design"));
    const sharedWebflow = path.join(target.skillsDir, "webflow-designer-agent-browser");
    assert.equal((await lstat(sharedWebflow)).isSymbolicLink(), true);
    assert.equal(await readlink(sharedWebflow), webflowSkill);
    const command = path.join(target.commandsDir, "pi-update-all");
    assert.equal((await lstat(command)).isSymbolicLink(), true);
    assert.equal(await readlink(command), path.join(repoRoot, "scripts/pi-update-all"));

    const customTools = path.join(target.agentDir, "codex-conversion-custom-tools");
    const definition = path.join(customTools, "webflow_designer.toml");
    const launcher = path.join(customTools, "webflow-designer");
    assert.equal((await lstat(definition)).isSymbolicLink(), true);
    assert.equal(
      await readlink(definition),
      path.join(repoRoot, "config/codex-conversion-custom-tools/webflow_designer.toml"),
    );
    assert.equal((await lstat(launcher)).isSymbolicLink(), true);
    assert.equal(
      await readlink(launcher),
      path.join(repoRoot, "scripts/webflow-designer"),
    );
    const toolHelp = await execFileAsync(launcher, ["help"], {
      cwd: repoRoot,
      env: {
        ...process.env,
        PI_AGENT_DIR: target.agentDir,
        PI_CODING_AGENT_DIR: target.agentDir,
      },
    });
    assert.equal(JSON.parse(toolHelp.stdout).operation, "help");
  });

  it("loads Prewalk only from the canonical development checkout when it exists", async () => {
    const target = await tempTarget();
    const prewalk = path.join(target.root, "Developer/pi-prewalk");
    await mkdir(prewalk, { recursive: true });
    await execFileAsync("git", ["init", "-q", prewalk]);

    await run(setupScript, [], target);

    const settings = JSON.parse(
      await readFile(path.join(target.agentDir, "settings.json"), "utf8"),
    );
    assert.equal(settings.packages.includes(prewalk), true);
    assert.equal(
      settings.packages.includes("git:github.com/javonmcgilberry/pi-prewalk"),
      false,
    );
  });

  it("loads personal products from canonical development checkouts when they exist", async () => {
    const target = await tempTarget();
    const { personal, webflow } = await installLocalPackageFixtures(target);

    await run(setupScript, [], target);

    const settings = JSON.parse(
      await readFile(path.join(target.agentDir, "settings.json"), "utf8"),
    );
    assert.equal(settings.packages.includes(personal), true);
    assert.equal(settings.packages.includes(webflow), true);
    assert.equal(
      settings.packages.includes("git:git@github.com:javonmcgilberry/javon-pi-extensions.git"),
      false,
    );
    assert.equal(
      settings.packages.includes("git:git@github.com:javonmcgilberry/webflow-designer-agent-browser.git"),
      false,
    );
    assert.equal(
      await readlink(path.join(target.skillsDir, "webflow-designer-agent-browser")),
      path.join(webflow, "skills/webflow-designer-agent-browser"),
    );
  });

  it("rejects a non-Git canonical personal package checkout", async () => {
    const target = await tempTarget();
    await mkdir(path.join(target.root, "Developer/javon-pi-extensions"), { recursive: true });

    await assert.rejects(
      run(setupScript, [], target),
      /Canonical package checkout is not a Git working tree/,
    );
  });

  it("rejects a non-Git canonical Prewalk directory instead of selecting another path", async () => {
    const target = await tempTarget();
    await mkdir(path.join(target.root, "Developer/pi-prewalk"), { recursive: true });

    await assert.rejects(
      run(setupScript, [], target),
      /Canonical Prewalk checkout is not a Git working tree/,
    );
  });

  it("preserves live Pi preferences and repairs only repository-managed settings", async () => {
    const target = await tempTarget();
    const settingsFile = path.join(target.agentDir, "settings.json");
    await mkdir(target.agentDir, { recursive: true });
    await writeFile(settingsFile, `${JSON.stringify({
      defaultThinkingLevel: "low",
      httpIdleTimeoutMs: 300000,
      modelThinkingLevels: { "openai/example": "high" },
      packages: ["npm:stale"],
      retry: { enabled: false },
      subagents: { defaultModel: "stale" },
      transport: "websocket",
      vstack: { stale: true },
    })}\n`);

    await run(setupScript, [], target);
    let settings = JSON.parse(await readFile(settingsFile, "utf8"));
    assert.equal(settings.defaultThinkingLevel, "low");
    assert.equal(settings.httpIdleTimeoutMs, 300000);
    assert.deepEqual(settings.modelThinkingLevels, { "openai/example": "high" });
    assert.equal(settings.packages.includes("npm:stale"), false);
    assert.equal(settings.packages.includes(repoRoot), false);
    assert.equal(settings.packages.includes("git:git@github.com:javonmcgilberry/javon-pi-extensions.git"), true);
    assert.deepEqual(settings.retry, { enabled: false });
    assert.deepEqual(settings.subagents, { defaultModel: "stale" });
    assert.equal(settings.transport, "websocket");
    assert.deepEqual(settings.vstack, { stale: true });

    settings.defaultThinkingLevel = "high";
    settings.subagents = { defaultModel: "live" };
    await writeFile(settingsFile, `${JSON.stringify(settings, null, 2)}\n`);
    const preferenceDrift = await run(driftScript, [], target);
    assert.match(preferenceDrift.stdout, /No managed file drift detected\./);

    settings.packages = [];
    await writeFile(settingsFile, `${JSON.stringify(settings, null, 2)}\n`);
    await assert.rejects(
      run(driftScript, [], target),
      (error) => {
        assert.match(error.stdout, /different: settings\.json/);
        return true;
      },
    );
  });

  it("seeds global preference files once and never overwrites live changes", async () => {
    const target = await tempTarget();
    const prewalkFile = path.join(target.agentDir, "prewalk.json");
    const agentsFile = path.join(target.agentDir, "AGENTS.md");
    await mkdir(target.agentDir, { recursive: true });
    await writeFile(prewalkFile, '{"enabled":true,"children":{"agents":{"worker":true}}}\n');
    await writeFile(agentsFile, "live agent policy\n");

    const first = await run(setupScript, [], target);
    assert.match(first.stdout, /preserved: prewalk\.json \(live preference\)/);
    assert.match(first.stdout, /preserved: AGENTS\.md \(live preference\)/);
    assert.equal(
      await readFile(prewalkFile, "utf8"),
      '{"enabled":true,"children":{"agents":{"worker":true}}}\n',
    );
    assert.equal(await readFile(agentsFile, "utf8"), "live agent policy\n");

    const second = await run(setupScript, [], target);
    const drift = await run(driftScript, [], target);
    assert.match(second.stdout, /preserved: prewalk\.json \(live preference\)/);
    assert.match(drift.stdout, /No managed file drift detected\./);

    const fresh = await tempTarget();
    await run(setupScript, [], fresh);
    assert.equal(
      await readFile(path.join(fresh.agentDir, "prewalk.json"), "utf8"),
      await readFile(path.join(repoRoot, "prewalk.json"), "utf8"),
    );
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
    await writeFile(path.join(backupDir, "prewalk.json"), "restored live preference\n");

    await run(restoreScript, [backupDir], target);
    assert.equal(await readFile(oldExtension, "utf8"), "old extension\n");
    assert.equal(await readFile(oldPrewalk, "utf8"), "old prewalk\n");
    assert.equal(
      await readFile(path.join(target.agentDir, "prewalk.json"), "utf8"),
      "restored live preference\n",
    );
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
    assert.equal(await exists(target.commandsDir), false);
  });

  it("includes automatic tmux activation in a live macOS dry run", { skip: process.platform !== "darwin" }, async () => {
    const target = await tempTarget();
    const env = { ...process.env, HOME: target.root };
    delete env.PI_AGENT_DIR;
    delete env.AGENTS_SKILLS_DIR;
    delete env.PI_CODING_AGENT_DIR;

    const result = await execFileAsync(setupScript, ["--dry-run"], {
      cwd: repoRoot,
      env,
    });

    assert.match(result.stdout, /would run: .*activate-macos-tmux-gui-server\.sh --auto/);
    assert.equal(await exists(path.join(target.root, "Library/LaunchAgents")), false);
    assert.equal(await exists(path.join(target.root, ".pi")), false);
  });
});
