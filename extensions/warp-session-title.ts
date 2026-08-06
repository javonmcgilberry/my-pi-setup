import { basename } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f-\u009f]/g;

export function sanitizeTitleSegment(value: string): string {
	return value.replace(CONTROL_CHARACTERS, " ").replace(/\s+/g, " ").trim();
}

export function buildWarpSessionTitle(sessionName: string | undefined, cwd: string): string {
	const project = sanitizeTitleSegment(basename(cwd));
	const session = sessionName ? sanitizeTitleSegment(sessionName) : "";
	return ["π", session, project].filter(Boolean).join(" - ");
}

function setWarpTitle(ctx: ExtensionContext, sessionName: string | undefined): void {
	ctx.ui.setTitle(buildWarpSessionTitle(sessionName, ctx.cwd));
}

export default function warpSessionTitle(pi: ExtensionAPI): void {
	if (process.env.TERM_PROGRAM !== "WarpTerminal") return;

	pi.on("session_start", async (_event, ctx) => {
		setWarpTitle(ctx, pi.getSessionName());
	});

	pi.on("session_info_changed", async (event, ctx) => {
		setWarpTitle(ctx, event.name);
	});
}
