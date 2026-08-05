import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { DEFAULT_RETENTION_CONFIG, loadRetentionConfig, retentionConfigPath } from "../config.ts";

test("uses seven-day chats and one-year metrics by default", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "spend-config-default-"));
	assert.deepEqual(await loadRetentionConfig(root), DEFAULT_RETENTION_CONFIG);
	await rm(root, { recursive: true, force: true });
});

test("loads configurable retention and rejects unsafe values", async () => {
	const root = await mkdtemp(path.join(os.tmpdir(), "spend-config-custom-"));
	await writeFile(retentionConfigPath(root), JSON.stringify({ chatRetentionDays: 14, metricsRetentionDays: 730 }));
	assert.deepEqual(await loadRetentionConfig(root), { chatRetentionDays: 14, metricsRetentionDays: 730 });

	await writeFile(retentionConfigPath(root), JSON.stringify({ chatRetentionDays: 0, metricsRetentionDays: 9000 }));
	assert.deepEqual(await loadRetentionConfig(root), DEFAULT_RETENTION_CONFIG);

	await writeFile(retentionConfigPath(root), JSON.stringify({ chatRetentionDays: 30, metricsRetentionDays: 7 }));
	assert.deepEqual(await loadRetentionConfig(root), { chatRetentionDays: 30, metricsRetentionDays: 30 });
	await rm(root, { recursive: true, force: true });
});
