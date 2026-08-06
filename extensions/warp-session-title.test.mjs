import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";

import warpSessionTitle, {
	buildWarpSessionTitle,
	sanitizeTitleSegment,
} from "./warp-session-title.ts";

const originalTermProgram = process.env.TERM_PROGRAM;

afterEach(() => {
	if (originalTermProgram === undefined) delete process.env.TERM_PROGRAM;
	else process.env.TERM_PROGRAM = originalTermProgram;
});

describe("Warp session titles", () => {
	it("builds a project title with an optional sanitized session name", () => {
		assert.equal(buildWarpSessionTitle("Fix auth\nflow", "/work/my-project"), "π - Fix auth flow - my-project");
		assert.equal(buildWarpSessionTitle(undefined, "/work/my-project"), "π - my-project");
		assert.equal(sanitizeTitleSegment("unsafe\u001b]0;title\u0007"), "unsafe ]0;title");
	});

	it("sets the initial and renamed titles in Warp", async () => {
		process.env.TERM_PROGRAM = "WarpTerminal";
		const handlers = new Map();
		const titles = [];
		const pi = {
			getSessionName: () => "Initial task",
			on: (event, handler) => {
				handlers.set(event, handler);
			},
		};
		const ctx = {
			cwd: "/work/my-project",
			ui: { setTitle: (title) => titles.push(title) },
		};

		warpSessionTitle(pi);
		await handlers.get("session_start")?.({}, ctx);
		await handlers.get("session_info_changed")?.({ name: "New topic" }, ctx);

		assert.deepEqual(titles, ["π - Initial task - my-project", "π - New topic - my-project"]);
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
