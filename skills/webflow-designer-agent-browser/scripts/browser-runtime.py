#!/usr/bin/env python3
"""Own the dedicated Chrome profile and direct-CDP runtime for Designer work."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path.home() / ".config" / "webflow-designer-agent-browser"
DEFAULT_SOURCE_ROOT = Path.home() / "Library/Application Support/Google/Chrome"
DEFAULT_MAX_RUNTIME_SECONDS = 1800
MAX_RUNTIME_SECONDS = 14400
CONSUMERS = {"agent_browser", "chrome_devtools_mcp"}
SENSITIVE_PROFILE_DATABASES = {
    "Cookies",
    "Local State",
    "Login Data",
    "Web Data",
}
TRANSIENT_NAMES = {
    "Cache",
    "Code Cache",
    "Crashpad",
    "DawnCache",
    "DevToolsActivePort",
    "GPUCache",
    "GrShaderCache",
    "RunningChromeVersion",
    "ShaderCache",
    "Cookies",
    "Cookies-journal",
    "Login Data",
    "Login Data-journal",
    "Web Data",
    "Web Data-journal",
}


def discover_automation_chrome() -> Path:
    """Select the newest installed Chrome for Testing without a Chrome fallback."""
    root = Path.home() / ".cache/puppeteer/chrome"
    candidates = list(
        root.glob(
            "mac_arm-*/chrome-mac-arm64/Google Chrome for Testing.app/"
            "Contents/MacOS/Google Chrome for Testing"
        )
    )

    def version(path: Path) -> tuple[int, ...]:
        try:
            return tuple(
                int(part)
                for part in path.parents[4]
                .name.removeprefix("mac_arm-")
                .split(".")
            )
        except (IndexError, ValueError):
            return ()

    available = [path for path in candidates if path.is_file()]
    if not available:
        return root / "chrome-for-testing-not-installed"
    return max(available, key=version)


class RuntimeFailure(Exception):
    def __init__(self, code: str, phase: str, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.phase = phase
        self.retryable = retryable


@dataclass(frozen=True)
class RuntimeConfig:
    root: Path
    source_root: Path
    source_profile: str
    chrome: Path
    host: str
    port: int

    @property
    def profile_root(self) -> Path:
        return self.root / "chrome-user-data"

    @property
    def runtime_path(self) -> Path:
        return self.root / "runtime.json"

    @property
    def lease_path(self) -> Path:
        return self.root / "consumer-lease.json"

    @property
    def origin_path(self) -> Path:
        return self.root / "profile-origin.json"


def validate_config(config: RuntimeConfig) -> RuntimeConfig:
    if config.host != "127.0.0.1":
        raise RuntimeFailure("loopback_required", "configuration", False)
    if isinstance(config.port, bool) or not 1 <= config.port <= 65535:
        raise RuntimeFailure("invalid_port", "configuration", False)
    if (
        not config.source_profile
        or config.source_profile in {".", ".."}
        or "/" in config.source_profile
        or "\\" in config.source_profile
    ):
        raise RuntimeFailure("invalid_source_profile", "configuration", False)
    if config.profile_root.is_symlink():
        raise RuntimeFailure("unsafe_profile_root", "configuration", False)
    return config


def ensure_private_root(root: Path) -> None:
    if root.is_symlink():
        raise RuntimeFailure("unsafe_state_root", "configuration", False)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)


def write_private_json(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(value, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeFailure("state_unreadable", "state", False) from error
    if not isinstance(value, dict):
        raise RuntimeFailure("state_unreadable", "state", False)
    return value


def pid_alive(pid: object) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def process_matches_runtime(pid: object, config: RuntimeConfig) -> bool:
    if not pid_alive(pid):
        return False
    completed = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    command = completed.stdout.strip()
    return (
        completed.returncode == 0
        and str(config.chrome) in command
        and f"--user-data-dir={config.profile_root}" in command
    )


def process_matches_watchdog(pid: object) -> bool:
    if not pid_alive(pid):
        return False
    completed = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    command = completed.stdout.strip()
    return (
        completed.returncode == 0
        and str(Path(__file__).resolve()) in command
        and "_watchdog" in command
    )


def port_open(host: str, port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def cdp_ready(config: RuntimeConfig, timeout: float = 2.0) -> bool:
    request = urllib.request.Request(
        f"http://{config.host}:{config.port}/json/version",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read(65536))
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return False
    return (
        isinstance(value, dict)
        and isinstance(value.get("Browser"), str)
        and isinstance(value.get("webSocketDebuggerUrl"), str)
    )


def browser_kind(config: RuntimeConfig) -> str:
    return (
        "chrome_for_testing"
        if config.chrome.name == "Google Chrome for Testing"
        else "unsupported_browser"
    )


def is_verified_chrome_for_testing(executable: Path) -> bool:
    try:
        resolved = executable.resolve(strict=True)
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
        and metadata.get("CFBundleExecutable")
        == "Google Chrome for Testing"
    )


def terminate_owned_runtime(
    pid: int,
    config: RuntimeConfig,
    *,
    graceful_timeout: float = 5.0,
) -> None:
    def group_alive() -> bool:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return False
        return True

    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + graceful_timeout
    while time.monotonic() < deadline:
        if not group_alive() and not port_open(config.host, config.port):
            return
        time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not group_alive() and not port_open(config.host, config.port):
            return
        time.sleep(0.1)
    raise RuntimeFailure("runtime_cleanup_incomplete", "runtime_stop", True)


def build_chrome_launch_plan(
    config: RuntimeConfig, *, headless: bool = True
) -> list[str]:
    validate_config(config)
    plan = [
        str(config.chrome),
        f"--user-data-dir={config.profile_root}",
        "--profile-directory=Default",
        f"--remote-debugging-address={config.host}",
        f"--remote-debugging-port={config.port}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if headless:
        plan.extend(("--headless=new", "--window-size=1440,1000"))
    return plan


def source_locked(config: RuntimeConfig) -> bool:
    return any(
        (config.source_root / name).exists()
        or (config.source_root / name).is_symlink()
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie")
    )


def copy_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if (
            name in TRANSIENT_NAMES
            or any(
                name == database or name.startswith(f"{database}-")
                for database in SENSITIVE_PROFILE_DATABASES
            )
            or name.startswith("Singleton")
            or name.endswith("-journal")
            or name.endswith(".tmp")
        ):
            ignored.add(name)
    return ignored


def resolved_source_profile(config: RuntimeConfig) -> Path:
    source_root = config.source_root.resolve()
    source_profile = (source_root / config.source_profile).resolve()
    if source_profile.parent != source_root:
        raise RuntimeFailure("invalid_source_profile", "configuration", False)
    return source_profile


def reject_source_profile_symlinks(source_profile: Path) -> None:
    def raise_walk_error(error: OSError) -> None:
        raise error

    try:
        for directory, directories, files in os.walk(
            source_profile,
            followlinks=False,
            onerror=raise_walk_error,
        ):
            root = Path(directory)
            for name in (*directories, *files):
                if (root / name).is_symlink():
                    raise RuntimeFailure(
                        "source_profile_symlink",
                        "profile_bootstrap",
                        False,
                    )
    except OSError as error:
        raise RuntimeFailure(
            "source_profile_unreadable",
            "profile_bootstrap",
            False,
        ) from error


def bootstrap_profile(config: RuntimeConfig, *, replace: bool) -> dict[str, object]:
    validate_config(config)
    ensure_private_root(config.root)
    if source_locked(config):
        raise RuntimeFailure("source_profile_locked", "profile_bootstrap", True)
    source_profile = resolved_source_profile(config)
    if not source_profile.is_dir():
        raise RuntimeFailure("source_profile_unavailable", "profile_bootstrap", False)
    reject_source_profile_symlinks(source_profile)
    if config.profile_root.exists():
        if not replace:
            raise RuntimeFailure("profile_already_initialized", "profile_bootstrap", False)
        if read_json(config.runtime_path) is not None:
            raise RuntimeFailure("runtime_must_be_stopped", "profile_bootstrap", True)
        shutil.rmtree(config.profile_root)
    config.profile_root.mkdir(mode=0o700)
    try:
        shutil.copytree(
            source_profile,
            config.profile_root / "Default",
            ignore=copy_ignore,
        )
    except (OSError, shutil.Error) as error:
        shutil.rmtree(config.profile_root, ignore_errors=True)
        raise RuntimeFailure(
            "profile_copy_failed", "profile_bootstrap", True
        ) from error
    write_private_json(
        config.origin_path,
        {
            "version": 1,
            "sourceProfile": config.source_profile,
            "snapshotCreatedAt": int(time.time()),
            "refreshPolicy": "manual_login_only",
        },
    )
    return {
        "status": "succeeded",
        "classification": "profile_initialized",
        "sourceProfile": config.source_profile,
        "refreshPolicy": "manual_login_only",
    }


def inspect_runtime(config: RuntimeConfig) -> dict[str, object]:
    validate_config(config)
    runtime = read_json(config.runtime_path)
    lease = read_json(config.lease_path)
    runtime_pid = runtime.get("pid") if runtime else None
    alive = process_matches_runtime(runtime_pid, config)
    ready = cdp_ready(config) if alive else False
    consumer = lease.get("consumer") if lease else None
    return {
        "status": "ready" if ready else "unhealthy" if alive else "stopped",
        "profileInitialized": (config.profile_root / "Default").is_dir(),
        "runtimeOwned": alive,
        "cdpReady": ready,
        "mode": runtime.get("mode") if alive and runtime else None,
        "expiresAt": runtime.get("expiresAt") if alive and runtime else None,
        "browserKind": browser_kind(config),
        "consumer": consumer if consumer in CONSUMERS else None,
        "endpointKind": "direct_cdp",
        "host": "loopback",
        "port": config.port,
    }


def run_watchdog(
    config: RuntimeConfig,
    expected_pid: int,
    expected_started_at: int,
    delay: int,
) -> None:
    time.sleep(delay)
    runtime = read_json(config.runtime_path)
    if not runtime:
        return
    if (
        runtime.get("pid") != expected_pid
        or runtime.get("startedAt") != expected_started_at
    ):
        return
    if process_matches_runtime(expected_pid, config):
        terminate_owned_runtime(expected_pid, config)
    config.runtime_path.unlink(missing_ok=True)
    config.lease_path.unlink(missing_ok=True)


def start_runtime(
    config: RuntimeConfig,
    timeout: float,
    *,
    headless: bool = True,
    max_runtime_seconds: int = DEFAULT_MAX_RUNTIME_SECONDS,
) -> dict[str, object]:
    validate_config(config)
    if config.chrome.is_file() and not is_verified_chrome_for_testing(
        config.chrome
    ):
        raise RuntimeFailure("unsupported_browser", "runtime_start", False)
    ensure_private_root(config.root)
    current = inspect_runtime(config)
    requested_mode = "headless" if headless else "headed"
    if current["cdpReady"]:
        if current["mode"] != requested_mode:
            raise RuntimeFailure("runtime_mode_conflict", "runtime_start", True)
        return current
    if current["runtimeOwned"]:
        raise RuntimeFailure("runtime_unhealthy", "runtime_start", True)
    if port_open(config.host, config.port):
        raise RuntimeFailure("port_occupied", "runtime_start", True)
    if not (config.profile_root / "Default").is_dir():
        raise RuntimeFailure("profile_unavailable", "runtime_start", False)
    if not config.chrome.is_file():
        raise RuntimeFailure("chrome_unavailable", "runtime_start", False)
    process = subprocess.Popen(
        build_chrome_launch_plan(config, headless=headless),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    started_at = int(time.time())
    runtime_state: dict[str, object] = {
        "version": 1,
        "pid": process.pid,
        "startedAt": started_at,
        "expiresAt": started_at + max_runtime_seconds,
        "mode": requested_mode,
    }
    write_private_json(
        config.runtime_path,
        runtime_state,
    )
    watchdog = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "_watchdog",
            "--root",
            str(config.root),
            "--source-root",
            str(config.source_root),
            "--source-profile",
            config.source_profile,
            "--chrome",
            str(config.chrome),
            "--host",
            config.host,
            "--port",
            str(config.port),
            "--expected-pid",
            str(process.pid),
            "--expected-started-at",
            str(started_at),
            "--watchdog-delay",
            str(max_runtime_seconds),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    runtime_state["watchdogPid"] = watchdog.pid
    write_private_json(config.runtime_path, runtime_state)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            if process_matches_watchdog(watchdog.pid):
                os.kill(watchdog.pid, signal.SIGTERM)
            config.runtime_path.unlink(missing_ok=True)
            raise RuntimeFailure("chrome_exited", "runtime_start", True)
        if cdp_ready(config):
            return inspect_runtime(config)
        time.sleep(0.1)
    terminate_owned_runtime(process.pid, config)
    if process_matches_watchdog(watchdog.pid):
        os.kill(watchdog.pid, signal.SIGTERM)
    config.runtime_path.unlink(missing_ok=True)
    raise RuntimeFailure("cdp_readiness_timeout", "runtime_start", True)


def stop_runtime(config: RuntimeConfig) -> dict[str, object]:
    runtime = read_json(config.runtime_path)
    if runtime and pid_alive(runtime.get("pid")):
        if not process_matches_runtime(runtime.get("pid"), config):
            raise RuntimeFailure("runtime_ownership_unknown", "runtime_stop", False)
        pid = runtime["pid"]
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise RuntimeFailure("runtime_ownership_unknown", "runtime_stop", False)
        terminate_owned_runtime(pid, config)
    if runtime and process_matches_watchdog(runtime.get("watchdogPid")):
        watchdog_pid = runtime.get("watchdogPid")
        if isinstance(watchdog_pid, int) and not isinstance(watchdog_pid, bool):
            os.kill(watchdog_pid, signal.SIGTERM)
    config.runtime_path.unlink(missing_ok=True)
    config.lease_path.unlink(missing_ok=True)
    return inspect_runtime(config)


def claim_consumer(config: RuntimeConfig, consumer: str) -> dict[str, object]:
    if consumer not in CONSUMERS:
        raise RuntimeFailure("unsupported_consumer", "consumer_claim", False)
    status = inspect_runtime(config)
    if not status["cdpReady"]:
        raise RuntimeFailure("runtime_not_ready", "consumer_claim", True)
    existing = read_json(config.lease_path)
    if existing:
        if existing.get("consumer") == consumer:
            return {"status": "claimed", "consumer": consumer, "reused": True}
        raise RuntimeFailure("consumer_conflict", "consumer_claim", True)
    write_private_json(
        config.lease_path,
        {"version": 1, "consumer": consumer, "claimedAt": int(time.time())},
    )
    return {"status": "claimed", "consumer": consumer, "reused": False}


def release_consumer(config: RuntimeConfig, consumer: str) -> dict[str, object]:
    existing = read_json(config.lease_path)
    if existing and existing.get("consumer") != consumer:
        raise RuntimeFailure("consumer_mismatch", "consumer_release", False)
    runtime = stop_runtime(config)
    return {
        "status": "released_and_stopped",
        "consumer": consumer,
        "runtime": runtime,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=(
            "plan",
            "status",
            "bootstrap",
            "start",
            "stop",
            "claim",
            "release",
            "_watchdog",
        ),
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--source-profile", default="Default")
    parser.add_argument("--chrome", type=Path, default=discover_automation_chrome())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9333)
    parser.add_argument("--consumer", choices=sorted(CONSUMERS))
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--confirm-sensitive-copy", action="store_true")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--max-runtime-seconds",
        type=int,
        default=DEFAULT_MAX_RUNTIME_SECONDS,
        help="owned-runtime watchdog limit (default: 1800, maximum: 14400)",
    )
    parser.add_argument("--expected-pid", type=int)
    parser.add_argument("--expected-started-at", type=int)
    parser.add_argument("--watchdog-delay", type=int)
    parser.add_argument(
        "--headed",
        action="store_true",
        help="launch visible Chrome for login or visual debugging (start is headless by default)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = RuntimeConfig(
        root=args.root,
        source_root=args.source_root,
        source_profile=args.source_profile,
        chrome=args.chrome,
        host=args.host,
        port=args.port,
    )
    try:
        if args.command == "_watchdog":
            if not all(
                isinstance(value, int) and not isinstance(value, bool) and value > 0
                for value in (
                    args.expected_pid,
                    args.expected_started_at,
                    args.watchdog_delay,
                )
            ):
                raise RuntimeFailure("invalid_watchdog", "configuration", False)
            run_watchdog(
                config,
                args.expected_pid,
                args.expected_started_at,
                args.watchdog_delay,
            )
            return 0
        if args.command == "plan":
            result = {
                "status": "planned",
                "endpointKind": "direct_cdp",
                "host": "loopback",
                "port": config.port,
                "mode": "headed" if args.headed else "headless",
                "browserKind": browser_kind(config),
                "maxRuntimeSeconds": args.max_runtime_seconds,
                "profileInitialized": (config.profile_root / "Default").is_dir(),
            }
        elif args.command == "status":
            result = inspect_runtime(config)
        elif args.command == "bootstrap":
            if not args.confirm_sensitive_copy:
                raise RuntimeFailure("sensitive_copy_confirmation_required", "profile_bootstrap", False)
            result = bootstrap_profile(config, replace=args.replace)
        elif args.command == "start":
            if args.timeout <= 0 or args.timeout > 120:
                raise RuntimeFailure("invalid_timeout", "configuration", False)
            if not 60 <= args.max_runtime_seconds <= MAX_RUNTIME_SECONDS:
                raise RuntimeFailure(
                    "invalid_max_runtime", "configuration", False
                )
            result = start_runtime(
                config,
                args.timeout,
                headless=not args.headed,
                max_runtime_seconds=args.max_runtime_seconds,
            )
        elif args.command == "stop":
            result = stop_runtime(config)
        elif args.command == "claim":
            if not args.consumer:
                raise RuntimeFailure("consumer_required", "configuration", False)
            result = claim_consumer(config, args.consumer)
        else:
            if not args.consumer:
                raise RuntimeFailure("consumer_required", "configuration", False)
            result = release_consumer(config, args.consumer)
    except RuntimeFailure as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": {
                        "code": error.code,
                        "phase": error.phase,
                        "retryable": error.retryable,
                    },
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
