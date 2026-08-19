# Automation maintenance loop

Use this reference during a separate maintenance review, not as a required
step after every browser task. Repeated browser actions can justify a helper,
but live task execution must stay separate from code generation and promotion.

## Review a complete run

Reconstruct the run from sanitized commands, service probes, snapshots, errors,
recovery actions, and postconditions. Include failures and recoveries that
occurred before the final successful action.

Group events into candidates. Each candidate records:

- known inputs
- one operation
- one observable postcondition
- occurrence count
- deterministic and stateful status
- sensitivity
- closest existing helper and tests
- supporting event IDs

Cover every inventoried event. Do not classify only the final successful event.
One-off, application-owned, nondeterministic, and sensitive events still need a
disposition.

## Classify candidates

Create the review file outside the repository:

```json
{
  "run": {
    "reconstruction_complete": true,
    "inventory_complete": true,
    "events": [
      {
        "id": "required-service-unavailable",
        "kind": "failure",
        "summary": "A declared service failed its readiness check",
        "occurrences": 2
      }
    ],
    "candidates": [
      {
        "name": "preflight declared services",
        "known_inputs": ["service label", "target", "timeout"],
        "bounded_operation": "probe each declared service once",
        "observable_postcondition": "report every service state",
        "occurrence_count": 2,
        "deterministic": true,
        "stateful": false,
        "sensitive": false,
        "closest_existing_helper": "designer-session.py",
        "evidence": ["required-service-unavailable"]
      }
    ]
  }
}
```

Run the classifier:

```sh
python3 scripts/automation-evidence.py /tmp/designer-automation-review.json
```

The result chooses one disposition:

- `extend_existing`: a current helper owns repeated deterministic work.
- `scriptify`: stable read-only work has no current owner.
- `guarded_helper`: repeated deterministic work changes browser or Designer
  state.
- `observe`: the evidence is one-off or the contract is not deterministic.
- `do_not_persist`: the candidate depends on sensitive state.

The classifier checks the supplied evidence. It does not discover candidates or
prove that the run inventory is complete.

## Incorporate the test corpus without copying it

When a repeated browser sequence should become reusable Designer knowledge,
first run `scripts/test-corpus-index.py discover` against a read-only Webflow
checkout. The tracked `test-corpus-policy.json` allowlists source roots and
helper sources; discovery extracts bounded test/helper fragments, groups their
non-sensitive action signatures, and reports subsystem coverage without
creating executable knowledge. Its independent-lineage holdouts prevent two
tests that invoke the same helper or live in the same scenario family from
corroborating each other.

Only after review should `build` use the small, explicit operation taxonomy to
create cards. Generated discovery and card indexes belong outside the
repository.

Review operation cards rather than whole test files. Keep the source commit,
source manifest, bounded line ranges, selector keys, context, postconditions,
and reason codes. Treat `candidate`, `negative_evidence`, and `holdout` as
meaningful outcomes. A high-frequency legacy test does not override a stale
selector, quarantine marker, missing assertion, or unsafe fixture dependency.

Keep held-out evidence separate from positive evidence. A recipe is improved
only when a held-out fixture or safe isolated Designer run demonstrates a
semantic postcondition, not merely because the recipe resembles its source
test. Promotion requires explicit semantic evidence, independent
corroboration, safe evidence, and human review; a runtime receipt can report
drift but never promote a candidate. Promote at most one deterministic helper
per maintenance pass and keep the existing `agent_browser` transport and
runtime ownership boundary intact.

For final verification, a declared scenario contract may be converted into a
plan with `scripts/test-scenario-eval.py`. The planner emits external setup,
managed browser, assertion, and teardown phases, but does not execute the
Playwright adapter. Existing Webflow scenario utilities own their own
Playwright contexts; only an explicitly reviewed adapter with a sanitized
target handoff may bridge that boundary.

## Promote one change

For one promotable candidate:

1. Reread the current helper tree and tests.
2. Extend the closest helper unless responsibilities would become mixed.
3. Keep the existing browser adapter. Do not recreate its daemon, CDP client,
   snapshot engine, network stack, or state store.
4. Validate structured inputs and bounded outputs. Reject secret-bearing data.
5. Keep read-only helpers read-only. For stateful work, require explicit
   mutation permission, capture a baseline, and verify postconditions.
6. Add a focused regression test from sanitized evidence.
7. Run the helper, its full test file, Python compilation, and capability
   catalog validation.
8. Update the catalog only after validation passes.

Do not persist site IDs, URLs, credentials, tokens, cookies, PII, raw DOM, or
customer content. Keep candidates that are not promoted classified as already
documented, overlapping, unsupported by repetition, application-owned,
sensitive, or nondeterministic.

## Maintenance result

Record the promoted helper and the repeated manual sequence it replaces. If no
candidate is promoted, record the dispositions that support that decision. A
missing run reconstruction or incomplete event coverage is an incomplete
review, not evidence that no improvement exists.
