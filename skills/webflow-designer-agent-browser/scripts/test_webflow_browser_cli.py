from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


LIB_DIR = Path(__file__).resolve().parents[1] / "lib"
BIN = Path(__file__).resolve().parents[1] / "bin" / "webflow-browser"
sys.path.insert(0, str(LIB_DIR))

from webflow_browser import cli, core


class FakeInput:
    def __init__(self, payload: str = ""):
        self.buffer = io.BytesIO(payload.encode("utf-8"))

    def isatty(self) -> bool:
        return False


class FakeCodeMode:
    def __init__(self, result: dict[str, object], requests: list[dict[str, object]]):
        self.result = result
        self.requests = requests

    def handle(self, request: dict[str, object]) -> dict[str, object]:
        self.requests.append(request)
        return self.result


class WebflowBrowserCliTests(unittest.TestCase):
    def run_cli(
        self,
        command: str,
        payload: str = "",
        *,
        result: dict[str, object] | None = None,
        argv: list[str] | None = None,
    ) -> tuple[int, dict[str, object] | None, list[dict[str, object]]]:
        requests: list[dict[str, object]] = []
        fake = FakeCodeMode(
            result or {"version": 1, "status": "finished"},
            requests,
        )
        output = io.StringIO()
        with (
            mock.patch.object(cli.core, "DesignerCodeMode", return_value=fake),
            mock.patch.object(cli.sys, "stdin", FakeInput(payload)),
            redirect_stdout(output),
        ):
            exit_code = cli.main(argv or [command])
        text = output.getvalue().strip()
        return exit_code, json.loads(text) if text else None, requests

    def test_prepare_reads_versioned_json_and_returns_success(self):
        request = {"version": 1, "operation": "prepare", "target": "bounded"}
        exit_code, result, requests = self.run_cli(
            "prepare", json.dumps(request), result={"status": "prepared"}
        )
        self.assertEqual(exit_code, cli.EXIT_SUCCESS)
        self.assertEqual(result, {"status": "prepared"})
        self.assertEqual(requests, [request])

    def test_cleanup_alias_requires_and_dispatches_finish(self):
        request = {"version": 1, "operation": "finish", "transactionId": "x"}
        exit_code, _result, requests = self.run_cli("cleanup", json.dumps(request))
        self.assertEqual(exit_code, cli.EXIT_SUCCESS)
        self.assertEqual(requests, [request])

    def test_status_without_stdin_builds_a_status_request(self):
        exit_code, _result, requests = self.run_cli(
            "status", result={"state": "clean_stopped"}
        )
        self.assertEqual(exit_code, cli.EXIT_SUCCESS)
        self.assertEqual(requests, [{"version": 1, "operation": "status"}])

    def test_readiness_blocker_has_a_distinct_exit_code(self):
        exit_code, result, _requests = self.run_cli(
            "verify",
            json.dumps({"version": 1, "operation": "verify"}),
            result={"status": "blocked", "classification": "auth_required"},
        )
        self.assertEqual(exit_code, cli.EXIT_BLOCKED)
        self.assertEqual(result["classification"], "auth_required")

    def test_transaction_classification_has_conflict_exit_code(self):
        for classification in ("transaction_active", "stale_transaction"):
            with self.subTest(classification=classification):
                exit_code, _result, _requests = self.run_cli(
                    "prepare",
                    json.dumps({"version": 1, "operation": "prepare"}),
                    result={"status": "blocked", "classification": classification},
                )
                self.assertEqual(exit_code, cli.EXIT_CONFLICT)

    def test_status_conflict_has_a_distinct_exit_code(self):
        for state in ("active_unknown_owner", "unverified_listener"):
            with self.subTest(state=state):
                exit_code, _result, _requests = self.run_cli(
                    "status", result={"state": state}
                )
                self.assertEqual(exit_code, cli.EXIT_CONFLICT)

    def test_runtime_ownership_errors_have_conflict_exit_code(self):
        request = json.dumps({"version": 1, "operation": "prepare"})
        for code in (
            "port_occupied",
            "runtime_generation_mismatch",
            "runtime_mode_conflict",
            "runtime_ownership_unknown",
            "stale_lease",
        ):
            with self.subTest(code=code):
                exit_code, _result, _requests = self.run_cli(
                    "prepare",
                    request,
                    result={"status": "blocked", "error": {"code": code}},
                )
                self.assertEqual(exit_code, cli.EXIT_CONFLICT)

    def test_reconcile_is_exposed_for_safe_stale_lease_recovery(self):
        request = {"version": 1, "operation": "reconcile"}
        exit_code, _result, requests = self.run_cli(
            "reconcile", json.dumps(request), result={"status": "reconciled"}
        )
        self.assertEqual(exit_code, cli.EXIT_SUCCESS)
        self.assertEqual(requests, [request])

    def test_reconcile_recovery_state_still_has_success_exit_code(self):
        exit_code, _result, _requests = self.run_cli(
            "reconcile",
            json.dumps({"version": 1, "operation": "reconcile"}),
            result={
                "state": "stale_transaction",
                "classification": "stale_transaction",
                "status": "reconciled",
                "recovered": True,
            },
        )
        self.assertEqual(exit_code, cli.EXIT_SUCCESS)

    def test_protocol_input_errors_are_json_and_nonzero(self):
        exit_code, result, requests = self.run_cli("prepare", "not-json")
        self.assertEqual(exit_code, cli.EXIT_INPUT)
        self.assertEqual(result["error"]["code"], "invalid_json")
        self.assertEqual(requests, [])

    def test_command_mismatch_is_rejected_before_dispatch(self):
        request = {"version": 1, "operation": "verify"}
        exit_code, result, requests = self.run_cli("prepare", json.dumps(request))
        self.assertEqual(exit_code, cli.EXIT_INPUT)
        self.assertEqual(result["error"]["code"], "command_mismatch")
        self.assertEqual(requests, [])

    def test_invalid_command_has_json_error(self):
        exit_code, result, requests = self.run_cli("ignored", argv=["unknown"])
        self.assertEqual(exit_code, cli.EXIT_INPUT)
        self.assertEqual(result["error"]["code"], "invalid_command")
        self.assertEqual(requests, [])

    def test_help_is_human_readable_and_does_not_open_runtime(self):
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = cli.main(["--help"])
        self.assertEqual(exit_code, cli.EXIT_SUCCESS)
        self.assertIn("webflow-browser COMMAND", output.getvalue())

    def test_output_uses_core_redaction(self):
        exit_code, result, _requests = self.run_cli(
            "status",
            result={"status": "ok", "token": "do-not-return"},
        )
        self.assertEqual(exit_code, cli.EXIT_SUCCESS)
        self.assertNotIn("do-not-return", json.dumps(result))

    def test_executable_help_and_invalid_command_use_the_public_interface(self):
        help_result = subprocess.run(
            [str(BIN), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(help_result.returncode, cli.EXIT_SUCCESS)
        self.assertIn("webflow-browser COMMAND", help_result.stdout)

        invalid_result = subprocess.run(
            [str(BIN), "unknown"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(invalid_result.returncode, cli.EXIT_INPUT)
        self.assertEqual(
            json.loads(invalid_result.stdout)["error"]["code"],
            "invalid_command",
        )


if __name__ == "__main__":
    unittest.main()
