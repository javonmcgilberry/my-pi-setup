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

function finiteNumber(value: unknown): number {
	return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function compact(value: unknown): string {
	const n = finiteNumber(value);
	if (n < 1_000) return String(Math.round(n));
	if (n < 10_000) return `${(n / 1_000).toFixed(1)}k`;
	if (n < 1_000_000) return `${Math.round(n / 1_000)}k`;
	return `${(n / 1_000_000).toFixed(1)}M`;
}

function compactOrDash(value: unknown, present: boolean): string {
	if (!present) return "—";
	return compact(value);
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
	hasReasoning: boolean;
	cacheRead: number;
	cacheWrite: number;
	cost: number;
}

function usageFromEntry(usage: {
	input?: unknown;
	output?: unknown;
	reasoning?: unknown;
	cacheRead?: unknown;
	cacheWrite?: unknown;
	cost?: { total?: unknown };
}): Omit<UsageSummary, "hasReasoning"> & { sawReasoning: boolean } {
	return {
		input: finiteNumber(usage.input),
		output: finiteNumber(usage.output),
		reasoning: finiteNumber(usage.reasoning),
		sawReasoning: typeof usage.reasoning === "number" && Number.isFinite(usage.reasoning),
		cacheRead: finiteNumber(usage.cacheRead),
		cacheWrite: finiteNumber(usage.cacheWrite),
		cost: finiteNumber(usage.cost?.total),
	};
}

function usageSummary(ctx: ExtensionContext): UsageSummary {
	let input = 0;
	let output = 0;
	let reasoning = 0;
	let hasReasoning = false;
	let cacheRead = 0;
	let cacheWrite = 0;
	let cost = 0;
	for (const entry of ctx.sessionManager.getEntries()) {
		let usage: ReturnType<typeof usageFromEntry> | undefined;
		if (entry.type === "message" && entry.message.role === "assistant") {
			usage = usageFromEntry(entry.message.usage);
		} else if (entry.type === "message" && entry.message.role === "toolResult" && entry.message.usage) {
			usage = usageFromEntry(entry.message.usage);
		} else if ((entry.type === "branch_summary" || entry.type === "compaction") && entry.usage) {
			usage = usageFromEntry(entry.usage);
		}
		if (!usage) continue;
		input += usage.input;
		output += usage.output;
		reasoning += usage.reasoning;
		hasReasoning ||= usage.sawReasoning;
		cacheRead += usage.cacheRead;
		cacheWrite += usage.cacheWrite;
		cost += usage.cost;
	}
	return { input, output, reasoning, hasReasoning, cacheRead, cacheWrite, cost };
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
	return `${theme.fg("dim", "MODEL")} ${theme.fg("text", id)}${theme.fg("dim", " · think ")}${theme.fg("thinkingText", level)}`;
}

function costText(ctx: ExtensionContext, cost: number): { value: string; note?: string } {
	if (cost > 0) return { value: `$${cost.toFixed(3)}` };
	const provider = ctx.model?.provider;
	const rates = ctx.model?.cost;
	const hasRates = Boolean(
		rates &&
			(finiteNumber(rates.input) > 0 ||
				finiteNumber(rates.output) > 0 ||
				finiteNumber(rates.cacheRead) > 0 ||
				finiteNumber(rates.cacheWrite) > 0),
	);
	if (provider === "cursor" || !hasRates) {
		return { value: "$0.000", note: "sub" };
	}
	return { value: "$0.000" };
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
	const hasContext =
		context !== null &&
		context !== undefined &&
		typeof context.percent === "number" &&
		Number.isFinite(context.percent) &&
		typeof context.contextWindow === "number" &&
		Number.isFinite(context.contextWindow);
	const contextText = hasContext
		? `${context.percent.toFixed(1)}% of ${compact(context.contextWindow)}`
		: "?";
	const contextColor =
		hasContext && context.percent > 90
			? "error"
			: hasContext && context.percent > 70
				? "warning"
				: "success";
	const thinkingValue = compactOrDash(usage.reasoning, usage.hasReasoning);
	const tokenMetrics = [
		metric(theme, "Input", compact(usage.input), "text"),
		metric(theme, "Output", compact(usage.output), "text"),
		metric(theme, "Thinking", thinkingValue, "thinkingText"),
	];
	const cacheMetrics = [
		valueThenLabel(theme, compact(usage.cacheRead), "reused", "text"),
		valueThenLabel(theme, compact(usage.cacheWrite), "stored", "text"),
		valueThenLabel(theme, cacheHitRate, "hit", cacheHitRate === "n/a" ? "muted" : "success"),
	];
	const cost = costText(ctx, usage.cost);
	const costDisplay = cost.note
		? `${cost.value}${theme.fg("dim", ` (${cost.note})`)}`
		: cost.value;
	return [
		...alignedPair(
			section(theme, "TOKENS", tokenMetrics.join(theme.fg("dim", ITEM_SEPARATOR))),
			metric(theme, "COST", costDisplay, "text"),
			width,
		),
		...alignedPair(
			section(theme, "CACHE", cacheMetrics.join(theme.fg("dim", ITEM_SEPARATOR))),
			metric(theme, "CONTEXT", contextText, contextColor),
			width,
		),
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

function footerLines(
	ctx: ExtensionContext,
	footerData: ReadonlyFooterDataProvider,
	theme: Theme,
	width: number,
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
