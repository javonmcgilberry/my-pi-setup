import assert from "node:assert/strict";
import { test } from "node:test";

import {
	buildFooterMetricModel,
	type FooterUsage,
	packFooterSection,
} from "./pretty-footer-view.ts";

function usage(overrides: Partial<FooterUsage> = {}): FooterUsage {
	return {
		input: 1_200,
		output: 350,
		reasoning: 200,
		hasReasoning: true,
		cacheRead: 800,
		cacheWrite: 100,
		cost: 0.123,
		...overrides,
	};
}

test("labels session cost, context, tokens, and prompt cache in plain language", () => {
	const model = buildFooterMetricModel({
		usage: usage(),
		context: { tokens: 50_000, contextWindow: 200_000, percent: 25 },
		provider: "openai",
		rates: { input: 1, output: 1, cacheRead: 0.1, cacheWrite: 0.1 },
		width: 120,
	});

	assert.deepEqual(model.session, [
		{ label: "Cost", value: "$0.123", tone: "text" },
		{
			label: "Context",
			value: "50k used · 150k left (25.0%)",
			tone: "success",
		},
	]);
	assert.deepEqual(model.tokens, [
		{ label: "Input", value: "1.2k", tone: "text" },
		{ label: "Output", value: "350", tone: "text" },
		{ label: "Reasoning", value: "200", tone: "thinkingText" },
	]);
	assert.deepEqual(model.cache, [
		{ label: "Reused", value: "800", tone: "text" },
		{ label: "Stored", value: "100", tone: "text" },
		{ label: "Hit rate", value: "38.1%", tone: "success" },
	]);
});

test("distinguishes subscription cost, missing rates, and updating context", () => {
	const context = { tokens: null, contextWindow: 200_000, percent: null };
	const subscription = buildFooterMetricModel({
		usage: usage({ cost: 0, reasoning: 0, hasReasoning: false }),
		context,
		provider: "cursor",
		width: 100,
	});
	const unknownRates = buildFooterMetricModel({
		usage: usage({ cost: 0 }),
		context,
		provider: "custom",
		width: 100,
	});

	assert.deepEqual(subscription.session, [
		{ label: "Cost", value: "Included (subscription)", tone: "text" },
		{ label: "Context", value: "Usage updating · 200k limit", tone: "muted" },
	]);
	assert.deepEqual(subscription.tokens[2], {
		label: "Reasoning",
		value: "—",
		tone: "thinkingText",
	});
	assert.deepEqual(unknownRates.session[0], {
		label: "Cost",
		value: "Unavailable",
		tone: "muted",
	});
});

test("uses a compact but explicit context label on narrower terminals", () => {
	const model = buildFooterMetricModel({
		usage: usage(),
		context: { tokens: 50_000, contextWindow: 200_000, percent: 25 },
		provider: "openai",
		rates: { input: 1 },
		width: 60,
	});
	assert.deepEqual(model.session[1], {
		label: "Context",
		value: "50k / 200k used (25.0%)",
		tone: "success",
	});
	const veryNarrow = buildFooterMetricModel({
		usage: usage(),
		context: { tokens: 50_000, contextWindow: 200_000, percent: 25 },
		provider: "openai",
		rates: { input: 1 },
		width: 24,
	});
	assert.deepEqual(veryNarrow.session[1], {
		label: "Context",
		value: "50k/200k used",
		tone: "success",
	});
});

test("wraps each labelled group without overflowing", () => {
	const model = buildFooterMetricModel({
		usage: usage(),
		context: { tokens: 50_000, contextWindow: 200_000, percent: 25 },
		provider: "openai",
		rates: { input: 1 },
		width: 40,
	});
	const sections = [
		["SESSION", model.session],
		["SESSION TOKENS", model.tokens],
		["PROMPT CACHE", model.cache],
	] as const;
	for (const width of [24, 40, 72]) {
		for (const [heading, metrics] of sections) {
			const lines = packFooterSection({
				heading,
				items: metrics.map((metric) => `${metric.label} ${metric.value}`),
				width,
				operations: {
					measure: (text) => text.length,
					truncate: (text, available) =>
						text.length <= available
							? text
							: `${text.slice(0, Math.max(0, available - 3))}...`,
				},
			});
			assert.ok(
				lines.every((line) => line.length <= width),
				`${heading} overflowed at ${width}`,
			);
			assert.match(lines[0] ?? "", new RegExp(`^${heading}`));
		}
	}
});
