import { mkdirSync } from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";

import type { SessionFile, UsageRecord } from "./scan.ts";

const SCHEMA_VERSION = 2;

export interface LedgerIngestResult {
	sessions: number;
	usageRecords: number;
	toolCalls: number;
}

export interface LedgerCoverage {
	missingUsageRecords: number;
	missingToolCalls: number;
}

export function defaultMetricsDatabase(sessionsRoot: string, agentDir = path.dirname(sessionsRoot)): string {
	return path.join(agentDir, "session-metrics", "metrics.sqlite");
}

function optionalText(value: unknown): string | null {
	return typeof value === "string" && value.length > 0 ? value : null;
}

function numberValue(value: unknown): number {
	return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export class MetricsLedger {
	private readonly database: DatabaseSync;

	constructor(databasePath: string) {
		mkdirSync(path.dirname(databasePath), { recursive: true, mode: 0o700 });
		this.database = new DatabaseSync(databasePath);
		try {
			this.database.exec("PRAGMA journal_mode = WAL");
			this.database.exec("PRAGMA busy_timeout = 5000");
			this.database.exec("PRAGMA foreign_keys = ON");
			this.initializeSchema();
		} catch (error) {
			this.database.close();
			throw error;
		}
	}

	private initializeSchema(): void {
		const version = Number(this.database.prepare("PRAGMA user_version").get()?.user_version ?? 0);
		if (version > SCHEMA_VERSION) {
			throw new Error(`Unsupported session metrics schema ${version}; expected ${SCHEMA_VERSION}`);
		}
		if (version === SCHEMA_VERSION) return;
		this.database.exec(`
			BEGIN IMMEDIATE;
			CREATE TABLE IF NOT EXISTS source_files (
				rel_path TEXT PRIMARY KEY,
				file_path TEXT NOT NULL,
				session_id TEXT NOT NULL,
				name TEXT,
				cwd TEXT NOT NULL,
				started_at INTEGER NOT NULL,
				updated_at INTEGER NOT NULL,
				mtime_ms INTEGER NOT NULL,
				size_bytes INTEGER NOT NULL,
				parent_session_id TEXT,
				malformed_lines INTEGER NOT NULL,
				truncated INTEGER NOT NULL
			);
			CREATE TABLE IF NOT EXISTS usage_records (
				dedupe_key TEXT PRIMARY KEY,
				origin_rel_path TEXT NOT NULL REFERENCES source_files(rel_path) ON DELETE CASCADE,
				timestamp INTEGER NOT NULL,
				provider TEXT NOT NULL,
				model TEXT NOT NULL,
				usage_type TEXT NOT NULL CHECK (usage_type IN ('assistant', 'compaction', 'branch_summary')),
				input_tokens INTEGER NOT NULL,
				output_tokens INTEGER NOT NULL,
				cache_read_tokens INTEGER NOT NULL,
				cache_write_tokens INTEGER NOT NULL,
				reasoning_tokens INTEGER NOT NULL,
				total_tokens INTEGER NOT NULL,
				cost REAL NOT NULL,
				cost_reported INTEGER NOT NULL
			);
			CREATE TABLE IF NOT EXISTS tool_calls (
				dedupe_key TEXT PRIMARY KEY,
				origin_rel_path TEXT NOT NULL REFERENCES source_files(rel_path) ON DELETE CASCADE
			);
			CREATE TABLE IF NOT EXISTS usage_occurrences (
				dedupe_key TEXT NOT NULL REFERENCES usage_records(dedupe_key) ON DELETE CASCADE,
				source_rel_path TEXT NOT NULL REFERENCES source_files(rel_path) ON DELETE CASCADE,
				PRIMARY KEY (dedupe_key, source_rel_path)
			);
			CREATE TABLE IF NOT EXISTS tool_call_occurrences (
				dedupe_key TEXT NOT NULL REFERENCES tool_calls(dedupe_key) ON DELETE CASCADE,
				source_rel_path TEXT NOT NULL REFERENCES source_files(rel_path) ON DELETE CASCADE,
				PRIMARY KEY (dedupe_key, source_rel_path)
			);
			INSERT OR IGNORE INTO usage_occurrences (dedupe_key, source_rel_path)
				SELECT dedupe_key, origin_rel_path FROM usage_records;
			INSERT OR IGNORE INTO tool_call_occurrences (dedupe_key, source_rel_path)
				SELECT dedupe_key, origin_rel_path FROM tool_calls;
			CREATE INDEX IF NOT EXISTS usage_timestamp_idx ON usage_records(timestamp);
			CREATE INDEX IF NOT EXISTS usage_origin_idx ON usage_records(origin_rel_path);
			CREATE INDEX IF NOT EXISTS tool_origin_idx ON tool_calls(origin_rel_path);
			PRAGMA user_version = ${SCHEMA_VERSION};
			COMMIT;
		`);
	}

	ingest(files: readonly SessionFile[]): LedgerIngestResult {
		const ordered = [...files].sort((a, b) => a.startedAt - b.startedAt || a.relPath.localeCompare(b.relPath));
		const upsertSource = this.database.prepare(`
			INSERT INTO source_files (
				rel_path, file_path, session_id, name, cwd, started_at, updated_at,
				mtime_ms, size_bytes, parent_session_id, malformed_lines, truncated
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			ON CONFLICT(rel_path) DO UPDATE SET
				file_path = excluded.file_path,
				session_id = excluded.session_id,
				name = excluded.name,
				cwd = excluded.cwd,
				started_at = excluded.started_at,
				updated_at = excluded.updated_at,
				mtime_ms = excluded.mtime_ms,
				size_bytes = excluded.size_bytes,
				parent_session_id = excluded.parent_session_id,
				malformed_lines = excluded.malformed_lines,
				truncated = excluded.truncated
		`);
		const insertUsage = this.database.prepare(`
			INSERT OR IGNORE INTO usage_records (
				dedupe_key, origin_rel_path, timestamp, provider, model, usage_type,
				input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
				reasoning_tokens, total_tokens, cost, cost_reported
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		`);
		const insertToolCall = this.database.prepare(
			"INSERT OR IGNORE INTO tool_calls (dedupe_key, origin_rel_path) VALUES (?, ?)",
		);
		const insertUsageOccurrence = this.database.prepare(
			"INSERT OR IGNORE INTO usage_occurrences (dedupe_key, source_rel_path) VALUES (?, ?)",
		);
		const insertToolOccurrence = this.database.prepare(
			"INSERT OR IGNORE INTO tool_call_occurrences (dedupe_key, source_rel_path) VALUES (?, ?)",
		);
		let usageRecords = 0;
		let toolCalls = 0;

		this.database.exec("BEGIN IMMEDIATE");
		try {
			for (const file of ordered) {
				const latestUsage = file.records.reduce((latest, record) => Math.max(latest, record.timestamp), 0);
				const updatedAt = Math.max(file.startedAt, file.mtimeMs, latestUsage);
				upsertSource.run(
					file.relPath,
					file.file,
					file.sessionId,
					null,
					file.cwd,
					file.startedAt,
					updatedAt,
					file.mtimeMs,
					file.sizeBytes,
					optionalText(file.parentSessionId),
					file.malformedLines,
					file.truncated ? 1 : 0,
				);
				for (const record of file.records) {
					const result = insertUsage.run(
						record.dedupeKey,
						file.relPath,
						record.timestamp,
						record.provider,
						record.model,
						record.usageType,
						record.input,
						record.output,
						record.cacheRead,
						record.cacheWrite,
						record.reasoning,
						record.totalTokens,
						record.cost,
						record.costReported ? 1 : 0,
					);
					usageRecords += Number(result.changes);
					insertUsageOccurrence.run(record.dedupeKey, file.relPath);
				}
				for (const key of file.toolCallKeys) {
					toolCalls += Number(insertToolCall.run(key, file.relPath).changes);
					insertToolOccurrence.run(key, file.relPath);
				}
			}
			this.database.exec("COMMIT");
		} catch (error) {
			this.database.exec("ROLLBACK");
			throw error;
		}
		return { sessions: ordered.length, usageRecords, toolCalls };
	}

	readSessions(): SessionFile[] {
		const rows = this.database
			.prepare(`
				SELECT rel_path, file_path, session_id, name, cwd, started_at, mtime_ms,
					size_bytes, parent_session_id, malformed_lines, truncated
				FROM source_files
				ORDER BY started_at, rel_path
			`)
			.all() as Record<string, unknown>[];
		const sessions = new Map<string, SessionFile>();
		for (const row of rows) {
			const relPath = String(row.rel_path);
			sessions.set(relPath, {
				file: String(row.file_path),
				relPath,
				sessionId: String(row.session_id),
				name: undefined,
				cwd: String(row.cwd),
				startedAt: numberValue(row.started_at),
				mtimeMs: numberValue(row.mtime_ms),
				sizeBytes: numberValue(row.size_bytes),
				parentSessionId: optionalText(row.parent_session_id) ?? undefined,
				records: [],
				toolCallKeys: [],
				malformedLines: numberValue(row.malformed_lines),
				truncated: numberValue(row.truncated) === 1,
			});
		}

		const usageRows = this.database
			.prepare(`
				SELECT usage_records.*, usage_occurrences.source_rel_path
				FROM usage_occurrences
				JOIN usage_records USING (dedupe_key)
				ORDER BY timestamp, dedupe_key, source_rel_path
			`)
			.all() as Record<string, unknown>[];
		for (const row of usageRows) {
			const session = sessions.get(String(row.source_rel_path));
			if (!session) continue;
			const usageType = String(row.usage_type) as UsageRecord["usageType"];
			session.records.push({
				dedupeKey: String(row.dedupe_key),
				timestamp: numberValue(row.timestamp),
				provider: String(row.provider),
				model: String(row.model),
				usageType,
				input: numberValue(row.input_tokens),
				output: numberValue(row.output_tokens),
				cacheRead: numberValue(row.cache_read_tokens),
				cacheWrite: numberValue(row.cache_write_tokens),
				reasoning: numberValue(row.reasoning_tokens),
				totalTokens: numberValue(row.total_tokens),
				cost: numberValue(row.cost),
				costReported: numberValue(row.cost_reported) === 1,
			});
		}

		const toolRows = this.database
			.prepare("SELECT dedupe_key, source_rel_path FROM tool_call_occurrences")
			.all() as Record<string, unknown>[];
		for (const row of toolRows) {
			sessions.get(String(row.source_rel_path))?.toolCallKeys.push(String(row.dedupe_key));
		}
		return [...sessions.values()];
	}

	verifyCoverage(files: readonly SessionFile[]): LedgerCoverage {
		const hasUsage = this.database.prepare("SELECT 1 AS present FROM usage_records WHERE dedupe_key = ?");
		const hasTool = this.database.prepare("SELECT 1 AS present FROM tool_calls WHERE dedupe_key = ?");
		let missingUsageRecords = 0;
		let missingToolCalls = 0;
		for (const file of files) {
			for (const record of file.records) {
				if (!hasUsage.get(record.dedupeKey)) missingUsageRecords++;
			}
			for (const key of file.toolCallKeys) {
				if (!hasTool.get(key)) missingToolCalls++;
			}
		}
		return { missingUsageRecords, missingToolCalls };
	}

	pruneMetricsBefore(cutoffMs: number): number {
		this.database.exec("BEGIN IMMEDIATE");
		try {
			this.database
				.prepare(`
					UPDATE usage_records
					SET origin_rel_path = (
						SELECT occurrence.source_rel_path
						FROM usage_occurrences AS occurrence
						JOIN source_files AS source ON source.rel_path = occurrence.source_rel_path
						WHERE occurrence.dedupe_key = usage_records.dedupe_key
							AND source.updated_at >= ?
						ORDER BY source.started_at, source.rel_path
						LIMIT 1
					)
					WHERE origin_rel_path IN (SELECT rel_path FROM source_files WHERE updated_at < ?)
						AND EXISTS (
							SELECT 1
							FROM usage_occurrences AS occurrence
							JOIN source_files AS source ON source.rel_path = occurrence.source_rel_path
							WHERE occurrence.dedupe_key = usage_records.dedupe_key
								AND source.updated_at >= ?
						)
				`)
				.run(cutoffMs, cutoffMs, cutoffMs);
			this.database
				.prepare(`
					UPDATE tool_calls
					SET origin_rel_path = (
						SELECT occurrence.source_rel_path
						FROM tool_call_occurrences AS occurrence
						JOIN source_files AS source ON source.rel_path = occurrence.source_rel_path
						WHERE occurrence.dedupe_key = tool_calls.dedupe_key
							AND source.updated_at >= ?
						ORDER BY source.started_at, source.rel_path
						LIMIT 1
					)
					WHERE origin_rel_path IN (SELECT rel_path FROM source_files WHERE updated_at < ?)
						AND EXISTS (
							SELECT 1
							FROM tool_call_occurrences AS occurrence
							JOIN source_files AS source ON source.rel_path = occurrence.source_rel_path
							WHERE occurrence.dedupe_key = tool_calls.dedupe_key
								AND source.updated_at >= ?
						)
				`)
				.run(cutoffMs, cutoffMs, cutoffMs);
			const result = this.database.prepare("DELETE FROM source_files WHERE updated_at < ?").run(cutoffMs);
			this.database.exec("COMMIT");
			return Number(result.changes);
		} catch (error) {
			this.database.exec("ROLLBACK");
			throw error;
		}
	}

	close(): void {
		this.database.close();
	}
}
