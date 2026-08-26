#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "reconcile_chrome_profile", SCRIPT_DIR / "reconcile-chrome-profile.py"
)
assert SPEC is not None and SPEC.loader is not None
reconcile_chrome_profile = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reconcile_chrome_profile
SPEC.loader.exec_module(reconcile_chrome_profile)


class FakeRunner:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.calls = []

    def run(self, command, *, timeout=None):
        self.calls.append((command, timeout))
        stdout = self.snapshots.pop(0) if self.snapshots else ""
        return subprocess.CompletedProcess(command, 0, stdout, "")


class ReconcileChromeProfileTests(unittest.TestCase):
    def setUp(self):
        self.original_root = reconcile_chrome_profile.ALLOWED_PROFILE_ROOT

    def tearDown(self):
        reconcile_chrome_profile.ALLOWED_PROFILE_ROOT = self.original_root

    def chrome_fixture(self, base: Path):
        app = base / "Google Chrome for Testing.app"
        main = app / "Contents/MacOS/Google Chrome for Testing"
        helper = (
            app
            / "Contents/Frameworks/Google Chrome for Testing Framework.framework"
            / "Versions/1/Helpers/Google Chrome for Testing Helper.app"
            / "Contents/MacOS/Google Chrome for Testing Helper"
        )
        main.parent.mkdir(parents=True)
        helper.parent.mkdir(parents=True)
        main.write_text("synthetic")
        helper.write_text("synthetic")
        return main, helper

    def snapshot(self, profile: Path, main: Path, helper: Path, *, active: bool):
        root_ppid = 101 if active else 1
        lines = []
        if active:
            lines.append(
                "101 1 "
                + shlex.join(["/opt/agent-browser/bin/agent-browser-darwin-arm64"])
            )
        lines.extend(
            [
                f"200 {root_ppid} "
                + shlex.join(
                    [str(main), f"--user-data-dir={profile}"]
                ),
                "201 200 "
                + shlex.join(
                    [str(helper), f"--user-data-dir={profile}"]
                ),
            ]
        )
        return "\n".join(lines) + "\n"

    def test_process_snapshot_parser_ignores_malformed_lines(self):
        result = reconcile_chrome_profile.parse_process_snapshot(
            "bad\n200 1 /path/chrome --flag\n201 x malformed\n"
        )
        self.assertEqual(
            result,
            [reconcile_chrome_profile.ProcessInfo(200, 1, "/path/chrome --flag")],
        )

    def test_active_profile_is_never_terminated(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            allowed = base / "profiles"
            profile = allowed / "designer-load"
            profile.mkdir(parents=True)
            main, helper = self.chrome_fixture(base)
            reconcile_chrome_profile.ALLOWED_PROFILE_ROOT = allowed
            runner = FakeRunner([self.snapshot(profile, main, helper, active=True)])
            result = reconcile_chrome_profile.reconcile(
                profile,
                runner,
                verifier=lambda _path: True,
                confirm=True,
                kill=lambda *_args: self.fail("active browser was terminated"),
            )
        self.assertEqual(result["status"], "active")

    def test_orphan_requires_confirmation_before_termination(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            allowed = base / "profiles"
            profile = allowed / "designer-load"
            profile.mkdir(parents=True)
            main, helper = self.chrome_fixture(base)
            reconcile_chrome_profile.ALLOWED_PROFILE_ROOT = allowed
            runner = FakeRunner([self.snapshot(profile, main, helper, active=False)])
            result = reconcile_chrome_profile.reconcile(
                profile,
                runner,
                verifier=lambda _path: True,
            )
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["orphanedPids"], [200, 201])
        self.assertEqual(len(runner.calls), 1)

    def test_confirmed_orphan_tree_is_stopped_and_locks_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            allowed = base / "profiles"
            profile = allowed / "designer-load"
            profile.mkdir(parents=True)
            main, helper = self.chrome_fixture(base)
            for name in reconcile_chrome_profile.PROFILE_LOCK_NAMES:
                (profile / name).symlink_to("stale-lock")
            reconcile_chrome_profile.ALLOWED_PROFILE_ROOT = allowed
            orphan = self.snapshot(profile, main, helper, active=False)
            runner = FakeRunner([orphan, "", ""])
            killed = []
            result = reconcile_chrome_profile.reconcile(
                profile,
                runner,
                verifier=lambda _path: True,
                confirm=True,
                sleep=lambda _seconds: None,
                monotonic=iter([0.0, 3.0]).__next__,
                kill=lambda pid, signal_value: killed.append((pid, signal_value)),
            )
            self.assertFalse(any((profile / name).exists() for name in reconcile_chrome_profile.PROFILE_LOCK_NAMES))
        self.assertEqual(result["status"], "recovered")
        self.assertEqual(result["orphanedPids"], [200, 201])
        self.assertEqual([pid for pid, _signal in killed], [201, 200])

    def test_unknown_profile_owner_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            allowed = base / "profiles"
            profile = allowed / "designer-load"
            profile.mkdir(parents=True)
            reconcile_chrome_profile.ALLOWED_PROFILE_ROOT = allowed
            runner = FakeRunner(
                [
                    "300 1 "
                    + shlex.join(
                        ["/tmp/Other Browser", f"--user-data-dir={profile}"]
                    )
                ]
            )
            with self.assertRaisesRegex(
                reconcile_chrome_profile.ProfileRecoveryError, "non-Chrome"
            ):
                reconcile_chrome_profile.reconcile(profile, runner, confirm=True)

    def test_profile_outside_dedicated_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            reconcile_chrome_profile.ALLOWED_PROFILE_ROOT = base / "profiles"
            with self.assertRaisesRegex(
                reconcile_chrome_profile.ProfileRecoveryError, "dedicated"
            ):
                reconcile_chrome_profile.reconcile(base / "elsewhere", FakeRunner([]))


if __name__ == "__main__":
    unittest.main()
