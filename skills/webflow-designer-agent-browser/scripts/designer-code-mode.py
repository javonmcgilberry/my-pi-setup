#!/usr/bin/env python3
"""Deterministic Code Mode facade for the Webflow Designer browser skill.

This command owns the non-interactive part of a Designer transaction.  It does
not implement a browser transport: native ``agent_browser`` (or the explicit
CLI fallback) performs page interaction using the bounded plan returned by
``prepare``.  The command keeps the runtime lease and sanitized transaction
receipt across the short ``prepare``/``verify``/``finish`` calls.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable, NoReturn, cast
from urllib.parse import parse_qsl, urlsplit

try:
    import fcntl
except ImportError:  # pragma: no cover - the supported runtime is macOS/Linux.
    fcntl = None


SCRIPT_DIR = Path(__file__).resolve().parent
PROTOCOL_VERSION = 1
CONSUMER = "agent_browser"
OPERATIONS = {
    "help",
    "capabilities",
    "test_knowledge",
    "scenario_plan",
    "status",
    "reconcile",
    "prepare",
    "verify",
    "finish",
}
REQUIRED_CHECKS = (
    "hud",
    "designer_service",
    "target_http",
    "browser_profile",
    "designer_surface",
)
SERVICE_CHECKS = REQUIRED_CHECKS[:3]
CHECK_STATES = {"ready", "unavailable", "error"}
SURFACE_STATES = {"designer", "login", "error", "unknown"}
SAFE_QUERY_KEYS = {"pageId", "simulateRole"}
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
SENSITIVE_TERMS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "storage",
    "token",
)
SERVICE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$")
SESSION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
TRANSACTION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
MAX_REQUEST_BYTES = 32 * 1024
MAX_OUTPUT_BYTES = 48 * 1024
MAX_EVIDENCE_STRING = 200
RUNTIME_SETTLE_SECONDS = 2.0
RUNTIME_SETTLE_INTERVAL_SECONDS = 0.1


def _load_script(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


browser_runtime = _load_script(
    "webflow_designer_browser_runtime", "browser-runtime.py"
)
designer_session = _load_script(
    "webflow_designer_designer_session", "designer-session.py"
)
readiness_gate = _load_script(
    "webflow_designer_readiness_gate", "readiness-gate.py"
)
sanitize_evidence = _load_script(
    "webflow_designer_sanitize_evidence", "sanitize-evidence.py"
)
capability_catalog = _load_script(
    "webflow_designer_capability_catalog", "capability-catalog.py"
)
test_corpus_index = _load_script(
    "webflow_designer_test_corpus_index", "test-corpus-index.py"
)
test_scenario_eval = _load_script(
    "webflow_designer_test_scenario_eval", "test-scenario-eval.py"
)


class ProtocolError(Exception):
    """An expected, bounded protocol or lifecycle failure."""

    def __init__(
        self,
        code: str,
        phase: str = "input",
        retryable: bool = False,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.phase = phase
        self.retryable = retryable


def _error_from_exception(
    error: Exception,
    *,
    phase: str,
    default_code: str = "runtime_helper_failure",
) -> ProtocolError:
    code = getattr(error, "code", default_code)
    error_phase = getattr(error, "phase", phase)
    retryable = getattr(error, "retryable", False)
    if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", code):
        code = default_code
    if not isinstance(error_phase, str) or not re.fullmatch(
        r"[a-z][a-z0-9_]{1,63}", error_phase
    ):
        error_phase = phase
    return ProtocolError(code, error_phase, bool(retryable))


def _fail(code: str, phase: str = "input", retryable: bool = False) -> NoReturn:
    raise ProtocolError(code, phase, retryable)


def _require_object(value: object, code: str = "invalid_request") -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(code)
    return cast(dict[str, Any], value)


def _bounded_string(
    value: object,
    field: str,
    *,
    maximum: int = 2000,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        _fail("invalid_request")
    if len(value) > maximum or "\x00" in value:
        _fail("input_too_large")
    return value


def _bounded_int(
    value: object,
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("invalid_request")
    if value < minimum or value > maximum:
        _fail("invalid_request")
    return value


def _local_path(value: object, field: str, *, maximum: int = 1000) -> Path:
    raw = _bounded_string(value, field, maximum=maximum)
    if raw.startswith(("http://", "https://", "file://")):
        _fail(f"invalid_{field}")
    path = Path(raw)
    if "\x00" in raw or ".." in path.parts:
        _fail(f"invalid_{field}")
    return path


def _is_true(value: object) -> bool:
    return isinstance(value, bool) and value


def _is_false(value: object) -> bool:
    return isinstance(value, bool) and not value


def _reject_sensitive_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and any(
                term in key.lower() for term in SENSITIVE_TERMS
            ):
                _fail("sensitive_input_rejected")
            _reject_sensitive_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_sensitive_keys(item)


def _validate_selector(value: object, field: str, *, default: str = "body") -> str:
    selector = default if value is None else _bounded_string(value, field, maximum=500)
    if "\r" in selector or "\n" in selector:
        _fail("invalid_request")
    if any(term in selector.lower() for term in SENSITIVE_TERMS):
        _fail("sensitive_input_rejected")
    return selector


def _validate_target(value: object) -> tuple[str, str]:
    target = _bounded_string(value, "target")
    try:
        designer_session.reject_sensitive_url(target)
    except (ValueError, TypeError):
        _fail("unsafe_target", "input")
    parts = urlsplit(target)
    if any(key not in SAFE_QUERY_KEYS for key, _item in parse_qsl(parts.query)):
        _fail("unsafe_target", "input")
    return target, sanitize_evidence.sanitize_url(target)


def _validate_session(value: object) -> str:
    session = _bounded_string(value, "session", maximum=64)
    if not SESSION_NAME.fullmatch(session):
        _fail("invalid_session")
    if any(term in session.lower() for term in SENSITIVE_TERMS):
        _fail("sensitive_input_rejected")
    return session


def _validate_transport(value: object) -> str:
    if not isinstance(value, str) or value not in {"native", "cli"}:
        _fail("invalid_transport")
    return value


def _validate_mode(value: object) -> str:
    if not isinstance(value, str) or value not in {"attached", "isolated"}:
        _fail("invalid_mode")
    return value


def _validate_runtime_mode(value: object) -> str:
    if value is None:
        return "headless"
    if not isinstance(value, str) or value not in {"headless", "headed"}:
        _fail("invalid_runtime_mode")
    return value


def _validate_check(check: object, target: str) -> dict[str, object]:
    item = _require_object(check)
    name = item.get("name")
    if name not in SERVICE_CHECKS:
        _fail("invalid_readiness_check")
    kind = item.get("kind")
    if kind not in {"tcp", "http"}:
        _fail("invalid_readiness_check")
    label = str(name)
    if kind == "tcp":
        if set(item) != {"name", "kind", "host", "port"}:
            _fail("invalid_readiness_check")
        host = item.get("host")
        if not isinstance(host, str) or host.lower() not in LOOPBACK_HOSTS:
            _fail("loopback_required")
        port = _bounded_int(item.get("port"), "port", minimum=1, maximum=65535)
        return {"label": label, "kind": "tcp", "host": host, "port": port}

    if set(item) != {"name", "kind", "url", "status"}:
        _fail("invalid_readiness_check")
    raw_url, sanitized_url = _validate_target(item.get("url"))
    if name == "target_http" and sanitized_url != target:
        _fail("target_check_mismatch")
    status = _bounded_int(item.get("status"), "status", minimum=100, maximum=599)
    return {
        "label": label,
        "kind": "http",
        "url": raw_url,
        "status": status,
    }


def _validate_checks(value: object, target: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) != len(SERVICE_CHECKS):
        _fail("invalid_readiness_check")
    checks = [_validate_check(item, target) for item in value]
    names = [str(check["label"]) for check in checks]
    if set(names) != set(SERVICE_CHECKS) or len(names) != len(set(names)):
        _fail("invalid_readiness_check")
    return checks


def _validate_surface(value: object, target: str, selector: str) -> dict[str, object]:
    surface = _require_object(value, "invalid_surface_evidence")
    expected = {
        "url",
        "title",
        "document",
        "authenticated",
        "errorPage",
        "scope",
        "scopeObserved",
    }
    if set(surface) != expected:
        _fail("invalid_surface_evidence")
    raw_url = _bounded_string(surface.get("url"), "surface.url")
    document = surface.get("document")
    if document not in SURFACE_STATES:
        _fail("invalid_surface_evidence")
    title = _bounded_string(
        surface.get("title"),
        "surface.title",
        maximum=MAX_EVIDENCE_STRING,
        allow_empty=True,
    )
    authenticated = surface.get("authenticated")
    error_page = surface.get("errorPage")
    scope_observed = surface.get("scopeObserved")
    if not all(isinstance(item, bool) for item in (authenticated, error_page, scope_observed)):
        _fail("invalid_surface_evidence")
    observed_scope = _validate_selector(surface.get("scope"), "surface.scope")
    if observed_scope != selector:
        _fail("surface_scope_mismatch")

    if error_page or document == "error" or raw_url.startswith("chrome-error://"):
        normalized_url = "chrome-error://chromewebdata/"
    elif document == "login":
        try:
            designer_session.reject_sensitive_url(raw_url)
        except (ValueError, TypeError):
            _fail("invalid_surface_evidence")
        normalized_url = sanitize_evidence.sanitize_url(raw_url)
    else:
        _raw, normalized_url = _validate_target(raw_url)
    return {
        "url": normalized_url,
        "title": title,
        "document": document,
        "authenticated": authenticated,
        "errorPage": error_page,
        "scopeObserved": scope_observed,
    }


def parse_request(raw: str) -> dict[str, Any]:
    """Parse the one-string custom-tool protocol without accepting extra fields."""
    if not isinstance(raw, str):
        _fail("invalid_request")
    if len(raw.encode("utf-8")) > MAX_REQUEST_BYTES:
        _fail("input_too_large")
    stripped = raw.strip()
    if stripped == "help" or not stripped:
        return {"version": PROTOCOL_VERSION, "operation": "help"}
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as error:
        raise ProtocolError("invalid_json") from error
    request = _require_object(value)
    _reject_sensitive_keys(request)
    if request.get("version") != PROTOCOL_VERSION:
        _fail("unsupported_version")
    operation = request.get("operation")
    if not isinstance(operation, str) or operation not in OPERATIONS:
        _fail("invalid_operation")
    allowed = {
        "help": {"version", "operation"},
        "capabilities": {"version", "operation", "id", "category", "offset", "limit"},
        "test_knowledge": {
            "version", "operation", "indexPath", "repoPath", "policyPath",
            "operationId", "category", "limit", "view",
        },
        "scenario_plan": {
            "version", "operation", "scenarioPath", "operationPath",
            "policyPath", "dryRun",
        },
        "status": {"version", "operation"},
        "reconcile": {"version", "operation"},
        "prepare": {
            "version",
            "operation",
            "transport",
            "mode",
            "target",
            "surface",
            "readySelector",
            "session",
            "checks",
            "timeoutSeconds",
            "runtimeMode",
            "maxRuntimeSeconds",
        },
        "verify": {"version", "operation", "transactionId", "transport", "surface"},
        "finish": {"version", "operation", "transactionId", "transport"},
    }[operation]
    if set(request) - allowed:
        _fail("unknown_request_field")
    return request


class TransactionStore:
    """Keep only a private, content-free receipt for the active transaction."""

    filename = "code-mode-transaction.json"
    lock_filename = ".code-mode.lock"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / self.filename

    def _ensure_root(self) -> None:
        if self.root.is_symlink():
            _fail("unsafe_state_root", "configuration")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        if self.path.is_symlink():
            _fail("unsafe_state_file", "configuration")

    @contextmanager
    def lock(self):
        self._ensure_root()
        lock_path = self.root / self.lock_filename
        if lock_path.is_symlink():
            _fail("unsafe_lock_file", "configuration")
        try:
            with lock_path.open("a+") as handle:
                lock_path.chmod(0o600)
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as error:
            raise ProtocolError("transaction_lock_failed", "transaction", True) from error

    def load(self) -> dict[str, Any] | None:
        if self.path.is_symlink():
            _fail("unsafe_state_file", "configuration")
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            _fail("transaction_state_invalid", "transaction")
        state = _require_object(value, "transaction_state_invalid")
        transaction_id = state.get("transactionId")
        if state.get("version") != PROTOCOL_VERSION or not isinstance(transaction_id, str):
            _fail("transaction_state_invalid", "transaction")
        if not TRANSACTION_ID.fullmatch(transaction_id):
            _fail("transaction_state_invalid", "transaction")
        for field in (
            "transport",
            "mode",
            "runtimeMode",
            "target",
            "surface",
            "checks",
            "checkSpecs",
            "preflightTimeout",
            "runtimeIdentity",
        ):
            if field not in state:
                _fail("transaction_state_invalid", "transaction")
        if state["transport"] not in {"native", "cli"}:
            _fail("transaction_state_invalid", "transaction")
        if state["mode"] not in {"attached", "isolated"}:
            _fail("transaction_state_invalid", "transaction")
        if state["runtimeMode"] not in {"headless", "headed"}:
            _fail("transaction_state_invalid", "transaction")
        if not isinstance(state["target"], str) or not isinstance(state["surface"], str):
            _fail("transaction_state_invalid", "transaction")
        try:
            _raw_target, normalized_target = _validate_target(state["target"])
            _validate_selector(state["surface"], "surface")
        except ProtocolError as error:
            raise ProtocolError("transaction_state_invalid", "transaction") from error
        if normalized_target != state["target"]:
            _fail("transaction_state_invalid", "transaction")
        timeout_value = state["preflightTimeout"]
        if (
            isinstance(timeout_value, bool)
            or not isinstance(timeout_value, (int, float))
            or timeout_value <= 0
            or timeout_value > 30
        ):
            _fail("transaction_state_invalid", "transaction")
        stored_checks = state["checks"]
        if not isinstance(stored_checks, list) or len(stored_checks) != len(SERVICE_CHECKS):
            _fail("transaction_state_invalid", "transaction")
        stored_names = set()
        for item in stored_checks:
            check = _require_object(item, "transaction_state_invalid")
            name = check.get("name")
            state_value = check.get("state")
            if name not in SERVICE_CHECKS or state_value not in CHECK_STATES:
                _fail("transaction_state_invalid", "transaction")
            stored_names.add(name)
        if stored_names != set(SERVICE_CHECKS):
            _fail("transaction_state_invalid", "transaction")
        try:
            _validate_checks(state["checkSpecs"], state["target"])
        except ProtocolError as error:
            raise ProtocolError("transaction_state_invalid", "transaction") from error
        identity = state["runtimeIdentity"]
        if not isinstance(identity, dict):
            _fail("transaction_state_invalid", "transaction")
        if (
            isinstance(identity.get("pid"), bool)
            or not isinstance(identity.get("pid"), int)
            or isinstance(identity.get("startedAt"), bool)
            or not isinstance(identity.get("startedAt"), int)
            or isinstance(identity.get("claimedAt"), bool)
            or not isinstance(identity.get("claimedAt"), int)
            or not isinstance(identity.get("leaseId"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", identity["leaseId"])
        ):
            _fail("transaction_state_invalid", "transaction")
        owner = identity.get("owner")
        owner_id = identity.get("ownerId")
        if owner is not None and (
            owner != "code_mode"
            or not isinstance(owner_id, str)
            or not TRANSACTION_ID.fullmatch(owner_id)
        ):
            _fail("transaction_state_invalid", "transaction")
        return state

    def write(self, state: dict[str, Any]) -> None:
        self._ensure_root()
        payload = json.dumps(state, sort_keys=True, separators=(",", ":"))
        if len(payload.encode("utf-8")) > MAX_OUTPUT_BYTES:
            _fail("output_too_large", "transaction")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.root,
                prefix=".code-mode-transaction-",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
            os.chmod(temporary, 0o600, follow_symlinks=False)
            os.replace(temporary, self.path)
        except OSError:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            _fail("transaction_state_write_failed", "transaction", True)

    def remove(self) -> None:
        if self.path.is_symlink():
            _fail("unsafe_state_file", "configuration")
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            _fail("transaction_state_remove_failed", "transaction", True)


def _public_runtime(status: object) -> dict[str, object]:
    value = _require_object(status, "runtime_status_invalid")
    return {
        key: value.get(key)
        for key in (
            "status",
            "runtimeOwned",
            "cdpReady",
            "mode",
            "consumer",
            "leaseOwner",
            "leasePresent",
            "endpointKind",
            "host",
            "port",
        )
    }


def _clean_stopped(status: dict[str, object]) -> bool:
    return (
        status.get("status") == "stopped"
        and _is_false(status.get("runtimeOwned"))
        and _is_false(status.get("cdpReady"))
        and status.get("consumer") is None
        and _is_false(status.get("leasePresent"))
    )


def _check_state(result: object) -> str:
    item = _require_object(result, "preflight_invalid")
    ready = item.get("ready")
    if isinstance(ready, bool) and ready:
        return "ready"
    if item.get("observed") == "connection_failed":
        return "unavailable"
    return "error"


def _gate_checks(
    service_results: list[dict[str, object]],
    *,
    browser_state: str,
    surface_state: str,
) -> list[tuple[str, str]]:
    states = {str(result["name"]): str(result["state"]) for result in service_results}
    return [
        ("hud", states.get("hud", "unavailable")),
        ("designer_service", states.get("designer_service", "unavailable")),
        ("target_http", states.get("target_http", "unavailable")),
        ("browser_profile", browser_state),
        ("designer_surface", surface_state),
    ]


def _is_designer_title(url: str, title: str) -> bool:
    observed = title.lower().strip()
    host = (urlsplit(url).hostname or "").lower()
    designer_host = (
        host in {"design.webflow.com", "design.wfdev.io"}
        or host.endswith(".design.wfdev.io")
    )
    return (
        "webflow" in observed
        and "designer" in observed
    ) or (
        designer_host
        and re.match(r"^(?:dev:\s*)?webflow\s+-", observed) is not None
    )


class DesignerCodeMode:
    """Compose the existing runtime and readiness authorities."""

    def __init__(
        self,
        *,
        runtime: ModuleType = browser_runtime,
        preflight_runner: Callable[[list[dict[str, object]], float], dict[str, object]]
        | None = None,
        runtime_config: object | None = None,
        store: TransactionStore | None = None,
    ) -> None:
        self.runtime = runtime
        self.preflight_runner = preflight_runner or designer_session.run_preflight
        self.config: Any = runtime_config or runtime.RuntimeConfig(
            root=runtime.DEFAULT_ROOT,
            source_root=runtime.DEFAULT_SOURCE_ROOT,
            source_profile="Default",
            chrome=runtime.discover_automation_chrome(),
            host="127.0.0.1",
            port=9333,
        )
        self.store = store or TransactionStore(self.config.root)

    def _runtime_status(self) -> dict[str, object]:
        try:
            return _public_runtime(self.runtime.inspect_runtime(self.config))
        except ProtocolError:
            raise
        except Exception as error:
            raise _error_from_exception(error, phase="runtime_status") from error

    def _settled_runtime_status(self, runtime_mode: str) -> dict[str, object]:
        deadline = time.monotonic() + RUNTIME_SETTLE_SECONDS
        ready_observations = 0
        status: dict[str, object] = {}
        while True:
            status = self._runtime_status()
            if (
                status.get("status") == "ready"
                and _is_true(status.get("cdpReady"))
                and status.get("mode") == runtime_mode
                and status.get("endpointKind") == "direct_cdp"
                and status.get("host") == "loopback"
            ):
                ready_observations += 1
                if ready_observations == 2:
                    return status
            else:
                ready_observations = 0
            if time.monotonic() >= deadline:
                return status
            time.sleep(RUNTIME_SETTLE_INTERVAL_SECONDS)

    @contextmanager
    def _runtime_lock(self):
        lock_factory = getattr(self.runtime, "consumer_lease_lock", None)
        if not callable(lock_factory):
            with nullcontext():
                yield
            return
        try:
            with cast(Any, lock_factory(self.config)):
                yield
        except ProtocolError:
            raise
        except Exception as error:
            raise _error_from_exception(error, phase="runtime_lock") from error

    def _call_runtime(self, name: str, *args: object, **kwargs: object) -> object:
        try:
            return getattr(self.runtime, name)(*args, **kwargs)
        except ProtocolError:
            raise
        except Exception as error:
            raise _error_from_exception(error, phase=name)

    def _runtime_identity(
        self,
        *,
        expected_owner_id: str | None = None,
    ) -> dict[str, int | str]:
        try:
            runtime_state = self.runtime.read_json(self.config.runtime_path)
            lease_state = self.runtime.read_json(self.config.lease_path)
        except Exception as error:
            raise _error_from_exception(error, phase="runtime_identity") from error
        if not isinstance(runtime_state, dict) or not isinstance(lease_state, dict):
            _fail("runtime_identity_unavailable", "runtime_identity", True)
        pid = runtime_state.get("pid")
        started_at = runtime_state.get("startedAt")
        claimed_at = lease_state.get("claimedAt")
        lease_id = lease_state.get("leaseId")
        lease_pid = lease_state.get("runtimePid")
        lease_started_at = lease_state.get("runtimeStartedAt")
        owner = lease_state.get("owner")
        owner_id = lease_state.get("ownerId")
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or isinstance(started_at, bool)
            or not isinstance(started_at, int)
            or isinstance(claimed_at, bool)
            or not isinstance(claimed_at, int)
            or not isinstance(lease_id, str)
            or not re.fullmatch(r"[0-9a-f]{32}", lease_id)
            or lease_state.get("consumer") != CONSUMER
            or isinstance(lease_pid, bool)
            or not isinstance(lease_pid, int)
            or lease_pid != pid
            or isinstance(lease_started_at, bool)
            or not isinstance(lease_started_at, int)
            or lease_started_at != started_at
        ):
            _fail("runtime_identity_unavailable", "runtime_identity", True)
        identity: dict[str, int | str] = {
            "pid": pid,
            "startedAt": started_at,
            "claimedAt": claimed_at,
            "leaseId": lease_id,
        }
        if owner is not None:
            if (
                owner not in {"direct", "code_mode"}
                or owner == "code_mode"
                and (
                    not isinstance(owner_id, str)
                    or not TRANSACTION_ID.fullmatch(owner_id)
                )
                or owner == "direct"
                and owner_id is not None
            ):
                _fail("runtime_identity_unavailable", "runtime_identity", True)
            identity["owner"] = owner
            if owner_id is not None:
                identity["ownerId"] = owner_id
        if expected_owner_id is not None and (
            owner != "code_mode" or owner_id != expected_owner_id
        ):
            _fail("runtime_identity_unavailable", "runtime_identity", True)
        return identity

    def _runtime_generation(self) -> dict[str, int]:
        try:
            runtime_state = self.runtime.read_json(self.config.runtime_path)
        except Exception as error:
            raise _error_from_exception(error, phase="runtime_identity") from error
        if not isinstance(runtime_state, dict):
            _fail("runtime_identity_unavailable", "runtime_identity", True)
        pid = runtime_state.get("pid")
        started_at = runtime_state.get("startedAt")
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or isinstance(started_at, bool)
            or not isinstance(started_at, int)
        ):
            _fail("runtime_identity_unavailable", "runtime_identity", True)
        return {"pid": pid, "startedAt": started_at}

    def _assert_runtime_identity(self, state: dict[str, Any]) -> None:
        expected = state.get("runtimeIdentity")
        if not isinstance(expected, dict):
            _fail("transaction_state_invalid", "transaction")
        current = self._runtime_identity()
        if current != expected:
            _fail("runtime_identity_mismatch", "runtime_identity", True)

    def _assert_transaction_id(self, request: dict[str, Any], state: dict[str, Any]) -> None:
        transaction_id = request.get("transactionId")
        if not isinstance(transaction_id, str) or not TRANSACTION_ID.fullmatch(transaction_id):
            _fail("invalid_transaction")
        if transaction_id != state.get("transactionId"):
            _fail("transaction_mismatch")
        transport = request.get("transport")
        if not isinstance(transport, str) or transport not in {"native", "cli"}:
            _fail("transport_required", "transaction")
        if transport != state.get("transport"):
            _fail("transport_mismatch", "transaction")

    def _load_active(self, request: dict[str, Any]) -> dict[str, Any]:
        state = self.store.load()
        if state is None:
            _fail("transaction_not_found", "transaction")
        self._assert_transaction_id(request, state)
        return state

    def _lease_state(self) -> dict[str, object] | None:
        try:
            value = self.runtime.read_json(self.config.lease_path)
        except Exception as error:
            raise _error_from_exception(error, phase="lease_status") from error
        if value is None:
            return None
        if not isinstance(value, dict):
            _fail("lease_state_invalid", "lease_status")
        return value

    def _classify_state_locked(self) -> dict[str, object]:
        state = self.store.load()
        runtime_status = self._runtime_status()
        lease = self._lease_state()
        base: dict[str, object] = {
            "version": PROTOCOL_VERSION,
            "runtime": runtime_status,
            "transactionPresent": state is not None,
            "leasePresent": lease is not None,
        }

        if state is not None:
            base["transactionId"] = state["transactionId"]
            if _clean_stopped(runtime_status):
                return {
                    **base,
                    "state": "stale_transaction",
                    "safeToRecover": True,
                    "action": "finish",
                    "evidence": {"runtime": "stopped", "lease": "absent"},
                }
            if runtime_status.get("status") == "unverified_listener":
                return {
                    **base,
                    "state": "unverified_listener",
                    "safeToRecover": False,
                    "action": "fail_closed",
                    "evidence": {"listener": "not_owned"},
                }
            if (
                runtime_status.get("status") == "stopped"
                and _is_false(runtime_status.get("runtimeOwned"))
                and _is_false(runtime_status.get("cdpReady"))
                and _is_true(runtime_status.get("leasePresent"))
            ):
                if self._lease_matches_transaction(state):
                    return {
                        **base,
                        "state": "stale_transaction_lease",
                        "safeToRecover": True,
                        "action": "finish",
                        "evidence": {
                            "runtime": "stopped",
                            "lease": "matching",
                        },
                    }
                return {
                    **base,
                    "state": "transaction_identity_unknown",
                    "safeToRecover": False,
                    "action": "fail_closed",
                    "evidence": {"reason": "stopped_runtime_lease_mismatch"},
                }
            try:
                identity = self._runtime_identity()
            except ProtocolError as error:
                return {
                    **base,
                    "state": "transaction_identity_unknown",
                    "safeToRecover": False,
                    "action": "fail_closed",
                    "evidence": {"reason": error.code},
                }
            if identity != state["runtimeIdentity"]:
                return {
                    **base,
                    "state": "replacement_runtime",
                    "safeToRecover": False,
                    "action": "fail_closed",
                    "evidence": {"identity": "mismatch"},
                }
            if (
                runtime_status.get("status") == "ready"
                and _is_true(runtime_status.get("runtimeOwned"))
                and _is_true(runtime_status.get("cdpReady"))
                and runtime_status.get("consumer") == CONSUMER
            ):
                return {
                    **base,
                    "state": "active_transaction",
                    "safeToRecover": False,
                    "action": "continue_or_finish",
                    "evidence": {"identity": "matched"},
                }
            return {
                **base,
                "state": "transaction_runtime_unhealthy",
                "safeToRecover": False,
                "action": "fail_closed",
                "evidence": {"runtime": str(runtime_status.get("status"))},
            }

        if _clean_stopped(runtime_status):
            return {
                **base,
                "state": "clean_stopped",
                "safeToRecover": False,
                "action": "start_transaction",
            }
        if runtime_status.get("status") == "unverified_listener":
            return {
                **base,
                "state": "unverified_listener",
                "safeToRecover": False,
                "action": "fail_closed",
                "evidence": {"listener": "not_owned"},
            }
        if runtime_status.get("status") == "stopped" and lease is not None:
            return {
                **base,
                "state": "stale_lease",
                "safeToRecover": True,
                "action": "reconcile",
                "evidence": {"runtime": "stopped", "listener": "absent"},
            }
        if _is_true(runtime_status.get("runtimeOwned")):
            owner = runtime_status.get("leaseOwner")
            if lease is None:
                state_name = "owned_runtime_without_lease"
            elif owner == "direct":
                state_name = "active_direct_owner"
            elif owner == "code_mode":
                state_name = "active_code_mode_owner_without_receipt"
            else:
                state_name = "active_unknown_owner"
            return {
                **base,
                "state": state_name,
                "safeToRecover": False,
                "action": "defer",
                "evidence": {"runtime": str(runtime_status.get("status"))},
            }
        return {
            **base,
            "state": "unknown_runtime_state",
            "safeToRecover": False,
            "action": "fail_closed",
        }

    def _status(self, _request: dict[str, Any]) -> dict[str, object]:
        with self.store.lock():
            with self._runtime_lock():
                return self._classify_state_locked()

    def _reconcile(self, _request: dict[str, Any]) -> dict[str, object]:
        with self.store.lock():
            with self._runtime_lock():
                classification = self._classify_state_locked()
            if classification["state"] == "clean_stopped":
                return {
                    **classification,
                    "status": "reconciled",
                    "recovered": False,
                }
            if classification["state"] == "stale_transaction":
                state = self.store.load()
                if state is None:
                    _fail("transaction_state_invalid", "reconcile")
                self.store.remove()
                return {
                    **classification,
                    "status": "reconciled",
                    "recovered": True,
                }
            if classification["state"] == "stale_transaction_lease":
                state = self.store.load()
                if state is None:
                    _fail("transaction_state_invalid", "reconcile")
                lease_id = state["runtimeIdentity"].get("leaseId")
                if not isinstance(lease_id, str):
                    _fail("transaction_state_invalid", "reconcile")
                self._call_runtime(
                    "release_consumer",
                    self.config,
                    CONSUMER,
                    lease_id=lease_id,
                )
                with self._runtime_lock():
                    after = self._runtime_status()
                if not _clean_stopped(after):
                    return {
                        **classification,
                        "status": "blocked",
                        "recovered": False,
                        "runtime": after,
                    }
                self.store.remove()
                return {
                    **classification,
                    "status": "reconciled",
                    "recovered": True,
                    "runtime": after,
                }
            if classification["state"] == "stale_lease":
                with self._runtime_lock():
                    lease = self._lease_state()
                lease_id = lease.get("leaseId") if lease else None
                if (
                    not isinstance(lease_id, str)
                    or not re.fullmatch(r"[0-9a-f]{32}", lease_id)
                    or not lease
                    or lease.get("consumer") != CONSUMER
                ):
                    _fail("lease_state_invalid", "reconcile")
                self._call_runtime(
                    "release_consumer",
                    self.config,
                    CONSUMER,
                    lease_id=lease_id,
                )
                with self._runtime_lock():
                    after = self._classify_state_locked()
                if after["state"] != "clean_stopped":
                    return {
                        **after,
                        "status": "blocked",
                        "recovered": False,
                    }
                return {
                    **after,
                    "status": "reconciled",
                    "recovered": True,
                }
            return {
                **classification,
                "status": "blocked",
                "recovered": False,
            }

    def _lease_matches_transaction(self, state: dict[str, Any]) -> bool:
        expected = state.get("runtimeIdentity")
        lease = self._lease_state()
        if not isinstance(expected, dict) or lease is None:
            return False
        if (
            lease.get("consumer") != CONSUMER
            or lease.get("leaseId") != expected.get("leaseId")
            or lease.get("runtimePid") != expected.get("pid")
            or lease.get("runtimeStartedAt") != expected.get("startedAt")
            or lease.get("claimedAt") != expected.get("claimedAt")
        ):
            return False
        for key in ("owner", "ownerId"):
            if key in expected and lease.get(key) != expected[key]:
                return False
            if key not in expected and key in lease:
                return False
        return True

    def _build_actions(
        self,
        *,
        transport: str,
        mode: str,
        target: str,
        selector: str,
        ready_selector: str,
        session: str | None,
    ) -> list[dict[str, object]]:
        namespace = SimpleNamespace()
        namespace.transport = transport
        namespace.mode = mode
        namespace.url = target
        namespace.surface = selector
        namespace.ready_selector = ready_selector
        namespace.port = self.config.port
        namespace.session = session
        namespace.tab = None
        namespace.user_agent = None
        namespace.managed_runtime = True
        try:
            return designer_session.build_commands(namespace)
        except (ValueError, TypeError):
            _fail("invalid_browser_plan")

    def _service_results(
        self,
        checks: list[dict[str, object]],
        timeout: float,
    ) -> list[dict[str, object]]:
        try:
            preflight = self.preflight_runner(checks, timeout)
        except ProtocolError:
            raise
        except Exception as error:
            raise _error_from_exception(error, phase="service_preflight") from error
        value = _require_object(preflight, "preflight_invalid")
        raw_results_value = value.get("checks")
        if not isinstance(raw_results_value, list) or len(raw_results_value) != len(checks):
            _fail("preflight_invalid", "service_preflight")
        raw_results = cast(list[Any], raw_results_value)
        normalized = []
        expected_names = {str(check["label"]) for check in checks}
        for result in raw_results:
            item = _require_object(result, "preflight_invalid")
            name = item.get("label")
            if name not in expected_names:
                _fail("preflight_invalid", "service_preflight")
            normalized.append(
                {
                    "name": name,
                    "kind": item.get("kind"),
                    "state": _check_state(item),
                    "ready": item.get("ready"),
                    "expected": item.get("expected"),
                    "observed": item.get("observed"),
                }
            )
        if {str(item["name"]) for item in normalized} != expected_names:
            _fail("preflight_invalid", "service_preflight")
        return sorted(normalized, key=lambda item: str(item["name"]))

    def _sanitized_check_specs(
        self, checks: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        specs = []
        for check in checks:
            spec: dict[str, object] = {
                "name": check["label"],
                "kind": check["kind"],
            }
            if check["kind"] == "tcp":
                spec.update({"host": check["host"], "port": check["port"]})
            else:
                spec.update(
                    {
                        "url": sanitize_evidence.sanitize_url(str(check["url"])),
                        "status": check["status"],
                    }
                )
            specs.append(spec)
        return specs

    def _cleanup_unclaimed(
        self,
        *,
        started_here: bool,
        expected_generation: dict[str, int] | None,
    ) -> None:
        if not started_here or expected_generation is None:
            return
        try:
            self._call_runtime(
                "stop_if_unclaimed",
                self.config,
                expected_pid=expected_generation["pid"],
                expected_started_at=expected_generation["startedAt"],
            )
        except ProtocolError:
            return

    def _prepare_locked(self, request: dict[str, Any]) -> dict[str, object]:
        existing = self.store.load()
        if existing is not None:
            status = self._runtime_status()
            code = "transaction_active" if (
                status.get("runtimeOwned") or status.get("consumer")
            ) else "stale_transaction"
            return {
                "version": PROTOCOL_VERSION,
                "status": "blocked",
                "classification": code,
                "qaLaunchAllowed": False,
                "transactionId": existing["transactionId"],
                "blockers": [code],
            }

        transport = _validate_transport(request.get("transport"))
        mode = _validate_mode(request.get("mode"))
        target_raw, target = _validate_target(request.get("target"))
        selector = _validate_selector(request.get("surface"), "surface")
        ready_selector = _validate_selector(
            request.get("readySelector"), "readySelector"
        )
        runtime_mode = _validate_runtime_mode(request.get("runtimeMode"))
        session = None
        if transport == "cli":
            if "session" not in request:
                _fail("session_required")
            session = _validate_session(request.get("session"))
        elif "session" in request:
            _fail("session_not_allowed")
        checks = _validate_checks(request.get("checks"), target)
        timeout_value = request.get("timeoutSeconds", 2)
        if isinstance(timeout_value, bool) or not isinstance(timeout_value, (int, float)):
            _fail("invalid_timeout")
        if timeout_value <= 0 or timeout_value > 30:
            _fail("invalid_timeout")
        try:
            timeout = float(timeout_value)
        except (TypeError, ValueError, OverflowError):
            _fail("invalid_timeout")
        max_runtime = _bounded_int(
            request.get("maxRuntimeSeconds", 1800),
            "maxRuntimeSeconds",
            minimum=60,
            maximum=14400,
        )
        actions = self._build_actions(
            transport=transport,
            mode=mode,
            target=target_raw,
            selector=selector,
            ready_selector=ready_selector,
            session=session,
        )
        service_results = self._service_results(checks, timeout)
        failed = [
            str(result["name"])
            for result in service_results
            if result["state"] != "ready"
        ]
        if failed:
            return {
                "version": PROTOCOL_VERSION,
                "status": "blocked",
                "classification": "readiness_blocked",
                "qaLaunchAllowed": False,
                "checks": service_results,
                "blockers": failed,
                "cleanup": {"runtimeStarted": False, "runtimeStopped": True},
            }

        try:
            existing_lease = self.runtime.read_json(self.config.lease_path)
        except Exception as error:
            raise _error_from_exception(error, phase="consumer_claim") from error
        if existing_lease:
            _fail("consumer_conflict", "consumer_claim", True)
        before = self._runtime_status()
        started_here = not bool(before.get("runtimeOwned"))
        started_generation: dict[str, int] | None = None
        claimed = False
        lease_id: str | None = None
        transaction_id = str(uuid.uuid4())
        try:
            self._call_runtime(
                "start_runtime",
                self.config,
                max(browser_runtime.MIN_STARTUP_TIMEOUT_SECONDS, timeout),
                headless=runtime_mode == "headless",
                max_runtime_seconds=max_runtime,
            )
            if started_here:
                started_generation = self._runtime_generation()
            status = self._settled_runtime_status(runtime_mode)
            if not (
                status.get("status") == "ready"
                and _is_true(status.get("cdpReady"))
                and status.get("mode") == runtime_mode
                and status.get("endpointKind") == "direct_cdp"
                and status.get("host") == "loopback"
            ):
                _fail("runtime_not_ready", "runtime_prepare", True)
            claim_result = self._call_runtime(
                "claim_consumer",
                self.config,
                CONSUMER,
                exclusive=True,
                owner="code_mode",
                owner_id=transaction_id,
            )
            claimed = True
            status = self._runtime_status()
            if status.get("consumer") != CONSUMER:
                _fail("lease_not_confirmed", "consumer_claim", True)
            claim = _require_object(claim_result, "lease_not_confirmed")
            candidate_lease_id = claim.get("leaseId")
            lease_id = candidate_lease_id if isinstance(candidate_lease_id, str) else ""
            if not isinstance(lease_id, str) or not re.fullmatch(
                r"[0-9a-f]{32}", lease_id
            ):
                _fail("lease_not_confirmed", "consumer_claim", True)
            identity = self._runtime_identity(expected_owner_id=transaction_id)
            if identity["leaseId"] != lease_id:
                _fail("lease_not_confirmed", "consumer_claim", True)
            state = {
                "version": PROTOCOL_VERSION,
                "transactionId": transaction_id,
                "status": "prepared",
                "consumer": CONSUMER,
                "transport": transport,
                "mode": mode,
                "runtimeMode": runtime_mode,
                "target": target,
                "surface": selector,
                "readySelector": ready_selector,
                "session": session,
                "port": status.get("port"),
                "checks": service_results,
                "checkSpecs": self._sanitized_check_specs(checks),
                "preflightTimeout": timeout,
                "runtimeIdentity": identity,
                "createdAt": int(time.time()),
            }
            self.store.write(state)
        except ProtocolError:
            if claimed:
                try:
                    self._call_runtime(
                        "release_consumer",
                        self.config,
                        CONSUMER,
                        lease_id=lease_id,
                    )
                except ProtocolError as cleanup_error:
                    raise ProtocolError(
                        "prepare_cleanup_failed", "runtime_cleanup", True
                    ) from cleanup_error
            else:
                self._cleanup_unclaimed(
                    started_here=started_here,
                    expected_generation=started_generation,
                )
            raise

        runtime_receipt = {
            "endpointKind": "direct_cdp",
            "host": "loopback",
            "port": status.get("port"),
            "mode": runtime_mode,
            "consumer": CONSUMER,
        }
        browser_profile = {"name": "browser_profile", "state": "ready"}
        checks_for_output = [
            *service_results,
            browser_profile,
            {"name": "designer_surface", "state": "pending"},
        ]
        return {
            "version": PROTOCOL_VERSION,
            "status": "prepared",
            "classification": "browser_ready_pending_surface",
            "qaLaunchAllowed": False,
            "transactionId": transaction_id,
            "transport": transport,
            "mode": mode,
            "runtime": runtime_receipt,
            "target": target,
            "actions": actions,
            "checks": checks_for_output,
            "blockers": ["designer_surface"],
            "cleanup": {
                "finishRequired": True,
                "order": ["finish", "retire_browser_session"],
                "finish": {
                    "version": PROTOCOL_VERSION,
                    "operation": "finish",
                    "transactionId": transaction_id,
                    "transport": transport,
                },
                "retireAfterFinish": (
                    {"tool": "agent_browser", "args": ["close"]}
                    if transport == "native"
                    else {
                        "command": "agent-browser",
                        "args": ["--session", session, "close"],
                    }
                ),
            },
        }

    def _prepare(self, request: dict[str, Any]) -> dict[str, object]:
        with self.store.lock():
            return self._prepare_locked(request)

    def _verify_transaction_locked(self, request: dict[str, Any]) -> dict[str, object]:
        state = self._load_active(request)
        surface = _validate_surface(
            request.get("surface"), str(state["target"]), str(state["surface"])
        )
        timeout_value = state.get("preflightTimeout", 2)
        if isinstance(timeout_value, bool) or not isinstance(
            timeout_value, (int, float)
        ):
            _fail("transaction_state_invalid", "transaction")
        try:
            runner_specs = _validate_checks(state["checkSpecs"], state["target"])
            fresh_checks = self._service_results(
                runner_specs, float(timeout_value)
            )
        except (ProtocolError, TypeError, ValueError, OverflowError) as error:
            raise ProtocolError("transaction_state_invalid", "transaction") from error
        state["checks"] = fresh_checks
        runtime_status = self._runtime_status()
        self._assert_runtime_identity(state)
        browser_state = "ready"
        if not (
            runtime_status.get("status") == "ready"
            and _is_true(runtime_status.get("runtimeOwned"))
            and _is_true(runtime_status.get("cdpReady"))
            and runtime_status.get("consumer") == CONSUMER
            and runtime_status.get("mode") == state.get("runtimeMode")
            and runtime_status.get("port") == state.get("port")
            and runtime_status.get("endpointKind") == "direct_cdp"
        ):
            browser_state = "error"

        if surface["errorPage"] or surface["document"] == "error":
            surface_state = "error"
        elif surface["document"] == "login" or not surface["authenticated"]:
            surface_state = "auth_required"
        elif surface["url"] != state["target"]:
            surface_state = "error"
        elif not (
            surface["document"] == "designer"
            and _is_designer_title(str(surface["url"]), str(surface["title"]))
            and surface["scopeObserved"]
        ):
            surface_state = "error"
        else:
            surface_state = "ready"

        service_results = [
            {"name": item["name"], "state": item["state"]}
            for item in fresh_checks
        ]
        checks = _gate_checks(
            service_results,
            browser_state=browser_state,
            surface_state=surface_state,
        )
        try:
            gate = readiness_gate.classify(
                checks,
                runtime_stopped=False,
                runtime_held=browser_state == "ready",
            )
        except ValueError:
            _fail("readiness_classification_failed", "readiness", True)
        if surface_state == "auth_required":
            classification = "auth_required"
        else:
            classification = gate["classification"]
        if gate["qaLaunchAllowed"]:
            state["status"] = "verified"
        state["lastVerification"] = classification
        self.store.write(state)
        return {
            "version": PROTOCOL_VERSION,
            "status": "verified" if gate["qaLaunchAllowed"] else "blocked",
            "classification": classification,
            "qaLaunchAllowed": gate["qaLaunchAllowed"],
            "transactionId": state["transactionId"],
            "readiness": gate,
        }

    def _verify_locked(self, request: dict[str, Any]) -> dict[str, object]:
        with self._runtime_lock():
            return self._verify_transaction_locked(request)

    def _verify(self, request: dict[str, Any]) -> dict[str, object]:
        with self.store.lock():
            return self._verify_locked(request)

    def _finish_locked(self, request: dict[str, Any]) -> dict[str, object]:
        transaction_id = request.get("transactionId")
        if not isinstance(transaction_id, str) or not TRANSACTION_ID.fullmatch(transaction_id):
            _fail("invalid_transaction")
        if not isinstance(request.get("transport"), str) or request.get(
            "transport"
        ) not in {"native", "cli"}:
            _fail("transport_required", "transaction")
        state = self.store.load()
        if state is None:
            with self._runtime_lock():
                runtime_status = self._runtime_status()
                stopped = _clean_stopped(runtime_status)
                if not stopped:
                    return {
                        "version": PROTOCOL_VERSION,
                        "status": "blocked",
                        "classification": "cleanup_failed",
                        "runtimeStopped": False,
                        "blockers": ["browser_runtime_cleanup"],
                    }
                return {
                    "version": PROTOCOL_VERSION,
                    "status": "finished",
                    "classification": "already_finished",
                    "alreadyFinished": True,
                    "runtimeStopped": stopped,
                }
        self._assert_transaction_id(request, state)
        recover_lost_runtime = False
        with self._runtime_lock():
            runtime_status = self._runtime_status()
            stopped = _clean_stopped(runtime_status)
            if stopped:
                self.store.remove()
                return {
                    "version": PROTOCOL_VERSION,
                    "status": "finished",
                    "classification": "finished",
                    "runtimeStopped": True,
                    "transactionId": state["transactionId"],
                    "cleanup": _public_runtime(runtime_status),
                }
            if (
                runtime_status.get("status") == "stopped"
                and _is_false(runtime_status.get("runtimeOwned"))
                and _is_false(runtime_status.get("cdpReady"))
                and _is_true(runtime_status.get("leasePresent"))
            ):
                if not self._lease_matches_transaction(state):
                    return {
                        "version": PROTOCOL_VERSION,
                        "status": "blocked",
                        "classification": "cleanup_failed",
                        "runtimeStopped": False,
                        "blockers": ["runtime_identity"],
                        "transactionId": state["transactionId"],
                    }
                recover_lost_runtime = True
        if not recover_lost_runtime:
            self._assert_runtime_identity(state)
        try:
            self._call_runtime(
                "release_consumer",
                self.config,
                CONSUMER,
                lease_id=state["runtimeIdentity"]["leaseId"],
            )
        except ProtocolError:
            raise
        with self._runtime_lock():
            runtime_status = self._runtime_status()
            stopped = _clean_stopped(runtime_status)
            if not stopped:
                return {
                    "version": PROTOCOL_VERSION,
                    "status": "blocked",
                    "classification": "cleanup_failed",
                    "runtimeStopped": False,
                    "blockers": ["browser_runtime_cleanup"],
                    "transactionId": state["transactionId"],
                }
            self.store.remove()
            return {
                "version": PROTOCOL_VERSION,
                "status": "finished",
                "classification": "finished",
                "runtimeStopped": True,
                "transactionId": state["transactionId"],
                "cleanup": _public_runtime(runtime_status),
            }

    def _finish(self, request: dict[str, Any]) -> dict[str, object]:
        with self.store.lock():
            return self._finish_locked(request)

    def _test_knowledge(self, request: dict[str, Any]) -> dict[str, object]:
        index_path = _local_path(request.get("indexPath"), "index_path")
        repo_path = _local_path(request.get("repoPath"), "repo_path")
        policy_path = _local_path(
            request.get("policyPath", str(test_corpus_index.DEFAULT_POLICY)),
            "policy_path",
        )
        if not index_path.is_file() or not repo_path.is_dir() or not policy_path.is_file():
            _fail("test_knowledge_input_missing", "test_knowledge")
        operation_id = request.get("operationId")
        category = request.get("category")
        if operation_id is not None:
            operation_id = _bounded_string(operation_id, "operation_id", maximum=120)
            if not re.fullmatch(r"[a-z0-9_.-]+", operation_id):
                _fail("invalid_operation_id")
        if category is not None:
            category = _bounded_string(category, "category", maximum=120)
            if not re.fullmatch(r"[a-z0-9_.-]+", category):
                _fail("invalid_category")
        limit = _bounded_int(request.get("limit", 5), "limit", minimum=1, maximum=5)
        view = request.get("view", "cards")
        if not isinstance(view, str) or view not in {"cards", "status"}:
            _fail("invalid_test_knowledge_view")
        if view == "status" and (operation_id is not None or category is not None):
            _fail("status_view_disallows_selector")
        try:
            policy = test_corpus_index.read_json(policy_path)
            index = test_corpus_index.read_json(index_path)
            freshness = test_corpus_index.validate_index(index, repo_path, policy)
        except Exception as error:
            _fail(getattr(error, "code", "test_knowledge_invalid"), "test_knowledge")
        cards = index["cards"]
        if view == "status":
            return {
                "version": PROTOCOL_VERSION,
                "status": "ok",
                "operation": "test_knowledge",
                "view": "status",
                "freshness": freshness,
                "counts": test_corpus_index.summarize_cards(cards),
                "portfolio": test_corpus_index.choose_portfolio(cards),
            }
        if operation_id is not None:
            cards = [card for card in cards if card["id"] == operation_id]
            if not cards:
                _fail("operation_not_found", "test_knowledge")
        if category is not None:
            cards = [card for card in cards if category in card["capabilities"]]
        if not cards:
            _fail("operation_category_empty", "test_knowledge")
        return {
            "version": PROTOCOL_VERSION,
            "status": "ok",
            "operation": "test_knowledge",
            "freshness": freshness,
            "operations": cards[:limit],
            "count": min(len(cards), limit),
            "total": len(cards),
        }

    def _scenario_plan(self, request: dict[str, Any]) -> dict[str, object]:
        scenario_path = _local_path(request.get("scenarioPath"), "scenario_path")
        operation_path = _local_path(request.get("operationPath"), "operation_path")
        policy_path = _local_path(
            request.get("policyPath", str(test_scenario_eval.POLICY_PATH)),
            "policy_path",
        )
        if not scenario_path.is_file() or not operation_path.is_file() or not policy_path.is_file():
            _fail("scenario_plan_input_missing", "scenario_plan")
        if request.get("dryRun") is not True:
            _fail("scenario_plan_requires_dry_run", "scenario_plan")
        try:
            policy = test_scenario_eval.load_json(policy_path)
            contract = test_scenario_eval.load_json(scenario_path)
            operation = test_scenario_eval.load_json(operation_path)
            adapter = test_scenario_eval.validate_contract(contract, policy)
            plan = test_scenario_eval.build_plan(contract, operation, adapter)
        except Exception as error:
            _fail(getattr(error, "code", "scenario_plan_invalid"), "scenario_plan")
        return {
            "version": PROTOCOL_VERSION,
            "status": "ok",
            "operation": "scenario_plan",
            "plan": plan,
        }

    def _capabilities(self, request: dict[str, Any]) -> dict[str, object]:
        if "id" not in request and "category" not in request:
            _fail("capability_selector_required")
        capability_id = request.get("id")
        category = request.get("category")
        if capability_id is not None:
            capability_id = _bounded_string(capability_id, "id", maximum=120)
            if not re.fullmatch(r"[a-z0-9_.-]+", capability_id):
                _fail("invalid_capability_selector")
        if category is not None:
            category = _bounded_string(category, "category", maximum=120)
            if not re.fullmatch(r"[a-z0-9_.-]+", category):
                _fail("invalid_capability_selector")
        offset = _bounded_int(request.get("offset", 0), "offset", minimum=0, maximum=1000)
        limit = _bounded_int(request.get("limit", 5), "limit", minimum=1, maximum=20)
        try:
            raw_catalog = json.loads(capability_catalog.CATALOG_PATH.read_text())
            catalog = capability_catalog.validate_catalog(
                raw_catalog, capability_catalog.CATALOG_PATH.parent
            )
        except (OSError, json.JSONDecodeError, ValueError):
            _fail("capability_catalog_invalid", "capability_lookup")
        entries = catalog["capabilities"]
        selected = [
            entry
            for entry in entries
            if (capability_id is None or entry["id"] == capability_id)
            and (category is None or entry["category"] == category)
        ]
        if capability_id is not None and not selected:
            _fail("capability_not_found", "capability_lookup")
        if not selected:
            _fail("capability_category_empty", "capability_lookup")
        page = selected[offset : offset + limit]
        result_entries = [
            {
                "id": entry["id"],
                "category": entry["category"],
                "implementation": entry["implementation"],
                "purpose": entry["purpose"],
                "inputs": entry["inputs"],
                "postconditions": entry["postconditions"],
                "sensitivity": entry["sensitivity"],
                "loadWhen": entry["loadWhen"],
            }
            for entry in page
        ]
        result: dict[str, object] = {
            "version": PROTOCOL_VERSION,
            "status": "ok",
            "operation": "capabilities",
            "capabilities": result_entries,
            "offset": offset,
            "count": len(result_entries),
            "total": len(selected),
        }
        if offset + len(page) < len(selected):
            result["nextOffset"] = offset + len(page)
        return result

    def handle(self, request: dict[str, Any]) -> dict[str, object]:
        operation = request.get("operation")
        if operation == "help":
            return {
                "version": PROTOCOL_VERSION,
                "status": "ok",
                "operation": "help",
                "operations": [
                    "help",
                    "capabilities",
                    "test_knowledge",
                    "scenario_plan",
                    "status",
                    "reconcile",
                    "prepare",
                    "verify",
                    "finish",
                ],
                "workflow": [
                    "prepare",
                    "native agent_browser work",
                    "verify",
                    "authorized work",
                    "finish in finally",
                    "retire browser session after successful finish",
                ],
                "transport": {
                    "preferred": "native",
                    "fallback": "cli",
                    "switching": "forbidden_after_prepare",
                },
                "output": "sanitized_bounded_json",
            }
        if operation == "capabilities":
            return self._capabilities(request)
        if operation == "test_knowledge":
            return self._test_knowledge(request)
        if operation == "scenario_plan":
            return self._scenario_plan(request)
        if operation == "status":
            return self._status(request)
        if operation == "reconcile":
            return self._reconcile(request)
        if operation == "prepare":
            return self._prepare(request)
        if operation == "verify":
            return self._verify(request)
        if operation == "finish":
            return self._finish(request)
        _fail("invalid_operation")


def error_result(error: ProtocolError) -> dict[str, object]:
    return {
        "version": PROTOCOL_VERSION,
        "status": "blocked",
        "error": {
            "code": error.code,
            "phase": error.phase,
            "retryable": error.retryable,
        },
    }


def emit(result: dict[str, object]) -> None:
    sanitized = sanitize_evidence.sanitize(result)
    payload = json.dumps(sanitized, sort_keys=True, separators=(",", ":"))
    if len(payload.encode("utf-8")) > MAX_OUTPUT_BYTES:
        payload = json.dumps(
            error_result(ProtocolError("output_too_large", "output")),
            sort_keys=True,
            separators=(",", ":"),
        )
    print(payload)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"help", "--help"}:
        raw = "help"
    else:
        try:
            raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1).decode("utf-8")
        except UnicodeDecodeError:
            emit(error_result(ProtocolError("invalid_encoding")))
            return 0
    try:
        request = parse_request(raw)
        result = DesignerCodeMode().handle(request)
    except Exception as error:
        result = error_result(
            error
            if isinstance(error, ProtocolError)
            else ProtocolError("internal_error", "dispatch", True)
        )
    emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
