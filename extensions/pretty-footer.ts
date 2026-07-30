import os from "node:os";
import path from "node:path";
import type {
	ExtensionAPI,
	ExtensionContext,
	ReadonlyFooterDataProvider,
	Theme,
} from "@earendil-works/pi-coding-agent";
import { truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

const STATUS_PRIORITY = ["prewalk", "codex-adapter", "mcp", "pi-lens-lsp"];
const ITEM_SEPARATOR = "  ·  ";
const SYSTEM_SEPARATOR = "  |  ";
const ANSI_SGR_PATTERN = new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, "g");

function compact(value: number): string {
	if (value < 1_000) return String(value);
	if (value < 10_000) return `${(value / 1_000).toFixed(1)}k`;
	if (value < 1_000_000) return `${Math.round(value / 1_000)}k`;
	return `${(value / 1_000_000).toFixed(1)}M`;
}

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
	cacheRead: number;
	cacheWrite: number;
	cost: number;
}

function usageSummary(ctx: ExtensionContext): UsageSummary {
	let input = 0;
	let output = 0;
	let reasoning = 0;
	let cacheRead = 0;
	let cacheWrite = 0;
	let cost = 0;
	for (const entry of ctx.sessionManager.getEntries()) {
		if (entry.type !== "message" || entry.message.role !== "assistant") continue;
		input += entry.message.usage.input;
		output += entry.message.usage.output;
		reasoning += entry.message.usage.reasoning;
		cacheRead += entry.message.usage.cacheRead;
		cacheWrite += entry.message.usage.cacheWrite;
		cost += entry.message.usage.cost.total;
	}
	return { input, output, reasoning, cacheRead, cacheWrite, cost };
}

function metric(
	theme: Theme,
	label: string,
	value: string,
	color: "accent" | "success" | "thinkingText" | "warning" | "muted" | "text" | "error",
): string {
	return `${theme.fg("dim", `${label} `)}${theme.fg(color, value)}`;
}

function section(theme: Theme, label: string, content: string): string {
	return `${theme.bold(theme.fg("accent", label))}  ${content}`;
}

function valueThenLabel(
	theme: Theme,
	value: string,
	label: string,
	color: "success" | "muted" | "text",
): string {
	return `${theme.fg(color, value)}${theme.fg("dim", ` ${label}`)}`;
}

function metricLines(ctx: ExtensionContext, theme: Theme, width: number): string[] {
	const usage = usageSummary(ctx);
	const cachePromptTokens = usage.input + usage.cacheRead + usage.cacheWrite;
	const cacheHitRate =
		cachePromptTokens > 0
			? `${((usage.cacheRead / cachePromptTokens) * 100).toFixed(1)}%`
			: "n/a";
	const context = ctx.getContextUsage();
	const contextText = context
		? `${context.percent.toFixed(1)}% of ${compact(context.contextWindow)}`
		: "?";
	const contextColor =
		context && context.percent > 90
			? "error"
			: context && context.percent > 70
				? "warning"
				: "success";
	const tokenMetrics = [
		metric(theme, "Input", compact(usage.input), "text"),
		metric(theme, "Output", compact(usage.output), "text"),
		metric(theme, "Thinking", compact(usage.reasoning), "thinkingText"),
	];
	const cacheMetrics = [
		valueThenLabel(theme, compact(usage.cacheRead), "reused", "text"),
		valueThenLabel(theme, compact(usage.cacheWrite), "stored", "text"),
		valueThenLabel(theme, cacheHitRate, "hit", cacheHitRate === "n/a" ? "muted" : "success"),
	];
	return [
		...alignedPair(
			section(theme, "TOKENS", tokenMetrics.join(theme.fg("dim", ITEM_SEPARATOR))),
			metric(theme, "COST", `$${usage.cost.toFixed(3)}`, "text"),
			width,
		),
		...alignedPair(
			section(theme, "CACHE", cacheMetrics.join(theme.fg("dim", ITEM_SEPARATOR))),
			metric(theme, "CONTEXT", contextText, contextColor),
			width,
		),
	];
}

function prewalkLines(text: string, ctx: ExtensionContext, theme: Theme, width: number): string[] {
	const solActive = text.includes("[5.6 Sol]");
	const lunaActive = text.includes("[Luna]");
	const sol = `Sol · ${ctx.thinkingLevel ?? "off"}`;
	const luna = "Luna · low";
	const route = [
		solActive ? theme.bold(theme.fg("accent", sol)) : theme.fg("dim", sol),
		theme.fg("dim", " → "),
		lunaActive ? theme.bold(theme.fg("success", luna)) : theme.fg("dim", luna),
	].join("");
	const failed = /\(failed(?:: ([^)]+))?\)/.exec(text);
	const cancelled = /\(cancelled(?:; ([^)]+))?\)/.exec(text);
	let state: string;
	if (failed) {
		state = theme.bold(theme.fg("error", `✕ FAILED${failed[1] ? `  ${failed[1]}` : ""}`));
	} else if (cancelled) {
		state = theme.fg("muted", `○ CANCELLED${cancelled[1] ? `  ${cancelled[1]}` : ""}`);
	} else if (text.includes("(ready)")) {
		state = theme.bold(theme.fg("warning", "● READY TO SWITCH"));
	} else if (lunaActive) {
		state = theme.bold(theme.fg("success", "● EXECUTING ON LUNA"));
	} else {
		state = theme.bold(theme.fg("accent", "● PLANNING ON SOL"));
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

function footerLines(
	ctx: ExtensionContext,
	footerData: ReadonlyFooterDataProvider,
	theme: Theme,
	width: number,
): string[] {
	const branch = footerData.getGitBranch();
	const statuses = footerData.getExtensionStatuses();
	const prewalk = statuses.get("prewalk");
	return [
		...alignedPair(
			theme.fg("dim", displayPath(ctx.cwd)),
			branch ? theme.fg("dim", `BRANCH  ${branch}`) : "",
			width,
		),
		...(prewalk ? prewalkLines(cleanStatus(prewalk), ctx, theme, width) : []),
		...metricLines(ctx, theme, width),
		...secondaryStatusLines(statuses, theme, width),
	];
}

export default function prettyFooter(pi: ExtensionAPI): void {
	pi.on("session_start", (_event, ctx) => {
		if (ctx.mode !== "tui") return;
		ctx.ui.setFooter((tui, theme, footerData) => {
			const unsubscribe = footerData.onBranchChange(() => tui.requestRender());
			return {
				dispose: unsubscribe,
				invalidate() {},
				render(width: number): string[] {
					return footerLines(ctx, footerData, theme, width);
				},
			};
		});
	});
}
