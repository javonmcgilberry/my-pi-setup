#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "ensure_hud_tasks", SCRIPT_DIR / "ensure-hud-tasks.py"
)
assert SPEC is not None and SPEC.loader is not None
ensure_hud_tasks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ensure_hud_tasks)


class FakeRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def run(self, command, *, cwd=None, timeout=None):
        self.calls.append((command, cwd, timeout))
        returncode, stdout = self.responses.pop(0)
        return subprocess.CompletedProcess(command, returncode, stdout, "")


def status(*tasks):
    return json.dumps(
        [
            {
                "taskName": name,
                "category": "synthetic",
                "state": state,
                "health": health,
            }
            for name, state, health in tasks
        ]
    )


class EnsureHudTasksTests(unittest.TestCase):
    def repo(self, root: str) -> Path:
        repo = Path(root)
        (repo / "package.json").write_text("{}")
        return repo

    def test_ready_tasks_are_a_noop(self):
        runner = FakeRunner(
            [
                (
                    0,
                    status(
                        ("server", "running", "up"),
                        ("entrypoints/designer/client", "running", "up"),
                    ),
                ),
                (
                    0,
                    status(
                        ("server", "running", "up"),
                        ("entrypoints/designer/client", "running", "up"),
                    ),
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            result = ensure_hud_tasks.recover(
                self.repo(root),
                ["server", "entrypoints/designer/client"],
                runner,
                wait_seconds=1,
                poll_seconds=0.1,
            )
        self.assertFalse(result["recoveryAttempted"])
        self.assertEqual(len(runner.calls), 2)

    def test_exited_up_meta_task_is_not_restarted(self):
        runner = FakeRunner(
            [
                (0, status(("designer", "exited", "up"))),
                (0, status(("designer", "exited", "up"))),
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            result = ensure_hud_tasks.recover(
                self.repo(root),
                ["designer"],
                runner,
                wait_seconds=1,
                poll_seconds=0.1,
            )
        self.assertEqual(result["restartedTasks"], [])
        self.assertEqual(len(runner.calls), 2)

    def test_stopped_task_is_started_and_polled(self):
        runner = FakeRunner(
            [
                (0, status(("entrypoints/designer/client", "stopped", "down"))),
                (0, "started"),
                (0, status(("entrypoints/designer/client", "running", "up"))),
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            result = ensure_hud_tasks.recover(
                self.repo(root),
                ["entrypoints/designer/client"],
                runner,
                wait_seconds=1,
                poll_seconds=0.1,
            )
        self.assertEqual(result["restartedTasks"], ["entrypoints/designer/client"])
        self.assertEqual(
            [call[0] for call in runner.calls],
            [
                ensure_hud_tasks.HUD_STATUS_COMMAND,
                [
                    "npm",
                    "run",
                    "--silent",
                    "hud",
                    "start",
                    "entrypoints/designer/client",
                ],
                ensure_hud_tasks.HUD_STATUS_COMMAND,
            ],
        )

    def test_running_unhealthy_task_is_stopped_then_started(self):
        runner = FakeRunner(
            [
                (0, status(("server", "running", "down"))),
                (0, "stopped"),
                (0, "started"),
                (0, status(("server", "running", "up"))),
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            ensure_hud_tasks.recover(
                self.repo(root),
                ["server"],
                runner,
                wait_seconds=1,
                poll_seconds=0.1,
            )
        self.assertEqual(
            [call[0][4] for call in runner.calls[1:3]], ["stop", "start"]
        )

    def test_missing_task_fails_closed_without_starting_any_task(self):
        runner = FakeRunner([(0, status(("server", "running", "up")))])
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(
                ensure_hud_tasks.HudRecoveryError, "not found"
            ):
                ensure_hud_tasks.recover(
                    self.repo(root),
                    ["missing"],
                    runner,
                    wait_seconds=1,
                    poll_seconds=0.1,
                )
        self.assertEqual(len(runner.calls), 1)

    def test_unhealthy_task_timeout_reports_final_status(self):
        runner = FakeRunner(
            [
                (0, status(("server", "stopped", "down"))),
                (0, "started"),
                (0, status(("server", "starting", "down"))),
            ]
        )
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(
                ensure_hud_tasks.HudRecoveryError, "deadline"
            ):
                ensure_hud_tasks.recover(
                    self.repo(root),
                    ["server"],
                    runner,
                    wait_seconds=0.01,
                    poll_seconds=0.01,
                    sleep=lambda _seconds: None,
                    monotonic=iter([0.0, 1.0]).__next__,
                )


if __name__ == "__main__":
    unittest.main()
