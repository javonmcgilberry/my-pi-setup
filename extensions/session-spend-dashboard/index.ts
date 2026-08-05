import { spawn } from "node:child_process";
import type { AutocompleteItem } from "@earendil-works/pi-tui";
import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";

import { defaultSessionsDir } from "./scan.ts";
import { DEFAULT_PORT, startServer, type RunningServer } from "./server.ts";

const STATUS_KEY = "spend-dashboard";
const ACTIONS = ["start", "stop", "restart", "status", "open"] as const;

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

export default function (pi: ExtensionAPI) {
	let server: RunningServer | undefined;

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
			server = await startServer({ sessionsRoot, port });
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			const hint = message.includes("EADDRINUSE") ? ` Port ${port} is already in use; pass another port.` : "";
			ctx.ui.notify(`Could not start the spend dashboard: ${message}.${hint}`, "error");
			return;
		}
		setStatus(ctx);
		ctx.ui.notify(`Spend dashboard reading ${sessionsRoot} at ${server.url}`, "info");
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
		description: "Read-only localhost dashboard for Pi session spend and activity",
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

	pi.on("session_shutdown", async () => {
		await stop();
	});
}
