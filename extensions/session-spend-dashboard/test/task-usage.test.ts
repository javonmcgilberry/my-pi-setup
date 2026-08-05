import assert from "node:assert/strict";
import { test } from "node:test";

import { summarizeTaskEntries, type TaskUsage } from "../task-usage.ts";

function assistant(cost: number) {
	return {
		type: "message",
		message: {
			role: "assistant",
			usage: { input: 10, output: 2, cacheRead: 3, cacheWrite: 1, cost: { total: cost } },
		},
	};
}

test("adds direct child usage to the parent task total", () => {
	const entries = [
		assistant(1),
		{
			type: "message",
			message: {
				role: "toolResult",
				toolName: "subagent",
				details: {
					runId: "run-1",
					results: [
						{
							index: 0,
							sessionFile: "/tmp/child.jsonl",
							usage: { input: 100, output: 20, cacheRead: 30, cacheWrite: 4, cost: 5 },
						},
					],
				},
			},
		},
	];
	const total = summarizeTaskEntries(entries);
	assert.equal(total.cost, 6);
	assert.equal(total.input, 110);
	assert.equal(total.output, 22);
	assert.equal(total.cacheRead, 33);
	assert.equal(total.childRuns, 1);
});

test("deduplicates the same child reported by a tool result and run artifact", () => {
	const child: TaskUsage = {
		input: 100,
		output: 20,
		reasoning: 0,
		cacheRead: 0,
		cacheWrite: 0,
		cost: 5,
		hasReasoning: false,
	};
	const entries = [
		assistant(1),
		{
			type: "message",
			message: {
				role: "toolResult",
				details: { runId: "run-1", totalCost: { inputTokens: 100, outputTokens: 20, costUsd: 5 } },
			},
		},
	];
	const total = summarizeTaskEntries(entries, new Map([["run-1", child]]));
	assert.equal(total.cost, 6);
	assert.equal(total.childRuns, 1);
});

test("includes asynchronous child artifacts when no terminal tool result exists", () => {
	const child: TaskUsage = {
		input: 200,
		output: 40,
		reasoning: 0,
		cacheRead: 0,
		cacheWrite: 0,
		cost: 7,
		hasReasoning: false,
	};
	const total = summarizeTaskEntries([assistant(1)], new Map([["async-1", child]]));
	assert.equal(total.cost, 8);
	assert.equal(total.input, 210);
	assert.equal(total.childRuns, 1);
});
