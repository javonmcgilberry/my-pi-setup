import type { SessionFile } from "./scan.ts";
import type { RunSnapshot } from "./runs.ts";

export type SessionActivity = "live" | "active" | "idle" | "dormant";

export const ACTIVE_WINDOW_MS = 5 * 60 * 1000;
export const IDLE_WINDOW_MS = 24 * 60 * 60 * 1000;

export interface TokenTotals {
	input: number;
	output: number;
	cacheRead: number;
	cacheWrite: number;
	reasoning: number;
	totalTokens: number;
}

export interface Totals extends TokenTotals {
	cost: number;
	calls: number;
	toolCalls: number;
	sessions: number;
	projects: number;
	callsWithoutReportedCost: number;
}

export interface DayBucket {
	day: string;
	cost: number;
	totalTokens: number;
	calls: number;
}

export interface ModelBucket extends TokenTotals {
	model: string;
	providers: string[];
	cost: number;
	calls: number;
}

export interface ProviderBucket extends TokenTotals {
	provider: string;
	cost: number;
	calls: number;
}

export interface ProjectBucket extends TokenTotals {
	cwd: string;
	label: string;
	cost: number;
	calls: number;
	sessions: number;
	updatedAt: number;
}

export interface SessionRow extends TokenTotals {
	sessionId: string;
	name?: string;
	relPath: string;
	cwd: string;
	label: string;
	startedAt: number;
	updatedAt: number;
	activity: SessionActivity;
	cost: number;
	/** Spend replayed from an ancestor session, already attributed to that ancestor. */
	inheritedCost: number;
	calls: number;
	toolCalls: number;
	models: string[];
	providers: string[];
	parentSessionId?: string;
	isSubagent: boolean;
	runState?: string;
	runAgent?: string;
	runTool?: string;
}

export interface Snapshot {
	generatedAt: number;
	sessionsRoot: string;
	scan: {
		files: number;
		malformedLines: number;
		truncatedFiles: number;
		durationMs: number;
	};
	runs: {
		available: boolean;
		activeRuns: number;
	};
	totals: Totals;
	byDay: DayBucket[];
	byModel: ModelBucket[];
	byProvider: ProviderBucket[];
	byProject: ProjectBucket[];
	sessions: SessionRow[];
}

export interface AggregateOptions {
	sessionsRoot: string;
	now: number;
	scanDurationMs: number;
	runs?: RunSnapshot;
	maxSessions?: number;
	maxDays?: number;
}

function emptyTokens(): TokenTotals {
	return { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, reasoning: 0, totalTokens: 0 };
}

function addTokens(target: TokenTotals, source: TokenTotals): void {
	target.input += source.input;
	target.output += source.output;
	target.cacheRead += source.cacheRead;
	target.cacheWrite += source.cacheWrite;
	target.reasoning += source.reasoning;
	target.totalTokens += source.totalTokens;
}

export function projectLabel(cwd: string): string {
	if (!cwd || cwd === "unknown") return "unknown";
	const parts = cwd.split("/").filter(Boolean);
	if (parts.length === 0) return cwd;
	return parts.slice(-2).join("/");
}

function dayKey(timestamp: number): string {
	const date = new Date(timestamp);
	if (!Number.isFinite(date.getTime())) return "unknown";
	const month = `${date.getMonth() + 1}`.padStart(2, "0");
	const day = `${date.getDate()}`.padStart(2, "0");
	return `${date.getFullYear()}-${month}-${day}`;
}

function deriveActivity(updatedAt: number, now: number, runState: string | undefined): SessionActivity {
	if (runState === "running") return "live";
	const age = now - updatedAt;
	if (age <= ACTIVE_WINDOW_MS) return "active";
	if (age <= IDLE_WINDOW_MS) return "idle";
	return "dormant";
}

/**
 * Forked and resumed sessions replay their ancestor's entries, so the same LLM call is
 * present in several files. Each call is attributed once, to the earliest session that
 * contains it, which keeps every rollup summing to the same grand total.
 */
function buildOriginIndex(files: SessionFile[]): Map<string, string> {
	const ordered = [...files].sort((a, b) => a.startedAt - b.startedAt || a.relPath.localeCompare(b.relPath));
	const origin = new Map<string, string>();
	for (const file of ordered) {
		for (const record of file.records) {
			if (!origin.has(record.dedupeKey)) origin.set(record.dedupeKey, file.relPath);
		}
	}
	return origin;
}

function buildToolOriginIndex(files: SessionFile[]): Map<string, string> {
	const ordered = [...files].sort((a, b) => a.startedAt - b.startedAt || a.relPath.localeCompare(b.relPath));
	const origin = new Map<string, string>();
	for (const file of ordered) {
		for (const key of file.toolCallKeys) {
			if (!origin.has(key)) origin.set(key, file.relPath);
		}
	}
	return origin;
}

export function aggregate(files: SessionFile[], options: AggregateOptions): Snapshot {
	const { sessionsRoot, now, scanDurationMs } = options;
	const maxSessions = options.maxSessions ?? 400;
	const maxDays = options.maxDays ?? 120;
	const origin = buildOriginIndex(files);
	const toolOrigin = buildToolOriginIndex(files);
	const runs = options.runs;

	const totals: Totals = {
		...emptyTokens(),
		cost: 0,
		calls: 0,
		toolCalls: 0,
		sessions: 0,
		projects: 0,
		callsWithoutReportedCost: 0,
	};

	const days = new Map<string, DayBucket>();
	const models = new Map<string, ModelBucket & { providerSet: Set<string> }>();
	const providers = new Map<string, ProviderBucket>();
	const projects = new Map<string, ProjectBucket>();
	const sessions: SessionRow[] = [];

	let malformedLines = 0;
	let truncatedFiles = 0;

	for (const file of files) {
		malformedLines += file.malformedLines;
		if (file.truncated) truncatedFiles++;

		const sessionTokens = emptyTokens();
		let sessionCost = 0;
		let inheritedCost = 0;
		let sessionCalls = 0;
		let sessionToolCalls = 0;
		let updatedAt = Math.max(file.mtimeMs, file.startedAt);
		const sessionModels = new Set<string>();
		const sessionProviders = new Set<string>();

		for (const record of file.records) {
			if (record.timestamp > 0) updatedAt = Math.max(updatedAt, record.timestamp);
			if (record.model !== "unknown") sessionModels.add(record.model);
			if (record.provider !== "unknown") sessionProviders.add(record.provider);

			if (origin.get(record.dedupeKey) !== file.relPath) {
				inheritedCost += record.cost;
				continue;
			}

			sessionCost += record.cost;
			sessionCalls++;
			addTokens(sessionTokens, record);
			if (!record.costReported) totals.callsWithoutReportedCost++;

			const bucketDay = dayKey(record.timestamp > 0 ? record.timestamp : file.startedAt);
			const dayBucket = days.get(bucketDay) ?? { day: bucketDay, cost: 0, totalTokens: 0, calls: 0 };
			dayBucket.cost += record.cost;
			dayBucket.totalTokens += record.totalTokens;
			dayBucket.calls++;
			days.set(bucketDay, dayBucket);

			const modelBucket =
				models.get(record.model) ??
				{ model: record.model, providers: [], providerSet: new Set<string>(), cost: 0, calls: 0, ...emptyTokens() };
			modelBucket.cost += record.cost;
			modelBucket.calls++;
			modelBucket.providerSet.add(record.provider);
			addTokens(modelBucket, record);
			models.set(record.model, modelBucket);

			const providerBucket =
				providers.get(record.provider) ?? { provider: record.provider, cost: 0, calls: 0, ...emptyTokens() };
			providerBucket.cost += record.cost;
			providerBucket.calls++;
			addTokens(providerBucket, record);
			providers.set(record.provider, providerBucket);
		}

		for (const key of file.toolCallKeys) {
			if (toolOrigin.get(key) === file.relPath) sessionToolCalls++;
		}

		const run = runs?.bySessionFile.get(file.file);
		const activity = deriveActivity(updatedAt, now, run?.state);

		totals.cost += sessionCost;
		totals.calls += sessionCalls;
		totals.toolCalls += sessionToolCalls;
		addTokens(totals, sessionTokens);

		const projectBucket =
			projects.get(file.cwd) ??
			{ cwd: file.cwd, label: projectLabel(file.cwd), cost: 0, calls: 0, sessions: 0, updatedAt: 0, ...emptyTokens() };
		projectBucket.cost += sessionCost;
		projectBucket.calls += sessionCalls;
		projectBucket.sessions++;
		projectBucket.updatedAt = Math.max(projectBucket.updatedAt, updatedAt);
		addTokens(projectBucket, sessionTokens);
		projects.set(file.cwd, projectBucket);

		sessions.push({
			sessionId: file.sessionId,
			name: file.name,
			relPath: file.relPath,
			cwd: file.cwd,
			label: projectLabel(file.cwd),
			startedAt: file.startedAt,
			updatedAt,
			activity,
			cost: sessionCost,
			inheritedCost,
			calls: sessionCalls,
			toolCalls: sessionToolCalls,
			models: [...sessionModels].sort(),
			providers: [...sessionProviders].sort(),
			parentSessionId: file.parentSessionId,
			isSubagent: file.parentSessionId !== undefined || file.name?.startsWith("subagent-") === true,
			runState: run?.state,
			runAgent: run?.agent,
			runTool: run?.currentTool,
			...sessionTokens,
		});
	}

	totals.sessions = files.length;
	totals.projects = projects.size;

	const activityRank: Record<SessionActivity, number> = { live: 0, active: 1, idle: 2, dormant: 3 };
	sessions.sort(
		(a, b) => activityRank[a.activity] - activityRank[b.activity] || b.updatedAt - a.updatedAt,
	);

	return {
		generatedAt: now,
		sessionsRoot,
		scan: { files: files.length, malformedLines, truncatedFiles, durationMs: scanDurationMs },
		runs: { available: runs?.available ?? false, activeRuns: runs?.activeRuns ?? 0 },
		totals,
		byDay: [...days.values()].sort((a, b) => a.day.localeCompare(b.day)).slice(-maxDays),
		byModel: [...models.values()]
			.map(({ providerSet, ...bucket }) => ({ ...bucket, providers: [...providerSet].sort() }))
			.sort((a, b) => b.cost - a.cost || b.totalTokens - a.totalTokens),
		byProvider: [...providers.values()].sort((a, b) => b.cost - a.cost || b.totalTokens - a.totalTokens),
		byProject: [...projects.values()].sort((a, b) => b.cost - a.cost || b.updatedAt - a.updatedAt),
		sessions: sessions.slice(0, maxSessions),
	};
}
