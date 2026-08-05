#!/usr/bin/env node

import os from "node:os";
import path from "node:path";

import { runMaintenance } from "../extensions/session-spend-dashboard/maintenance.ts";

const args = new Set(process.argv.slice(2));
const known = new Set(["--apply", "--help", "-h"]);
for (const arg of args) {
	if (!known.has(arg)) {
		console.error(`Unknown option: ${arg}`);
		process.exit(2);
	}
}

if (args.has("--help") || args.has("-h")) {
	console.log(`Usage: node scripts/session-maintenance.mjs [--apply]

Without --apply, imports metrics and previews eligible chat trees.
With --apply, refuses to run while any Pi session is active, then imports metrics
and removes whole session trees older than the configured chat retention window.`);
	process.exit(0);
}

const agentDir =
	process.env.PI_AGENT_DIR ||
	process.env.PI_CODING_AGENT_DIR ||
	path.join(process.env.HOME || os.homedir(), ".pi", "agent");
const sessionsRoot = process.env.PI_CODING_AGENT_SESSION_DIR || path.join(agentDir, "sessions");
const report = await runMaintenance({
	sessionsRoot,
	agentDir,
	dryRun: !args.has("--apply"),
});

console.log(JSON.stringify(report, null, 2));
