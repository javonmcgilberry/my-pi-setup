import {
	closeSync,
	existsSync,
	mkdirSync,
	openSync,
	readFileSync,
	writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawn } from "node:child_process";

import {
	applyGitPinUpdates,
	parseGitPin,
	planGitPinUpdate,
} from "./setup-update.js";

const CHECK_TIMEOUT_MS = 15 * 60 * 1000;
const STATUS_KEY = "sync-me";

/** Fast pre-shutdown gate. The full matrix runs detached, once no Pi session is waiting on it. */
export const CHECK_COMMAND =
	"./scripts/check.sh --fast && npm pack --dry-run >/dev/null";

export const LEGACY_UPDATE_MESSAGE =
	"`/sync-me update` is retired. Exit Pi and run `pi update --extensions` for registry packages, or use `/sync-me publish` to publish owned Git checkouts.";

/** Git never gets to open an interactive credential prompt that nobody can answer. */
export function gitCommand(args) {
	return ["env", ["GIT_TERMINAL_PROMPT=0", "git", ...args]];
}

export const APPLY_SCRIPT = `
set -eu
repo="$1"
cd "$repo"
waited=0
while pgrep -x pi >/dev/null 2>&1; do
  if [ "$(( waited % 15 ))" -eq 0 ]; then
    printf 'Waiting for these Pi processes to exit: %s\\n' "$(pgrep -x pi | tr '\\n' ' ')"
  fi
  sleep 1
  waited=$(( waited + 1 ))
done
printf 'All Pi sessions closed. Running the full checks...\\n'
if ! ./scripts/check.sh; then
  printf 'FAILED: the full checks did not pass. Setup was NOT applied.\\n'
  exit 1
fi
./setup.sh
./scripts/drift.sh
printf 'Setup applied and drift verified. Start Pi again from the setup repository.\\n'
`;

export function applyLogPath(env = process.env, home = homedir()) {
	return join(env.PI_AGENT_DIR || join(home, ".pi", "agent"), "sync-me.log");
}

/** Footer progress, so a multi-second step never looks like a frozen session. */
function startProgress(ctx, label) {
	const started = Date.now();
	const render = () => {
		const seconds = Math.round((Date.now() - started) / 1000);
		ctx.ui.setStatus(STATUS_KEY, `${label} (${seconds}s)`);
	};
	render();
	const timer = setInterval(render, 1000);
	timer.unref?.();
	return () => {
		clearInterval(timer);
		ctx.ui.setStatus(STATUS_KEY, undefined);
	};
}

/** Match a local checkout back to the tracked git pin it replaces. */
export function trackedPinFor(packages, replacementSource) {
	return packages.find((source) => {
		const pin = parseGitPin(source);
		return pin?.locator === replacementSource;
	});
}

/**
 * Bring one local checkout to a state whose HEAD is safe to pin: clean, and
 * present on a remote branch. Dirty work is only ever committed after the user
 * supplies a message and confirms both the commit and the push.
 */
export async function readyCheckoutForPinning(checkout, exec, ctx) {
	const run = (args, timeout = 30_000) =>
		exec(...gitCommand(["-C", checkout, ...args]), { cwd: checkout, timeout });
	const headIsPublished = async () => {
		const remote = await run(["branch", "-r", "--contains", "HEAD"]);
		return remote.code === 0 && remote.stdout.trim().length > 0;
	};

	const status = await run(["status", "--porcelain"]);
	if (status.code !== 0) {
		return {
			ok: false,
			message: `Could not inspect ${checkout}: ${summarizeFailure(status)}`,
		};
	}

	if (status.stdout.trim()) {
		const files = status.stdout.trim().split(/\r?\n/);
		const preview = files.slice(0, 10).join("\n");
		const extra = files.length > 10 ? `\n...and ${files.length - 10} more` : "";
		const message = await ctx.ui.input(
			`Commit message for ${files.length} changed file(s) in ${checkout}`,
			"Leave empty to cancel",
		);
		if (!message?.trim()) {
			return {
				ok: false,
				message: `${checkout} has uncommitted changes; nothing was committed.`,
			};
		}
		const confirmed = await ctx.ui.confirm(
			`Commit and push to ${checkout}?`,
			`${preview}${extra}\n\nMessage: ${message.trim()}\n\nThis pushes to the public remote. Nothing else is published.`,
		);
		if (!confirmed) {
			return { ok: false, message: "Commit cancelled; no pin was changed." };
		}
		const staged = await run(["add", "-A"]);
		if (staged.code !== 0) {
			return {
				ok: false,
				message: `Could not stage ${checkout}: ${summarizeFailure(staged)}`,
			};
		}
		const committed = await run(["commit", "-m", message.trim()]);
		if (committed.code !== 0) {
			return {
				ok: false,
				message: `Could not commit ${checkout}: ${summarizeFailure(committed)}`,
			};
		}
	}

	// A pin is only installable once the commit exists on a remote branch. A clean
	// checkout that is already published needs no network write at all.
	if (!(await headIsPublished())) {
		const pushed = await run(["push"], 120_000);
		if (pushed.code !== 0) {
			return {
				ok: false,
				message: `Could not push ${checkout}: ${summarizeFailure(pushed)}`,
			};
		}
		if (!(await headIsPublished())) {
			return {
				ok: false,
				message: `HEAD of ${checkout} is not on any remote branch; it cannot be pinned.`,
			};
		}
	}
	const head = await run(["rev-parse", "HEAD"]);
	if (head.code !== 0) {
		return {
			ok: false,
			message: `Could not read HEAD of ${checkout}: ${summarizeFailure(head)}`,
		};
	}
	return { ok: true, head: head.stdout.trim() };
}

export function describeUpdates(updates) {
	return updates
		.map((update) => `  ${update.name}  ${update.from} → ${update.to}`)
		.join("\n");
}

export function findSetupRoot(cwd, fileExists = existsSync) {
	let current = resolve(cwd);
	while (true) {
		if (
			fileExists(join(current, "setup.sh")) &&
			fileExists(join(current, "config", "manifest.json"))
		) {
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
	let settings;
	try {
		settings = JSON.parse(readFileSync(settingsPath, "utf8"));
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		throw new Error(`Could not read ${settingsPath}: ${message}`, {
			cause: error,
		});
	}
	const replacements = settings?.packageReplacements;
	if (
		!replacements ||
		typeof replacements !== "object" ||
		Array.isArray(replacements)
	)
		return [];
	return Object.entries(replacements)
		.filter(
			([source, target]) =>
				source.startsWith("git:") && typeof target === "string",
		)
		.map(([source, target]) => ({ source, path: resolve(root, target) }));
}

export async function syncLocalGitCheckouts(root, exec) {
	const synced = [];
	const seen = new Set();
	for (const replacement of localGitReplacements(root)) {
		if (seen.has(replacement.path)) continue;
		seen.add(replacement.path);
		const status = await exec(
			...gitCommand(["-C", replacement.path, "status", "--porcelain"]),
			{
				cwd: root,
				timeout: 30_000,
			},
		);
		if (status.code !== 0) {
			return {
				ok: false,
				message: `Could not inspect ${replacement.path}: ${summarizeFailure(status)}`,
			};
		}
		if (status.stdout.trim()) {
			return {
				ok: false,
				message: `${replacement.path} has uncommitted changes; commit or stash them before /sync-me.`,
			};
		}
		const pull = await exec(
			...gitCommand(["-C", replacement.path, "pull", "--ff-only"]),
			{
				cwd: root,
				timeout: 120_000,
			},
		);
		if (pull.code !== 0) {
			return {
				ok: false,
				message: `Could not fast-forward ${replacement.path}: ${summarizeFailure(pull)}`,
			};
		}
		synced.push(replacement.path);
	}
	return { ok: true, synced };
}

function startApply(root) {
	const logPath = applyLogPath();
	mkdirSync(dirname(logPath), { recursive: true });
	const log = openSync(logPath, "w");
	try {
		const child = spawn(
			process.env.SHELL || "/bin/sh",
			["-c", APPLY_SCRIPT, "sync-me", root],
			{
				cwd: root,
				detached: true,
				stdio: ["ignore", log, log],
			},
		);
		child.unref();
		return { logPath, pid: child.pid };
	} finally {
		closeSync(log);
	}
}

/**
 * Every commit this extension makes goes through scripts/land.sh, the single
 * supported commit path. The script runs check.sh before staging, so the secret
 * scan, forbidden-path scan, and manifest inventory check can never be skipped
 * by committing from here.
 */
async function land(pi, ctx, root, { message, paths = [], push = false }) {
	const args = ["--message", message];
	for (const pathspec of paths) args.push("--path", pathspec);
	if (push) args.push("--push");

	const stop = startProgress(ctx, "sync-me: validating and committing");
	const result = await pi
		.exec("./scripts/land.sh", args, { cwd: root, timeout: CHECK_TIMEOUT_MS })
		.finally(stop);
	if (result.code !== 0) {
		return {
			ok: false,
			message: `Nothing was committed:\n${summarizeFailure(result)}`,
		};
	}
	return { ok: true, stdout: result.stdout };
}

/** A commit message that names what actually moved, so history stays readable. */
export function defaultCommitMessage(updates) {
	const subject = `chore: update ${updates.length} tracked pin${updates.length === 1 ? "" : "s"}`;
	return `${subject}\n\n${updates.map((update) => `${update.name} ${update.from} -> ${update.to}`).join("\n")}\n`;
}

/**
 * Shut this session down and hand the apply to a detached helper. Shared by
 * `/sync-me` and the tail of `/sync-me publish`.
 */
async function runApply(pi, ctx, root) {
	// Applying a dirty tree puts source into the live setup that exists in no
	// commit, which is how the live install and the repository drift apart.
	const status = await pi.exec(
		...gitCommand(["-C", root, "status", "--porcelain"]),
		{
			cwd: root,
			timeout: 30_000,
		},
	);
	if (status.code === 0 && status.stdout.trim()) {
		const files = status.stdout.trim().split(/\r?\n/);
		const preview = files.slice(0, 10).join("\n");
		const extra = files.length > 10 ? `\n...and ${files.length - 10} more` : "";
		const commitFirst = await ctx.ui.confirm(
			`Commit ${files.length} uncommitted change(s) before applying?`,
			`${preview}${extra}\n\nApplying without committing puts source into your live setup that exists in no commit. Decline to apply anyway.`,
		);
		if (commitFirst) {
			const message = await ctx.ui.input(
				"Commit message",
				"Leave empty to cancel",
			);
			if (!message?.trim()) {
				ctx.ui.notify("Nothing was committed and nothing was applied.", "info");
				return;
			}
			const landed = await land(pi, ctx, root, { message: message.trim() });
			if (!landed.ok) {
				ctx.ui.notify(landed.message, "error");
				return;
			}
			ctx.ui.notify("Committed. Continuing with the apply...", "info");
		}
	}

	ctx.ui.notify("Updating clean local package checkouts...", "info");
	const stopSyncProgress = startProgress(
		ctx,
		"sync-me: updating local package checkouts",
	);
	const localSync = await syncLocalGitCheckouts(
		root,
		(command, commandArgs, options) => pi.exec(command, commandArgs, options),
	).finally(stopSyncProgress);
	if (!localSync.ok) {
		ctx.ui.notify(`Local package sync failed: ${localSync.message}`, "error");
		return;
	}

	ctx.ui.notify(
		"Local packages synced. Running fast checks before shutdown...",
		"info",
	);
	const stopCheckProgress = startProgress(ctx, "sync-me: running fast checks");
	const checks = await pi
		.exec("bash", ["-c", CHECK_COMMAND], {
			cwd: root,
			timeout: CHECK_TIMEOUT_MS,
		})
		.finally(stopCheckProgress);
	if (checks.code !== 0) {
		ctx.ui.notify(`Fast checks failed:\n${summarizeFailure(checks)}`, "error");
		return;
	}

	try {
		const { logPath } = startApply(root);
		ctx.ui.notify(
			`Fast checks passed. Pi will close, then the helper waits for other Pi sessions, runs the full checks, and applies the checkout. Follow it with: tail -f ${logPath}`,
			"info",
		);
		ctx.shutdown();
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		ctx.ui.notify(`Could not schedule setup apply: ${message}`, "error");
	}
}

/**
 * Review, validate, and commit the pin changes without leaving Pi. Each step is
 * a gate: declining any of them stops the chain and leaves the edited
 * settings.json in place to finish by hand.
 */
async function reviewAndCommit(pi, ctx, root, updates) {
	const git = (args, timeout = 30_000) =>
		pi.exec(...gitCommand(["-C", root, ...args]), { cwd: root, timeout });

	const diff = await git(["diff", "--", "settings.json"]);
	if (diff.code !== 0) {
		ctx.ui.notify(
			`Could not read the diff: ${summarizeFailure(diff)}`,
			"error",
		);
		return;
	}
	const changed = diff.stdout
		.split(/\r?\n/)
		.filter((line) => /^[+-]\s*"/.test(line))
		.join("\n");

	if (
		!(await ctx.ui.confirm(
			"Run the fast checks on these changes?",
			`${changed}\n\nDeclining leaves settings.json edited so you can finish by hand.`,
		))
	) {
		ctx.ui.notify(
			"Stopped before checks. settings.json is still edited.",
			"info",
		);
		return;
	}

	const suggested = defaultCommitMessage(updates);
	const typed = await ctx.ui.input(
		"Commit message (empty accepts the suggested one)",
		suggested.split("\n", 1)[0],
	);
	if (typed === undefined) {
		ctx.ui.notify("Commit cancelled. settings.json is still edited.", "info");
		return;
	}

	const landed = await land(pi, ctx, root, {
		message: typed.trim() ? typed.trim() : suggested,
		paths: ["settings.json"],
	});
	if (!landed.ok) {
		ctx.ui.notify(landed.message, "error");
		return;
	}
	ctx.ui.notify("Checks passed and settings.json is committed.", "info");

	if (
		await ctx.ui.confirm(
			"Apply the setup now?",
			"Pi closes, then a detached helper waits for every Pi process to exit, runs the full checks, applies the checkout, and verifies drift. Decline to keep working and run /sync-me later.",
		)
	) {
		await runApply(pi, ctx, root);
		return;
	}
	ctx.ui.notify("Committed. Run /sync-me when you want to apply.", "info");
}

/**
 * `/sync-me publish`: advance tracked Git pins from owned local checkouts, then
 * walk the review, check, commit, and apply gates without leaving Pi.
 *
 * It never writes live settings. Every mutation is behind its own confirmation.
 */
async function runPublish(pi, ctx, root) {
	const settingsPath = join(root, "settings.json");
	const settingsText = readFileSync(settingsPath, "utf8");
	let packages;
	try {
		packages = JSON.parse(settingsText).packages ?? [];
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		ctx.ui.notify(`Could not read ${settingsPath}: ${message}`, "error");
		return;
	}
	const exec = (command, commandArgs, options) =>
		pi.exec(command, commandArgs, options);

	// Local checkouts first: a git pin can only move to a commit that is pushed.
	const gitUpdates = [];
	for (const replacement of localGitReplacements(root)) {
		const pinned = trackedPinFor(packages, replacement.source);
		if (!pinned) continue;
		const ready = await readyCheckoutForPinning(replacement.path, exec, ctx);
		if (!ready.ok) {
			ctx.ui.notify(ready.message, "warning");
			continue;
		}
		const update = planGitPinUpdate(pinned, ready.head);
		if (update) gitUpdates.push(update);
	}

	if (gitUpdates.length === 0) {
		ctx.ui.notify("No publishable Git pin changes were found.", "info");
		return;
	}

	const confirmed = await ctx.ui.confirm(
		`Write ${gitUpdates.length} Git pin update(s) to settings.json?`,
		`${describeUpdates(gitUpdates)}\n\nThis publishes owned Git checkout commits into tracked settings.json. It does not update registry packages, touch live settings, or apply the setup.`,
	);
	if (!confirmed) {
		ctx.ui.notify("No pins were changed.", "info");
		return;
	}

	try {
		writeFileSync(settingsPath, applyGitPinUpdates(settingsText, gitUpdates));
	} catch (error) {
		const message = error instanceof Error ? error.message : String(error);
		ctx.ui.notify(`Could not update settings.json: ${message}`, "error");
		return;
	}

	ctx.ui.notify(
		`Published ${gitUpdates.length} Git pin(s) to settings.json.`,
		"info",
	);
	await reviewAndCommit(pi, ctx, root, gitUpdates);
}

export default function setupSync(pi) {
	pi.registerCommand("sync-me", {
		description:
			"Apply this setup, or publish owned Git checkout commits",
		handler: async (args, ctx) => {
			const subcommand = args.trim();
			if (subcommand === "update") {
				ctx.ui.notify(LEGACY_UPDATE_MESSAGE, "warning");
				return;
			}
			if (subcommand && subcommand !== "publish") {
				ctx.ui.notify("Usage: /sync-me [publish]", "warning");
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

			if (subcommand === "publish") {
				await runPublish(pi, ctx, root);
				return;
			}

			const confirmed = await ctx.ui.confirm(
				"Apply the Pi setup after shutdown?",
				"Fast-forwards clean local Git package replacements, runs the fast checks, then shuts this session down. A detached helper waits for every Pi process to exit, runs the full checks, applies the current checkout, and verifies drift. It does not pull the setup repository, publish Git pins, or update registry packages.",
			);
			if (!confirmed) {
				ctx.ui.notify("Setup apply cancelled.", "info");
				return;
			}

			await runApply(pi, ctx, root);
		},
	});
}
