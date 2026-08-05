import { mkdir, readFile, readdir, rename, stat, unlink, writeFile } from "node:fs/promises";
import path from "node:path";

import { maintenanceLockPath } from "./retention.ts";

interface ActiveSessionMarker {
	pid: number;
	sessionFile: string;
}

function markerDirectory(agentDir: string): string {
	return path.join(agentDir, "session-metrics", "active");
}

function markerPath(agentDir: string, pid = process.pid): string {
	return path.join(markerDirectory(agentDir), `${pid}.json`);
}

export class MaintenanceInProgressError extends Error {
	constructor() {
		super("Session maintenance is in progress; Pi startup is blocked until it finishes");
		this.name = "MaintenanceInProgressError";
	}
}

async function maintenanceRunning(agentDir: string): Promise<boolean> {
	try {
		await stat(maintenanceLockPath(agentDir));
		return true;
	} catch (error) {
		const code = (error as NodeJS.ErrnoException).code;
		if (code === "ENOENT") return false;
		throw error;
	}
}

export async function registerActiveSession(agentDir: string, sessionFile: string | undefined): Promise<void> {
	const protectedSession = sessionFile || `<in-memory:${process.pid}>`;
	await mkdir(markerDirectory(agentDir), { recursive: true, mode: 0o700 });
	const target = markerPath(agentDir);
	const temporary = `${target}.tmp-${process.pid}-${Math.random().toString(36).slice(2)}`;
	await writeFile(temporary, JSON.stringify({ pid: process.pid, sessionFile: protectedSession } satisfies ActiveSessionMarker), {
		encoding: "utf8",
		mode: 0o600,
	});
	await rename(temporary, target);
	if (await maintenanceRunning(agentDir)) throw new MaintenanceInProgressError();
}

export async function unregisterActiveSession(agentDir: string): Promise<void> {
	await unlink(markerPath(agentDir)).catch(() => undefined);
}

export async function listActiveSessionFiles(agentDir: string): Promise<Set<string>> {
	const active = new Set<string>();
	let names: string[];
	try {
		names = await readdir(markerDirectory(agentDir));
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return active;
		throw new Error(`Cannot read active-session markers: ${markerDirectory(agentDir)}`, { cause: error });
	}
	for (const name of names) {
		if (!name.endsWith(".json")) continue;
		const file = path.join(markerDirectory(agentDir), name);
		let marker: Partial<ActiveSessionMarker>;
		try {
			marker = JSON.parse(await readFile(file, "utf8")) as Partial<ActiveSessionMarker>;
		} catch {
			throw new Error(`Unreadable active-session marker: ${file}`);
		}
		if (
			typeof marker.pid !== "number" ||
			!Number.isInteger(marker.pid) ||
			marker.pid <= 0 ||
			typeof marker.sessionFile !== "string" ||
			marker.sessionFile.length === 0
		) {
			throw new Error(`Invalid active-session marker: ${file}`);
		}
		active.add(marker.sessionFile);
	}
	return active;
}
