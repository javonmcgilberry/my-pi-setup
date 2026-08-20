#!/usr/bin/env python3
"""Own the dedicated Chrome profile and direct-CDP runtime for Designer work."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - the supported runtime is macOS/Linux.
    fcntl = None

DEFAULT_ROOT = Path.home() / ".config" / "webflow-designer-agent-browser"
DEFAULT_SOURCE_ROOT = Path.home() / "Library/Application Support/Google/Chrome"
MIN_STARTUP_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RUNTIME_SECONDS = 1800
MAX_RUNTIME_SECONDS = 14400
POLICY_FILENAME = "agent-browser-policy.json"
COOKIE_TRANSFER_SCRIPT = Path(__file__).with_name("cookie-transfer.mjs")
CONSUMERS = {"agent_browser", "chrome_devtools_mcp"}
LEASE_ID = re.compile(r"[0-9a-f]{32}")
LEASE_OWNERS = {"direct", "code_mode"}
CODE_MODE_OWNER_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
SENSITIVE_PROFILE_DATABASES = {
    "Cookies",
    "Local State",
    "Login Data",
    "Web Data",
}
SENSITIVE_PROFILE_DIRECTORIES = {
    "Extension State",
    "IndexedDB",
    "Local Extension Settings",
    "Local Storage",
    "Session Storage",
    "Sync Extension Settings",
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
RUNTIME_PROFILE_LINKS = {
    "RunningChromeVersion",
    "SingletonCookie",
    "SingletonLock",
    "SingletonSocket",
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


def validate_lease_id(value: str) -> str:
    if not LEASE_ID.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "lease id must be 32 lowercase hex characters"
        )
    return value


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
    def lease_lock_path(self) -> Path:
        return self.root / ".consumer-lease.lock"

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
    for state_path in (
        config.runtime_path,
        config.lease_path,
        config.origin_path,
        config.lease_lock_path,
    ):
        if state_path.is_symlink():
            raise RuntimeFailure("unsafe_state_file", "configuration", False)
    if config.profile_root.exists():
        for directory, directories, files in os.walk(config.profile_root):
            for name in [*directories, *files]:
                candidate = Path(directory) / name
                if candidate.is_symlink() and not (
                    Path(directory) == config.profile_root
                    and name in RUNTIME_PROFILE_LINKS
                ):
                    raise RuntimeFailure("unsafe_profile_symlink", "configuration", False)
    return config


@contextmanager
def consumer_lease_lock(config: RuntimeConfig):
    """Serialize lease read/modify/write operations across tool processes."""
    validate_config(config)
    ensure_private_root(config.root)
    if config.lease_lock_path.is_symlink():
        raise RuntimeFailure("unsafe_lease_lock", "configuration", False)
    if fcntl is None:
        yield
        return
    with config.lease_lock_path.open("a+") as lock:
        config.lease_lock_path.chmod(0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def ensure_private_root(root: Path) -> None:
    if root.is_symlink():
        raise RuntimeFailure("unsafe_state_root", "configuration", False)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)


def write_private_json(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_TRUNC
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "w") as handle:
            descriptor = None
            json.dump(value, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
        os.chmod(path, 0o600, follow_symlinks=False)
    finally:
        if descriptor is not None:
            os.close(descriptor)
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


def process_listens_on_port(pid: object, config: RuntimeConfig) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        return False
    lsof = next(
        (
            candidate
            for candidate in (Path("/usr/sbin/lsof"), Path("/usr/bin/lsof"))
            if candidate.is_file()
        ),
        None,
    )
    if lsof is None:
        return False
    try:
        completed = subprocess.run(
            [
                str(lsof),
                "-nP",
                "-a",
                "-p",
                str(pid),
                "-iTCP:" + str(config.port),
                "-sTCP:LISTEN",
                "-Fn",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and f"n{config.host}:{config.port}" in completed.stdout


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


def terminate_watchdog(pid: object) -> None:
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or not process_matches_watchdog(pid)
    ):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


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


def owned_cdp_ready(config: RuntimeConfig, pid: object) -> bool:
    if not process_matches_runtime(pid, config):
        return False
    if not process_listens_on_port(pid, config):
        return False
    if not cdp_ready(config):
        return False
    return process_matches_runtime(pid, config) and process_listens_on_port(pid, config)


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
    if not process_matches_runtime(pid, config):
        raise RuntimeFailure("runtime_ownership_unknown", "runtime_stop", False)

    def group_alive() -> bool:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # macOS can reject a group probe while the just-signalled group is
            # exiting. The owned root PID and loopback listener remain the
            # bounded fallback evidence for that transient state.
            return pid_alive(pid)
        return True

    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        if not port_open(config.host, config.port):
            return
        raise RuntimeFailure("runtime_cleanup_incomplete", "runtime_stop", True)
    deadline = time.monotonic() + graceful_timeout
    while time.monotonic() < deadline:
        if not group_alive() and not port_open(config.host, config.port):
            return
        time.sleep(0.1)
    if not process_matches_runtime(pid, config):
        if not group_alive() and not port_open(config.host, config.port):
            return
        raise RuntimeFailure("runtime_ownership_unknown", "runtime_stop", False)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        if not port_open(config.host, config.port):
            return
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


def policy_path(configured_override: str | None = None) -> Path:
    configured = (
        configured_override.strip()
        if configured_override is not None
        else os.environ.get("PI_AGENT_BROWSER_POLICY_CONFIG", "").strip()
    )
    if configured:
        candidate = Path(configured).expanduser()
        return candidate if candidate.is_absolute() else Path.cwd() / candidate
    installed = Path.home() / ".pi" / "agent" / POLICY_FILENAME
    if installed.is_file():
        return installed
    return Path(__file__).resolve().parents[3] / POLICY_FILENAME


def source_cookie_database(config: RuntimeConfig) -> Path:
    profile = resolved_source_profile(config)
    reject_source_profile_symlinks(profile)
    for candidate in (profile / "Network" / "Cookies", profile / "Cookies"):
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise RuntimeFailure("cookie_database_missing", "cookie_transfer", False)


def transfer_cookies(
    config: RuntimeConfig,
    *,
    confirm: bool,
    dry_run: bool = False,
    policy: str | None = None,
    lease_id: str | None = None,
) -> dict[str, object]:
    lock = consumer_lease_lock(config) if not dry_run else nullcontext()
    with lock:
        return _transfer_cookies(
            config,
            confirm=confirm,
            dry_run=dry_run,
            policy=policy,
            lease_id=lease_id,
        )


def _transfer_cookies(
    config: RuntimeConfig,
    *,
    confirm: bool,
    dry_run: bool = False,
    policy: str | None = None,
    lease_id: str | None = None,
) -> dict[str, object]:
    if not confirm:
        raise RuntimeFailure(
            "cookie_transfer_confirmation_required", "cookie_transfer", False
        )
    if not COOKIE_TRANSFER_SCRIPT.is_file():
        raise RuntimeFailure("cookie_transfer_unavailable", "cookie_transfer", False)
    selected_policy = policy_path(policy)
    if not selected_policy.is_file():
        raise RuntimeFailure("policy_missing", "cookie_transfer", False)
    if not dry_run:
        if lease_id is not None and (
            not isinstance(lease_id, str) or not LEASE_ID.fullmatch(lease_id)
        ):
            raise RuntimeFailure("lease_invalid", "cookie_transfer", False)
        runtime = inspect_runtime(config)
        if not runtime["cdpReady"] or not runtime["runtimeOwned"]:
            raise RuntimeFailure("runtime_not_ready", "cookie_transfer", True)
        lease = read_json(config.lease_path)
        if not lease or lease.get("consumer") != "agent_browser":
            raise RuntimeFailure("agent_browser_lease_required", "cookie_transfer", False)
        if lease_id is None:
            raise RuntimeFailure("lease_id_required", "cookie_transfer", False)
        if lease.get("leaseId") != lease_id:
            raise RuntimeFailure("lease_mismatch", "cookie_transfer", False)
        expected_generation = lease_generation(lease)
        if expected_generation is None:
            raise RuntimeFailure("lease_identity_required", "cookie_transfer", True)
        current_generation = runtime_generation(config)
        if current_generation is None or expected_generation != current_generation:
            raise RuntimeFailure("runtime_generation_mismatch", "cookie_transfer", True)
    node = shutil.which("node")
    if not node:
        raise RuntimeFailure("node_unavailable", "cookie_transfer", False)
    database = source_cookie_database(config)
    command = [
        node,
        str(COOKIE_TRANSFER_SCRIPT),
        "--source-db",
        str(database),
        "--cdp-endpoint",
        f"http://{config.host}:{config.port}",
        "--policy",
        str(selected_policy),
    ]
    if dry_run:
        command.append("--dry-run")
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeFailure("cookie_transfer_timeout", "cookie_transfer", True) from error
    try:
        result = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise RuntimeFailure("cookie_transfer_invalid_result", "cookie_transfer", False) from error
    if completed.returncode != 0 or result.get("status") == "blocked":
        error = result.get("error")
        code = error.get("code") if isinstance(error, dict) else "cookie_transfer_failed"
        raise RuntimeFailure(str(code), "cookie_transfer", False)
    return result


def copy_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if (
            name in TRANSIENT_NAMES
            or name in SENSITIVE_PROFILE_DIRECTORIES
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
    alive = process_matches_runtime(runtime_pid, config) and process_listens_on_port(
        runtime_pid, config
    )
    ready = owned_cdp_ready(config, runtime_pid) if alive else False
    if alive and not ready:
        alive = process_matches_runtime(runtime_pid, config) and process_listens_on_port(
            runtime_pid, config
        )
    occupied = port_open(config.host, config.port) if not alive else False
    consumer = lease.get("consumer") if lease else None
    consumer_known = isinstance(consumer, str) and consumer in CONSUMERS
    lease_valid = lease is None or consumer_known
    return {
        "status": (
            "ready"
            if ready
            else "unhealthy"
            if alive
            else "unverified_listener"
            if occupied
            else "stopped"
        ),
        "profileInitialized": (config.profile_root / "Default").is_dir(),
        "runtimeOwned": alive,
        "cdpReady": ready,
        "mode": runtime.get("mode") if alive and runtime else None,
        "expiresAt": runtime.get("expiresAt") if alive and runtime else None,
        "browserKind": browser_kind(config),
        "consumer": consumer if consumer_known else None,
        "leaseOwner": lease_owner(lease) if lease else None,
        "leasePresent": lease is not None,
        "leaseValid": lease_valid,
        "endpointKind": "direct_cdp",
        "host": "loopback",
        "port": config.port,
    }


def runtime_process_is_stopped(status: dict[str, object]) -> bool:
    return (
        all(key in status for key in ("status", "runtimeOwned", "cdpReady", "leaseValid"))
        and type(status.get("runtimeOwned")) is bool
        and type(status.get("cdpReady")) is bool
        and type(status.get("leaseValid")) is bool
        and status.get("status") == "stopped"
        and status.get("runtimeOwned") is False
        and status.get("cdpReady") is False
        and status.get("leaseValid") is True
    )


def runtime_is_stopped(status: dict[str, object]) -> bool:
    return (
        runtime_process_is_stopped(status)
        and "leasePresent" in status
        and "consumer" in status
        and type(status.get("leasePresent")) is bool
        and status.get("leasePresent") is False
        and status.get("consumer") is None
    )


def runtime_generation(config: RuntimeConfig) -> dict[str, int] | None:
    runtime = read_json(config.runtime_path)
    if runtime is None:
        return None
    pid = runtime.get("pid")
    started_at = runtime.get("startedAt")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or isinstance(started_at, bool)
        or not isinstance(started_at, int)
    ):
        raise RuntimeFailure("runtime_identity_unavailable", "runtime_identity", True)
    return {"pid": pid, "startedAt": started_at}


def lease_generation(lease: dict[str, object]) -> dict[str, int] | None:
    pid = lease.get("runtimePid")
    started_at = lease.get("runtimeStartedAt")
    if pid is None and started_at is None:
        return None
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or isinstance(started_at, bool)
        or not isinstance(started_at, int)
    ):
        raise RuntimeFailure("lease_invalid", "consumer_lease", False)
    return {"pid": pid, "startedAt": started_at}


def lease_owner(lease: dict[str, object]) -> str:
    owner = lease.get("owner")
    owner_id = lease.get("ownerId")
    if owner == "direct" and owner_id is None:
        return "direct"
    if (
        owner == "code_mode"
        and isinstance(owner_id, str)
        and CODE_MODE_OWNER_ID.fullmatch(owner_id)
    ):
        return "code_mode"
    return "unknown"


def run_watchdog(
    config: RuntimeConfig,
    expected_pid: int,
    expected_started_at: int,
    delay: int,
) -> None:
    validate_config(config)
    time.sleep(delay)
    with consumer_lease_lock(config):
        _run_watchdog_locked(config, expected_pid, expected_started_at)


def _run_watchdog_locked(
    config: RuntimeConfig,
    expected_pid: int,
    expected_started_at: int,
) -> None:
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
    if runtime_process_is_stopped(inspect_runtime(config)):
        config.runtime_path.unlink(missing_ok=True)
        config.lease_path.unlink(missing_ok=True)


def _start_runtime(
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
    if read_json(config.lease_path):
        raise RuntimeFailure("stale_lease", "runtime_start", True)
    if port_open(config.host, config.port):
        raise RuntimeFailure("port_occupied", "runtime_start", True)
    if not (config.profile_root / "Default").is_dir():
        raise RuntimeFailure("profile_unavailable", "runtime_start", False)
    if not config.chrome.is_file():
        raise RuntimeFailure("chrome_unavailable", "runtime_start", False)
    process = None
    watchdog = None
    try:
        process = subprocess.Popen(
            build_chrome_launch_plan(config, headless=headless),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        started_at = time.time_ns()
        runtime_state: dict[str, object] = {
            "version": 1,
            "pid": process.pid,
            "startedAt": started_at,
            "expiresAt": int(time.time()) + max_runtime_seconds,
            "mode": requested_mode,
        }
        write_private_json(config.runtime_path, runtime_state)
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
    except Exception as error:
        if watchdog is not None:
            terminate_watchdog(watchdog.pid)
        if process is not None and process.poll() is None:
            terminate_owned_runtime(process.pid, config)
        if runtime_is_stopped(inspect_runtime(config)):
            config.runtime_path.unlink(missing_ok=True)
        if isinstance(error, RuntimeFailure):
            raise
        raise RuntimeFailure("runtime_start_failed", "runtime_start", True) from error
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            terminate_watchdog(watchdog.pid)
            if runtime_is_stopped(inspect_runtime(config)):
                config.runtime_path.unlink(missing_ok=True)
            raise RuntimeFailure("chrome_exited", "runtime_start", True)
        if owned_cdp_ready(config, process.pid):
            return inspect_runtime(config)
        time.sleep(0.1)
    terminate_owned_runtime(process.pid, config)
    terminate_watchdog(watchdog.pid)
    if runtime_is_stopped(inspect_runtime(config)):
        config.runtime_path.unlink(missing_ok=True)
    raise RuntimeFailure("cdp_readiness_timeout", "runtime_start", True)


def start_runtime(
    config: RuntimeConfig,
    timeout: float,
    *,
    headless: bool = True,
    max_runtime_seconds: int = DEFAULT_MAX_RUNTIME_SECONDS,
) -> dict[str, object]:
    with consumer_lease_lock(config):
        return _start_runtime(
            config,
            timeout,
            headless=headless,
            max_runtime_seconds=max_runtime_seconds,
        )


def stop_runtime(config: RuntimeConfig) -> dict[str, object]:
    with consumer_lease_lock(config):
        return _stop_runtime(config)


def stop_if_unclaimed(
    config: RuntimeConfig,
    *,
    expected_pid: int,
    expected_started_at: int,
) -> dict[str, object]:
    with consumer_lease_lock(config):
        runtime = read_json(config.runtime_path)
        lease = read_json(config.lease_path)
        if (
            not isinstance(runtime, dict)
            or runtime.get("pid") != expected_pid
            or runtime.get("startedAt") != expected_started_at
            or lease is not None
        ):
            return inspect_runtime(config)
        return _stop_runtime(config)


def _stop_runtime(config: RuntimeConfig) -> dict[str, object]:
    validate_config(config)
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
            terminate_watchdog(watchdog_pid)
    status = inspect_runtime(config)
    if runtime_process_is_stopped(status):
        config.runtime_path.unlink(missing_ok=True)
        config.lease_path.unlink(missing_ok=True)
        return inspect_runtime(config)
    return status


def claim_consumer(
    config: RuntimeConfig,
    consumer: str,
    *,
    exclusive: bool = False,
    owner: str = "direct",
    owner_id: str | None = None,
) -> dict[str, object]:
    if not isinstance(consumer, str) or consumer not in CONSUMERS:
        raise RuntimeFailure("unsupported_consumer", "consumer_claim", False)
    if owner not in LEASE_OWNERS:
        raise RuntimeFailure("unsupported_lease_owner", "consumer_claim", False)
    if owner == "direct" and owner_id is not None:
        raise RuntimeFailure("lease_owner_id_invalid", "consumer_claim", False)
    if owner == "code_mode" and (
        not isinstance(owner_id, str) or not CODE_MODE_OWNER_ID.fullmatch(owner_id)
    ):
        raise RuntimeFailure("lease_owner_id_required", "consumer_claim", False)
    with consumer_lease_lock(config):
        status = inspect_runtime(config)
        if not status["cdpReady"]:
            raise RuntimeFailure("runtime_not_ready", "consumer_claim", True)
        generation = runtime_generation(config)
        if generation is None:
            raise RuntimeFailure("runtime_identity_unavailable", "consumer_claim", True)
        existing = read_json(config.lease_path)
        if existing:
            if existing.get("consumer") == consumer:
                existing_owner = lease_owner(existing)
                if existing_owner not in {owner, "unknown"}:
                    raise RuntimeFailure("consumer_conflict", "consumer_claim", True)
                if existing_owner == "code_mode" and existing.get("ownerId") != owner_id:
                    raise RuntimeFailure("consumer_conflict", "consumer_claim", True)
                existing_generation = lease_generation(existing)
                existing_lease_id = existing.get("leaseId")
                if (
                    existing_generation is None
                    or not isinstance(existing_lease_id, str)
                    or not LEASE_ID.fullmatch(existing_lease_id)
                ):
                    raise RuntimeFailure("lease_identity_required", "consumer_claim", True)
                if existing_generation != generation:
                    raise RuntimeFailure("runtime_generation_mismatch", "consumer_claim", True)
                if exclusive:
                    raise RuntimeFailure("consumer_conflict", "consumer_claim", True)
                return {
                    "status": "claimed",
                    "consumer": consumer,
                    "reused": True,
                    "leaseId": existing_lease_id,
                    "owner": existing_owner,
                }
            raise RuntimeFailure("consumer_conflict", "consumer_claim", True)
        lease_id = uuid.uuid4().hex
        write_private_json(
            config.lease_path,
            {
                "version": 1,
                "consumer": consumer,
                "claimedAt": int(time.time()),
                "leaseId": lease_id,
                "runtimePid": generation["pid"],
                "runtimeStartedAt": generation["startedAt"],
                "owner": owner,
                **({"ownerId": owner_id} if owner_id is not None else {}),
            },
        )
        return {
            "status": "claimed",
            "consumer": consumer,
            "reused": False,
            "leaseId": lease_id,
            "owner": owner,
        }


def release_consumer(
    config: RuntimeConfig,
    consumer: str,
    *,
    lease_id: str | None = None,
) -> dict[str, object]:
    validate_config(config)
    with consumer_lease_lock(config):
        if lease_id is not None and (
            not isinstance(lease_id, str) or not LEASE_ID.fullmatch(lease_id)
        ):
            raise RuntimeFailure("lease_invalid", "consumer_release", False)
        existing = read_json(config.lease_path)
        if existing and existing.get("consumer") != consumer:
            raise RuntimeFailure("consumer_mismatch", "consumer_release", False)
        if existing and lease_id is None:
            raise RuntimeFailure("lease_id_required", "consumer_release", False)
        if lease_id is not None and (
            not existing or existing.get("leaseId") != lease_id
        ):
            raise RuntimeFailure("lease_mismatch", "consumer_release", False)
        if existing:
            expected_generation = lease_generation(existing)
            if expected_generation is None:
                raise RuntimeFailure("lease_identity_required", "consumer_release", True)
            current_generation = runtime_generation(config)
            if current_generation is None:
                status = inspect_runtime(config)
                if not runtime_process_is_stopped(status):
                    raise RuntimeFailure(
                        "runtime_generation_mismatch", "consumer_release", True
                    )
                config.lease_path.unlink(missing_ok=True)
                config.runtime_path.unlink(missing_ok=True)
                return {
                    "status": "released_and_stopped",
                    "consumer": consumer,
                    "runtime": inspect_runtime(config),
                }
            if expected_generation != current_generation:
                raise RuntimeFailure(
                    "runtime_generation_mismatch", "consumer_release", True
                )
        runtime = _stop_runtime(config)
        if not runtime_is_stopped(runtime):
            raise RuntimeFailure("runtime_stop_unverified", "consumer_release", True)
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
            "ensure",
            "transfer-cookies",
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
    parser.add_argument("--lease-id", type=validate_lease_id)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--confirm-sensitive-copy", action="store_true")
    parser.add_argument("--confirm-cookie-transfer", action="store_true")
    parser.add_argument("--policy", help="private browser-policy JSON override")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--timeout", type=float, default=MIN_STARTUP_TIMEOUT_SECONDS
    )
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
        elif args.command in {"start", "ensure"}:
            if args.timeout <= 0 or args.timeout > 120:
                raise RuntimeFailure("invalid_timeout", "configuration", False)
            if not 60 <= args.max_runtime_seconds <= MAX_RUNTIME_SECONDS:
                raise RuntimeFailure(
                    "invalid_max_runtime", "configuration", False
                )
            result = start_runtime(
                config,
                max(MIN_STARTUP_TIMEOUT_SECONDS, args.timeout),
                headless=not args.headed,
                max_runtime_seconds=args.max_runtime_seconds,
            )
        elif args.command == "transfer-cookies":
            result = transfer_cookies(
                config,
                confirm=args.confirm_cookie_transfer,
                dry_run=args.dry_run,
                policy=args.policy,
                lease_id=args.lease_id,
            )
        elif args.command == "stop":
            result = stop_runtime(config)
        elif args.command == "claim":
            if not args.consumer:
                raise RuntimeFailure("consumer_required", "configuration", False)
            result = claim_consumer(config, args.consumer, exclusive=True)
        else:
            if not args.consumer:
                raise RuntimeFailure("consumer_required", "configuration", False)
            result = release_consumer(
                config,
                args.consumer,
                lease_id=args.lease_id,
            )
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
