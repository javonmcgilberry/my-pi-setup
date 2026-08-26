#!/usr/bin/env python3
"""Restart selected unhealthy Webflow HUD tasks and wait for healthy status."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Protocol

HUD_STATUS_COMMAND = [
    "npm",
    "run",
    "--silent",
    "hud",
    "getTaskStatus",
    "--",
    "--json",
]
READY_STATES = {"running", "exited"}
MAX_WAIT_SECONDS = 300.0
MAX_TASK_NAME_LENGTH = 200


class CommandRunner(Protocol):
    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunner:
    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            stdout, stderr = process.communicate()
            return subprocess.CompletedProcess(command, 124, stdout, stderr)


class HudRecoveryError(RuntimeError):
    """A bounded HUD status or task recovery step failed."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def validate_task_names(task_names: list[str]) -> list[str]:
    if not task_names:
        raise HudRecoveryError("tasks_required", "at least one HUD task is required")
    if len(set(task_names)) != len(task_names):
        raise HudRecoveryError("duplicate_task", "HUD tasks must not contain duplicates")
    for task_name in task_names:
        if (
            not task_name
            or len(task_name) > MAX_TASK_NAME_LENGTH
            or "\n" in task_name
            or "\r" in task_name
        ):
            raise HudRecoveryError("invalid_task", "HUD task name is invalid")
    return task_names


def parse_task_status(stdout: str) -> list[dict[str, str]]:
    start = stdout.find("[")
    end = stdout.rfind("]")
    if start < 0 or end < start:
        raise HudRecoveryError(
            "hud_status_invalid", "HUD task status did not contain JSON"
        )
    try:
        value = json.loads(stdout[start : end + 1])
    except json.JSONDecodeError as error:
        raise HudRecoveryError("hud_status_invalid", "HUD task status JSON was invalid") from error
    if not isinstance(value, list):
        raise HudRecoveryError("hud_status_invalid", "HUD task status was not a list")

    tasks: list[dict[str, str]] = []
    for task in value:
        if not isinstance(task, dict):
            raise HudRecoveryError("hud_status_invalid", "HUD task status had an invalid shape")
        name = task.get("taskName")
        state = task.get("state")
        health = task.get("health")
        if not all(isinstance(item, str) and item for item in (name, state, health)):
            raise HudRecoveryError("hud_status_invalid", "HUD task status had an invalid shape")
        tasks.append({"taskName": name, "state": state, "health": health})
    return tasks


def get_task_status(repo: Path, runner: CommandRunner) -> list[dict[str, str]]:
    completed = runner.run(HUD_STATUS_COMMAND.copy(), cwd=repo, timeout=15)
    if completed.returncode != 0:
        raise HudRecoveryError(
            "hud_status_failed",
            "HUD task status command failed",
            {"exitCode": completed.returncode},
        )
    return parse_task_status(completed.stdout)


def select_tasks(
    tasks: list[dict[str, str]], task_names: list[str]
) -> list[dict[str, str]]:
    by_name = {task["taskName"]: task for task in tasks}
    missing = [name for name in task_names if name not in by_name]
    if missing:
        raise HudRecoveryError(
            "hud_task_missing",
            "configured HUD tasks were not found",
            {"missing": missing},
        )
    return [by_name[name].copy() for name in task_names]


def task_is_healthy(task: dict[str, str]) -> bool:
    # HUD reports meta-tasks such as `designer` as exited/up because their
    # `true` command is complete while their dependency health remains good.
    return task["health"] == "up" and task["state"] in READY_STATES


def unhealthy_tasks(tasks: list[dict[str, str]]) -> list[dict[str, str]]:
    return [task for task in tasks if not task_is_healthy(task)]


def run_task_command(
    repo: Path,
    task_name: str,
    action: str,
    runner: CommandRunner,
) -> None:
    completed = runner.run(
        ["npm", "run", "--silent", "hud", action, task_name],
        cwd=repo,
        timeout=30,
    )
    if completed.returncode != 0:
        raise HudRecoveryError(
            "hud_task_recovery_failed",
            f"HUD task {action} command failed",
            {"task": task_name, "action": action, "exitCode": completed.returncode},
        )


def wait_for_healthy_tasks(
    repo: Path,
    task_names: list[str],
    runner: CommandRunner,
    *,
    wait_seconds: float,
    poll_seconds: float,
    sleep=time.sleep,
    monotonic=time.monotonic,
) -> list[dict[str, str]]:
    deadline = monotonic() + wait_seconds
    last: list[dict[str, str]] = []
    while True:
        last = select_tasks(get_task_status(repo, runner), task_names)
        if not unhealthy_tasks(last):
            return last
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(poll_seconds, remaining))
    raise HudRecoveryError(
        "hud_task_not_ready",
        "configured HUD tasks did not become healthy before the recovery deadline",
        {"tasks": last},
    )


def recover(
    repo: Path,
    task_names: list[str],
    runner: CommandRunner,
    *,
    wait_seconds: float = 120.0,
    poll_seconds: float = 2.0,
    sleep=time.sleep,
    monotonic=time.monotonic,
) -> dict[str, object]:
    if not repo.is_dir() or not (repo / "package.json").is_file():
        raise HudRecoveryError("repo_invalid", "--repo must point to the Webflow monorepo")
    validate_task_names(task_names)
    if wait_seconds <= 0 or wait_seconds > MAX_WAIT_SECONDS:
        raise HudRecoveryError("invalid_wait", "wait time is outside the supported range")
    if poll_seconds <= 0 or poll_seconds > wait_seconds:
        raise HudRecoveryError("invalid_poll", "poll interval is outside the supported range")

    initial = select_tasks(get_task_status(repo, runner), task_names)
    to_restart = unhealthy_tasks(initial)
    restarted: list[str] = []
    for task in to_restart:
        task_name = task["taskName"]
        # HUD's start request is a no-op for a running task. Stop it first so
        # a running/down client is actually rerun, while stopped/exited tasks
        # are started directly. No umbrella or unrelated task is touched.
        if task["state"] == "running":
            run_task_command(repo, task_name, "stop", runner)
        run_task_command(repo, task_name, "start", runner)
        restarted.append(task_name)

    final = wait_for_healthy_tasks(
        repo,
        task_names,
        runner,
        wait_seconds=wait_seconds,
        poll_seconds=poll_seconds,
        sleep=sleep,
        monotonic=monotonic,
    )
    return {
        "status": "ready",
        "recoveryAttempted": bool(restarted),
        "restartedTasks": restarted,
        "initialTasks": initial,
        "tasks": final,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("ensure",))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--task", dest="tasks", action="append", required=True)
    parser.add_argument("--wait-seconds", type=float, default=120.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = recover(
            args.repo.resolve(),
            args.tasks,
            SubprocessRunner(),
            wait_seconds=args.wait_seconds,
            poll_seconds=args.poll_seconds,
        )
    except HudRecoveryError as error:
        error_result: dict[str, object] = {
            "code": error.code,
            "message": str(error),
        }
        if error.details is not None:
            error_result["details"] = error.details
        result: dict[str, object] = {"status": "blocked", "error": error_result}
        print(json.dumps(result, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
