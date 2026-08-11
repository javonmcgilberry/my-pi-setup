import os from "node:os";
import path from "node:path";
import type {
	ExtensionAPI,
	ExtensionContext,
	ReadonlyFooterDataProvider,
	Theme,
} from "@earendil-works/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";
import {
	buildFooterMetricModel,
	type FooterMetricTone,
	packFooterSection,
} from "./pretty-footer-view.ts";
import { readTaskRunUsage } from "./session-spend-dashboard/runs.ts";
import {
	type TaskUsage,
	summarizeTaskEntries,
} from "./session-spend-dashboard/task-usage.ts";

const STATUS_PRIORITY = ["prewalk", "codex-adapter", "mcp", "pi-lens-lsp"];
const ITEM_SEPARATOR = "  ·  ";
const SYSTEM_SEPARATOR = "  |  ";
const ANSI_SGR_PATTERN = new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, "g");

function displayPath(cwd: string): string {
	const home = os.homedir();
	const relative = path.relative(home, cwd);
	if (relative === "") return "~";
	if (relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
		return cwd;
	}
	return `~${path.sep}${relative}`;
}

function cleanStatus(text: string): string {
	return text
		.replace(/[\r\n\t]+/g, " ")
		.replace(/ {2,}/g, " ")
		.trim();
}

function plainStatus(text: string): string {
	return cleanStatus(text.replace(ANSI_SGR_PATTERN, ""));
}

function statusRank(key: string): number {
	const rank = STATUS_PRIORITY.indexOf(key);
	return rank === -1 ? STATUS_PRIORITY.length : rank;
}

function wrapItems(items: string[], width: number, separator: string): string[] {
	const lines: string[] = [];
	let current = "";

	for (const item of items) {
		const candidate = current ? `${current}${separator}${item}` : item;
		if (visibleWidth(candidate) <= width) {
			current = candidate;
			continue;
		}
		if (current) lines.push(current);
		current = visibleWidth(item) <= width ? item : truncateToWidth(item, width, "...");
	}
	if (current) lines.push(current);
	return lines;
}

function rightAligned(text: string, width: number): string {
	const clipped = truncateToWidth(text, width, "...");
	return `${" ".repeat(Math.max(0, width - visibleWidth(clipped)))}${clipped}`;
}

function alignedPair(left: string, right: string, width: number): string[] {
	const clippedLeft = truncateToWidth(left, width, "...");
	const clippedRight = truncateToWidth(right, width, "...");
	if (!clippedRight) return [clippedLeft];
	const gap = width - visibleWidth(clippedLeft) - visibleWidth(clippedRight);
	if (gap >= 3) return [`${clippedLeft}${" ".repeat(gap)}${clippedRight}`];
	return [clippedLeft, rightAligned(clippedRight, width)];
}

interface UsageSummary {
	input: number;
	output: number;
	reasoning: number;
	hasReasoning: boolean;
	cacheRead: number;
	cacheWrite: number;
	cost: number;
}

function usageSummary(ctx: ExtensionContext, artifactRuns: ReadonlyMap<string, TaskUsage>): UsageSummary {
	const usage = summarizeTaskEntries(ctx.sessionManager.getEntries(), artifactRuns);
	return {
		input: usage.input,
		output: usage.output,
		reasoning: usage.reasoning,
		hasReasoning: usage.hasReasoning,
		cacheRead: usage.cacheRead,
		cacheWrite: usage.cacheWrite,
		cost: usage.cost,
	};
}

function modelStatusText(ctx: ExtensionContext, theme: Theme): string {
	const model = ctx.model;
	if (!model) return theme.fg("dim", "MODEL  —");
	const id = model.id || "unknown";
	const thinking = ctx.thinkingLevel;
	const showThinking = Boolean(model.reasoning) || (thinking !== undefined && thinking !== "off");
	if (!showThinking || thinking === undefined) {
		return `${theme.fg("dim", "MODEL")} ${theme.fg("text", id)}`;
	}
	const level = thinking === "off" ? "off" : String(thinking);
	return `${theme.fg("dim", "MODEL")} ${theme.fg("text", id)}${theme.fg("dim", " · reasoning ")}${theme.fg("thinkingText", level)}`;
}

function metric(
	theme: Theme,
	label: string,
	value: string,
	color: FooterMetricTone,
): string {
	return `${theme.fg("dim", `${label} `)}${theme.fg(color, value)}`;
}

function section(theme: Theme, label: string, content: string): string {
	return `${theme.bold(theme.fg("accent", label))}  ${content}`;
}

function sectionItems(theme: Theme, label: string, items: string[], width: number): string[] {
	return packFooterSection({
		heading: theme.bold(theme.fg("accent", label)),
		items,
		width,
		operations: {
			measure: visibleWidth,
			truncate: (text, availableWidth) => truncateToWidth(text, availableWidth, "..."),
		},
		separator: theme.fg("dim", ITEM_SEPARATOR),
	});
}

function metricLines(
	ctx: ExtensionContext,
	theme: Theme,
	width: number,
	artifactRuns: ReadonlyMap<string, TaskUsage>,
): string[] {
	const usage = usageSummary(ctx, artifactRuns);
	const model = buildFooterMetricModel({
		usage,
		context: ctx.getContextUsage(),
		provider: ctx.model?.provider,
		rates: ctx.model?.cost,
		width,
	});
	const renderMetric = (item: (typeof model.session)[number]) =>
		metric(theme, item.label, item.value, item.tone);
	return [
		...sectionItems(theme, "SESSION", model.session.map(renderMetric), width),
		...sectionItems(theme, "SESSION TOKENS", model.tokens.map(renderMetric), width),
		...sectionItems(theme, "PROMPT CACHE", model.cache.map(renderMetric), width),
	];
}

function prewalkLines(text: string, theme: Theme, width: number): string[] {
	const routeText = text.replace(/^prewalk:\s*/i, "").split(" (", 1)[0] ?? "";
	const [plannerText = "planner", executorText = "executor"] = routeText.split(/\s+\/\s+/, 2);
	const plannerActive = plannerText.startsWith("[") && plannerText.endsWith("]");
	const executorActive = executorText.startsWith("[") && executorText.endsWith("]");
	const planner = plannerText.replace(/^\[|\]$/g, "");
	const executor = executorText.replace(/^\[|\]$/g, "");
	const route = [
		plannerActive ? theme.bold(theme.fg("accent", planner)) : theme.fg("dim", planner),
		theme.fg("dim", " → "),
		executorActive ? theme.bold(theme.fg("success", executor)) : theme.fg("dim", executor),
	].join("");
	const failed = /\(failed(?:: ([^)]+))?\)/.exec(text);
	const cancelled = /\(cancelled(?:; ([^)]+))?\)/.exec(text);
	let state: string;
	if (failed) {
		state = theme.bold(theme.fg("error", `✕ FAILED${failed[1] ? `  ${failed[1]}` : ""}`));
	} else if (cancelled) {
		state = theme.fg("muted", `○ CANCELLED${cancelled[1] ? `  ${cancelled[1]}` : ""}`);
	} else if (text.includes("(switching after this turn)")) {
		state = theme.bold(theme.fg("warning", "● SWITCHING AFTER THIS TURN"));
	} else if (text.includes("(waiting for first code change)")) {
		state = theme.bold(theme.fg("warning", "● WAITING FOR FIRST CODE CHANGE"));
	} else if (executorActive) {
		state = theme.bold(theme.fg("success", `● EXECUTING WITH ${executor.toUpperCase()}`));
	} else {
		state = theme.bold(theme.fg("accent", `● PLANNING WITH ${planner.toUpperCase()}`));
	}
	return alignedPair(section(theme, "PREWALK", route), state, width);
}

function compactSystemStatus(key: string, text: string, theme: Theme): string {
	const plain = plainStatus(text);
	if (key === "codex-adapter") {
		const details = plain
			.replace(/^Codex adapter\s*/i, "")
			.split(/\s*•\s*/)
			.map((part) =>
				part
					.replace(/^V:\s*/i, "")
					.replace(/\s+mode$/i, "")
					.trim(),
			)
			.filter((part) => part.length > 0)
			.join(" · ");
		return `${theme.bold(theme.fg("accent", "CODEX"))}${details ? ` ${theme.fg("dim", details)}` : ""}`;
	}
	if (key === "mcp") {
		const count = /\bMCP:\s*(\d+)\s+server/i.exec(plain)?.[1];
		return theme.bold(theme.fg("accent", count ? `MCP ${count}` : plain));
	}
	if (key === "pi-lens-lsp" && /\binactive\b/i.test(plain)) {
		return `${theme.bold(theme.fg("accent", "LSP"))} ${theme.fg("muted", "off")}`;
	}
	return cleanStatus(text);
}

function secondaryStatusLines(
	statuses: ReadonlyMap<string, string>,
	theme: Theme,
	width: number,
): string[] {
	const items = [...statuses.entries()]
		.filter(([key, text]) => key !== "prewalk" && cleanStatus(text).length > 0)
		.sort(([left], [right]) => {
			const rankDifference = statusRank(left) - statusRank(right);
			return rankDifference || left.localeCompare(right);
		})
		.map(([key, text]) => compactSystemStatus(key, text, theme));
	if (items.length === 0) return [];
	const wrapped = wrapItems(items, width, theme.fg("dim", SYSTEM_SEPARATOR));
	const [first, ...remaining] = wrapped;
	if (!first) return [];
	return [
		...alignedPair(theme.bold(theme.fg("accent", "SYSTEM")), first, width),
		...remaining.map((line) => rightAligned(line, width)),
	];
}

export function renderPrettyFooterLines(
	ctx: ExtensionContext,
	footerData: ReadonlyFooterDataProvider,
	theme: Theme,
	width: number,
	artifactRuns: ReadonlyMap<string, TaskUsage>,
): string[] {
	const branch = footerData.getGitBranch();
	const statuses = footerData.getExtensionStatuses();
	const prewalk = statuses.get("prewalk");
	const pathLeft = branch
		? `${theme.fg("dim", displayPath(ctx.cwd))}${theme.fg("dim", `  ·  ${branch}`)}`
		: theme.fg("dim", displayPath(ctx.cwd));
	return [
		...alignedPair(pathLeft, modelStatusText(ctx, theme), width),
		...(prewalk ? prewalkLines(cleanStatus(prewalk), theme, width) : []),
		...metricLines(ctx, theme, width, artifactRuns),
		...secondaryStatusLines(statuses, theme, width),
	];
}

export default function prettyFooter(pi: ExtensionAPI): void {
	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		ctx.ui.setFooter((tui, theme, footerData) => {
			let artifactRuns = new Map<string, TaskUsage>();
			let disposed = false;
			let refreshPending = false;
			const refreshChildren = async (): Promise<void> => {
				if (refreshPending) return;
				refreshPending = true;
				const sessionFile = ctx.sessionManager.getSessionFile();
				try {
					if (!sessionFile) return;
					artifactRuns = await readTaskRunUsage(sessionFile);
					if (!disposed) tui.requestRender();
				} finally {
					refreshPending = false;
				}
			};
			void refreshChildren();
			const unsubscribe = footerData.onBranchChange(() => {
				void refreshChildren();
				tui.requestRender();
			});
			return {
				dispose() {
					disposed = true;
					unsubscribe();
				},
				invalidate() {
					void refreshChildren();
				},
				render(width: number): string[] {
					return renderPrettyFooterLines(ctx, footerData, theme, width, artifactRuns);
				},
			};
		});
	});
}
