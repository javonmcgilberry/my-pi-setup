#!/usr/bin/env python3
"""Classify and clean orphaned Chrome for Testing processes for one profile."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

ALLOWED_PROFILE_ROOT = (
    Path.home() / ".config" / "webflow-designer-agent-browser" / "profiles"
)
PROFILE_LOCK_NAMES = ("SingletonLock", "SingletonSocket", "SingletonCookie")
PS_COMMAND = ["/bin/ps", "-axo", "pid=,ppid=,command="]


class CommandRunner(Protocol):
    def run(
        self,
        command: list[str],
        *,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunner:
    def run(
        self,
        command: list[str],
        *,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )


class ProfileRecoveryError(RuntimeError):
    """The profile owner could not be verified or cleanup could not finish."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    ppid: int
    command: str

    @property
    def arguments(self) -> list[str] | None:
        try:
            return shlex.split(self.command)
        except ValueError:
            return None


def parse_process_snapshot(stdout: str) -> list[ProcessInfo]:
    processes: list[ProcessInfo] = []
    for line in stdout.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3:
            continue
        try:
            pid, ppid = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        if pid > 1 and ppid >= 0:
            processes.append(ProcessInfo(pid, ppid, fields[2]))
    return processes


def process_snapshot(runner: CommandRunner) -> list[ProcessInfo]:
    try:
        completed = runner.run(PS_COMMAND.copy(), timeout=3)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProfileRecoveryError(
            "process_snapshot_failed", "could not inspect local browser processes"
        ) from error
    if completed.returncode != 0:
        raise ProfileRecoveryError(
            "process_snapshot_failed", "could not inspect local browser processes"
        )
    return parse_process_snapshot(completed.stdout)


def validate_profile(profile: Path) -> Path:
    if profile.expanduser().is_symlink():
        raise ProfileRecoveryError(
            "profile_symlink", "profile must not be a symbolic link"
        )
    resolved = profile.expanduser().resolve(strict=False)
    allowed = ALLOWED_PROFILE_ROOT.expanduser().resolve(strict=False)
    try:
        resolved.relative_to(allowed)
    except ValueError as error:
        raise ProfileRecoveryError(
            "profile_outside_dedicated_root",
            "profile must be inside the dedicated Chrome-for-Testing profile root",
        ) from error
    if resolved == allowed:
        raise ProfileRecoveryError(
            "profile_invalid", "profile must name a dedicated profile directory"
        )
    return resolved


def user_data_dir(arguments: list[str] | None) -> Path | None:
    if not arguments:
        return None
    for index, argument in enumerate(arguments):
        if argument.startswith("--user-data-dir="):
            return Path(argument.partition("=")[2]).expanduser().resolve(strict=False)
        if argument == "--user-data-dir" and index + 1 < len(arguments):
            return Path(arguments[index + 1]).expanduser().resolve(strict=False)
    return None


def is_verified_chrome_for_testing(executable: str) -> bool:
    try:
        resolved = Path(executable).resolve(strict=True)
        app_bundle = resolved.parents[2]
        if (
            resolved.name != "Google Chrome for Testing"
            or app_bundle.name != "Google Chrome for Testing.app"
        ):
            return False
        with (app_bundle / "Contents/Info.plist").open("rb") as file:
            metadata = plistlib.load(file)
    except (IndexError, OSError, plistlib.InvalidFileException):
        return False
    return (
        metadata.get("CFBundleIdentifier") == "com.google.chrome.for.testing"
        and metadata.get("CFBundleExecutable") == "Google Chrome for Testing"
    )


def is_verified_chrome_for_testing_process(
    executable: str,
    *,
    verifier: Callable[[str], bool] = is_verified_chrome_for_testing,
) -> bool:
    try:
        resolved = Path(executable).resolve(strict=True)
        app_bundle = next(
            parent
            for parent in (resolved, *resolved.parents)
            if parent.name == "Google Chrome for Testing.app"
        )
    except (OSError, StopIteration):
        return False
    return verifier(
        str(app_bundle / "Contents/MacOS/Google Chrome for Testing")
    )


def profile_processes(
    profile: Path,
    processes: list[ProcessInfo],
    *,
    verifier: Callable[[str], bool] = is_verified_chrome_for_testing,
) -> tuple[list[ProcessInfo], list[ProcessInfo], list[ProcessInfo]]:
    matching: list[ProcessInfo] = []
    roots: list[ProcessInfo] = []
    unknown: list[ProcessInfo] = []
    for process in processes:
        arguments = process.arguments
        if user_data_dir(arguments) != profile:
            continue
        matching.append(process)
        if arguments and is_verified_chrome_for_testing_process(
            arguments[0], verifier=verifier
        ):
            if Path(arguments[0]).name == "Google Chrome for Testing":
                roots.append(process)
        else:
            unknown.append(process)
    return matching, roots, unknown


def descendants(
    roots: list[ProcessInfo], processes: list[ProcessInfo]
) -> list[ProcessInfo]:
    by_parent: dict[int, list[ProcessInfo]] = {}
    for process in processes:
        by_parent.setdefault(process.ppid, []).append(process)
    result: dict[int, ProcessInfo] = {process.pid: process for process in roots}
    pending = list(result)
    while pending:
        parent = pending.pop()
        for child in by_parent.get(parent, []):
            if child.pid not in result:
                result[child.pid] = child
                pending.append(child.pid)
    return list(result.values())


def has_live_parent(process: ProcessInfo, by_pid: dict[int, ProcessInfo]) -> bool:
    # Chrome launched by agent-browser is parented by its long-lived daemon.
    # A root reparented to PID 1 after that owner dies is the orphan case.
    return process.ppid != 1 and process.ppid in by_pid


def remove_stale_locks(profile: Path) -> list[str]:
    removed: list[str] = []
    for name in PROFILE_LOCK_NAMES:
        candidate = profile / name
        if not candidate.is_symlink():
            continue
        try:
            candidate.unlink()
        except OSError as error:
            raise ProfileRecoveryError(
                "profile_lock_cleanup_failed", "could not remove a stale profile lock"
            ) from error
        removed.append(name)
    return removed


def current_profile_roots(
    profile: Path,
    runner: CommandRunner,
    *,
    verifier: Callable[[str], bool] = is_verified_chrome_for_testing,
) -> tuple[list[ProcessInfo], list[ProcessInfo], list[ProcessInfo]]:
    return profile_processes(profile, process_snapshot(runner), verifier=verifier)


def terminate_processes(
    profile: Path,
    targets: list[ProcessInfo],
    runner: CommandRunner,
    *,
    verifier: Callable[[str], bool] = is_verified_chrome_for_testing,
    grace_seconds: float = 2.0,
    sleep=time.sleep,
    monotonic=time.monotonic,
    kill=os.kill,
) -> list[int]:
    target_pids = {process.pid for process in targets}
    for process in sorted(targets, key=lambda item: item.pid, reverse=True):
        try:
            kill(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError as error:
            raise ProfileRecoveryError(
                "profile_process_cleanup_denied", "could not stop an orphaned browser process"
            ) from error

    deadline = monotonic() + grace_seconds
    remaining: list[ProcessInfo] = []
    while True:
        matching, roots, unknown = current_profile_roots(
            profile, runner, verifier=verifier
        )
        if unknown:
            raise ProfileRecoveryError(
                "profile_owner_unknown",
                "a non-Chrome-for-Testing process still owns the dedicated profile",
            )
        remaining = [process for process in matching if process.pid in target_pids]
        if not remaining or monotonic() >= deadline:
            break
        sleep(min(0.1, max(0.0, deadline - monotonic())))

    if remaining:
        for process in remaining:
            try:
                kill(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError as error:
                raise ProfileRecoveryError(
                    "profile_process_cleanup_denied", "could not force-stop an orphaned browser process"
                ) from error
        matching, _roots, unknown = current_profile_roots(
            profile, runner, verifier=verifier
        )
        if unknown or any(process.pid in target_pids for process in matching):
            raise ProfileRecoveryError(
                "profile_process_cleanup_incomplete",
                "orphaned browser processes did not stop",
            )
    return sorted(target_pids)


def reconcile(
    profile: Path,
    runner: CommandRunner,
    *,
    confirm: bool = False,
    verifier: Callable[[str], bool] = is_verified_chrome_for_testing,
    grace_seconds: float = 2.0,
    sleep=time.sleep,
    monotonic=time.monotonic,
    kill=os.kill,
) -> dict[str, object]:
    profile = validate_profile(profile)
    processes = process_snapshot(runner)
    matching, roots, unknown = profile_processes(
        profile, processes, verifier=verifier
    )
    if unknown:
        raise ProfileRecoveryError(
            "profile_owner_unknown",
            "a non-Chrome-for-Testing process owns the dedicated profile",
        )
    if not roots:
        return {
            "status": "clean",
            "profileProcessCount": len(matching),
            "orphanedPids": [],
        }

    by_pid = {process.pid: process for process in processes}
    active_roots = [root for root in roots if has_live_parent(root, by_pid)]
    if active_roots:
        return {
            "status": "active",
            "profileProcessCount": len(matching),
            "orphanedPids": [],
        }

    targets = descendants(roots, matching)
    if not confirm:
        return {
            "status": "stale",
            "profileProcessCount": len(matching),
            "orphanedPids": sorted(process.pid for process in targets),
            "confirmationRequired": True,
        }

    terminated = terminate_processes(
        profile,
        targets,
        runner,
        verifier=verifier,
        grace_seconds=grace_seconds,
        sleep=sleep,
        monotonic=monotonic,
        kill=kill,
    )
    removed_locks = remove_stale_locks(profile)
    matching_after, roots_after, unknown_after = current_profile_roots(
        profile, runner, verifier=verifier
    )
    if unknown_after or roots_after:
        raise ProfileRecoveryError(
            "profile_process_cleanup_incomplete",
            "dedicated Chrome-for-Testing profile is still owned after cleanup",
        )
    return {
        "status": "recovered",
        "profileProcessCount": len(matching_after),
        "orphanedPids": terminated,
        "removedLocks": removed_locks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("reconcile",))
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--confirm", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = reconcile(args.profile, SubprocessRunner(), confirm=args.confirm)
    except ProfileRecoveryError as error:
        error_result: dict[str, object] = {
            "code": error.code,
            "message": str(error),
        }
        if error.details is not None:
            error_result["details"] = error.details
        result: dict[str, object] = {"status": "blocked", "error": error_result}
        print(json.dumps(result, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
