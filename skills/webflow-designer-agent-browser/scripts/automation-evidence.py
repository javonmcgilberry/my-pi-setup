#!/usr/bin/env python3
"""Review complete browser runs and maintain a bounded automation evidence queue."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

EVENT_FIELDS = {
    "id",
    "kind",
    "summary",
    "occurrences",
}
CANDIDATE_FIELDS = {
    "name",
    "known_inputs",
    "bounded_operation",
    "observable_postcondition",
    "occurrence_count",
    "deterministic",
    "stateful",
    "sensitive",
    "closest_existing_helper",
    "evidence",
}
RUN_FIELDS = {
    "reconstruction_complete",
    "inventory_complete",
    "events",
    "candidates",
}
EVENT_KINDS = {"action", "failure", "postcondition", "recovery"}
PROMOTABLE_CLASSIFICATIONS = {
    "extend_existing",
    "guarded_helper",
    "scriptify",
}
QUEUE_CANDIDATE_FIELDS = {
    "candidateId",
    "operationClass",
    "inputShape",
    "postconditionKind",
    "deterministic",
    "stateful",
    "sensitive",
    "existingHelper",
}
QUEUE_VERSION = 1


def validate_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 240:
        raise ValueError(f"{field} must contain 1 to 240 characters")
    return value


def validate_event(value: object, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"run.events[{index}] must be an object")
    if set(value) != EVENT_FIELDS:
        raise ValueError(
            f"run.events[{index}] must contain exactly {sorted(EVENT_FIELDS)}"
        )

    event_id = validate_text(value["id"], f"run.events[{index}].id")
    if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in event_id):
        raise ValueError(
            f"run.events[{index}].id must use lowercase letters, digits, hyphens, or underscores"
        )
    kind = value["kind"]
    if kind not in EVENT_KINDS:
        raise ValueError(
            f"run.events[{index}].kind must be one of {sorted(EVENT_KINDS)}"
        )
    validate_text(value["summary"], f"run.events[{index}].summary")

    occurrences = value.get("occurrences")
    if not isinstance(occurrences, int) or isinstance(occurrences, bool):
        raise ValueError(f"run.events[{index}].occurrences must be an integer")
    if occurrences < 1:
        raise ValueError(f"run.events[{index}].occurrences must be positive")
    return value


def validate_candidate(
    value: object,
    index: int,
    event_occurrences: dict[str, int],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"run.candidates[{index}] must be an object")
    if set(value) != CANDIDATE_FIELDS:
        raise ValueError(
            f"run.candidates[{index}] must contain exactly {sorted(CANDIDATE_FIELDS)}"
        )

    validate_text(value["name"], f"run.candidates[{index}].name")

    known_inputs = value["known_inputs"]
    if not isinstance(known_inputs, list) or not known_inputs:
        raise ValueError(
            f"run.candidates[{index}].known_inputs must be a non-empty array"
        )
    for input_index, item in enumerate(known_inputs):
        validate_text(
            item,
            f"run.candidates[{index}].known_inputs[{input_index}]",
        )

    validate_text(
        value["bounded_operation"],
        f"run.candidates[{index}].bounded_operation",
    )
    validate_text(
        value["observable_postcondition"],
        f"run.candidates[{index}].observable_postcondition",
    )

    occurrences = value["occurrence_count"]
    if not isinstance(occurrences, int) or isinstance(occurrences, bool):
        raise ValueError(
            f"run.candidates[{index}].occurrence_count must be an integer"
        )
    if occurrences < 1:
        raise ValueError(
            f"run.candidates[{index}].occurrence_count must be positive"
        )

    for field in ("deterministic", "stateful", "sensitive"):
        if not isinstance(value.get(field), bool):
            raise ValueError(f"run.candidates[{index}].{field} must be a boolean")

    existing = value["closest_existing_helper"]
    if existing is not None:
        helper_suffixes = (".py", ".sh", ".js", ".mjs", ".cjs")
        if not isinstance(existing, str) or not existing.endswith(helper_suffixes):
            raise ValueError(
                f"run.candidates[{index}].closest_existing_helper must name a helper script"
            )

    evidence = value["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(
            f"run.candidates[{index}].evidence must be a non-empty array"
        )
    if not all(isinstance(event_id, str) for event_id in evidence):
        raise ValueError(
            f"run.candidates[{index}].evidence must contain event IDs"
        )
    unknown_events = set(evidence) - event_occurrences.keys()
    if unknown_events:
        raise ValueError(
            f"run.candidates[{index}].evidence references unknown events: "
            f"{sorted(unknown_events)}"
        )
    evidence_occurrences = max(
        event_occurrences[event_id]
        for event_id in evidence
    )
    if occurrences < evidence_occurrences:
        raise ValueError(
            f"run.candidates[{index}].occurrence_count understates its evidence"
        )
    return value


def classify(candidate: dict[str, Any]) -> str:
    if candidate["sensitive"]:
        return "do_not_persist"
    if not candidate["deterministic"] or candidate["occurrence_count"] < 2:
        return "observe"
    if candidate["closest_existing_helper"]:
        return "extend_existing"
    if candidate["stateful"]:
        return "guarded_helper"
    return "scriptify"


def classification_reason(candidate: dict[str, Any]) -> str:
    if candidate["sensitive"]:
        return "depends_on_sensitive_state"
    if not candidate["deterministic"]:
        return "behavior_is_not_deterministic"
    if candidate["occurrence_count"] < 2:
        return "lacks_repeated_evidence"
    if candidate["closest_existing_helper"]:
        return "overlaps_existing_helper"
    if candidate["stateful"]:
        return "requires_explicit_stateful_guards"
    return "repeated_read_only_sequence"


def review(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"run"}:
        raise ValueError("input must be an object containing only run")
    run = value["run"]
    if not isinstance(run, dict) or set(run) != RUN_FIELDS:
        raise ValueError(f"run must contain exactly {sorted(RUN_FIELDS)}")
    if run["reconstruction_complete"] is not True:
        raise ValueError("run.reconstruction_complete must be true")
    if run["inventory_complete"] is not True:
        raise ValueError("run.inventory_complete must be true")

    events = run["events"]
    if not isinstance(events, list) or not events:
        raise ValueError("run.events must be a non-empty array")
    validated_events = [
        validate_event(event, index) for index, event in enumerate(events)
    ]
    event_occurrences = {
        event["id"]: event["occurrences"]
        for event in validated_events
    }
    if len(event_occurrences) != len(validated_events):
        raise ValueError("run.events IDs must be unique")

    candidates = run["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("run.candidates must be a non-empty array")
    results = []
    covered_events: set[str] = set()
    for index, raw_candidate in enumerate(candidates):
        candidate = validate_candidate(
            raw_candidate,
            index,
            event_occurrences,
        )
        covered_events.update(candidate["evidence"])
        results.append(
            {
                "name": candidate["name"],
                "classification": classify(candidate),
                "reason": classification_reason(candidate),
                "existingHelper": candidate["closest_existing_helper"],
                "evidence": candidate["evidence"],
            }
        )

    uncovered_events = event_occurrences.keys() - covered_events
    if uncovered_events:
        raise ValueError(
            "candidate inventory is incomplete; unadjudicated events: "
            f"{sorted(uncovered_events)}"
        )

    promotable_count = sum(
        result["classification"] in PROMOTABLE_CLASSIFICATIONS
        for result in results
    )
    return {
        "fullRunReviewed": True,
        "eventCount": len(validated_events),
        "candidateCount": len(results),
        "promotableCandidateCount": promotable_count,
        "noPromotableDeterministicSequence": promotable_count == 0,
        "automationReview": results,
    }


def validate_slug(value: object, field: str) -> str:
    text = validate_text(value, field)
    if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_." for character in text):
        raise ValueError(
            f"{field} must use lowercase letters, digits, dots, hyphens, or underscores"
        )
    return text


def validate_queue_candidate(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != QUEUE_CANDIDATE_FIELDS:
        raise ValueError(
            f"candidate must contain exactly {sorted(QUEUE_CANDIDATE_FIELDS)}"
        )
    for field in (
        "candidateId",
        "operationClass",
        "inputShape",
        "postconditionKind",
    ):
        validate_slug(value[field], f"candidate.{field}")
    for field in ("deterministic", "stateful", "sensitive"):
        if not isinstance(value[field], bool):
            raise ValueError(f"candidate.{field} must be a boolean")
    existing = value["existingHelper"]
    if existing is not None:
        validate_slug(existing, "candidate.existingHelper")
    return value


def candidate_fingerprint(candidate: dict[str, Any]) -> str:
    stable = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode()).hexdigest()[:24]


def empty_queue() -> dict[str, Any]:
    return {"version": QUEUE_VERSION, "candidates": []}


def read_queue(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return empty_queue()
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("evidence queue is unreadable") from error
    if (
        not isinstance(value, dict)
        or value.get("version") != QUEUE_VERSION
        or not isinstance(value.get("candidates"), list)
    ):
        raise ValueError("evidence queue has an unsupported shape")
    return value


def write_private_queue(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def queue_candidate(path: Path, value: object) -> dict[str, Any]:
    candidate = validate_queue_candidate(value)
    if candidate["sensitive"]:
        return {
            "queued": False,
            "classification": "do_not_persist",
            "reason": "depends_on_sensitive_state",
        }
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = path.with_suffix(path.suffix + ".lock")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fingerprint = candidate_fingerprint(candidate)
    try:
        with os.fdopen(descriptor, "r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            queue = read_queue(path)
            candidates = queue["candidates"]
            now = int(time.time())
            for record in candidates:
                if record.get("fingerprint") == fingerprint:
                    record["occurrences"] += 1
                    record["lastObservedAt"] = now
                    break
            else:
                candidates.append(
                    {
                        **candidate,
                        "fingerprint": fingerprint,
                        "occurrences": 1,
                        "firstObservedAt": now,
                        "lastObservedAt": now,
                    }
                )
            candidates.sort(key=lambda record: record["fingerprint"])
            write_private_queue(path, queue)
            fcntl.flock(lock, fcntl.LOCK_UN)
    finally:
        lock_path.chmod(0o600)
    record = next(
        item for item in read_queue(path)["candidates"]
        if item["fingerprint"] == fingerprint
    )
    return {
        "queued": True,
        "fingerprint": fingerprint,
        "occurrences": record["occurrences"],
    }


def review_queue(path: Path) -> dict[str, Any]:
    queue = read_queue(path)
    results = []
    for record in queue["candidates"]:
        if not record["deterministic"] or record["occurrences"] < 2:
            classification = "observe"
        elif record["existingHelper"]:
            classification = "extend_existing"
        else:
            classification = "candidate_for_promotion"
        results.append(
            {
                "candidateId": record["candidateId"],
                "fingerprint": record["fingerprint"],
                "occurrences": record["occurrences"],
                "classification": classification,
                "existingHelper": record["existingHelper"],
            }
        )
    return {
        "queueReviewed": True,
        "candidateCount": len(results),
        "candidates": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, nargs="?")
    parser.add_argument("--queue", type=Path)
    parser.add_argument("--append-candidate", type=Path)
    parser.add_argument("--review-queue", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.append_candidate:
            if not args.queue:
                raise ValueError("--queue is required with --append-candidate")
            value = json.loads(args.append_candidate.read_text())
            result = queue_candidate(args.queue, value)
        elif args.review_queue:
            if not args.queue:
                raise ValueError("--queue is required with --review-queue")
            result = review_queue(args.queue)
        else:
            if not args.path:
                raise ValueError("a complete run path is required")
            value = json.loads(args.path.read_text())
            result = review(value)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Unable to review automation candidates: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
