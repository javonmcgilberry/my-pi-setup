# Compounding Automation Loop

Run this review after every completed browser use and verified browser cleanup. Candidate discovery and candidate classification are separate steps: reconstruct the complete sanitized run first, then let `automation-evidence.py` adjudicate every grounded candidate. A live browser run may queue evidence, but it never modifies or executes helper source.

## Reconstruct the complete run

Build an event inventory from the run's sanitized commands, service probes, snapshots, errors, recovery actions, and verified postconditions. Include every meaningful failure and recovery, even when it occurred before the final successful action.

Group related events into behavioral candidates. Each candidate must state:

- known inputs
- one bounded operation
- one observable postcondition
- occurrence count
- whether behavior is deterministic
- whether behavior is stateful
- whether it is sensitive
- the closest existing helper, after searching `scripts/` and its tests
- the event IDs that support the classification

Do not classify a handpicked final event. Every inventoried event must be covered by at least one candidate, including one-off, sensitive, application-owned, and nondeterministic findings.

## Classify the complete inventory

Create a temporary JSON file outside the skill:

```json
{
  "run": {
    "reconstruction_complete": true,
    "inventory_complete": true,
    "events": [
      {
        "id": "required-service-unavailable",
        "kind": "failure",
        "summary": "A required labeled service failed its explicit readiness check",
        "occurrences": 2
      }
    ],
    "candidates": [
      {
        "name": "preflight explicit required services",
        "known_inputs": ["service label", "explicit target", "bounded timeout"],
        "bounded_operation": "probe each required service once",
        "observable_postcondition": "report readiness for every labeled service",
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

Run:

```bash
python3 scripts/automation-evidence.py /tmp/designer-automation-review.json
```

The classifier rejects a missing reconstruction, an incomplete inventory, any event that no candidate adjudicates, and any candidate occurrence count that understates its evidence. It returns:

- `extend_existing`: a current helper owns the repeated deterministic behavior.
- `scriptify`: repeated read-only work has stable inputs and outputs but no current owner.
- `guarded_helper`: repeated deterministic work changes browser or Designer state.
- `observe`: the behavior occurred once or its contract is not deterministic.
- `do_not_persist`: the candidate depends on sensitive state.

The classifier is the final adjudicator of grounded candidates. It does not discover candidates or prove that the run inventory is complete.

## Review and promote one learning per maintenance pass

Queue only non-sensitive candidate shapes. Repetition in the queue is evidence for review, not permission to change code. Sensitive candidates are rejected from persistence. Same-run helper generation is forbidden.

1. Select one classified promotable candidate.
2. Reread the actual skill tree and tests so the overlap decision uses the current implementation.
3. Extend the closest helper unless that would mix unrelated responsibilities.
4. Keep agent-browser as the runtime. Do not recreate its daemon, CDP client, snapshot engine, network stack, or state store.
5. Require sanitized structured inputs and bounded structured outputs. Reject secret-bearing arguments before execution.
6. Keep read-only helpers read-only. For stateful behavior, default to observation, require explicit mutation permission, capture a baseline, and verify postconditions.
7. Add a focused regression test from sanitized run evidence.
8. Run the helper, focused tests, Python compilation, and `scripts/capability-catalog.py validate`.
9. Update the static catalog and start another promotion pass only after validation, then reread the skill tree again.

For every candidate that is not promoted, record whether it belongs in application code or tests, is already documented, overlaps an existing helper, lacks repeated evidence, depends on sensitive or hidden state, or remains nondeterministic. Do not force a promotion.

## Completion contract

Before classifying the run as complete, verify that the native managed session is closed and `browser-runtime.py status` reports no consumer, no owned runtime, and no ready CDP endpoint. Missing cleanup proof is an incomplete inventory, not a successful run.

End each browser task with one concise audit line:

```text
Compounding: extended designer-session.py; replaces manual required-service probes.
```

Use this line only after full-run reconstruction, complete event coverage, and classification:

```text
Compounding: no promotable deterministic sequence found; all candidates were adjudicated as observe or do_not_persist.
```

If reconstruction or inventory coverage is incomplete, report that exact blocker. Never report that no promotable sequence exists from a narrow synthetic candidate.
