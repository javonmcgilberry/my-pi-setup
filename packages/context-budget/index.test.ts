import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import type { ExtensionAPI, Skill } from "@earendil-works/pi-coding-agent";

import contextBudget from "./index.ts";

type Handler = (event: any) => any;
type RegisteredTool = {
	name: string;
	execute: (...args: any[]) => Promise<any>;
};

function createHarness() {
	const handlers = new Map<string, Handler>();
	const tools = new Map<string, RegisteredTool>();
	let activeTools = [
		"read",
		"subagent",
		"subagent_wait",
		"subagent_supervisor",
		"agent_browser",
		"intercom",
		"mcp",
		"mcpScript",
	];
	const configuredTools = new Set(activeTools);

	const pi = {
		registerTool(tool: RegisteredTool) {
			tools.set(tool.name, tool);
			configuredTools.add(tool.name);
			activeTools.push(tool.name);
		},
		on(name: string, handler: Handler) {
			handlers.set(name, handler);
		},
		getActiveTools() {
			return [...activeTools];
		},
		getAllTools() {
			return [...configuredTools].map((name) => ({ name }));
		},
		setActiveTools(names: string[]) {
			activeTools = [...names];
		},
	} as unknown as ExtensionAPI;

	contextBudget(pi);
	return {
		handlers,
		tools,
		activeTools: () => [...activeTools],
	};
}

function beforeAgentStartEvent(skills: Skill[]) {
	return {
		systemPrompt: `before
<skills_instructions>
full catalog
</skills_instructions>
after`,
		systemPromptOptions: { skills },
	};
}

describe("context budget extension", () => {
	it("defers capability tools and preserves groups activated for the session", async () => {
		const harness = createHarness();
		const beforeAgentStart = harness.handlers.get("before_agent_start");
		assert.ok(beforeAgentStart);

		const result = await beforeAgentStart(beforeAgentStartEvent([]));
		assert.match(result.systemPrompt, /Skills remain available on demand/);
		assert.deepEqual(harness.activeTools(), ["read", "skills_catalog", "activate_capability"]);

		const activate = harness.tools.get("activate_capability");
		assert.ok(activate);
		await activate.execute("call", { capability: "delegation" });
		assert.deepEqual(harness.activeTools(), [
			"read",
			"skills_catalog",
			"activate_capability",
			"subagent",
			"subagent_wait",
			"subagent_supervisor",
		]);

		await beforeAgentStart(beforeAgentStartEvent([]));
		assert.ok(harness.activeTools().includes("subagent"));
		assert.ok(!harness.activeTools().includes("agent_browser"));
	});

	it("searches loaded skills and reads the selected instructions", async () => {
		const directory = await mkdtemp(join(tmpdir(), "pi-context-budget-test-"));
		try {
			const filePath = join(directory, "SKILL.md");
			await writeFile(filePath, "---\nname: focused-testing\ndescription: Run focused tests\n---\n\n# Focused testing\n");
			const skill = {
				name: "focused-testing",
				description: "Run focused tests",
				filePath,
				baseDir: directory,
				sourceInfo: {} as Skill["sourceInfo"],
				disableModelInvocation: false,
			};
			const harness = createHarness();
			await harness.handlers.get("before_agent_start")?.(beforeAgentStartEvent([skill]));

			const catalog = harness.tools.get("skills_catalog");
			assert.ok(catalog);
			const search = await catalog.execute("search", { action: "search", query: "tests" });
			assert.match(search.content[0].text, /focused-testing: Run focused tests/);

			const read = await catalog.execute("read", { action: "read", query: "focused-testing" });
			assert.match(read.content[0].text, /# Focused testing/);
			assert.equal(read.details.filePath, filePath);
		} finally {
			await rm(directory, { recursive: true, force: true });
		}
	});
});
