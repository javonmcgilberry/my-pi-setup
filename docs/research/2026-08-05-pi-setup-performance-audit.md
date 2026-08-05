# Pi setup performance audit

## Findings

- Pi retains session JSONL history; compaction reduces model context but does
  not archive or delete the original files.
- The old setup maintained both an approximately 943 MB root dependency tree and
  Pi's approximately 687 MB managed package tree. Runtime extensions resolve Pi
  APIs through the host loader, so the duplicate root install was unnecessary.
- The previous footer-only session scan measured roughly 0.04 ms on the active
  session and 0.16 ms on the largest inspected session. The later child-spend
  integration introduced a two-second artifact polling loop; final review
  replaced it with initial and invalidation-driven refreshes.
- Repeated startup timing under concurrent Webflow E2E load varied from roughly
  3–10 seconds and was rejected as contaminated evidence.

## Implemented changes

- Reduced `compaction.reserveTokens` from 65,536 to 32,768.
- Removed the disabled Explore Subagents package, cache-hit predictor, and
  duplicate extension toggler from canonical settings and dependency metadata.
- Retired `pi-explore-subagents.json` through backup-first setup migration.
- Removed root `npm ci` from normal setup/sync; Pi remains responsible for its
  managed npm and Git package directories.
- Removed periodic footer artifact polling while preserving initial and
  invalidation-driven child-spend refreshes.

## Deferred measurement

After every Pi session closes, measure ten provider-free launches before live
sync and ten equivalent launches afterward. Compare medians and tails rather
than individual samples, record RSS, and verify each launch leaves no orphaned
process. Do not claim a startup improvement until this uncontaminated comparison
is complete.
