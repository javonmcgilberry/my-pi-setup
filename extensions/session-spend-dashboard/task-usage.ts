export interface TaskUsage {
	input: number;
	output: number;
	reasoning: number;
	cacheRead: number;
	cacheWrite: number;
	cost: number;
	hasReasoning: boolean;
}

export interface TaskUsageSummary extends TaskUsage {
	childRuns: number;
}

export function emptyTaskUsage(): TaskUsage {
	return { input: 0, output: 0, reasoning: 0, cacheRead: 0, cacheWrite: 0, cost: 0, hasReasoning: false };
}

function record(value: unknown): Record<string, unknown> | undefined {
	return value !== null && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: undefined;
}

function finite(value: unknown): number {
	return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function usageFromValue(value: unknown): TaskUsage {
	const usage = record(value);
	if (!usage) return emptyTaskUsage();
	const cost = record(usage.cost);
	const reasoning = finite(usage.reasoning ?? usage.reasoningOutputTokens);
	return {
		input: finite(usage.input ?? usage.inputTokens),
		output: finite(usage.output ?? usage.outputTokens),
		reasoning,
		cacheRead: finite(usage.cacheRead ?? usage.cacheReadTokens),
		cacheWrite: finite(usage.cacheWrite ?? usage.cacheWriteTokens),
		cost: finite(cost?.total ?? usage.costUsd ?? usage.cost),
		hasReasoning:
			typeof usage.reasoning === "number" || typeof usage.reasoningOutputTokens === "number",
	};
}

export function addTaskUsage(target: TaskUsage, source: TaskUsage): void {
	target.input += source.input;
	target.output += source.output;
	target.reasoning += source.reasoning;
	target.cacheRead += source.cacheRead;
	target.cacheWrite += source.cacheWrite;
	target.cost += source.cost;
	target.hasReasoning ||= source.hasReasoning;
}

function runKey(details: Record<string, unknown>, result: Record<string, unknown>, index: number): string {
	const sessionFile = typeof result.sessionFile === "string" ? result.sessionFile : undefined;
	const runId = typeof details.runId === "string"
		? details.runId
		: typeof details.asyncId === "string"
			? details.asyncId
			: "unknown-run";
	return sessionFile ?? `${runId}:${index}`;
}

function nestedUsage(value: unknown, seen: Set<string>, fallbackKey: string): TaskUsage {
	const item = record(value);
	if (!item) return emptyTaskUsage();
	const key = typeof item.sessionFile === "string"
		? item.sessionFile
		: typeof item.id === "string"
			? item.id
			: fallbackKey;
	if (seen.has(key)) return emptyTaskUsage();
	seen.add(key);

	const totalCost = record(item.totalCost);
	const usage = totalCost ? usageFromValue(totalCost) : usageFromValue(item.usage);
	if (!totalCost && Array.isArray(item.children)) {
		for (let index = 0; index < item.children.length; index++) {
			addTaskUsage(usage, nestedUsage(item.children[index], seen, `${key}:${index}`));
		}
	}
	return usage;
}

export function childUsageFromDetails(value: unknown, seen = new Set<string>()): Map<string, TaskUsage> {
	const details = record(value);
	const runs = new Map<string, TaskUsage>();
	if (!details) return runs;
	const totalCost = record(details.totalCost);
	const topKey = typeof details.runId === "string"
		? details.runId
		: typeof details.asyncId === "string"
			? details.asyncId
			: undefined;
	if (topKey && seen.has(topKey)) return runs;
	if (totalCost && topKey) {
		if (!seen.has(topKey)) {
			seen.add(topKey);
			runs.set(topKey, usageFromValue(totalCost));
		}
		return runs;
	}
	if (!Array.isArray(details.results)) return runs;
	for (let index = 0; index < details.results.length; index++) {
		const result = record(details.results[index]);
		if (!result) continue;
		const key = runKey(details, result, index);
		if (seen.has(key)) continue;
		seen.add(key);
		const usage = usageFromValue(result.usage);
		if (Array.isArray(result.children)) {
			for (let childIndex = 0; childIndex < result.children.length; childIndex++) {
				addTaskUsage(usage, nestedUsage(result.children[childIndex], seen, `${key}:${childIndex}`));
			}
		}
		runs.set(key, usage);
	}
	if (topKey) seen.add(topKey);
	return runs;
}

export function summarizeTaskEntries(
	entries: readonly unknown[],
	artifactRuns: ReadonlyMap<string, TaskUsage> = new Map(),
): TaskUsageSummary {
	const total = emptyTaskUsage();
	const childRuns = new Map<string, TaskUsage>();
	const seenChildren = new Set<string>();

	for (const value of entries) {
		const entry = record(value);
		if (!entry) continue;
		if (entry.type === "message") {
			const message = record(entry.message);
			if (!message) continue;
			if (message.role === "assistant") {
				addTaskUsage(total, usageFromValue(message.usage));
				continue;
			}
			if (message.role !== "toolResult") continue;
			const fromChildren = childUsageFromDetails(message.details, seenChildren);
			if (fromChildren.size > 0) {
				for (const [key, usage] of fromChildren) childRuns.set(key, usage);
			} else if (message.usage) {
				addTaskUsage(total, usageFromValue(message.usage));
			}
			continue;
		}
		if ((entry.type === "branch_summary" || entry.type === "compaction") && entry.usage) {
			addTaskUsage(total, usageFromValue(entry.usage));
		}
	}

	for (const [key, usage] of artifactRuns) {
		if (!childRuns.has(key)) childRuns.set(key, usage);
	}
	for (const usage of childRuns.values()) addTaskUsage(total, usage);
	return { ...total, childRuns: childRuns.size };
}
