import { closeSync, existsSync, mkdtempSync, openSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawn } from "node:child_process";

const CHECK_TIMEOUT_MS = 15 * 60 * 1000;
const APPLY_SCRIPT = `
set -eu
repo="$1"
printf 'Waiting for every Pi process to exit...\\n'
while pgrep -x pi >/dev/null 2>&1; do
  sleep 1
done
cd "$repo"
./setup.sh
./scripts/drift.sh
printf 'Setup applied and drift verified. Start Pi again from the setup repository.\\n'
`;

export function findSetupRoot(cwd, fileExists = existsSync) {
	let current = resolve(cwd);
	while (true) {
		if (fileExists(join(current, "setup.sh")) && fileExists(join(current, "config", "manifest.json"))) {
			return current;
		}
		const parent = dirname(current);
		if (parent === current) return undefined;
		current = parent;
	}
}

export function summarizeFailure(result) {
	const output = `${result.stderr}\n${result.stdout}`
		.trim()
		.split(/\r?\n/)
		.filter(Boolean);
	return output.slice(-6).join("\n") || `exit code ${result.code}`;
}

export function localGitReplacements(root) {
	const settingsPath = join(root, "settings.local.json");
	if (!existsSync(settingsPath)) return [];
	const settings = JSON.parse(readFileSync(settingsPath, "utf8"));
	const replacements = settings?.packageReplacements;
	if (!replacements || typeof replacements !== "object" || Array.isArray(replacements)) return [];
	return Object.entries(replacements)
		.filter(([source, target]) => source.startsWith("git:") && typeof target === "string")
		.map(([source, target]) => ({ source, path: resolve(root, target) }));
}

export async function syncLocalGitCheckouts(root, exec) {
	const synced = [];
	const seen = new Set();
	for (const replacement of localGitReplacements(root)) {
		if (seen.has(replacement.path)) continue;
		seen.add(replacement.path);
		const status = await exec("git", ["-C", replacement.path, "status", "--porcelain"], {
			cwd: root,
			timeout: 30_000,
		});
		if (status.code !== 0) {
			return { ok: false, message: `Could not inspect ${replacement.path}: ${summarizeFailure(status)}` };
		}
		if (status.stdout.trim()) {
			return { ok: false, message: `${replacement.path} has uncommitted changes; commit or stash them before /sync-me.` };
		}
		const pull = await exec("git", ["-C", replacement.path, "pull", "--ff-only"], {
			cwd: root,
			timeout: 120_000,
		});
		if (pull.code !== 0) {
			return { ok: false, message: `Could not fast-forward ${replacement.path}: ${summarizeFailure(pull)}` };
		}
		synced.push(replacement.path);
	}
	return { ok: true, synced };
}

function startApply(root) {
	const directory = mkdtempSync(join(tmpdir(), "pi-sync-me-"));
	const logPath = join(directory, "apply.log");
	const log = openSync(logPath, "a");
	try {
		const child = spawn(process.env.SHELL || "/bin/sh", ["-c", APPLY_SCRIPT, "sync-me", root], {
			cwd: root,
			detached: true,
			stdio: ["ignore", log, log],
		});
		child.unref();
		return { logPath, pid: child.pid };
	} finally {
		closeSync(log);
	}
}

export default function setupSync(pi) {
	pi.registerCommand("sync-me", {
		description: "Validate and apply this setup after Pi sessions close",
		handler: async (args, ctx) => {
			if (args.trim()) {
				ctx.ui.notify("Usage: /sync-me", "warning");
				return;
			}
			if (!ctx.hasUI) {
				ctx.ui.notify("/sync-me requires an interactive Pi session.", "error");
				return;
			}

			const root = findSetupRoot(ctx.cwd);
			if (!root) {
				ctx.ui.notify("Run /sync-me from ~/Developer/my-pi-setup.", "error");
				return;
			}

			const confirmed = await ctx.ui.confirm(
				"Apply the Pi setup after shutdown?",
				"Fast-forwards clean local Git package replacements, runs the full checks, waits for every Pi process to exit, applies the current checkout, and verifies drift. It does not pull the setup repository, push, commit, or upgrade pinned packages.",
			);
			if (!confirmed) {
				ctx.ui.notify("Setup apply cancelled.", "info");
				return;
			}

			ctx.ui.notify("Updating clean local package checkouts...", "info");
			const localSync = await syncLocalGitCheckouts(root, (command, commandArgs, options) =>
				pi.exec(command, commandArgs, options),
			);
			if (!localSync.ok) {
				ctx.ui.notify(`Local package sync failed: ${localSync.message}`, "error");
				return;
			}

			ctx.ui.notify("Local packages synced. Running setup checks before shutdown...", "info");
			const checks = await pi.exec(
				"bash",
				["-c", "./scripts/check.sh && npm pack --dry-run >/dev/null"],
				{ cwd: root, timeout: CHECK_TIMEOUT_MS },
			);
			if (checks.code !== 0) {
				ctx.ui.notify(`Setup checks failed:\n${summarizeFailure(checks)}`, "error");
				return;
			}

			try {
				const { logPath } = startApply(root);
				ctx.ui.notify(
					`Checks passed. Pi will close, then setup will wait for other Pi sessions and apply the checkout. Log: ${logPath}`,
					"info",
				);
				ctx.shutdown();
			} catch (error) {
				const message = error instanceof Error ? error.message : String(error);
				ctx.ui.notify(`Could not schedule setup apply: ${message}`, "error");
			}
		},
	});
}
