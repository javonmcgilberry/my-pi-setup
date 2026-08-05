import type { Dirent } from "node:fs";
import { readdir, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { type TaskUsage, usageFromValue } from "./task-usage.ts";

export interface RunInfo {
	runId: string;
	state: string;
	agent?: string;
	currentTool?: string;
	activityState?: string;
	startedAt?: number;
	lastUpdate?: number;
}

export interface RunSnapshot {
	available: boolean;
	activeRuns: number;
	/** Absolute session file path to the live run that is writing it. */
	bySessionFile: Map<string, RunInfo>;
}

export function emptyRunSnapshot(): RunSnapshot {
	return { available: false, activeRuns: 0, bySessionFile: new Map() };
}

export function asyncRunsRoot(): string {
	const uid = typeof process.getuid === "function" ? process.getuid() : "unknown";
	return path.join(os.tmpdir(), `pi-subagents-uid-${uid}`, "async-subagent-runs");
}

function text(value: unknown): string | undefined {
	return typeof value === "string" && value.length > 0 ? value : undefined;
}

function finiteOrUndefined(value: unknown): number | undefined {
	return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function readStep(step: unknown): { sessionFile?: string; agent?: string; status?: string } {
	if (!step || typeof step !== "object") return {};
	const record = step as Record<string, unknown>;
	return {
		sessionFile: text(record.sessionFile),
		agent: text(record.agent),
		status: text(record.status),
	};
}

export async function readRunSnapshot(root = asyncRunsRoot(), maxRuns = 500): Promise<RunSnapshot> {
	let entries: Dirent[];
	try {
		entries = await readdir(root, { withFileTypes: true, encoding: "utf8" });
	} catch {
		// No directory means subagents have not run on this machine, which is not an error.
		return emptyRunSnapshot();
	}

	const snapshot: RunSnapshot = { available: true, activeRuns: 0, bySessionFile: new Map() };
	let inspected = 0;

	for (const entry of entries) {
		if (!entry.isDirectory() || inspected >= maxRuns) continue;
		inspected++;

		let status: Record<string, unknown>;
		try {
			const raw = await readFile(path.join(root, entry.name, "status.json"), "utf8");
			const parsed: unknown = JSON.parse(raw);
			if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) continue;
			status = parsed as Record<string, unknown>;
		} catch {
			continue;
		}

		const state = text(status.state) ?? "unknown";
		if (state === "running") snapshot.activeRuns++;

		const info: RunInfo = {
			runId: text(status.runId) ?? entry.name,
			state,
			currentTool: text(status.currentTool),
			activityState: text(status.activityState),
			startedAt: finiteOrUndefined(status.startedAt),
			lastUpdate: finiteOrUndefined(status.lastUpdate),
		};

		const steps = Array.isArray(status.steps) ? status.steps : [];
		for (const step of steps) {
			const { sessionFile, agent, status: stepStatus } = readStep(step);
			if (!sessionFile) continue;
			const existing = snapshot.bySessionFile.get(sessionFile);
			const stepState = stepStatus ?? state;
			// A running step wins so an active session is never masked by a finished sibling.
			if (existing && existing.state === "running" && stepState !== "running") continue;
			snapshot.bySessionFile.set(sessionFile, { ...info, state: stepState, agent });
		}

		const topSessionFile = text(status.sessionId);
		if (topSessionFile?.endsWith(".jsonl") && !snapshot.bySessionFile.has(topSessionFile)) {
			snapshot.bySessionFile.set(topSessionFile, info);
		}
	}

	return snapshot;
}

export async function readTaskRunUsage(
	parentSessionFile: string,
	root = asyncRunsRoot(),
	maxRuns = 500,
): Promise<Map<string, TaskUsage>> {
	const usage = new Map<string, TaskUsage>();
	let entries: Dirent[];
	try {
		entries = await readdir(root, { withFileTypes: true, encoding: "utf8" });
	} catch {
		return usage;
	}
	let inspected = 0;
	for (const entry of entries) {
		if (!entry.isDirectory() || inspected >= maxRuns) continue;
		inspected++;
		try {
			const raw = await readFile(path.join(root, entry.name, "status.json"), "utf8");
			const parsed: unknown = JSON.parse(raw);
			if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) continue;
			const status = parsed as Record<string, unknown>;
			if (status.sessionId !== parentSessionFile) continue;
			const runId = text(status.runId) ?? entry.name;
			const totalCost = status.totalCost;
			if (totalCost && typeof totalCost === "object") usage.set(runId, usageFromValue(totalCost));
		} catch {
			continue;
		}
	}
	return usage;
}
