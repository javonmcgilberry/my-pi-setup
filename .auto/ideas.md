# Deferred ideas

- Measure whether batching per-file Git metadata is safe after the frozen scale
  oracle exposes the exact rename and provenance requirements.
- Compare a per-repository discovery cache against a fresh-call contract; keep
  only if cache invalidation is explicit and canonical output remains unchanged.
