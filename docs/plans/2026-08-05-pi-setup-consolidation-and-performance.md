# Pi setup consolidation and performance completion

> Superseded on 2026-08-06 by
> [`2026-08-06-002-package-first-pi-setup-migration-brief.md`](2026-08-06-002-package-first-pi-setup-migration-brief.md).
> The unchecked `./sync` and Prewalk-submodule steps below are historical and
> must not be executed.

Status: Local consolidation complete; publication and measurement pending

## Goal

Make `~/Developer/my-pi-setup` the sole source of truth for personal Pi setup
development, preserve every completed workstream, remove temporary branches and
worktrees only after integration, publish safely, and finish the deferred
startup performance comparison without contaminating its measurements.

## Completed

- [x] Collected context from the live `.pi`, `my-pi-setup`, dashboard, Prewalk,
      performance-audit, and Webflow workstreams.
- [x] Preserved dashboard commit `70945d5` and its 41-test baseline.
- [x] Committed setup pruning and duplicate-install removal as `35e0561`.
- [x] Committed Prewalk comparison and async child-spend work as `6407791` and
      `c5db8a6`; full Prewalk verification passed (312 tests, 1 skipped).
- [x] Integrated footer child-spend support as `ec149b5`.
- [x] Integrated Webflow Chrome-for-Testing automation as `7540bb5`.
- [x] Migrated root product authority and completed dashboard/tool-output
      research into the canonical repository.
- [x] Ran two-axis review and added regression coverage for browser-profile
      boundaries, credential exclusion, and child-spend deduplication.

## Remaining local consolidation

- [x] Run the complete combined checks (61 Webflow tests and 42 dashboard
      tests), full Prewalk suite (312 passed, 1 skipped), Prewalk typecheck/lint,
      Python diagnostics, temporary installer/drift checks, and targeted
      custom-agent sync-guard test.
- [x] Re-review the final diff against `origin/main` and resolve browser
      traversal, credential-sidecar, sync-safety, footer-polling, and spend
      deduplication findings.
- [x] Commit review fixes plus migrated product/research artifacts.
- [x] Fast-forward local `main`, remove the merged Webflow worktree, delete only
      merged temporary branches, and verify one clean worktree remains.

## Publication and live migration

These steps require every Pi session to be closed.

- [ ] Record ten provider-free launches against the current live setup for the
      deferred baseline; capture startup time, RSS, and orphan-process state.
- [ ] Push Prewalk `main` first so the parent submodule pin is fetchable.
- [ ] From clean `~/Developer/my-pi-setup/main`, run `./sync` to pull/rebase,
      validate, commit if needed, push, apply, and verify zero managed drift.
- [ ] Remove retired managed npm packages
      `@howaboua/pi-cache-hit-predictor` and
      `@petechu/pi-extension-toggle`, then remove the obsolete duplicate
      `~/.pi/agent/node_modules` tree after verifying no process uses it.
- [ ] Record ten equivalent launches against the final setup and compare median,
      tail latency, RSS, and orphan-process results with the baseline.
- [ ] Remove the now-canonical duplicate `~/.pi/PRODUCT.md` and
      `~/.pi/research/` sources; retain runtime data, sessions, credentials, and
      backups.

## Development rule after completion

- Personal setup, skills, extensions, and configuration:
  `~/Developer/my-pi-setup`
- Pi core: `~/Developer/pi`
- Prewalk: the `prewalk` submodule, committed there before advancing the parent
  pin
- Never develop under `~/.pi/agent`, `~/.pi/agent/npm`, or `~/.pi/agent/git`.
