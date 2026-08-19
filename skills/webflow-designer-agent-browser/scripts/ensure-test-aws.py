#!/usr/bin/env python3
"""Deterministically repair AWS credentials used by local Designer tests."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Protocol

AWS_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
PROFILE = "dev-publish-only"
SSO_SESSION = "wf-session"
SERVER_PROCESS = "wf-app"
SERVER_TASK = "server"
DEFAULT_STATE_PATH = (
    Path.home()
    / ".config"
    / "webflow-designer-agent-browser"
    / "aws-server-credentials.json"
)


class CommandRunner(Protocol):
    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


class SubprocessRunner:
    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
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


class AwsRepairError(RuntimeError):
    """A deterministic credential repair step failed."""


def without_aws_credentials(environment: dict[str, str]) -> dict[str, str]:
    clean = environment.copy()
    for key in (*AWS_KEYS, "AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        clean.pop(key, None)
    return clean


def profile_is_valid(runner: CommandRunner, environment: dict[str, str]) -> bool:
    result = runner.run(
        ["aws", "sts", "get-caller-identity", "--profile", PROFILE],
        env=without_aws_credentials(environment),
    )
    return result.returncode == 0


def ensure_profile(runner: CommandRunner, environment: dict[str, str]) -> bool:
    if profile_is_valid(runner, environment):
        return False
    login = runner.run(
        ["aws", "sso", "login", "--sso-session", SSO_SESSION],
        env=without_aws_credentials(environment),
    )
    if login.returncode != 0 or not profile_is_valid(runner, environment):
        raise AwsRepairError("AWS SSO login did not produce valid dev-publish-only credentials")
    return True


def server_pids(runner: CommandRunner) -> list[int]:
    result = runner.run(["pgrep", "-x", SERVER_PROCESS])
    if result.returncode == 1:
        return []
    if result.returncode != 0:
        raise AwsRepairError("unable to inspect the local Webflow server process")
    try:
        return [int(value) for value in result.stdout.split()]
    except ValueError as error:
        raise AwsRepairError("local Webflow server returned an invalid process id") from error


def process_credentials(runner: CommandRunner, pid: int) -> dict[str, str] | None:
    visited = set()
    for _ in range(8):
        if pid <= 1 or pid in visited:
            return None
        visited.add(pid)
        result = runner.run(["ps", "eww", "-p", str(pid), "-o", "command="])
        if result.returncode != 0:
            return None
        credentials: dict[str, str] = {}
        for key in AWS_KEYS:
            match = re.search(rf"(?:^|\s){key}=([^\s]+)", result.stdout)
            if match is not None:
                credentials[key] = match.group(1)
        if len(credentials) == len(AWS_KEYS):
            return credentials
        parent = runner.run(["ps", "-p", str(pid), "-o", "ppid="])
        if parent.returncode != 0:
            return None
        try:
            pid = int(parent.stdout.strip())
        except ValueError:
            return None
    return None


def process_credentials_are_valid(
    runner: CommandRunner, credentials: dict[str, str], environment: dict[str, str]
) -> bool:
    credential_environment = without_aws_credentials(environment)
    credential_environment.update(credentials)
    result = runner.run(
        ["aws", "sts", "get-caller-identity"], env=credential_environment
    )
    return result.returncode == 0


def wait_for_started_server(
    runner: CommandRunner, *, attempts: int = 24, sleep=time.sleep
) -> list[int]:
    for attempt in range(attempts):
        pids = server_pids(runner)
        if pids:
            return pids
        if attempt + 1 < attempts:
            sleep(5)
    raise AwsRepairError(
        f"the restarted {SERVER_TASK} task did not start a {SERVER_PROCESS} process"
    )


def wait_for_stopped_server(
    runner: CommandRunner, *, attempts: int = 12, sleep=time.sleep
) -> None:
    for attempt in range(attempts):
        if not server_pids(runner):
            return
        if attempt + 1 < attempts:
            sleep(5)
    raise AwsRepairError(f"the {SERVER_TASK} HUD task did not stop")


def profile_expiration_epoch(runner: CommandRunner, environment: dict[str, str]) -> int:
    result = runner.run(
        [
            "aws",
            "configure",
            "export-credentials",
            "--profile",
            PROFILE,
            "--format",
            "process",
        ],
        env=without_aws_credentials(environment),
    )
    if result.returncode != 0:
        raise AwsRepairError("unable to read the dev-publish-only credential expiration")
    try:
        expiration = json.loads(result.stdout)["Expiration"]
        parsed = datetime.datetime.fromisoformat(expiration.replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise AwsRepairError("AWS returned an invalid credential expiration") from error
    return int(parsed.timestamp())


def receipt_is_valid(path: Path, pids: list[int], now: int | None = None) -> bool:
    try:
        receipt = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    current_time = int(time.time()) if now is None else now
    return (
        receipt.get("serverPids") == pids
        and isinstance(receipt.get("credentialExpirationEpoch"), int)
        and receipt["credentialExpirationEpoch"] > current_time + 300
    )


def write_receipt(path: Path, pids: list[int], expiration_epoch: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "serverPids": pids,
                "credentialExpirationEpoch": expiration_epoch,
            },
            sort_keys=True,
        )
        + "\n"
    )
    path.chmod(0o600)


def repair(
    repo: Path,
    runner: CommandRunner,
    environment: dict[str, str],
    state_path: Path = DEFAULT_STATE_PATH,
) -> dict[str, object]:
    if not (repo / "bin" / "run-with-aws").is_file():
        raise AwsRepairError("--repo must point to the Webflow monorepo")

    pids = server_pids(runner)
    stale_pids = []
    receipt_valid = receipt_is_valid(state_path, pids)
    if not receipt_valid:
        for pid in pids:
            credentials = process_credentials(runner, pid)
            if credentials is None or not process_credentials_are_valid(
                runner, credentials, environment
            ):
                stale_pids.append(pid)

    restarted = bool(stale_pids)
    started = not pids
    logged_in = False
    if restarted or started:
        logged_in = ensure_profile(runner, environment)
    if restarted:
        stop = runner.run(
            ["npm", "run", "hud", "stop", SERVER_TASK], cwd=repo, timeout=15
        )
        if stop.returncode not in (0, 124):
            raise AwsRepairError(f"unable to stop the {SERVER_TASK} HUD task")
        wait_for_stopped_server(runner)
        start = runner.run(
            ["npm", "run", "hud", "start", SERVER_TASK], cwd=repo, timeout=15
        )
        if start.returncode not in (0, 124):
            raise AwsRepairError(f"unable to start the {SERVER_TASK} HUD task")
        new_pids = wait_for_started_server(runner)
        expiration_epoch = profile_expiration_epoch(runner, environment)
        write_receipt(state_path, new_pids, expiration_epoch)
    elif started:
        start = runner.run(
            ["npm", "run", "hud", "start", SERVER_TASK], cwd=repo, timeout=15
        )
        if start.returncode not in (0, 124):
            raise AwsRepairError(f"unable to start the {SERVER_TASK} HUD task")
        new_pids = wait_for_started_server(runner)
        expiration_epoch = profile_expiration_epoch(runner, environment)
        write_receipt(state_path, new_pids, expiration_epoch)

    return {
        "status": "ready",
        "profile": PROFILE,
        "ssoSession": SSO_SESSION,
        "loginRefreshed": logged_in,
        "runningServerProcesses": len(pids),
        "staleServerProcesses": len(stale_pids),
        "serverRestarted": restarted,
        "serverStarted": started,
        "restartReceiptValid": receipt_valid,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = repair(args.repo.resolve(), SubprocessRunner(), dict(os.environ))
    except AwsRepairError as error:
        print(json.dumps({"status": "blocked", "error": str(error)}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
