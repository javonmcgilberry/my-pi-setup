#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "ensure_test_aws", SCRIPT_DIR / "ensure-test-aws.py"
)
assert SPEC is not None and SPEC.loader is not None
ensure_test_aws = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ensure_test_aws
SPEC.loader.exec_module(ensure_test_aws)


class FakeRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def run(self, command, *, cwd=None, env=None, timeout=None):
        self.calls.append((command, cwd, env, timeout))
        returncode, stdout = self.responses.pop(0)
        return subprocess.CompletedProcess(command, returncode, stdout, "")


class EnsureTestAwsTests(unittest.TestCase):
    def repo(self, root: str) -> Path:
        repo = Path(root)
        (repo / "bin").mkdir()
        (repo / "bin" / "run-with-aws").touch()
        return repo

    def test_valid_profile_and_server_credentials_are_a_noop(self):
        runner = FakeRunner(
            [
                (0, "123\n"),
                (
                    0,
                    "wf-app AWS_ACCESS_KEY_ID=a AWS_SECRET_ACCESS_KEY=b AWS_SESSION_TOKEN=c",
                ),
                (0, "identity"),
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            report = ensure_test_aws.repair(
                self.repo(root), runner, {}, Path(root) / "state.json"
            )
        self.assertFalse(report["loginRefreshed"])
        self.assertFalse(report["serverRestarted"])
        self.assertEqual(len(runner.calls), 3)

    def test_stale_server_credentials_restart_only_the_server_task(self):
        runner = FakeRunner(
            [
                (0, "123\n"),
                (
                    0,
                    "wf-app AWS_ACCESS_KEY_ID=a AWS_SECRET_ACCESS_KEY=b AWS_SESSION_TOKEN=c",
                ),
                (1, ""),
                (0, "identity"),
                (0, "stopped"),
                (1, ""),
                (0, "started"),
                (0, "456\n"),
                (0, '{"Expiration":"2099-01-01T00:00:00Z"}'),
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / "state.json"
            report = ensure_test_aws.repair(self.repo(root), runner, {}, state)
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)
        self.assertTrue(report["serverRestarted"])
        self.assertEqual(
            [call[0] for call in runner.calls if "hud" in call[0]],
            [
                ["npm", "run", "hud", "stop", "server"],
                ["npm", "run", "hud", "start", "server"],
            ],
        )

    def test_expired_profile_logs_in_verifies_and_restarts_stale_server(self):
        runner = FakeRunner(
            [
                (0, "123\n"),
                (1, ""),
                (1, ""),
                (0, "logged in"),
                (0, "identity"),
                (0, "stopped"),
                (1, ""),
                (0, "started"),
                (0, "456\n"),
                (0, '{"Expiration":"2099-01-01T00:00:00Z"}'),
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            report = ensure_test_aws.repair(
                self.repo(root), runner, {}, Path(root) / "state.json"
            )
        self.assertTrue(report["loginRefreshed"])
        self.assertTrue(report["serverRestarted"])
        self.assertEqual(
            runner.calls[3][0],
            ["aws", "sso", "login", "--sso-session", "wf-session"],
        )

    def test_process_credentials_follow_the_server_parent_chain(self):
        runner = FakeRunner(
            [
                (0, "wf-app"),
                (0, "122\n"),
                (
                    0,
                    "node AWS_ACCESS_KEY_ID=a AWS_SECRET_ACCESS_KEY=b AWS_SESSION_TOKEN=c",
                ),
            ]
        )
        self.assertEqual(
            ensure_test_aws.process_credentials(runner, 123),
            {
                "AWS_ACCESS_KEY_ID": "a",
                "AWS_SECRET_ACCESS_KEY": "b",
                "AWS_SESSION_TOKEN": "c",
            },
        )

    def test_failed_login_blocks_before_touching_hud(self):
        runner = FakeRunner([(1, ""), (1, ""), (1, "")])
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(
                ensure_test_aws.AwsRepairError, "did not produce valid"
            ):
                ensure_test_aws.repair(self.repo(root), runner, {})
        self.assertFalse(any("hud" in call[0] for call in runner.calls))

    def test_missing_server_is_started_with_verified_profile(self):
        runner = FakeRunner(
            [
                (1, ""),
                (0, "identity"),
                (0, "started"),
                (0, "456\n"),
                (0, '{"Expiration":"2099-01-01T00:00:00Z"}'),
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            report = ensure_test_aws.repair(
                self.repo(root), runner, {}, Path(root) / "state.json"
            )
        self.assertTrue(report["serverStarted"])
        self.assertFalse(report["serverRestarted"])
        self.assertEqual(
            [call[0] for call in runner.calls if "hud" in call[0]],
            [["npm", "run", "hud", "start", "server"]],
        )

    def test_valid_private_receipt_skips_process_environment_inspection(self):
        runner = FakeRunner([(0, "123\n")])
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / "state.json"
            state.write_text(
                '{"serverPids":[123],"credentialExpirationEpoch":4102444800}'
            )
            report = ensure_test_aws.repair(self.repo(root), runner, {}, state)
        self.assertTrue(report["restartReceiptValid"])
        self.assertFalse(report["serverRestarted"])
        self.assertEqual(len(runner.calls), 1)


if __name__ == "__main__":
    unittest.main()
