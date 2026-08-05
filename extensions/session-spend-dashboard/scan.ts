import type { Dirent, Stats } from "node:fs";
import { createReadStream } from "node:fs";
import { readdir, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createInterface } from "node:readline";

export interface UsageRecord {
	/** Stable across replayed copies of the same LLM call in forked/resumed sessions. */
	dedupeKey: string;
	timestamp: number;
	provider: string;
	model: string;
	input: number;
	output: number;
	cacheRead: number;
	cacheWrite: number;
	reasoning: number;
	totalTokens: number;
	cost: number;
	costReported: boolean;
}

export interface SessionFile {
	file: string;
	relPath: string;
	sessionId: string;
	name?: string;
	cwd: string;
	startedAt: number;
	mtimeMs: number;
	sizeBytes: number;
	/** Present when the file lives under another session's directory. */
	parentSessionId?: string;
	records: UsageRecord[];
	malformedLines: number;
	truncated: boolean;
}

export interface ScanLimits {
	maxFiles: number;
	maxBytesPerFile: number;
}

export const DEFAULT_LIMITS: ScanLimits = {
	maxFiles: 4000,
	maxBytesPerFile: 64 * 1024 * 1024,
};

export function defaultSessionsDir(): string {
	const override = process.env.PI_CODING_AGENT_SESSION_DIR;
	if (override && override.trim()) return override;
	const agentDir = process.env.PI_CODING_AGENT_DIR;
	if (agentDir && agentDir.trim()) return path.join(agentDir, "sessions");
	return path.join(os.homedir(), ".pi", "agent", "sessions");
}

function finite(value: unknown): number {
	return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function text(value: unknown): string | undefined {
	return typeof value === "string" && value.length > 0 ? value : undefined;
}

function parseTimestamp(value: unknown): number {
	if (typeof value === "number" && Number.isFinite(value)) return value;
	if (typeof value === "string") {
		const parsed = Date.parse(value);
		if (Number.isFinite(parsed)) return parsed;
	}
	return 0;
}

interface ExtractedUsage {
	usage: Record<string, unknown>;
	provider: string;
	model: string;
	timestamp: number;
}

function extractUsage(entry: Record<string, unknown>): ExtractedUsage | undefined {
	const type = entry.type;

	if (type === "message") {
		const message = entry.message;
		if (!message || typeof message !== "object") return undefined;
		const record = message as Record<string, unknown>;
		// toolResult.usage restates nested subagent work that is also persisted as its
		// own session file, so counting it here would double-count that spend.
		if (record.role !== "assistant") return undefined;
		const usage = record.usage;
		if (!usage || typeof usage !== "object") return undefined;
		return {
			usage: usage as Record<string, unknown>,
			provider: text(record.provider) ?? "unknown",
			model: text(record.model) ?? "unknown",
			timestamp: parseTimestamp(record.timestamp) || parseTimestamp(entry.timestamp),
		};
	}

	if (type === "compaction" || type === "branch_summary") {
		const usage = entry.usage;
		if (!usage || typeof usage !== "object") return undefined;
		return {
			usage: usage as Record<string, unknown>,
			provider: "unknown",
			model: text(entry.model) ?? "unknown",
			timestamp: parseTimestamp(entry.timestamp),
		};
	}

	return undefined;
}

function toRecord(entry: Record<string, unknown>, extracted: ExtractedUsage): UsageRecord {
	const { usage, provider, model, timestamp } = extracted;
	const rawCost = usage.cost;
	const costObject = rawCost && typeof rawCost === "object" ? (rawCost as Record<string, unknown>) : undefined;
	const costReported = typeof costObject?.total === "number" && Number.isFinite(costObject.total);
	const cost = costReported ? finite(costObject?.total) : 0;
	const input = finite(usage.input);
	const output = finite(usage.output);
	const cacheRead = finite(usage.cacheRead);
	const cacheWrite = finite(usage.cacheWrite);
	const totalTokens = finite(usage.totalTokens) || input + output + cacheRead + cacheWrite;
	const entryId = text(entry.id) ?? "";

	return {
		dedupeKey: `${entryId}|${timestamp}|${model}|${totalTokens}|${cost}`,
		timestamp,
		provider,
		model,
		input,
		output,
		cacheRead,
		cacheWrite,
		reasoning: finite(usage.reasoning),
		totalTokens,
		cost,
		costReported,
	};
}

export interface ParsedSession {
	sessionId: string;
	name?: string;
	cwd: string;
	startedAt: number;
	records: UsageRecord[];
	malformedLines: number;
	truncated: boolean;
}

export async function parseSessionFile(file: string, maxBytes = DEFAULT_LIMITS.maxBytesPerFile): Promise<ParsedSession> {
	const records: UsageRecord[] = [];
	let malformedLines = 0;
	let bytesRead = 0;
	let truncated = false;
	let sessionId = "";
	let name: string | undefined;
	let cwd = "";
	let startedAt = 0;

	const stream = createReadStream(file, { encoding: "utf8" });
	const lines = createInterface({ input: stream, crlfDelay: Number.POSITIVE_INFINITY });

	try {
		for await (const line of lines) {
			bytesRead += Buffer.byteLength(line, "utf8") + 1;
			if (bytesRead > maxBytes) {
				truncated = true;
				break;
			}
			const trimmed = line.trim();
			if (!trimmed) continue;

			let entry: Record<string, unknown>;
			try {
				const parsed: unknown = JSON.parse(trimmed);
				if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
					malformedLines++;
					continue;
				}
				entry = parsed as Record<string, unknown>;
			} catch {
				malformedLines++;
				continue;
			}

			if (entry.type === "session") {
				sessionId = text(entry.id) ?? sessionId;
				cwd = text(entry.cwd) ?? cwd;
				startedAt = parseTimestamp(entry.timestamp) || startedAt;
				continue;
			}

			if (entry.type === "session_info") {
				name = text(entry.name) ?? name;
				continue;
			}

			const extracted = extractUsage(entry);
			if (extracted) records.push(toRecord(entry, extracted));
		}
	} finally {
		lines.close();
		stream.destroy();
	}

	return { sessionId, name, cwd, startedAt, records, malformedLines, truncated };
}

async function collectSessionFiles(root: string, maxFiles: number): Promise<string[]> {
	const found: string[] = [];
	const queue: string[] = [root];

	while (queue.length > 0 && found.length < maxFiles) {
		const dir = queue.shift();
		if (dir === undefined) break;
		let entries: Dirent[];
		try {
			entries = await readdir(dir, { withFileTypes: true, encoding: "utf8" });
		} catch {
			continue;
		}
		for (const entry of entries) {
			const full = path.join(dir, entry.name);
			if (entry.isDirectory()) {
				queue.push(full);
			} else if (entry.isFile() && entry.name.endsWith(".jsonl")) {
				found.push(full);
				if (found.length >= maxFiles) break;
			}
		}
	}

	return found;
}

function deriveParentSessionId(root: string, file: string): string | undefined {
	const rel = path.relative(root, file);
	const segments = rel.split(path.sep);
	// Layout: <project>/<sessionStem>.jsonl for roots, and
	// <project>/<parentSessionStem>/<...>/session.jsonl for nested subagent runs.
	if (segments.length < 3) return undefined;
	const parentStem = segments[1];
	if (!parentStem) return undefined;
	const underscore = parentStem.indexOf("_");
	return underscore >= 0 ? parentStem.slice(underscore + 1) : parentStem;
}

interface CacheEntry {
	mtimeMs: number;
	sizeBytes: number;
	parsed: ParsedSession;
}

export class SessionScanner {
	private readonly cache = new Map<string, CacheEntry>();
	private readonly root: string;
	private readonly limits: ScanLimits;

	constructor(root: string, limits: ScanLimits = DEFAULT_LIMITS) {
		this.root = root;
		this.limits = limits;
	}

	async scan(): Promise<SessionFile[]> {
		const files = await collectSessionFiles(this.root, this.limits.maxFiles);
		const seen = new Set<string>();
		const results: SessionFile[] = [];

		for (const file of files) {
			seen.add(file);
			let info: Stats;
			try {
				info = await stat(file);
			} catch {
				continue;
			}

			const cached = this.cache.get(file);
			let parsed: ParsedSession;
			if (cached && cached.mtimeMs === info.mtimeMs && cached.sizeBytes === info.size) {
				parsed = cached.parsed;
			} else {
				try {
					parsed = await parseSessionFile(file, this.limits.maxBytesPerFile);
				} catch {
					continue;
				}
				this.cache.set(file, { mtimeMs: info.mtimeMs, sizeBytes: info.size, parsed });
			}

			const relPath = path.relative(this.root, file);
			results.push({
				file,
				relPath,
				sessionId: parsed.sessionId || relPath,
				name: parsed.name,
				cwd: parsed.cwd || "unknown",
				startedAt: parsed.startedAt || info.mtimeMs,
				mtimeMs: info.mtimeMs,
				sizeBytes: info.size,
				parentSessionId: deriveParentSessionId(this.root, file),
				records: parsed.records,
				malformedLines: parsed.malformedLines,
				truncated: parsed.truncated,
			});
		}

		for (const key of this.cache.keys()) {
			if (!seen.has(key)) this.cache.delete(key);
		}

		return results;
	}

	get cachedFileCount(): number {
		return this.cache.size;
	}
}
