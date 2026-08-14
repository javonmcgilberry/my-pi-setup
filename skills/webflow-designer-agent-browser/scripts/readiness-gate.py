#!/usr/bin/env python3
"""Emit a bounded handoff that gates Designer QA behind proven readiness."""

from __future__ import annotations

import argparse
import json

REQUIRED_CHECKS = (
    "hud",
    "designer_service",
    "target_http",
    "browser_profile",
    "designer_surface",
)
CHECK_STATES = {"ready", "unavailable", "error", "auth_required"}


def parse_check(value: str) -> tuple[str, str]:
    name, separator, state = value.partition("=")
    if not separator or name not in REQUIRED_CHECKS:
        raise argparse.ArgumentTypeError(
            f"check must be one of {', '.join(REQUIRED_CHECKS)} as name=state"
        )
    if state not in CHECK_STATES:
        raise argparse.ArgumentTypeError(
            f"check state must be one of {', '.join(sorted(CHECK_STATES))}"
        )
    return name, state


def classify(
    checks: list[tuple[str, str]],
    *,
    runtime_stopped: bool,
    runtime_held: bool = False,
) -> dict[str, object]:
    if runtime_stopped and runtime_held:
        raise ValueError("runtime cannot be both stopped and held")
    observed: dict[str, str] = {}
    for name, state in checks:
        if name in observed:
            raise ValueError(f"duplicate readiness check: {name}")
        observed[name] = state

    normalized = [
        {"name": name, "state": observed.get(name, "unavailable")}
        for name in REQUIRED_CHECKS
    ]
    blockers = [
        check["name"] for check in normalized if check["state"] != "ready"
    ]
    if not runtime_stopped and not runtime_held:
        blockers.append("browser_runtime_cleanup")
    ready = not blockers
    return {
        "version": 1,
        "classification": "ready_for_qa" if ready else "blocked_before_qa",
        "qaLaunchAllowed": ready,
        "checks": normalized,
        "blockers": blockers,
        "cleanup": {
            "runtimeStopped": runtime_stopped,
            "runtimeHeld": runtime_held,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="append",
        default=[],
        type=parse_check,
        metavar="NAME=STATE",
    )
    parser.add_argument("--runtime-stopped", action="store_true")
    parser.add_argument(
        "--runtime-held",
        action="store_true",
        help="the current transaction holds the exclusive browser lease",
    )
    args = parser.parse_args()
    try:
        result = classify(
            args.check,
            runtime_stopped=args.runtime_stopped,
            runtime_held=args.runtime_held,
        )
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["qaLaunchAllowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
