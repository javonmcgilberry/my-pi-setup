#!/usr/bin/env python3
"""Validate browser evidence, review runs, and maintain a bounded candidate queue."""

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
REPORT_FIELDS = {
    "mode",
    "sanitized_url",
    "ownership_boundary",
    "target_frame",
    "verification",
    "observations",
    "authorized_actions",
    "diagnostics",
    "artifacts",
    "blockers",
    "assumptions",
    "finish",
    "scope_claim",
}
READINESS_CHECKS = {
    "hud",
    "designer_service",
    "target_http",
    "browser_profile",
    "designer_surface",
}
OBSERVATION_FIELDS = {"before", "after"}
DIAGNOSTIC_FIELDS = {"console", "page_errors", "network"}
SCOPE_CLAIMS = {
    "attached": "attached_state_only",
    "isolated": "repeatable_isolated_state_only",
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
    return validate_bounded_text(value, field, maximum=240)


def validate_bounded_text(value: object, field: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must contain 1 to {maximum} characters")
    return value


def validate_text_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    if len(value) > 50:
        raise ValueError(f"{field} must contain at most 50 entries")
    return [validate_text(item, f"{field}[{index}]") for index, item in enumerate(value)]


def validate_report(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"report"}:
        raise ValueError("input must be an object containing only report")
    report = value["report"]
    if not isinstance(report, dict) or set(report) != REPORT_FIELDS:
        raise ValueError(f"report must contain exactly {sorted(REPORT_FIELDS)}")

    mode = report["mode"]
    if not isinstance(mode, str) or mode not in SCOPE_CLAIMS:
        raise ValueError(f"report.mode must be one of {sorted(SCOPE_CLAIMS)}")
    validate_bounded_text(
        report["sanitized_url"], "report.sanitized_url", maximum=2_000
    )
    validate_text(report["ownership_boundary"], "report.ownership_boundary")
    validate_text(report["target_frame"], "report.target_frame")

    verification = report["verification"]
    if not isinstance(verification, dict):
        raise ValueError("report.verification must be an object")
    if verification.get("status") not in {"verified", "blocked"}:
        raise ValueError("report.verification.status must be verified or blocked")
    transaction_id = validate_text(
        verification.get("transactionId"), "report.verification.transactionId"
    )
    readiness = verification.get("readiness")
    if not isinstance(readiness, dict):
        raise ValueError("report.verification.readiness must be an object")
    checks = readiness.get("checks")
    if not isinstance(checks, list):
        raise ValueError("report.verification.readiness.checks must be an array")
    observed_checks: dict[str, str] = {}
    for index, check in enumerate(checks):
        if not isinstance(check, dict) or set(check) != {"name", "state"}:
            raise ValueError(
                "report.verification.readiness.checks"
                f"[{index}] must contain exactly name and state"
            )
        name = check["name"]
        state = check["state"]
        if not isinstance(name, str) or name not in READINESS_CHECKS:
            raise ValueError(f"unknown readiness check: {name!r}")
        if name in observed_checks:
            raise ValueError(f"duplicate readiness check: {name}")
        if not isinstance(state, str) or state not in {
            "ready",
            "unavailable",
            "error",
            "auth_required",
        }:
            raise ValueError(f"invalid readiness state for {name}: {state!r}")
        observed_checks[name] = state
    if set(observed_checks) != READINESS_CHECKS:
        raise ValueError(
            "report.verification.readiness.checks must name exactly "
            f"{sorted(READINESS_CHECKS)}"
        )
    blocked_checks = sorted(
        name for name, state in observed_checks.items() if state != "ready"
    )
    readiness_cleanup = readiness.get("cleanup")
    if not isinstance(readiness_cleanup, dict) or set(readiness_cleanup) != {
        "runtimeStopped",
        "runtimeHeld",
    }:
        raise ValueError(
            "report.verification.readiness.cleanup must contain exactly "
            "runtimeHeld and runtimeStopped"
        )
    if readiness_cleanup["runtimeStopped"] is not False or not isinstance(
        readiness_cleanup["runtimeHeld"], bool
    ):
        raise ValueError(
            "report.verification.readiness.cleanup is invalid during verification"
        )
    gate_blockers = list(blocked_checks)
    if readiness_cleanup["runtimeHeld"] is False:
        gate_blockers.append("browser_runtime_cleanup")
    expected_allowed = not gate_blockers
    if verification.get("qaLaunchAllowed") is not expected_allowed:
        raise ValueError(
            "report.verification.qaLaunchAllowed conflicts with readiness checks"
        )
    expected_status = "verified" if expected_allowed else "blocked"
    if verification.get("status") != expected_status:
        raise ValueError(
            "report.verification.status conflicts with readiness decision"
        )
    readiness_blockers = validate_text_list(
        readiness.get("blockers"), "report.verification.readiness.blockers"
    )
    if sorted(readiness_blockers) != sorted(gate_blockers):
        raise ValueError(
            "report.verification.readiness.blockers conflicts with readiness checks"
        )

    observations = report["observations"]
    if not isinstance(observations, dict) or set(observations) != OBSERVATION_FIELDS:
        raise ValueError(
            "report.observations must contain exactly "
            f"{sorted(OBSERVATION_FIELDS)}"
        )
    for name, observation in observations.items():
        validate_text(observation, f"report.observations.{name}")

    diagnostics = report["diagnostics"]
    if not isinstance(diagnostics, dict) or set(diagnostics) != DIAGNOSTIC_FIELDS:
        raise ValueError(
            "report.diagnostics must contain exactly "
            f"{sorted(DIAGNOSTIC_FIELDS)}"
        )
    diagnostic_counts = {
        name: len(validate_text_list(items, f"report.diagnostics.{name}"))
        for name, items in diagnostics.items()
    }
    action_count = len(
        validate_text_list(report["authorized_actions"], "report.authorized_actions")
    )
    artifact_count = len(validate_text_list(report["artifacts"], "report.artifacts"))
    blockers = validate_text_list(report["blockers"], "report.blockers")
    assumption_count = len(
        validate_text_list(report["assumptions"], "report.assumptions")
    )

    finish = report["finish"]
    if not isinstance(finish, dict):
        raise ValueError("report.finish must be an object")
    if finish.get("transactionId") != transaction_id:
        raise ValueError("report.finish transaction does not match verification")
    if finish.get("status") != "finished" or finish.get("runtimeStopped") is not True:
        raise ValueError("report.finish does not prove a finished transaction")
    cleanup = finish.get("cleanup")
    if not isinstance(cleanup, dict):
        raise ValueError("report.finish.cleanup must be an object")
    expected_cleanup = {
        "runtimeOwned": False,
        "cdpReady": False,
        "consumer": None,
        "leasePresent": False,
        "status": "stopped",
    }
    if any(cleanup.get(key) != expected for key, expected in expected_cleanup.items()):
        raise ValueError("report.finish.cleanup does not prove a clean stopped runtime")

    expected_scope = SCOPE_CLAIMS[mode]
    if report["scope_claim"] != expected_scope:
        raise ValueError(
            f"report.scope_claim must be {expected_scope!r} for mode {mode!r}"
        )

    missing_blockers = set(gate_blockers) - set(blockers)
    if missing_blockers:
        raise ValueError(
            "report.blockers must name every non-ready check: "
            f"{sorted(missing_blockers)}"
        )
    return {
        "evidenceContractValid": True,
        "mode": mode,
        "scopeClaim": expected_scope,
        "allReadinessChecksReady": not blocked_checks,
        "nonReadyChecks": blocked_checks,
        "blockerCount": len(blockers),
        "authorizedActionCount": action_count,
        "artifactCount": artifact_count,
        "assumptionCount": assumption_count,
        "diagnosticCounts": diagnostic_counts,
        "cleanupProven": True,
    }


def report_template(mode: str) -> dict[str, Any]:
    if mode not in SCOPE_CLAIMS:
        raise ValueError(f"report template mode must be one of {sorted(SCOPE_CLAIMS)}")
    return {
        "report": {
            "mode": mode,
            "sanitized_url": "REPLACE_WITH_SANITIZED_URL",
            "ownership_boundary": "REPLACE_WITH_OBSERVED_BOUNDARY",
            "target_frame": "REPLACE_WITH_TARGET_FRAME",
            "verification": "REPLACE_WITH_SANITIZED_VERIFY_OUTPUT",
            "observations": {
                "before": "REPLACE_WITH_SCOPED_BEFORE_OBSERVATION",
                "after": "REPLACE_WITH_SCOPED_AFTER_OBSERVATION",
            },
            "authorized_actions": [],
            "diagnostics": {name: [] for name in sorted(DIAGNOSTIC_FIELDS)},
            "artifacts": [],
            "blockers": sorted(READINESS_CHECKS),
            "assumptions": [],
            "finish": "REPLACE_WITH_SANITIZED_FINISH_OUTPUT",
            "scope_claim": SCOPE_CLAIMS[mode],
        }
    }


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
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--append-candidate", type=Path)
    action.add_argument("--review-queue", action="store_true")
    action.add_argument("--validate-report", action="store_true")
    action.add_argument("--report-template", choices=sorted(SCOPE_CLAIMS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.report_template:
            result = report_template(args.report_template)
        elif args.validate_report:
            if not args.path:
                raise ValueError("an evidence report path is required")
            value = json.loads(args.path.read_text())
            result = validate_report(value)
        elif args.append_candidate:
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
        print(f"Unable to process automation evidence: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
