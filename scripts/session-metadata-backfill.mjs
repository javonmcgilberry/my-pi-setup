#!/usr/bin/env node

import { createHash, randomBytes } from "node:crypto";
import {
	chmod,
	mkdir,
	mkdtemp,
	open,
	readdir,
	readFile,
	rename,
	rm,
	stat,
	writeFile,
} from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const DEFAULT_MAX_CHARS = 18_000;
const TITLE_MAX = 80;
const SUMMARY_MAX = 800;

const SENSITIVE_PATTERNS = [
	[/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, "[REDACTED_PRIVATE_KEY]"],
	[/\bAKIA[0-9A-Z]{16}\b/g, "[REDACTED_AWS_KEY]"],
	[/\bsk-[A-Za-z0-9_-]{20,}\b/g, "[REDACTED_API_KEY]"],
	[/\b(Bearer\s+)[A-Za-z0-9._~+/=-]{20,}/gi, "$1[REDACTED]"],
	[/\b([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD))\s*=\s*["']?[^"'\s]+/g, "$1=[REDACTED]"],
	[/\b(api[_-]?key|token|secret|password)\b\s*[:=]\s*["']?[^"'\s,;]+/gi, "$1=[REDACTED]"],
];

function agentDir() {
	return process.env.PI_AGENT_DIR || path.join(homedir(), ".pi", "agent");
}

function sessionsRoot() {
	return process.env.PI_CODING_AGENT_SESSION_DIR || path.join(agentDir(), "sessions");
}

function redact(text) {
	let output = text;
	for (const [pattern, replacement] of SENSITIVE_PATTERNS) output = output.replace(pattern, replacement);
	return output;
}

function contentText(content) {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content
		.filter((block) => block && typeof block === "object" && block.type === "text" && typeof block.text === "string")
		.map((block) => block.text)
		.join("\n");
}

function parseSession(raw) {
	let header;
	let name;
	let lastId = null;
	const dialogue = [];
	let userMessages = 0;
	for (const line of raw.split("\n")) {
		if (!line) continue;
		let entry;
		try {
			entry = JSON.parse(line);
		} catch {
			continue;
		}
		if (typeof entry.id === "string") lastId = entry.id;
		if (entry.type === "session" && !header) header = entry;
		if (entry.type === "session_info") name = typeof entry.name === "string" ? entry.name.trim() || undefined : undefined;
		if (entry.type === "message" && (entry.message?.role === "user" || entry.message?.role === "assistant")) {
			const text = contentText(entry.message.content).trim();
			if (!text) continue;
			if (entry.message.role === "user") userMessages++;
			dialogue.push(`${entry.message.role.toUpperCase()}:\n${text}`);
		}
		if ((entry.type === "compaction" || entry.type === "branch_summary") && typeof entry.summary === "string") {
			dialogue.push(`${entry.type.toUpperCase()}:\n${entry.summary}`);
		}
	}
	return { header, name, lastId, dialogue, userMessages };
}

function boundedTranscript(parts, maxChars) {
	const text = redact(parts.join("\n\n")).trim();
	if (text.length <= maxChars) return text;
	const head = Math.min(6_000, Math.floor(maxChars / 3));
	return `${text.slice(0, head)}\n\n[... middle omitted for bounded backfill context ...]\n\n${text.slice(-(maxChars - head))}`;
}

function temporaryCwd(cwd) {
	if (typeof cwd !== "string") return true;
	const resolved = path.resolve(cwd);
	return resolved.startsWith(path.resolve(tmpdir()) + path.sep) || resolved.startsWith("/private/tmp/") || resolved.startsWith("/tmp/");
}

async function activeSessionFiles(baseAgentDir) {
	const directory = path.join(baseAgentDir, "session-metrics", "active");
	const active = new Set();
	let names;
	try {
		names = await readdir(directory);
	} catch (error) {
		if (error.code === "ENOENT") return active;
		throw error;
	}
	for (const name of names) {
		if (!name.endsWith(".json")) continue;
		const marker = JSON.parse(await readFile(path.join(directory, name), "utf8"));
		if (typeof marker.sessionFile !== "string" || !marker.sessionFile) {
			throw new Error(`Malformed active-session marker: ${path.join(directory, name)}`);
		}
		active.add(path.resolve(marker.sessionFile));
	}
	return active;
}

export async function prepareBackfill(options = {}) {
	const baseAgentDir = options.agentDir || agentDir();
	const root = options.sessionsRoot || sessionsRoot();
	const output = options.output || await mkdtemp(path.join(tmpdir(), "pi-session-backfill-"));
	const maxChars = options.maxChars || DEFAULT_MAX_CHARS;
	await mkdir(output, { recursive: true, mode: 0o700 });
	const transcriptsDirectory = path.join(output, "transcripts");
	await mkdir(transcriptsDirectory, { recursive: true, mode: 0o700 });
	const active = await activeSessionFiles(baseAgentDir);
	const items = [];

	for (const projectName of (await readdir(root)).sort()) {
		const projectDirectory = path.join(root, projectName);
		let names;
		try {
			names = await readdir(projectDirectory, { withFileTypes: true });
		} catch {
			continue;
		}
		for (const entry of names) {
			if (!entry.isFile() || !entry.name.endsWith(".jsonl")) continue;
			const sessionFile = path.join(projectDirectory, entry.name);
			if (active.has(path.resolve(sessionFile))) continue;
			const raw = await readFile(sessionFile, "utf8");
			const parsed = parseSession(raw);
			if (!parsed.header || parsed.name || parsed.userMessages === 0 || temporaryCwd(parsed.header.cwd)) continue;
			const sessionId = typeof parsed.header.id === "string" ? parsed.header.id : entry.name.replace(/\.jsonl$/, "");
			const info = await stat(sessionFile);
			const transcriptFile = path.join(transcriptsDirectory, metadataFilename(sessionId, ".txt"));
			const prompt = [
				`Session ID: ${sessionId}`,
				`Project: ${parsed.header.cwd || "unknown"}`,
				`Started: ${parsed.header.timestamp || "unknown"}`,
				"",
				boundedTranscript(parsed.dialogue, maxChars),
			].join("\n");
			await writeFile(transcriptFile, prompt, { encoding: "utf8", mode: 0o600 });
			items.push({
				sessionId,
				sessionFile,
				relPath: path.relative(root, sessionFile),
				transcriptFile,
				expectedSize: info.size,
				expectedMtimeMs: info.mtimeMs,
				lastId: parsed.lastId,
			});
		}
	}

	const manifest = {
		schemaVersion: 1,
		generatedAt: new Date().toISOString(),
		sessionsRoot: root,
		metadataRoot: path.join(baseAgentDir, "session-metadata", "summaries"),
		items,
	};
	const manifestFile = path.join(output, "manifest.json");
	await writeFile(manifestFile, `${JSON.stringify(manifest, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
	return { manifestFile, manifest };
}

function cleanTitle(value) {
	if (typeof value !== "string") return undefined;
	const title = value.replace(/[\u0000-\u001f\u007f-\u009f]+/g, " ").replace(/\s+/g, " ").trim();
	return title.length >= 3 && title.length <= TITLE_MAX ? title : undefined;
}

function cleanSummary(value) {
	if (typeof value !== "string") return undefined;
	const summary = value.replace(/[\u0000-\u001f\u007f-\u009f]+/g, " ").replace(/\s+/g, " ").trim();
	return summary.length >= 10 && summary.length <= SUMMARY_MAX ? summary : undefined;
}

function entryId(existing) {
	let id;
	do id = randomBytes(4).toString("hex"); while (existing.has(id));
	existing.add(id);
	return id;
}

function metadataFilename(sessionId, extension = ".json") {
	const stem = /^[A-Za-z0-9._-]+$/.test(sessionId)
		? sessionId
		: createHash("sha256").update(sessionId).digest("hex");
	return `${stem}${extension}`;
}

async function atomicJson(target, value) {
	await mkdir(path.dirname(target), { recursive: true, mode: 0o700 });
	const temporary = `${target}.${process.pid}.tmp`;
	await writeFile(temporary, `${JSON.stringify(value)}\n`, { encoding: "utf8", mode: 0o600 });
	await rename(temporary, target);
	await chmod(target, 0o600);
}

export async function applyBackfill({ manifestFile, resultsFile, model = "openai-codex/gpt-5.6-luna" }) {
	const manifest = JSON.parse(await readFile(manifestFile, "utf8"));
	const parsedResults = JSON.parse(await readFile(resultsFile, "utf8"));
	const results = Array.isArray(parsedResults) ? parsedResults : parsedResults.sessions;
	if (!Array.isArray(results)) throw new Error("Results must be an array or an object with a sessions array");
	const byId = new Map(manifest.items.map((item) => [item.sessionId, item]));
	const active = await activeSessionFiles(path.dirname(path.dirname(manifest.metadataRoot)));
	const applied = [];
	const skipped = [];

	for (const result of results) {
		const item = byId.get(result?.sessionId);
		const title = cleanTitle(result?.title);
		const summary = cleanSummary(result?.summary);
		if (!item || !title || !summary) {
			skipped.push({ sessionId: result?.sessionId, reason: "invalid-result" });
			continue;
		}
		if (active.has(path.resolve(item.sessionFile))) {
			skipped.push({ sessionId: item.sessionId, reason: "active" });
			continue;
		}
		const handle = await open(item.sessionFile, "r+");
		try {
			const info = await handle.stat();
			if (info.size !== item.expectedSize || info.mtimeMs !== item.expectedMtimeMs) {
				skipped.push({ sessionId: item.sessionId, reason: "changed" });
				continue;
			}
			const raw = await readFile(item.sessionFile, "utf8");
			const parsed = parseSession(raw);
			if (parsed.name) {
				skipped.push({ sessionId: item.sessionId, reason: "already-named" });
				continue;
			}
			const ids = new Set(raw.split("\n").flatMap((line) => {
				try { const value = JSON.parse(line); return typeof value.id === "string" ? [value.id] : []; } catch { return []; }
			}));
			const timestamp = new Date().toISOString();
			const sessionInfoId = entryId(ids);
			const markerId = entryId(ids);
			const parentId = parsed.lastId;
			const entries = [
				{ type: "session_info", id: sessionInfoId, parentId, timestamp, name: title },
				{
					type: "custom",
					customType: "pi-autoname-state",
					data: { event: "user_rename", name: title, timestamp: Date.parse(timestamp) },
					id: markerId,
					parentId: sessionInfoId,
					timestamp,
				},
			];
			const sidecar = {
				schemaVersion: 1,
				sessionId: item.sessionId,
				sourceRelPath: item.relPath,
				title,
				summary,
				generatedAt: timestamp,
				model,
			};
			const metadataFile = path.join(manifest.metadataRoot, metadataFilename(item.sessionId));
			await atomicJson(metadataFile, sidecar);
			try {
				const prefix = raw.endsWith("\n") ? "" : "\n";
				const payload = Buffer.from(`${prefix}${entries.map((entry) => JSON.stringify(entry)).join("\n")}\n`);
				let written = 0;
				while (written < payload.length) {
					const result = await handle.write(payload, written, payload.length - written, item.expectedSize + written);
					if (result.bytesWritten === 0) throw new Error(`Could not append session metadata to ${item.sessionFile}`);
					written += result.bytesWritten;
				}
			} catch (error) {
				await rm(metadataFile, { force: true });
				throw error;
			}
			applied.push(item.sessionId);
		} finally {
			await handle.close();
		}
	}
	return { applied, skipped };
}

function option(args, name) {
	const index = args.indexOf(name);
	return index === -1 ? undefined : args[index + 1];
}

async function main(args) {
	const [command] = args;
	if (command === "prepare") {
		const output = option(args, "--output");
		if (!output) throw new Error("prepare requires --output <private-directory>");
		const result = await prepareBackfill({ output, maxChars: Number(option(args, "--max-chars")) || DEFAULT_MAX_CHARS });
		console.log(JSON.stringify({ manifestFile: result.manifestFile, sessions: result.manifest.items.length }, null, 2));
		return;
	}
	if (command === "apply") {
		const manifestFile = option(args, "--manifest");
		const resultsFile = option(args, "--results");
		if (!manifestFile || !resultsFile) throw new Error("apply requires --manifest <file> --results <file>");
		console.log(JSON.stringify(await applyBackfill({ manifestFile, resultsFile }), null, 2));
		return;
	}
	throw new Error("Usage: session-metadata-backfill.mjs prepare --output <dir> | apply --manifest <file> --results <file>");
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) {
	main(process.argv.slice(2)).catch((error) => {
		console.error(error instanceof Error ? error.message : String(error));
		process.exitCode = 1;
	});
}
