import { basename } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f-\u009f]/g;
// Match the pinned rpiv-warp cadence. This package loads afterward, so its
// session-aware frame is the final title written on each tick.
const TITLE_ACTIVITY_FRAMES = ["⠴", "⠦", "⠖", "⠲"] as const;

export const TITLE_ACTIVITY_INTERVAL_MS = 160;
export const TITLE_REASSERT_DELAY_MS = 250;

export function sanitizeTitleSegment(value: string): string {
	return value.replace(CONTROL_CHARACTERS, " ").replace(/\s+/g, " ").trim();
}

export function buildWarpSessionTitle(sessionName: string | undefined, cwd: string): string {
	const project = sanitizeTitleSegment(basename(cwd));
	const session = sessionName ? sanitizeTitleSegment(sessionName) : "";
	return ["π", session, project].filter(Boolean).join(" - ");
}

export function buildWarpActivityTitle(sessionName: string | undefined, cwd: string, frame: string): string {
	return `${frame}${buildWarpSessionTitle(sessionName, cwd).slice(1)}`;
}

function setWarpTitle(ctx: ExtensionContext, sessionName: string | undefined): void {
	ctx.ui.setTitle(buildWarpSessionTitle(sessionName, ctx.cwd));
}

export default function warpSessionTitle(pi: ExtensionAPI): void {
	if (process.env.TERM_PROGRAM !== "WarpTerminal") return;
	let reassertTimer: ReturnType<typeof setTimeout> | undefined;
	let activityTimer: ReturnType<typeof setInterval> | undefined;
	let activityFrame = 0;
	let activityContext: ExtensionContext | undefined;
	let activitySessionName: string | undefined;

	const cancelReassert = (): void => {
		if (reassertTimer === undefined) return;
		clearTimeout(reassertTimer);
		reassertTimer = undefined;
	};

	const restoreTitle = (ctx: ExtensionContext, sessionName: string | undefined, reassert: boolean): void => {
		cancelReassert();
		setWarpTitle(ctx, sessionName);
		if (!reassert) return;

		reassertTimer = setTimeout(() => {
			reassertTimer = undefined;
			setWarpTitle(ctx, sessionName);
		}, TITLE_REASSERT_DELAY_MS);
	};

	const stopActivityTitle = (): void => {
		if (activityTimer !== undefined) clearInterval(activityTimer);
		activityTimer = undefined;
		activityContext = undefined;
		activitySessionName = undefined;
		activityFrame = 0;
	};

	const writeActivityTitle = (): void => {
		if (!activityContext) return;
		activityContext.ui.setTitle(
			buildWarpActivityTitle(
				activitySessionName,
				activityContext.cwd,
				TITLE_ACTIVITY_FRAMES[activityFrame % TITLE_ACTIVITY_FRAMES.length],
			),
		);
		activityFrame += 1;
	};

	const startActivityTitle = (ctx: ExtensionContext): void => {
		stopActivityTitle();
		cancelReassert();
		activityContext = ctx;
		activitySessionName = ctx.sessionManager.getSessionName();
		writeActivityTitle();
		activityTimer = setInterval(writeActivityTitle, TITLE_ACTIVITY_INTERVAL_MS);
		activityTimer.unref();
	};

	pi.on("session_start", (_event, ctx) => {
		stopActivityTitle();
		restoreTitle(ctx, ctx.sessionManager.getSessionName(), true);
	});

	pi.on("session_info_changed", (event, ctx) => {
		if (activityTimer !== undefined) {
			activitySessionName = event.name;
			writeActivityTitle();
			return;
		}
		restoreTitle(ctx, event.name, true);
	});

	// Keep rpiv-warp's activity animation, but preserve the resumed session name
	// in every frame and in the title restored after the agent stops.
	pi.on("before_agent_start", (_event, ctx) => {
		stopActivityTitle();
		restoreTitle(ctx, ctx.sessionManager.getSessionName(), false);
	});

	pi.on("agent_start", (_event, ctx) => {
		startActivityTitle(ctx);
	});

	pi.on("agent_end", (_event, ctx) => {
		stopActivityTitle();
		restoreTitle(ctx, ctx.sessionManager.getSessionName(), true);
	});

	pi.on("session_shutdown", () => {
		stopActivityTitle();
		cancelReassert();
	});
}
