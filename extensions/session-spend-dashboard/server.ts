import { watch, type FSWatcher } from "node:fs";
import http from "node:http";
import type { IncomingMessage, ServerResponse } from "node:http";

import { aggregate, type Snapshot } from "./aggregate.ts";
import { APP_CSS, APP_JS, INDEX_HTML } from "./assets.ts";
import { readRunSnapshot } from "./runs.ts";
import { SessionScanner } from "./scan.ts";

export const DEFAULT_PORT = 4310;
export const HOST = "127.0.0.1";

const DEBOUNCE_MS = 750;
const SAFETY_REFRESH_MS = 30_000;
const HEARTBEAT_MS = 25_000;
const MAX_STREAM_CLIENTS = 24;

const ALLOWED_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);

export interface ServerOptions {
	sessionsRoot: string;
	port?: number;
}

export interface RunningServer {
	port: number;
	url: string;
	/** Bound interface, asserted by tests to prove the dashboard is loopback-only. */
	address: string;
	close: () => Promise<void>;
	getState: () => DashboardState;
}

export interface DashboardState {
	snapshot?: Snapshot;
	error?: string;
	scanning: boolean;
	clients: number;
	watching: boolean;
}

/** Blocks DNS-rebinding: a remote name resolving to 127.0.0.1 cannot read session data. */
function hostAllowed(header: string | undefined): boolean {
	if (!header) return false;
	const withoutPort = header.startsWith("[") ? header.slice(0, header.indexOf("]") + 1) : header.split(":")[0];
	return ALLOWED_HOSTS.has(withoutPort ?? "");
}

function securityHeaders(contentType: string): Record<string, string> {
	return {
		"content-type": contentType,
		"cache-control": "no-store",
		"x-content-type-options": "nosniff",
		"referrer-policy": "no-referrer",
		"content-security-policy":
			"default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'",
	};
}

export async function startServer(options: ServerOptions): Promise<RunningServer> {
	const port = options.port ?? DEFAULT_PORT;
	const scanner = new SessionScanner(options.sessionsRoot);
	const clients = new Set<ServerResponse>();

	const state: DashboardState = { scanning: false, clients: 0, watching: false };
	let refreshQueued = false;
	let debounceTimer: NodeJS.Timeout | undefined;
	let closed = false;

	async function refresh(): Promise<void> {
		if (state.scanning) {
			refreshQueued = true;
			return;
		}
		state.scanning = true;
		try {
			const started = Date.now();
			const files = await scanner.scan();
			const runs = await readRunSnapshot();
			state.snapshot = aggregate(files, {
				sessionsRoot: options.sessionsRoot,
				now: Date.now(),
				scanDurationMs: Date.now() - started,
				runs,
			});
			state.error = undefined;
		} catch (error) {
			state.error = error instanceof Error ? error.message : String(error);
		} finally {
			state.scanning = false;
		}

		broadcast();

		if (refreshQueued && !closed) {
			refreshQueued = false;
			void refresh();
		}
	}

	function scheduleRefresh(): void {
		if (closed) return;
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => {
			debounceTimer = undefined;
			void refresh();
		}, DEBOUNCE_MS);
	}

	function payload(): string {
		if (state.snapshot) return JSON.stringify(state.snapshot);
		return JSON.stringify({ pending: true, scanning: state.scanning, error: state.error ?? null });
	}

	function broadcast(): void {
		const data = payload();
		for (const client of clients) {
			client.write(`event: snapshot\ndata: ${data}\n\n`);
		}
	}

	const server = http.createServer((req, res) => {
		if (!hostAllowed(req.headers.host)) {
			res.writeHead(421, securityHeaders("application/json")).end(JSON.stringify({ error: "host not allowed" }));
			return;
		}

		const method = req.method ?? "GET";
		if (method !== "GET" && method !== "HEAD") {
			res.writeHead(405, { ...securityHeaders("application/json"), allow: "GET, HEAD" }).end(
				JSON.stringify({ error: "read-only dashboard: only GET and HEAD are supported" }),
			);
			return;
		}

		const route = (req.url ?? "/").split("?")[0];
		const headOnly = method === "HEAD";

		if (route === "/api/stream") {
			handleStream(req, res, headOnly);
			return;
		}

		const asset = staticAsset(route);
		if (asset) {
			res.writeHead(200, securityHeaders(asset.type));
			res.end(headOnly ? undefined : asset.body);
			return;
		}

		if (route === "/api/snapshot") {
			res.writeHead(200, securityHeaders("application/json"));
			res.end(headOnly ? undefined : payload());
			return;
		}

		if (route === "/api/health") {
			res.writeHead(200, securityHeaders("application/json"));
			res.end(
				headOnly
					? undefined
					: JSON.stringify({
							ok: true,
							scanning: state.scanning,
							watching: state.watching,
							clients: clients.size,
							hasSnapshot: state.snapshot !== undefined,
							sessionsRoot: options.sessionsRoot,
						}),
			);
			return;
		}

		res.writeHead(404, securityHeaders("application/json"));
		res.end(headOnly ? undefined : JSON.stringify({ error: "not found" }));
	});

	function handleStream(req: IncomingMessage, res: ServerResponse, headOnly: boolean): void {
		if (headOnly) {
			res.writeHead(200, securityHeaders("text/event-stream")).end();
			return;
		}
		if (clients.size >= MAX_STREAM_CLIENTS) {
			res.writeHead(503, securityHeaders("application/json")).end(JSON.stringify({ error: "too many stream clients" }));
			return;
		}

		res.writeHead(200, { ...securityHeaders("text/event-stream"), connection: "keep-alive" });
		res.write(`retry: 3000\n\n`);
		res.write(`event: snapshot\ndata: ${payload()}\n\n`);
		clients.add(res);
		state.clients = clients.size;

		const heartbeat = setInterval(() => res.write(": ping\n\n"), HEARTBEAT_MS);
		const drop = () => {
			clearInterval(heartbeat);
			clients.delete(res);
			state.clients = clients.size;
		};
		req.on("close", drop);
		res.on("close", drop);
		res.on("error", drop);
	}

	await new Promise<void>((resolve, reject) => {
		server.once("error", reject);
		server.listen(port, HOST, () => {
			server.removeListener("error", reject);
			resolve();
		});
	});

	const bound = server.address();
	const boundPort = typeof bound === "object" && bound !== null ? bound.port : port;
	const boundAddress = typeof bound === "object" && bound !== null ? bound.address : HOST;

	let watcher: FSWatcher | undefined;
	try {
		watcher = watch(options.sessionsRoot, { recursive: true, persistent: false }, () => scheduleRefresh());
		watcher.on("error", () => {
			watcher?.close();
			watcher = undefined;
			state.watching = false;
		});
		state.watching = true;
	} catch {
		state.watching = false;
	}

	const safety = setInterval(() => scheduleRefresh(), SAFETY_REFRESH_MS);
	safety.unref();

	void refresh();

	return {
		port: boundPort,
		address: boundAddress,
		url: `http://${HOST}:${boundPort}/`,
		getState: () => ({ ...state, clients: clients.size }),
		close: async () => {
			closed = true;
			if (debounceTimer) clearTimeout(debounceTimer);
			clearInterval(safety);
			watcher?.close();
			for (const client of clients) client.end();
			clients.clear();
			await new Promise<void>((resolve) => server.close(() => resolve()));
		},
	};
}

function staticAsset(route: string): { body: string; type: string } | undefined {
	if (route === "/" || route === "/index.html") return { body: INDEX_HTML, type: "text/html; charset=utf-8" };
	if (route === "/app.css") return { body: APP_CSS, type: "text/css; charset=utf-8" };
	if (route === "/app.js") return { body: APP_JS, type: "text/javascript; charset=utf-8" };
	return undefined;
}
