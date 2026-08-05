import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { after, before, beforeEach, test } from "node:test";

import type { ExtensionAPI, ExtensionCommandContext, RegisteredCommand } from "@earendil-works/pi-coding-agent";

import createExtension from "../index.ts";

type CommandOptions = Omit<RegisteredCommand, "name" | "sourceInfo">;

interface Harness {
	command: CommandOptions;
	shutdown: () => Promise<void>;
	notices: { message: string; level?: string }[];
	statuses: (string | undefined)[];
	ctx: ExtensionCommandContext;
}

type AnyHandler = (...args: never[]) => unknown;

/**
 * The extension only consumes a few members of each Pi interface. Access to anything else
 * throws instead of silently returning undefined, so a future wiring mistake fails loudly.
 */
function strictStub<T extends object>(implemented: Partial<T>, label: string): T {
	return new Proxy(implemented, {
		get(target, prop, receiver) {
			if (prop in target) return Reflect.get(target, prop, receiver);
			throw new Error(`unexpected ${label} member used: ${String(prop)}`);
		},
	}) as T;
}

function harness(): Harness {
	const notices: { message: string; level?: string }[] = [];
	const statuses: (string | undefined)[] = [];
	let command: CommandOptions | undefined;
	let shutdown: (() => Promise<void>) | undefined;

	const api = strictStub<ExtensionAPI>(
		{
			registerCommand: (name: string, options: CommandOptions) => {
				assert.equal(name, "spend-dashboard");
				command = options;
			},
			on: (event: string, handler: AnyHandler) => {
				if (event === "session_shutdown") shutdown = handler as () => Promise<void>;
			},
		},
		"ExtensionAPI",
	);

	createExtension(api);
	assert.ok(command, "command was not registered");
	assert.ok(shutdown, "session_shutdown handler was not registered");

	const ui = strictStub<ExtensionCommandContext["ui"]>(
		{
			notify: (message: string, level?: "info" | "warning" | "error") => {
				notices.push({ message, level });
			},
			setStatus: (_key: string, text: string | undefined) => {
				statuses.push(text);
			},
		},
		"ExtensionUIContext",
	);

	return { command, shutdown, notices, statuses, ctx: strictStub<ExtensionCommandContext>({ ui }, "ExtensionCommandContext") };
}

let cwd = "";
let active: Harness;

function freePort(): Promise<number> {
	return new Promise((resolve, reject) => {
		const probe = net.createServer();
		probe.once("error", reject);
		probe.listen(0, "127.0.0.1", () => {
			const address = probe.address();
			const port = typeof address === "object" && address !== null ? address.port : 0;
			probe.close(() => resolve(port));
		});
	});
}

before(async () => {
	cwd = await mkdtemp(path.join(os.tmpdir(), "spend-dash-cmd-"));
});

beforeEach(() => {
	active = harness();
});

after(async () => {
	await active?.shutdown();
	await rm(cwd, { recursive: true, force: true });
});

test("describes itself and completes its actions", () => {
	const { command } = active;
	assert.match(command.description ?? "", /read-only/i);
	const all = command.getArgumentCompletions?.("");
	assert.deepEqual(
		Array.isArray(all) ? all.map((item) => item.value) : [],
		["start", "stop", "restart", "status", "open"],
	);
	const filtered = command.getArgumentCompletions?.("sta");
	assert.deepEqual(Array.isArray(filtered) ? filtered.map((item) => item.value) : [], ["start", "status"]);
	assert.equal(command.getArgumentCompletions?.("zzz"), null);
});

test("explains itself when the action is unknown", async () => {
	await active.command.handler("frobnicate", active.ctx);
	const [notice] = active.notices;
	assert.equal(notice?.level, "warning");
	assert.match(notice?.message ?? "", /Unknown action "frobnicate"/);
	assert.match(notice?.message ?? "", /\/spend-dashboard start/);
	assert.match(notice?.message ?? "", /\/spend-dashboard open/);
});

test("rejects a port that is not a usable number", async () => {
	for (const bad of ["abc", "80", "70000", "4310.5"]) {
		const local = harness();
		await local.command.handler(`start ${bad}`, local.ctx);
		assert.equal(local.notices[0]?.level, "warning", bad);
		assert.match(local.notices[0]?.message ?? "", /Port must be a whole number/, bad);
		await local.shutdown();
	}
});

test("reports a stopped dashboard for a bare status", async () => {
	await active.command.handler("", active.ctx);
	assert.match(active.notices[0]?.message ?? "", /stopped/i);
	assert.equal(active.notices[0]?.level, "info");
});

test("starts, reports a live status, and stops again", async () => {
	const { command, ctx, notices, statuses } = active;
	const port = await freePort();

	await command.handler(`start ${port}`, ctx);
	const startNotice = notices.at(-1);
	assert.equal(startNotice?.level, "info");
	assert.ok(
		startNotice?.message.includes(`http://127.0.0.1:${port}/`),
		`expected a loopback url on ${port}, got: ${startNotice?.message}`,
	);
	assert.equal(statuses.at(-1), `spend :${port}`);

	const health = await new Promise<number>((resolve, reject) => {
		const req = http.request({ host: "127.0.0.1", port, path: "/api/health" }, (res) => {
			res.resume();
			resolve(res.statusCode ?? 0);
		});
		req.on("error", reject);
		req.end();
	});
	assert.equal(health, 200);

	await command.handler("status", ctx);
	assert.match(notices.at(-1)?.message ?? "", /Running at http:\/\/127\.0\.0\.1:/);
	assert.match(notices.at(-1)?.message ?? "", /Sessions root:/);

	await command.handler("start", ctx);
	assert.match(notices.at(-1)?.message ?? "", /already running/);

	await command.handler("stop", ctx);
	assert.match(notices.at(-1)?.message ?? "", /stopped/i);
	assert.equal(statuses.at(-1), undefined);

	await assert.rejects(
		new Promise((resolve, reject) => {
			const req = http.request({ host: "127.0.0.1", port, path: "/api/health" }, resolve);
			req.on("error", reject);
			req.end();
		}),
	);
});

test("stopping an idle dashboard is harmless", async () => {
	await active.command.handler("stop", active.ctx);
	assert.match(active.notices.at(-1)?.message ?? "", /not running/i);
});

test("session shutdown releases the port and runs twice safely", async () => {
	const { command, ctx, notices, shutdown } = active;
	const port = await freePort();
	await command.handler(`start ${port}`, ctx);
	assert.match(notices.at(-1)?.message ?? "", /Spend dashboard reading/);

	await shutdown();
	await shutdown();

	await assert.rejects(
		new Promise((resolve, reject) => {
			const req = http.request({ host: "127.0.0.1", port, path: "/api/health" }, resolve);
			req.on("error", reject);
			req.end();
		}),
	);
});
