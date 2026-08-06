#!/usr/bin/env node

import { runMaintenance } from "../extensions/session-spend-dashboard/maintenance.ts";
import { defaultAgentDir, defaultSessionsDir } from "../extensions/session-spend-dashboard/scan.ts";

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

const agentDir = defaultAgentDir();
const sessionsRoot = defaultSessionsDir();
const report = await runMaintenance({
	sessionsRoot,
	agentDir,
	dryRun: !args.has("--apply"),
});

console.log(JSON.stringify(report, null, 2));
