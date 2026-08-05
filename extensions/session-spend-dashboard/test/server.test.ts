import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import http from "node:http";
import type { IncomingMessage } from "node:http";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";

import { HOST, startServer, type RunningServer } from "../server.ts";

let root = "";
let server: RunningServer;

interface Reply {
	status: number;
	headers: NodeJS.Dict<string | string[]>;
	body: string;
}

/** Requests are addressed by explicit loopback host and port, never by an assembled URL. */
function request(route: string, options: { method?: string; host?: string } = {}): Promise<Reply> {
	return new Promise((resolve, reject) => {
		const req = http.request(
			{
				host: HOST,
				port: server.port,
				path: route,
				method: options.method ?? "GET",
				headers: options.host === undefined ? undefined : { host: options.host },
			},
			(res: IncomingMessage) => {
				let body = "";
				res.setEncoding("utf8");
				res.on("data", (chunk: string) => {
					body += chunk;
				});
				res.on("end", () => resolve({ status: res.statusCode ?? 0, headers: res.headers, body }));
			},
		);
		req.on("error", reject);
		req.end();
	});
}

function readStream(route: string, done: (buffer: string) => boolean): Promise<string> {
	return new Promise((resolve, reject) => {
		const req = http.request({ host: HOST, port: server.port, path: route, method: "GET" }, (res) => {
			let buffer = "";
			res.setEncoding("utf8");
			res.on("data", (chunk: string) => {
				buffer += chunk;
				if (done(buffer)) {
					req.destroy();
					resolve(buffer);
				}
			});
			res.on("error", () => resolve(buffer));
		});
		req.on("error", (error) => {
			if ((error as NodeJS.ErrnoException).code !== "ECONNRESET") reject(error);
		});
		req.end();
	});
}

async function waitForSnapshot(timeoutMs = 5000): Promise<void> {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		if (server.getState().snapshot) return;
		await new Promise((resolve) => setTimeout(resolve, 25));
	}
	throw new Error("snapshot did not arrive in time");
}

before(async () => {
	root = await mkdtemp(path.join(os.tmpdir(), "spend-dash-server-"));
	const project = path.join(root, "--proj--");
	await mkdir(project, { recursive: true });
	await writeFile(
		path.join(project, "2024-01-01T00-00-00-000Z_s1.jsonl"),
		`${[
			JSON.stringify({ type: "session", version: 3, id: "s1", cwd: "/proj", timestamp: "2024-01-01T00:00:00.000Z" }),
			JSON.stringify({
				type: "message",
				id: "e1",
				message: {
					role: "assistant",
					provider: "anthropic",
					model: "claude-x",
					usage: { input: 10, output: 5, cacheRead: 0, cacheWrite: 0, totalTokens: 15, cost: { total: 0.5 } },
					timestamp: 1_700_000_000_000,
				},
			}),
		].join("\n")}\n`,
		"utf8",
	);

	server = await startServer({ sessionsRoot: root, port: 0 });
	await waitForSnapshot();
});

after(async () => {
	await server.close();
	await rm(root, { recursive: true, force: true });
});

test("serves the dashboard shell with hardened headers and no cross-origin access", async () => {
	const res = await request("/");
	assert.equal(res.status, 200);
	assert.match(String(res.headers["content-type"]), /text\/html/);
	assert.equal(res.headers["cache-control"], "no-store");
	assert.equal(res.headers["x-content-type-options"], "nosniff");
	assert.match(String(res.headers["content-security-policy"]), /default-src 'none'/);
	assert.equal(res.headers["access-control-allow-origin"], undefined);
	assert.match(res.body, /Pi Session Spend/);
});

test("serves stylesheet and script from the same origin with no external references", async () => {
	const css = await request("/app.css");
	assert.equal(css.status, 200);
	assert.match(String(css.headers["content-type"]), /text\/css/);

	const js = await request("/app.js");
	assert.equal(js.status, 200);
	assert.match(String(js.headers["content-type"]), /javascript/);
	assert.match(js.body, /EventSource\("\/api\/stream"\)/);
	assert.doesNotMatch(js.body, /https?:\/\//);
	assert.doesNotMatch(css.body, /https?:\/\//);
});

test("exposes a JSON snapshot with provider-reported cost", async () => {
	const res = await request("/api/snapshot");
	assert.equal(res.status, 200);
	assert.match(String(res.headers["content-type"]), /application\/json/);
	const snapshot = JSON.parse(res.body);
	assert.equal(snapshot.totals.cost, 0.5);
	assert.equal(snapshot.totals.sessions, 1);
	assert.equal(snapshot.sessions[0].sessionId, "s1");
	assert.equal(snapshot.sessionsRoot, root);
});

test("reports health without leaking session content", async () => {
	const res = await request("/api/health");
	assert.equal(res.status, 200);
	const health = JSON.parse(res.body);
	assert.equal(health.ok, true);
	assert.equal(health.hasSnapshot, true);
	assert.equal(typeof health.clients, "number");
});

test("rejects every mutating HTTP method", async () => {
	for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
		for (const route of ["/", "/api/snapshot", "/api/stream", "/api/health"]) {
			const res = await request(route, { method });
			assert.equal(res.status, 405, `${method} ${route}`);
			assert.equal(res.headers.allow, "GET, HEAD");
		}
	}
});

test("answers HEAD without a body", async () => {
	const res = await request("/", { method: "HEAD" });
	assert.equal(res.status, 200);
	assert.equal(res.body, "");
});

test("returns 404 for unknown routes", async () => {
	const res = await request("/does-not-exist");
	assert.equal(res.status, 404);
	assert.equal(JSON.parse(res.body).error, "not found");
});

test("refuses requests that do not target localhost", async () => {
	const res = await request("/api/snapshot", { host: "attacker.example" });
	assert.equal(res.status, 421);
});

test("streams the current snapshot over server-sent events", async () => {
	const buffer = await readStream("/api/stream", (text) => /event: snapshot\ndata: .*\n\n/s.test(text));
	assert.match(buffer, /event: snapshot/);
	const line = buffer.split("\n").find((entry) => entry.startsWith("data: "));
	assert.ok(line);
	assert.equal(JSON.parse(line.slice(6)).totals.cost, 0.5);
});

test("binds only to the loopback interface", () => {
	assert.equal(server.address, HOST);
	assert.match(server.url, /^http:\/\/127\.0\.0\.1:\d+\/$/);
});
