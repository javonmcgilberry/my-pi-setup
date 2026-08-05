import path from "node:path";

import { listActiveSessionFiles } from "./active-sessions.ts";
import { loadRetentionConfig } from "./config.ts";
import { defaultMetricsDatabase, MetricsLedger } from "./ledger.ts";
import { planSessionPrune, pruneSessionTrees, withMaintenanceLock } from "./retention.ts";
import { SessionScanner, type ScanLimits } from "./scan.ts";

const DAY_MS = 24 * 60 * 60 * 1000;

export interface MaintenanceOptions {
	sessionsRoot: string;
	agentDir?: string;
	now?: number;
	dryRun?: boolean;
	activeFiles?: ReadonlySet<string>;
	databasePath?: string;
	scanLimits?: ScanLimits;
}

export interface MaintenanceReport {
	dryRun: boolean;
	chatRetentionDays: number;
	metricsRetentionDays: number;
	scannedSessions: number;
	insertedUsageRecords: number;
	insertedToolCalls: number;
	archivedSessions: number;
	archivedUsageRecords: number;
	archivedToolCalls: number;
	eligibleTrees: number;
	protectedTrees: number;
	eligibleFiles: number;
	eligibleBytes: number;
	removedTrees: number;
	removedFiles: number;
	removedBytes: number;
	expiredMetricSessions: number;
}

export async function runMaintenance(options: MaintenanceOptions): Promise<MaintenanceReport> {
	const now = options.now ?? Date.now();
	const dryRun = options.dryRun ?? true;
	const agentDir = options.agentDir ?? path.dirname(options.sessionsRoot);
	return withMaintenanceLock(agentDir, async () => {
		const config = await loadRetentionConfig(agentDir);
		const activeFiles = await listActiveSessionFiles(agentDir);
		for (const file of options.activeFiles ?? []) activeFiles.add(file);
		if (!dryRun && activeFiles.size > 0) {
			throw new Error("Close every Pi session before deleting expired chat trees");
		}
		const scanner = new SessionScanner(options.sessionsRoot, options.scanLimits);
		const files = await scanner.scan();
		const truncatedFiles = files.filter((file) => file.truncated).length;
		const malformedLines = files.reduce((sum, file) => sum + file.malformedLines, 0);
		if (scanner.fileLimitReached || scanner.unreadablePaths > 0 || truncatedFiles > 0 || malformedLines > 0) {
			throw new Error(
				`Session coverage is incomplete: limit=${scanner.fileLimitReached}, unreadable=${scanner.unreadablePaths}, truncated=${truncatedFiles}, malformed=${malformedLines}`,
			);
		}
		const ledger = new MetricsLedger(options.databasePath ?? defaultMetricsDatabase(options.sessionsRoot, agentDir));
		try {
			const inserted = ledger.ingest(files);
			const coverage = ledger.verifyCoverage(files);
			if (coverage.missingUsageRecords > 0 || coverage.missingToolCalls > 0) {
				throw new Error(
					`Metrics coverage check failed: ${coverage.missingUsageRecords} usage records and ${coverage.missingToolCalls} tool calls missing`,
				);
			}
			const expiredMetricSessions = ledger.pruneMetricsBefore(now - config.metricsRetentionDays * DAY_MS);
			const cutoffMs = now - config.chatRetentionDays * DAY_MS;
			const plan = await planSessionPrune(options.sessionsRoot, cutoffMs, activeFiles);
			const removed = dryRun
				? []
				: await pruneSessionTrees(options.sessionsRoot, cutoffMs, activeFiles, async () => {
						const refreshed = await listActiveSessionFiles(agentDir);
						for (const file of options.activeFiles ?? []) refreshed.add(file);
						return refreshed;
					});
			const archived = ledger.readSessions();
			return {
				dryRun,
				chatRetentionDays: config.chatRetentionDays,
				metricsRetentionDays: config.metricsRetentionDays,
				scannedSessions: files.length,
				insertedUsageRecords: inserted.usageRecords,
				insertedToolCalls: inserted.toolCalls,
				archivedSessions: archived.length,
				archivedUsageRecords: archived.reduce((sum, file) => sum + file.records.length, 0),
				archivedToolCalls: archived.reduce((sum, file) => sum + file.toolCallKeys.length, 0),
				eligibleTrees: plan.eligible.length,
				protectedTrees: plan.protected.length,
				eligibleFiles: plan.eligible.reduce((sum, tree) => sum + tree.files, 0),
				eligibleBytes: plan.eligible.reduce((sum, tree) => sum + tree.bytes, 0),
				removedTrees: removed.length,
				removedFiles: removed.reduce((sum, tree) => sum + tree.files, 0),
				removedBytes: removed.reduce((sum, tree) => sum + tree.bytes, 0),
				expiredMetricSessions,
			};
		} finally {
			ledger.close();
		}
	});
}
