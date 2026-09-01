"""Stable command-line interface for the Webflow browser lifecycle core."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from . import core

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_INPUT = 2
EXIT_BLOCKED = 3
EXIT_CONFLICT = 4

COMMANDS = {"prepare", "verify", "status", "reconcile", "finish", "cleanup"}
CONFLICT_CODES = {
    "consumer_conflict",
    "lease_not_confirmed",
    "runtime_identity_mismatch",
    "runtime_identity_unavailable",
    "runtime_generation_mismatch",
    "runtime_mode_conflict",
    "runtime_ownership_unknown",
    "transaction_mismatch",
    "transaction_not_found",
    "transport_mismatch",
    "port_occupied",
    "stale_lease",
}
CONFLICT_CLASSIFICATIONS = {"transaction_active", "stale_transaction"}
CONFLICT_STATES = {
    "active_code_mode_owner_without_receipt",
    "active_direct_owner",
    "active_unknown_owner",
    "owned_runtime_without_lease",
    "replacement_runtime",
    "stale_lease",
    "stale_transaction",
    "stale_transaction_lease",
    "transaction_identity_unknown",
    "unverified_listener",
}
FAILED_STATES = {
    "transaction_runtime_unhealthy",
    "unknown_runtime_state",
}


def _usage() -> str:
    return """Usage: webflow-browser COMMAND

Commands:
  prepare       Read one JSON prepare request from stdin and emit JSON.
  verify        Read one JSON verify request from stdin and emit JSON.
  status        Read an optional status request from stdin and emit JSON.
  reconcile     Recover only the stale states classified as safe.
  finish        Read one JSON finish request from stdin and emit JSON.
  cleanup       Alias for finish.

Exit codes:
  0  command completed
  1  lifecycle or cleanup failure
  2  invalid command or request
  3  readiness or authentication blocker
  4  ownership or transaction conflict

The JSON protocol is versioned and uses the same bounded lifecycle contract as
the Pi adapter. Browser actions are returned for the caller to execute; this
command never returns credentials, cookies, raw DOM, or browser state.
"""


def _read_request(command: str) -> dict[str, object]:
    if command == "status" and sys.stdin.isatty():
        return {"version": core.PROTOCOL_VERSION, "operation": "status"}
    try:
        raw = sys.stdin.buffer.read(core.MAX_REQUEST_BYTES + 1).decode("utf-8")
    except UnicodeDecodeError as error:
        raise core.ProtocolError("invalid_encoding") from error
    if not raw.strip():
        if command == "status":
            return {"version": core.PROTOCOL_VERSION, "operation": "status"}
        raise core.ProtocolError("request_required")
    request = core.parse_request(raw)
    expected_operation = "finish" if command == "cleanup" else command
    if request.get("operation") != expected_operation:
        raise core.ProtocolError("command_mismatch")
    return request


def _exit_code(result: dict[str, object]) -> int:
    error = result.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        phase = error.get("phase")
        if code in CONFLICT_CODES:
            return EXIT_CONFLICT
        if phase == "input":
            return EXIT_INPUT
        return EXIT_FAILURE

    if result.get("status") == "reconciled":
        return EXIT_SUCCESS
    if result.get("classification") in CONFLICT_CLASSIFICATIONS:
        return EXIT_CONFLICT
    state = result.get("state")
    if state in CONFLICT_STATES:
        return EXIT_CONFLICT
    if state in FAILED_STATES:
        return EXIT_FAILURE
    if result.get("classification") == "cleanup_failed":
        return EXIT_FAILURE
    if result.get("status") == "blocked":
        return EXIT_BLOCKED
    return EXIT_SUCCESS


def _run(command: str) -> int:
    try:
        request = _read_request(command)
        result = core.DesignerCodeMode().handle(request)
    except Exception as error:
        protocol_error = (
            error
            if isinstance(error, core.ProtocolError)
            else core.ProtocolError("internal_error", "dispatch", True)
        )
        result = core.error_result(protocol_error)
    core.emit(result)
    return _exit_code(result)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--help"] or arguments == ["-h"]:
        print(_usage(), end="")
        return EXIT_SUCCESS
    if len(arguments) != 1 or arguments[0] not in COMMANDS:
        core.emit(core.error_result(core.ProtocolError("invalid_command")))
        return EXIT_INPUT
    return _run(arguments[0])


if __name__ == "__main__":
    raise SystemExit(main())
