import { readFile } from "node:fs/promises";
import type { ExtensionAPI, Skill } from "@earendil-works/pi-coding-agent";

import {
	compactSkillCatalog,
	deduplicateProjectInstructions,
	DEFERRED_CAPABILITIES,
	leanToolNames,
	searchSkills,
} from "./context-budget.mjs";

type CatalogParameters = {
	action: "search" | "read";
	query: string;
};

type CapabilityParameters = {
	capability: keyof typeof DEFERRED_CAPABILITIES;
};

const CatalogParametersSchema = {
	type: "object",
	additionalProperties: false,
	properties: {
		action: { type: "string", enum: ["search", "read"] },
		query: { type: "string", description: "Search terms or an exact skill name." },
	},
	required: ["action", "query"],
} as const;

const CapabilityParametersSchema = {
	type: "object",
	additionalProperties: false,
	properties: {
		capability: { type: "string", enum: Object.keys(DEFERRED_CAPABILITIES) },
	},
	required: ["capability"],
} as const;

function textResult(text: string, details: Record<string, unknown> = {}) {
	return { content: [{ type: "text" as const, text }], details };
}

export default function contextBudget(pi: ExtensionAPI): void {
	let skills: Skill[] = [];
	const activatedTools = new Set<string>();

	pi.registerTool({
		name: "skills_catalog",
		label: "Skills catalog",
		description: "Search loaded skills or read one skill's full instructions on demand.",
		promptSnippet: "Search or read specialized skill instructions on demand",
		promptGuidelines: [
			"Use skills_catalog search when a task may have a specialized workflow, then read the selected skill before applying it.",
		],
		parameters: CatalogParametersSchema,
		async execute(_toolCallId, params: CatalogParameters) {
			if (params.action === "search") {
				const matches = searchSkills(skills, params.query) as Skill[];
				if (matches.length === 0) return textResult("No matching skills found.", { matches: [] });
				const text = matches.map((skill) => `- ${skill.name}: ${skill.description}`).join("\n");
				return textResult(text, { matches: matches.map(({ name, filePath }) => ({ name, filePath })) });
			}

			const skill = skills.find(({ name }) => name === params.query.trim());
			if (!skill) throw new Error(`Unknown skill: ${params.query}. Search first for the exact name.`);
			const content = await readFile(skill.filePath, "utf8");
			return textResult(`<skill name="${skill.name}" file="${skill.filePath}">\n${content}\n</skill>`, {
				name: skill.name,
				filePath: skill.filePath,
			});
		},
	});

	pi.registerTool({
		name: "activate_capability",
		label: "Activate capability",
		description: "Activate a heavyweight tool group for the rest of this Pi session.",
		promptSnippet: "Activate browser, coordination, delegation, or MCP tools when needed",
		parameters: CapabilityParametersSchema,
		async execute(_toolCallId, params: CapabilityParameters) {
			const configured = new Set(pi.getAllTools().map(({ name }) => name));
			const requested = DEFERRED_CAPABILITIES[params.capability].filter((name) => configured.has(name));
			if (requested.length === 0) throw new Error(`Capability is unavailable: ${params.capability}`);
			const active = new Set(pi.getActiveTools());
			for (const name of requested) {
				active.add(name);
				activatedTools.add(name);
			}
			pi.setActiveTools([...active]);
			return textResult(`Activated ${params.capability}: ${requested.join(", ")}`, {
				capability: params.capability,
				tools: requested,
			});
		},
	});

	pi.on("before_agent_start", (event) => {
		skills = event.systemPromptOptions.skills ?? [];
		pi.setActiveTools(leanToolNames(pi.getActiveTools(), activatedTools));
		return {
			systemPrompt: compactSkillCatalog(deduplicateProjectInstructions(event.systemPrompt)),
		};
	});
}
