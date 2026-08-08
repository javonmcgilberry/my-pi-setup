const SKILLS_OPENERS = ["<skills_instructions>", "<available_skills>"];
const SKILLS_CLOSERS = ["</skills_instructions>", "</available_skills>"];

export const COMPACT_SKILLS_GUIDANCE = `<skills_instructions>
Skills remain available on demand.
- Use skills_catalog search when a task may benefit from a specialized workflow.
- Use skills_catalog read before following a selected skill.
- Explicit /skill commands may inject full skill instructions directly.
</skills_instructions>`;

export const DEFERRED_CAPABILITIES = Object.freeze({
	browser: ["agent_browser"],
	coordination: ["intercom"],
	delegation: ["subagent", "subagent_wait", "subagent_supervisor"],
	mcp: ["mcp", "mcpScript"],
});

function replaceBlock(prompt, opener, closer, replacement) {
	const start = prompt.indexOf(opener);
	if (start === -1) return prompt;
	const close = prompt.indexOf(closer, start);
	if (close === -1) return prompt;
	const end = close + closer.length;
	return `${prompt.slice(0, start).trimEnd()}\n\n${replacement}${prompt.slice(end)}`;
}

export function compactSkillCatalog(prompt) {
	for (let index = 0; index < SKILLS_OPENERS.length; index += 1) {
		if (prompt.includes(SKILLS_OPENERS[index])) {
			return replaceBlock(prompt, SKILLS_OPENERS[index], SKILLS_CLOSERS[index], COMPACT_SKILLS_GUIDANCE);
		}
	}
	return prompt;
}

export function deduplicateProjectInstructions(prompt) {
	const pattern = /<project_instructions path="([^"]+)">\n([\s\S]*?)\n<\/project_instructions>/g;
	const matches = [...prompt.matchAll(pattern)];
	if (matches.length < 2) return prompt;

	const seen = new Set();
	let result = prompt;
	for (let index = matches.length - 1; index >= 0; index -= 1) {
		const match = matches[index];
		const content = match[2].replace(/\r\n?/g, "\n").trim();
		if (!seen.has(content)) {
			seen.add(content);
			continue;
		}
		result = `${result.slice(0, match.index)}${result.slice(match.index + match[0].length)}`;
	}
	return result.replace(/\n{3,}/g, "\n\n");
}

export function deferredToolNames() {
	return new Set(Object.values(DEFERRED_CAPABILITIES).flat());
}

export function leanToolNames(activeToolNames, activatedToolNames = new Set()) {
	const deferred = deferredToolNames();
	return activeToolNames.filter((name) => !deferred.has(name) || activatedToolNames.has(name));
}

function searchTerms(query) {
	return query.toLowerCase().match(/[a-z0-9]+/g) ?? [];
}

function skillScore(skill, terms) {
	if (terms.length === 0) return 0;
	const name = skill.name.toLowerCase();
	const description = skill.description.toLowerCase();
	let score = 0;
	for (const term of terms) {
		if (name === term) score += 12;
		else if (name.includes(term)) score += 6;
		if (description.includes(term)) score += 2;
	}
	return score;
}

export function searchSkills(skills, query, limit = 20) {
	const terms = searchTerms(query);
	return skills
		.map((skill) => ({ skill, score: skillScore(skill, terms) }))
		.filter(({ score }) => terms.length === 0 || score > 0)
		.sort((left, right) => right.score - left.score || left.skill.name.localeCompare(right.skill.name))
		.slice(0, limit)
		.map(({ skill }) => skill);
}
