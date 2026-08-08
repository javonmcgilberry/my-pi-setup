import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
	compactSkillCatalog,
	deduplicateProjectInstructions,
	leanToolNames,
	searchSkills,
} from "./context-budget.mjs";

describe("context budget", () => {
	it("replaces the startup skill inventory with on-demand guidance", () => {
		const prompt = "before\n<skills_instructions>\n- one: long description\n</skills_instructions>\nafter";
		const compact = compactSkillCatalog(prompt);
		assert.match(compact, /Skills remain available on demand/);
		assert.doesNotMatch(compact, /long description/);
		assert.match(compact, /after$/);
	});

	it("keeps the later copy of identical project instructions", () => {
		const prompt = `<project_context>
<project_instructions path="/global/AGENTS.md">
same rules
</project_instructions>

<project_instructions path="/project/AGENTS.md">
same rules
</project_instructions>
</project_context>`;
		const deduplicated = deduplicateProjectInstructions(prompt);
		assert.doesNotMatch(deduplicated, /\/global\/AGENTS\.md/);
		assert.match(deduplicated, /\/project\/AGENTS\.md/);
	});

	it("defers only heavyweight capability tools", () => {
		assert.deepEqual(
			leanToolNames(["read", "subagent", "agent_browser", "mcp", "lens_diagnostics"]),
			["read", "lens_diagnostics"],
		);
		assert.deepEqual(
			leanToolNames(["read", "subagent", "agent_browser"], new Set(["subagent"])),
			["read", "subagent"],
		);
	});

	it("ranks skill names ahead of description-only matches", () => {
		const skills = [
			{ name: "review", description: "Inspect code", filePath: "/review" },
			{ name: "testing", description: "Review test coverage", filePath: "/testing" },
		];
		assert.deepEqual(searchSkills(skills, "review").map(({ name }) => name), ["review", "testing"]);
	});
});
