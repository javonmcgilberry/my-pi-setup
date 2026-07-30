import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

type Usage = {
	input?: number;
	output?: number;
	reasoning?: number;
	cacheRead?: number;
	cacheWrite?: number;
	cost?: { total?: number };
};

function compact(value: number): string {
	if (value < 1000) return String(value);
	if (value < 10000) return `${(value / 1000).toFixed(1)}k`;
	if (value < 1_000_000) return `${Math.round(value / 1000)}k`;
	return `${(value / 1_000_000).toFixed(1)}M`;
}

export default function (pi: ExtensionAPI) {
	const update = (ctx: ExtensionContext) => {
		const totals = { input: 0, output: 0, reasoning: 0, cost: 0 };
		for (const entry of ctx.sessionManager.getEntries()) {
			if (entry.type !== "message" || entry.message.role !== "assistant") continue;
			const usage = entry.message.usage as Usage;
			totals.input += usage.input ?? 0;
			totals.output += usage.output ?? 0;
			totals.reasoning += usage.reasoning ?? 0;
			totals.cost += usage.cost?.total ?? 0;
		}
		const context = ctx.getContextUsage();
		const contextText = context ? `${context.percent.toFixed(1)}% / ${compact(context.contextWindow)}` : "?";
		ctx.ui.setStatus("clear-status", `Tokens ${compact(totals.input)} in · ${compact(totals.output)} out · ${compact(totals.reasoning)} thinking | Cost $${totals.cost.toFixed(3)} | Context ${contextText}`);
	};

	pi.on("session_start", async (_event, ctx) => update(ctx));
	pi.on("message_end", async (_event, ctx) => update(ctx));
	pi.on("thinking_level_select", async (_event, ctx) => update(ctx));
}
