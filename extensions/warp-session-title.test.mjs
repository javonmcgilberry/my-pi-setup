import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";

import warpSessionTitle, {
	buildWarpActivityTitle,
	buildWarpSessionTitle,
	sanitizeTitleSegment,
	TITLE_ACTIVITY_INTERVAL_MS,
	TITLE_REASSERT_DELAY_MS,
} from "./warp-session-title.ts";

const originalTermProgram = process.env.TERM_PROGRAM;

afterEach(() => {
	if (originalTermProgram === undefined) delete process.env.TERM_PROGRAM;
	else process.env.TERM_PROGRAM = originalTermProgram;
});

describe("Warp session titles", () => {
	it("builds a project title with an optional sanitized session name", () => {
		assert.equal(buildWarpSessionTitle("Fix auth\nflow", "/work/my-project"), "π - Fix auth flow - my-project");
		assert.equal(buildWarpActivityTitle("Fix auth flow", "/work/my-project", "⠴"), "⠴ - Fix auth flow - my-project");
		assert.equal(buildWarpSessionTitle(undefined, "/work/my-project"), "π - my-project");
		assert.equal(sanitizeTitleSegment("unsafe\u001b]0;title\u0007"), "unsafe ]0;title");
	});

	it("sets the initial and renamed titles in Warp", async () => {
		process.env.TERM_PROGRAM = "WarpTerminal";
		const handlers = new Map();
		const titles = [];
		const pi = {
			on: (event, handler) => {
				handlers.set(event, handler);
			},
		};
		const ctx = {
			cwd: "/work/my-project",
			sessionManager: { getSessionName: () => "Initial task" },
			ui: { setTitle: (title) => titles.push(title) },
		};

		warpSessionTitle(pi);
		await handlers.get("session_start")?.({}, ctx);
		await handlers.get("session_info_changed")?.({ name: "New topic" }, ctx);

		assert.deepEqual(titles, ["π - Initial task - my-project", "π - New topic - my-project"]);
		await handlers.get("session_shutdown")?.();
	});

	it("restores a resumed session title after startup and agent activity", async () => {
		process.env.TERM_PROGRAM = "WarpTerminal";
		const handlers = new Map();
		const titles = [];
		const pi = {
			on: (event, handler) => {
				handlers.set(event, handler);
			},
		};
		const ctx = {
			cwd: "/work/my-project",
			sessionManager: { getSessionName: () => "Saved task" },
			ui: { setTitle: (title) => titles.push(title) },
		};

		warpSessionTitle(pi);
		await handlers.get("session_start")?.({ reason: "resume" }, ctx);
		await new Promise((resolve) => setTimeout(resolve, TITLE_REASSERT_DELAY_MS + 25));
		await handlers.get("before_agent_start")?.({}, ctx);
		await handlers.get("agent_start")?.({}, ctx);
		await new Promise((resolve) => setTimeout(resolve, TITLE_ACTIVITY_INTERVAL_MS + 25));
		await handlers.get("agent_end")?.({}, ctx);

		assert.deepEqual(titles, [
			"π - Saved task - my-project",
			"π - Saved task - my-project",
			"π - Saved task - my-project",
			"⠴ - Saved task - my-project",
			"⠦ - Saved task - my-project",
			"π - Saved task - my-project",
		]);
		await handlers.get("session_shutdown")?.();
	});

	it("cancels a stale title reassertion when the session shuts down", async () => {
		process.env.TERM_PROGRAM = "WarpTerminal";
		const handlers = new Map();
		const titles = [];
		const pi = {
			on: (event, handler) => {
				handlers.set(event, handler);
			},
		};
		const ctx = {
			cwd: "/work/old-project",
			sessionManager: { getSessionName: () => "Old task" },
			ui: { setTitle: (title) => titles.push(title) },
		};

		warpSessionTitle(pi);
		await handlers.get("session_start")?.({ reason: "resume" }, ctx);
		await handlers.get("session_shutdown")?.();
		await new Promise((resolve) => setTimeout(resolve, TITLE_REASSERT_DELAY_MS + 25));

		assert.deepEqual(titles, ["π - Old task - old-project"]);
	});

	it("does not register outside Warp", () => {
		process.env.TERM_PROGRAM = "Apple_Terminal";
		let registrations = 0;
		const pi = {
			on: () => {
				registrations += 1;
			},
		};

		warpSessionTitle(pi);

		assert.equal(registrations, 0);
	});
});
