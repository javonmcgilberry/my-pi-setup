# Session performance and retention

Status: Approved on 2026-08-05

## Outcome

Reduce long-session rendering overhead with `pi-render-cache`, keep full Pi chat trees for
seven days by default, and retain content-free usage and session metrics for one year so
historical spend remains available after chat deletion.

## Current behavior

- Pi session JSONL files are append-only and compaction does not remove their history.
- The spend dashboard previously rebuilt all history directly from those files, so
  deleting a chat also deleted its historical dashboard metrics.
- Prewalk stores workflow-specific receipts separately. Those receipts do not cover all
  Pi usage and should not become the general usage ledger.
- `pi-render-cache` 1.1.0 directly caches streaming Markdown prefixes and repeated text
  segmentation. Its documented compatibility matrix stops at Pi 0.82.1, so Pi 0.83.0
  activation must be reported from an isolated runtime check rather than assumed.

## Decisions

- Install `pi-render-cache` 1.1.0 through canonical package metadata.
- Use one global SQLite ledger owned by Session Spend Dashboard.
- Store timestamps, project/session linkage, provider/model, usage category, token
  categories, reported cost, and deduplicated tool-call counts.
- Never store message content, raw JSON, tool names, arguments, or results.
- Keep chats for 7 days and metrics for 365 days by default; expose bounded tracked
  configuration.
- Treat a root session plus nested child runs as one deletion unit.
- Make transcript cleanup an explicit standalone `--apply` operation that refuses to run
  while Pi sessions are active. Dashboard refreshes may ingest metrics but never delete
  chat content.
- Keep Prewalk analytics independent; the general ledger does not infer planner/executor
  roles or savings.
- Do not compose third-party cleanup and telemetry extensions: available cleanup packages
  can delete before ingestion, `pi-archive` retains full content, `pi-usage` requires the
  source logs, and `pi-telemetry` is forward-only and noncanonical for Pi totals.

## Scope

- `settings.json`, `package.json`, and `package-lock.json`
- `session-spend-dashboard.json` and `config/manifest.json`
- `extensions/session-spend-dashboard/`
- setup validation and product documentation

Prewalk implementation and Pi core are out of scope.

## Acceptance criteria

- The tracked setup installs `pi-render-cache` without touching the live agent directory.
- Replayed usage and tool calls are counted once across forks and resumes.
- Dashboard totals remain available after source JSONL deletion.
- The SQLite file contains no prompt, response, tool name, tool payload, or raw JSON.
- Cleanup imports and verifies metrics before deleting anything.
- A tree with an active file or a child newer than the cutoff is not deleted.
- Defaults are seven days for chats and 365 days for metrics.
- Focused tests and `./scripts/check.sh` pass.
- The final diff receives independent standards and specification review.

## Implementation units

1. Add usage categories and content-free tool-call IDs at the session scanner seam.
2. Add the schema-versioned SQLite ledger and ledger-backed dashboard aggregation.
3. Add bounded retention configuration, whole-tree planning, locking, and confirmed
   maintenance commands.
4. Add `pi-render-cache` and isolated setup/runtime compatibility checks.
5. Update product documentation, run full verification, review, and commit.

## Execution

- [x] Extend scanner and aggregation records.
- [x] Add ledger storage and privacy/regression tests.
- [x] Add retention planning and maintenance tests.
- [x] Add package and tracked configuration.
- [x] Run isolated installation and compatibility checks. On Pi 0.83.0, `/rcstats`
  reported `seg active` and conservatively reported `md unsupported` for the unknown
  `Markdown.render` implementation.
- [x] Run full verification and independent Standards/Spec review.
- [x] Commit the approved implementation.

## Verification

- `node --test extensions/session-spend-dashboard/test/*.test.ts`
- `./scripts/check.sh`
- Temporary installation with `PI_AGENT_DIR` and `AGENTS_SKILLS_DIR` under one temporary
  root
- Provider-free Pi 0.83.0 extension load and `/rcstats` inspection
- Post-implementation Standards and Spec review against this file

## Open blockers

- Live publication and the first destructive cleanup require every Pi session to be
  closed. They are deliberately excluded from this implementation run.

## Approval

Approved by the user on 2026-08-05 through the explicit implementation request.
