import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { realpathSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { after, describe, it } from "node:test";

const execFileAsync = promisify(execFile);
const repoRoot = path.resolve(new URL("..", import.meta.url).pathname);
const socketName = `pi-gui-tmux-test-${process.pid}`;

async function tmux(...args) {
  return execFileAsync("tmux", ["-L", socketName, ...args], { cwd: repoRoot });
}

after(async () => {
  await tmux("kill-server").catch(() => {});
});

describe("macOS GUI tmux server", { skip: process.platform !== "darwin" }, () => {
  it("keeps an empty default-style server ready for Moshi directory sessions", async () => {
    await tmux("start-server", ";", "set-option", "-g", "exit-empty", "off");
    const option = await tmux("show-options", "-g", "-v", "exit-empty");
    assert.equal(option.stdout.trim(), "off");

    const emptySessions = await tmux("list-sessions", "-F", "#{session_name}");
    assert.equal(emptySessions.stdout, "");

    await tmux("new-session", "-d", "-s", "webdev", "-c", os.tmpdir());
    const context = await tmux(
      "display-message",
      "-p",
      "-t",
      "webdev:0.0",
      "#{session_name}|#{pane_current_path}",
    );
    assert.equal(context.stdout.trim(), `webdev|${realpathSync(os.tmpdir()).replace(/\/$/, "")}`);
  });

  it("refuses one-time activation from tmux or remote-login contexts", async () => {
    await assert.rejects(
      execFileAsync(path.join(repoRoot, "scripts/activate-macos-tmux-gui-server.sh"), [], {
        cwd: repoRoot,
        env: { ...process.env, TMUX: "diagnostic" },
      }),
      (error) => {
        assert.match(error.stderr, /Refusing to activate from tmux, SSH, or Mosh/);
        return true;
      },
    );
  });

  it("lets setup defer activation safely in a remote or tmux context", async () => {
    const result = await execFileAsync(
      path.join(repoRoot, "scripts/activate-macos-tmux-gui-server.sh"),
      ["--auto"],
      {
        cwd: repoRoot,
        env: { ...process.env, TMUX: "diagnostic" },
      },
    );

    assert.match(result.stdout, /activation deferred: setup is running from tmux, SSH, or Mosh/);
    assert.match(result.stdout, /automatically at the next macOS login/);
  });
});
