import { readFile } from "node:fs/promises";
import path from "node:path";

export interface RetentionConfig {
	chatRetentionDays: number;
	metricsRetentionDays: number;
}

export const DEFAULT_RETENTION_CONFIG: RetentionConfig = {
	chatRetentionDays: 7,
	metricsRetentionDays: 365,
};

const MIN_RETENTION_DAYS = 1;
const MAX_CHAT_RETENTION_DAYS = 3650;
const MAX_METRICS_RETENTION_DAYS = 3650;

export function retentionConfigPath(agentDir: string): string {
	return path.join(agentDir, "session-spend-dashboard.json");
}

function boundedDays(value: unknown, fallback: number, maximum: number): number {
	if (typeof value !== "number" || !Number.isInteger(value)) return fallback;
	if (value < MIN_RETENTION_DAYS || value > maximum) return fallback;
	return value;
}

export async function loadRetentionConfig(agentDir: string): Promise<RetentionConfig> {
	let parsed: unknown;
	try {
		parsed = JSON.parse(await readFile(retentionConfigPath(agentDir), "utf8"));
	} catch {
		return { ...DEFAULT_RETENTION_CONFIG };
	}
	if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
		return { ...DEFAULT_RETENTION_CONFIG };
	}
	const record = parsed as Record<string, unknown>;
	const chatRetentionDays = boundedDays(
			record.chatRetentionDays,
			DEFAULT_RETENTION_CONFIG.chatRetentionDays,
			MAX_CHAT_RETENTION_DAYS,
		);
	const metricsRetentionDays = boundedDays(
			record.metricsRetentionDays,
			DEFAULT_RETENTION_CONFIG.metricsRetentionDays,
			MAX_METRICS_RETENTION_DAYS,
		);
	return {
		chatRetentionDays,
		metricsRetentionDays: Math.max(chatRetentionDays, metricsRetentionDays),
	};
}
