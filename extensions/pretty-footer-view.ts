export type FooterMetricTone =
	| "success"
	| "thinkingText"
	| "warning"
	| "muted"
	| "text"
	| "error";

export interface FooterMetric {
	label: string;
	value: string;
	tone: FooterMetricTone;
}

export interface FooterUsage {
	input: number;
	output: number;
	reasoning: number;
	hasReasoning: boolean;
	cacheRead: number;
	cacheWrite: number;
	cost: number;
}

export interface FooterContextUsage {
	tokens: number | null;
	contextWindow: number;
	percent: number | null;
}

export interface FooterMetricModel {
	session: FooterMetric[];
	tokens: FooterMetric[];
	cache: FooterMetric[];
}

interface FooterMetricInput {
	usage: FooterUsage;
	context?: FooterContextUsage;
	provider?: string;
	rates?: {
		input?: number;
		output?: number;
		cacheRead?: number;
		cacheWrite?: number;
	};
	width: number;
}

interface WidthOperations {
	measure(text: string): number;
	truncate(text: string, width: number): string;
}

interface PackFooterSectionInput {
	heading: string;
	items: readonly string[];
	width: number;
	operations: WidthOperations;
	separator?: string;
}

function finiteNumber(value: unknown): number {
	return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function optionalFiniteNumber(
	value: unknown,
	minimum?: number,
): number | undefined {
	if (typeof value !== "number" || !Number.isFinite(value)) return undefined;
	return minimum === undefined ? value : Math.max(minimum, value);
}

export function compactFooterNumber(value: unknown): string {
	const number = finiteNumber(value);
	if (number < 1_000) return String(Math.round(number));
	if (number < 10_000) return `${(number / 1_000).toFixed(1)}k`;
	if (number < 1_000_000) return `${Math.round(number / 1_000)}k`;
	return `${(number / 1_000_000).toFixed(1)}M`;
}

function modelHasRates(rates: FooterMetricInput["rates"]): boolean {
	return Boolean(
		rates &&
			(finiteNumber(rates.input) > 0 ||
				finiteNumber(rates.output) > 0 ||
				finiteNumber(rates.cacheRead) > 0 ||
				finiteNumber(rates.cacheWrite) > 0),
	);
}

function costMetric(input: FooterMetricInput): FooterMetric {
	if (input.usage.cost > 0) {
		return {
			label: "Cost",
			value: `$${input.usage.cost.toFixed(3)}`,
			tone: "text",
		};
	}
	if (input.provider === "cursor") {
		return { label: "Cost", value: "Included (subscription)", tone: "text" };
	}
	if (!modelHasRates(input.rates)) {
		return { label: "Cost", value: "Unavailable", tone: "muted" };
	}
	return { label: "Cost", value: "$0.000", tone: "text" };
}

function contextMetric(input: FooterMetricInput): FooterMetric {
	const context = input.context;
	const tokens = optionalFiniteNumber(context?.tokens, 0);
	const percent = optionalFiniteNumber(context?.percent);
	const window = optionalFiniteNumber(context?.contextWindow, 0);

	if (tokens === undefined || percent === undefined || window === undefined) {
		let value = "Usage unavailable";
		if (window !== undefined && window > 0) {
			value = `Usage updating · ${compactFooterNumber(window)} limit`;
		}
		return {
			label: "Context",
			value,
			tone: "muted",
		};
	}

	const remaining = Math.max(0, window - tokens);
	let value: string;
	if (input.width >= 88) {
		value = `${compactFooterNumber(tokens)} used · ${compactFooterNumber(remaining)} left (${percent.toFixed(1)}%)`;
	} else if (input.width >= 40) {
		value = `${compactFooterNumber(tokens)} / ${compactFooterNumber(window)} used (${percent.toFixed(1)}%)`;
	} else {
		value = `${compactFooterNumber(tokens)}/${compactFooterNumber(window)} used`;
	}
	let tone: FooterMetricTone = "success";
	if (percent > 90) tone = "error";
	else if (percent > 70) tone = "warning";
	return { label: "Context", value, tone };
}

export function buildFooterMetricModel(
	input: FooterMetricInput,
): FooterMetricModel {
	const cachePromptTokens =
		input.usage.input + input.usage.cacheRead + input.usage.cacheWrite;
	const cacheHitRate =
		cachePromptTokens > 0
			? `${((input.usage.cacheRead / cachePromptTokens) * 100).toFixed(1)}%`
			: "—";
	return {
		session: [costMetric(input), contextMetric(input)],
		tokens: [
			{
				label: "Input",
				value: compactFooterNumber(input.usage.input),
				tone: "text",
			},
			{
				label: "Output",
				value: compactFooterNumber(input.usage.output),
				tone: "text",
			},
			{
				label: "Reasoning",
				value: input.usage.hasReasoning
					? compactFooterNumber(input.usage.reasoning)
					: "—",
				tone: "thinkingText",
			},
		],
		cache: [
			{
				label: "Reused",
				value: compactFooterNumber(input.usage.cacheRead),
				tone: "text",
			},
			{
				label: "Stored",
				value: compactFooterNumber(input.usage.cacheWrite),
				tone: "text",
			},
			{
				label: "Hit rate",
				value: cacheHitRate,
				tone: cacheHitRate === "—" ? "muted" : "success",
			},
		],
	};
}

export function packFooterSection(input: PackFooterSectionInput): string[] {
	const { heading, items, width, operations, separator = "  ·  " } = input;
	const safeWidth = Math.max(1, width);
	const lines: string[] = [];
	let current = operations.truncate(heading, safeWidth);
	let itemCount = 0;

	for (const item of items) {
		const gap = itemCount === 0 ? "  " : separator;
		const candidate = `${current}${gap}${item}`;
		if (operations.measure(candidate) <= safeWidth) {
			current = candidate;
			itemCount += 1;
			continue;
		}
		if (current) lines.push(current);
		current = operations.truncate(`  ${item}`, safeWidth);
		itemCount = 1;
	}
	if (current) lines.push(current);
	return lines;
}
