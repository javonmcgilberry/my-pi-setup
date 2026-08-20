# Autoresearch: Webflow corpus compiler wave two

## Objective

Use the native Pi autoresearch loop to improve the general-purpose offline Webflow
evidence compiler without changing its safety contract. The frozen scale workload
executes the compiler's index, discovery, validation, and operation-evidence paths
over synthetic 100-, 1,000-, and 10,000-file repositories. Optimize deterministic
compiler work, not a fixture-specific shortcut.

## Metrics

- **Primary**: `work_units` (unitless, lower is better). This is a deterministic
  count of Git calls, fixture reads, structural scans, metadata lookups,
  operation-evidence records, and bounded file work across all scale sizes.
- **Secondary**: `scale_*_work_units`, Git calls, file reads, bytes hashed,
  `canonical_mismatches`, `private_value_leaks`, `deterministic_runs`, and the
  complete hardening safety metrics emitted by the check workload.

## How to Run

`./.auto/measure.sh` emits structured `METRIC name=value` lines. The native
autoresearch extension owns timing, checks, keep/discard decisions, commits, and
reverts. Do not replace it with a custom experiment loop.

## Files in Scope

- `skills/webflow-designer-agent-browser/scripts/test-corpus-index.py` — the only
  mutable production candidate during this wave; compiler discovery, metadata,
  evidence, and index construction.
- `.auto/**` — session prompt, benchmark wrapper, checks, hooks, and log.

The scale benchmark and its test are frozen after the baseline harness is landed;
they define the workload and are not candidate files.

## Off Limits

Do not modify benchmark scripts, fixtures, schemas, policy files, acceptance tests,
other production modules, documentation, package metadata, or repository checks to
improve a metric. Do not add dependencies. Do not use browsers, network services,
AWS, credentials, customer data, or the real Webflow checkout. Do not special-case
fixture names, fixed counts, benchmark environment variables, or expected outputs.

## Hard Constraints

- Canonical index and discovery output must remain byte-identical to the frozen
  reference for the workload.
- All safety metrics must remain at their safe values: no false merges,
  unanchored corroboration, tamper acceptance, unsafe evidence, lineage overlap,
  trusted-route false positives, schema-invalid acceptance, empty-runner passes,
  runner false passes, stopped-runtime lease errors, or privacy leaks.
- `deterministic_runs=1`; scale work must be positive and monotonic for
  100 <= 1,000 <= 10,000 files.
- The complete checks script must pass. A primary improvement that violates a
  hard constraint is rejected as `checks_failed`, never kept.
- One causal hypothesis per run. Equal or noisy results are discarded. Confirm a
  promising performance change with repeated measurements before treating it as a
  real win.

## Suggested Experiment Order

1. Reduce repeated compiler I/O or metadata work while preserving output.
2. Reduce redundant discovery/index recomputation inside existing call contracts.
3. Try small, behavior-preserving simplifications only when the deterministic work
   count and full checks improve or remain valid.
4. Re-read the source and choose a structurally different idea after three
   consecutive discards; do not repeat a no-op variation.

## What's Been Tried

The previous 100-run wave hardened evidence, routing, lifecycle, privacy, and
runtime behavior and retained only an independently verified method-scan speedup.
This wave starts from a frozen synthetic scale oracle. The initial baseline and
each hypothesis must be recorded in `.auto/log.jsonl` by the native extension.
