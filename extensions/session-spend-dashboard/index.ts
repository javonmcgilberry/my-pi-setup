import { spawn } from "node:child_process";
import type { AutocompleteItem } from "@earendil-works/pi-tui";
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";

import { registerActiveSession, unregisterActiveSession } from "./active-sessions.ts";
import { runMaintenance } from "./maintenance.ts";
import { defaultAgentDir, defaultSessionsDir } from "./scan.ts";
import { DEFAULT_PORT, startServer, type RunningServer } from "./server.ts";

const STATUS_KEY = "spend-dashboard";
const ACTIONS = ["start", "stop", "restart", "status", "open", "maintain"] as const;

type Action = (typeof ACTIONS)[number];

function isAction(value: string): value is Action {
	return ACTIONS.some((action) => action === value);
}

const USAGE = [
	"/spend-dashboard start    launch the read-only dashboard",
	"/spend-dashboard stop     shut the dashboard down",
	"/spend-dashboard restart  relaunch it",
	"/spend-dashboard status   show whether it is running",
	"/spend-dashboard open     open it in your browser",
	"/spend-dashboard maintain import metrics and preview expired chat trees",
	"",
	`Add a port to override ${DEFAULT_PORT}, for example: /spend-dashboard start 4400`,
].join("\n");

function openInBrowser(url: string): void {
	const command = process.platform === "darwin" ? "open" : process.platform === "win32" ? "cmd" : "xdg-open";
	const args = process.platform === "win32" ? ["/c", "start", "", url] : [url];
	const child = spawn(command, args, { stdio: "ignore", detached: true });
	// A missing browser opener must not take the Pi session down with it.
	child.on("error", () => {});
	child.unref();
}

function formatBytes(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export default function (pi: ExtensionAPI) {
	let server: RunningServer | undefined;
	const agentDir = () => defaultAgentDir();

	function setStatus(ctx: ExtensionCommandContext): void {
		ctx.ui.setStatus(STATUS_KEY, server ? `spend :${server.port}` : undefined);
	}

	async function stop(): Promise<void> {
		const running = server;
		server = undefined;
		await running?.close();
	}

	async function start(ctx: ExtensionCommandContext, port: number): Promise<void> {
		if (server) {
			ctx.ui.notify(`Spend dashboard already running at ${server.url}`, "info");
			return;
		}
		const sessionsRoot = defaultSessionsDir();
		try {
			server = await startServer({ sessionsRoot, agentDir: agentDir(), port });
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			const hint = message.includes("EADDRINUSE") ? ` Port ${port} is already in use; pass another port.` : "";
			ctx.ui.notify(`Could not start the spend dashboard: ${message}.${hint}`, "error");
			return;
		}
		setStatus(ctx);
		ctx.ui.notify(`Spend dashboard reading ${sessionsRoot} at ${server.url}`, "info");
	}

	async function maintain(ctx: ExtensionCommandContext): Promise<void> {
		const sessionsRoot = defaultSessionsDir();
		const current = ctx.sessionManager.getSessionFile();
		try {
			const report = await runMaintenance({
				sessionsRoot,
				agentDir: agentDir(),
				dryRun: true,
				activeFiles: current ? new Set([current]) : new Set(),
			});
			ctx.ui.notify(
				[
					`Eligible: ${report.eligibleTrees} trees (${report.eligibleFiles} files, ${formatBytes(report.eligibleBytes)})`,
					`Protected active trees: ${report.protectedTrees}`,
					`Metrics ledger: ${report.archivedSessions} sessions, ${report.archivedUsageRecords} usage records, ${report.archivedToolCalls} tool calls`,
					`Retention: chats ${report.chatRetentionDays} days; metrics ${report.metricsRetentionDays} days`,
					"Close every Pi session, then run `node scripts/session-maintenance.mjs --apply` from my-pi-setup to delete eligible chats.",
				].join("\n"),
				"info",
			);
		} catch (error) {
			ctx.ui.notify(`Session maintenance failed: ${error instanceof Error ? error.message : String(error)}`, "error");
		}
	}

	function parse(args: string): { action: Action; port: number } | { error: string } {
		const parts = args.trim().split(/\s+/).filter(Boolean);
		const [rawAction = "status", rawPort] = parts;
		if (!isAction(rawAction)) {
			return { error: `Unknown action "${rawAction}".\n\n${USAGE}` };
		}
		if (rawPort === undefined) return { action: rawAction, port: DEFAULT_PORT };

		const port = Number(rawPort);
		if (!Number.isInteger(port) || port < 1024 || port > 65535) {
			return { error: `Port must be a whole number between 1024 and 65535, got "${rawPort}".\n\n${USAGE}` };
		}
		if (parts.length > 2) return { error: `Too many arguments.\n\n${USAGE}` };
		return { action: rawAction, port };
	}

	pi.registerCommand("spend-dashboard", {
		description: "Read-only localhost spend dashboard with content-free session retention",
		getArgumentCompletions: (prefix: string): AutocompleteItem[] | null => {
			const matches = ACTIONS.filter((action) => action.startsWith(prefix.trim()));
			return matches.length > 0 ? matches.map((action) => ({ value: action, label: action })) : null;
		},
		handler: async (args: string, ctx: ExtensionCommandContext) => {
			const parsed = parse(args);
			if ("error" in parsed) {
				ctx.ui.notify(parsed.error, "warning");
				return;
			}

			const { action, port } = parsed;

			if (action === "maintain") {
				await maintain(ctx);
				return;
			}

			if (action === "start") {
				await start(ctx, port);
				return;
			}

			if (action === "stop") {
				if (!server) {
					ctx.ui.notify("Spend dashboard is not running.", "info");
					return;
				}
				await stop();
				setStatus(ctx);
				ctx.ui.notify("Spend dashboard stopped.", "info");
				return;
			}

			if (action === "restart") {
				await stop();
				await start(ctx, port);
				return;
			}

			if (action === "open") {
				if (!server) await start(ctx, port);
				if (!server) return;
				openInBrowser(server.url);
				ctx.ui.notify(`Opening ${server.url}`, "info");
				return;
			}

			if (!server) {
				ctx.ui.notify(`Spend dashboard is stopped. Run /spend-dashboard start to launch it on port ${port}.`, "info");
				return;
			}

			const state = server.getState();
			const lines = [
				`Running at ${server.url}`,
				`Sessions root: ${defaultSessionsDir()}`,
				`Watching for changes: ${state.watching ? "yes" : "no, polling only"}`,
				`Connected browsers: ${state.clients}`,
				state.snapshot
					? `Tracking ${state.snapshot.totals.sessions} sessions across ${state.snapshot.totals.projects} projects`
					: state.error
						? `Last scan failed: ${state.error}`
						: "First scan still running",
			];
			ctx.ui.notify(lines.join("\n"), "info");
		},
	});

	pi.on("session_start", async (_event, ctx) => {
		try {
			await registerActiveSession(agentDir(), ctx.sessionManager.getSessionFile());
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			ctx.ui.notify(`Pi cannot start safely: ${message}`, "error");
			ctx.shutdown();
		}
	});

	pi.on("session_shutdown", async () => {
		await stop();
		await unregisterActiveSession(agentDir());
	});
}
