import { randomUUID } from "node:crypto";
import { lstat, mkdir, open, readdir, rename, rm, stat, unlink, writeFile } from "node:fs/promises";
import path from "node:path";

export interface SessionTreeCandidate {
	rootFile: string;
	companionDirectory?: string;
	latestMtimeMs: number;
	files: number;
	bytes: number;
}

export interface PrunePlan {
	cutoffMs: number;
	eligible: SessionTreeCandidate[];
	protected: SessionTreeCandidate[];
}

async function inspectTree(rootFile: string, companionDirectory: string): Promise<SessionTreeCandidate | undefined> {
	let rootInfo;
	try {
		rootInfo = await lstat(rootFile);
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
		throw error;
	}
	if (!rootInfo.isFile() || rootInfo.isSymbolicLink()) return undefined;

	let latestMtimeMs = rootInfo.mtimeMs;
	let files = 1;
	let bytes = rootInfo.size;
	let companion: string | undefined;
	const queue: string[] = [];
	try {
		const info = await lstat(companionDirectory);
		if (info.isDirectory() && !info.isSymbolicLink()) {
			companion = companionDirectory;
			queue.push(companionDirectory);
		}
	} catch (error) {
		// A root session does not need to have nested child runs.
		if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
	}

	while (queue.length > 0) {
		const directory = queue.shift();
		if (!directory) break;
		for (const entry of await readdir(directory, { withFileTypes: true })) {
			const full = path.join(directory, entry.name);
			if (entry.isSymbolicLink()) return undefined;
			if (entry.isDirectory()) {
				queue.push(full);
				continue;
			}
			if (!entry.isFile()) continue;
			const info = await stat(full);
			latestMtimeMs = Math.max(latestMtimeMs, info.mtimeMs);
			files++;
			bytes += info.size;
		}
	}
	return { rootFile, companionDirectory: companion, latestMtimeMs, files, bytes };
}

export async function collectSessionTrees(sessionsRoot: string): Promise<SessionTreeCandidate[]> {
	const trees: SessionTreeCandidate[] = [];
	let projects;
	try {
		projects = await readdir(sessionsRoot, { withFileTypes: true });
	} catch {
		return trees;
	}
	for (const project of projects) {
		if (!project.isDirectory() || project.isSymbolicLink()) continue;
		const projectDirectory = path.join(sessionsRoot, project.name);
		for (const entry of await readdir(projectDirectory, { withFileTypes: true })) {
			if (!entry.isFile() || entry.isSymbolicLink() || !entry.name.endsWith(".jsonl")) continue;
			const rootFile = path.join(projectDirectory, entry.name);
			const companionDirectory = path.join(projectDirectory, entry.name.slice(0, -".jsonl".length));
			const tree = await inspectTree(rootFile, companionDirectory);
			if (tree) trees.push(tree);
		}
	}
	return trees.sort((a, b) => a.latestMtimeMs - b.latestMtimeMs || a.rootFile.localeCompare(b.rootFile));
}

function treeContainsActiveFile(tree: SessionTreeCandidate, activeFiles: ReadonlySet<string>): boolean {
	const root = path.resolve(tree.rootFile);
	const companion = tree.companionDirectory ? `${path.resolve(tree.companionDirectory)}${path.sep}` : undefined;
	for (const active of activeFiles) {
		const resolved = path.resolve(active);
		if (resolved === root || (companion !== undefined && resolved.startsWith(companion))) return true;
	}
	return false;
}

export async function planSessionPrune(
	sessionsRoot: string,
	cutoffMs: number,
	activeFiles: ReadonlySet<string> = new Set(),
): Promise<PrunePlan> {
	const eligible: SessionTreeCandidate[] = [];
	const protectedTrees: SessionTreeCandidate[] = [];
	for (const tree of await collectSessionTrees(sessionsRoot)) {
		if (tree.latestMtimeMs >= cutoffMs) continue;
		if (treeContainsActiveFile(tree, activeFiles)) protectedTrees.push(tree);
		else eligible.push(tree);
	}
	return { cutoffMs, eligible, protected: protectedTrees };
}

function assertInsideSessionsRoot(sessionsRoot: string, target: string): void {
	const root = `${path.resolve(sessionsRoot)}${path.sep}`;
	if (!path.resolve(target).startsWith(root)) throw new Error(`Refusing to remove path outside sessions root: ${target}`);
}

export async function pruneSessionTrees(
	sessionsRoot: string,
	cutoffMs: number,
	activeFiles: ReadonlySet<string> = new Set(),
	refreshActiveFiles?: () => Promise<ReadonlySet<string>>,
): Promise<SessionTreeCandidate[]> {
	const plan = await planSessionPrune(sessionsRoot, cutoffMs, activeFiles);
	const removed: SessionTreeCandidate[] = [];
	for (const tree of plan.eligible) {
		const companion = path.join(path.dirname(tree.rootFile), path.basename(tree.rootFile, ".jsonl"));
		const current = await inspectTree(tree.rootFile, companion);
		const currentActive = refreshActiveFiles ? await refreshActiveFiles() : activeFiles;
		if (!current || current.latestMtimeMs >= cutoffMs || treeContainsActiveFile(current, currentActive)) continue;
		assertInsideSessionsRoot(sessionsRoot, current.rootFile);
		const quarantine = path.join(path.dirname(current.rootFile), `.session-retention-quarantine-${randomUUID()}`);
		const stagedRoot = path.join(quarantine, path.basename(current.rootFile));
		const stagedCompanion = current.companionDirectory
			? path.join(quarantine, path.basename(current.companionDirectory))
			: undefined;
		assertInsideSessionsRoot(sessionsRoot, quarantine);
		await mkdir(quarantine, { mode: 0o700 });
		let rootStaged = false;
		let companionStaged = false;
		let deletionStarted = false;
		try {
			await rename(current.rootFile, stagedRoot);
			rootStaged = true;
			if (current.companionDirectory && stagedCompanion) {
				assertInsideSessionsRoot(sessionsRoot, current.companionDirectory);
				await rename(current.companionDirectory, stagedCompanion);
				companionStaged = true;
			}
			const afterStaging = refreshActiveFiles ? await refreshActiveFiles() : currentActive;
			if (treeContainsActiveFile(current, afterStaging)) {
				if (companionStaged && current.companionDirectory && stagedCompanion) {
					await rename(stagedCompanion, current.companionDirectory);
					companionStaged = false;
				}
				await rename(stagedRoot, current.rootFile);
				rootStaged = false;
				await rm(quarantine, { recursive: true, force: true });
				continue;
			}
			deletionStarted = true;
			await rm(quarantine, { recursive: true, force: false });
			removed.push(current);
		} catch (error) {
			if (!deletionStarted) {
				let rollbackError: unknown;
				if (companionStaged && current.companionDirectory && stagedCompanion) {
					try {
						await rename(stagedCompanion, current.companionDirectory);
					} catch (restoreError) {
						rollbackError = restoreError;
					}
				}
				if (rootStaged) {
					try {
						await rename(stagedRoot, current.rootFile);
					} catch (restoreError) {
						rollbackError ??= restoreError;
					}
				}
				if (rollbackError) {
					throw new AggregateError([error, rollbackError], `Cleanup rollback failed; preserved quarantine at ${quarantine}`);
				}
				await rm(quarantine, { recursive: true, force: true });
			}
			throw error;
		}
	}
	return removed;
}

interface LockRecord {
	pid: number;
	createdAt: number;
}

export function maintenanceLockPath(agentDir: string): string {
	return path.join(agentDir, "session-metrics", "maintenance.lock");
}

export async function withMaintenanceLock<T>(agentDir: string, action: () => Promise<T>): Promise<T> {
	const metricsDirectory = path.join(agentDir, "session-metrics");
	const lockPath = maintenanceLockPath(agentDir);
	await mkdir(metricsDirectory, { recursive: true, mode: 0o700 });
	let handle;
	try {
		handle = await open(lockPath, "wx", 0o600);
	} catch (error) {
		if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
		throw new Error("Session metrics maintenance lock already exists; remove it manually only after confirming no maintenance process is running");
	}
	try {
		await writeFile(handle, JSON.stringify({ pid: process.pid, createdAt: Date.now() } satisfies LockRecord), "utf8");
		return await action();
	} finally {
		await handle.close();
		await unlink(lockPath).catch(() => undefined);
	}
}
