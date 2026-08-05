#!/usr/bin/env python3
"""Discover Webflow Designer tabs from a local Chrome CDP endpoint."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SAFE_QUERY_KEYS = {"pageId", "simulateRole"}
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
ATTACHMENT_CONFIG_VERSION = 1


def sanitize_url(value: str) -> str:
    parts = urlsplit(value)
    safe_query = []
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        safe_query.append((key, item if key in SAFE_QUERY_KEYS else "[REDACTED]"))
    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{parts.port}" if parts.port is not None else host
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(safe_query), ""))


def is_designer_url(value: str) -> bool:
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    return (
        parts.scheme in {"http", "https"}
        and parts.username is None
        and parts.password is None
        and (
            host == "design.webflow.com"
            or host.endswith(".design.wfdev.io")
            or host == "design.wfdev.io"
            or host == "wfdev.io"
        )
    )


def validate_attachment_config(config: object) -> dict[str, object]:
    """Validate non-secret settings for a standing local attachment plan."""
    if not isinstance(config, dict):
        raise ValueError("attachment config must be an object")
    if config.get("version") != ATTACHMENT_CONFIG_VERSION:
        raise ValueError("attachment config has an unsupported version")
    if config.get("authorization") != "always_localhost":
        raise ValueError(
            "attachment config must explicitly authorize localhost debugging"
        )

    host = config.get("host")
    if not isinstance(host, str) or host.lower() not in LOOPBACK_HOSTS:
        raise ValueError("attachment endpoint must use a loopback host")

    port = config.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("attachment endpoint port must be between 1 and 65535")

    endpoint_kind = config.get("endpointKind", "direct_cdp")
    if endpoint_kind not in {
        "direct_cdp",
        "chrome_remote_debugging_broker"
    }:
        raise ValueError("attachment endpoint kind is unsupported")

    return {
        "version": ATTACHMENT_CONFIG_VERSION,
        "authorization": "always_localhost",
        "port": port,
        "endpointKind": endpoint_kind,
    }


def build_attachment_plan(
    config: object,
    *,
    endpoint_kind: str | None = None,
    transport: str = "native",
) -> dict[str, object]:
    """Return sanitized next actions for the available browser transport."""
    validated = validate_attachment_config(config)
    kind = endpoint_kind or validated["endpointKind"]
    if kind not in {"direct_cdp", "chrome_remote_debugging_broker"}:
        raise ValueError("attachment endpoint kind is unsupported")

    if kind == "direct_cdp":
        if transport not in {"native", "cli"}:
            raise ValueError("direct CDP transport must be native or cli")
        action = (
            {
                "tool": "agent_browser",
                "sessionMode": "fresh",
                "args": ["connect", str(validated["port"])],
            }
            if transport == "native"
            else {
                "command": "agent-browser",
                "args": ["connect", str(validated["port"])],
            }
        )
        return {
            "classification": "attachment_plan",
            "endpointKind": "direct_cdp",
            "transport": transport,
            "authorization": "standing_localhost_authorization",
            "conversationPermissionRequired": False,
            "chromeConfirmationRequired": False,
            "exclusiveOwnershipRequired": True,
            "actions": [action],
        }

    return {
        "classification": "attachment_plan",
        "transport": "chrome_devtools_mcp",
        "authorization": "standing_localhost_authorization",
        "conversationPermissionRequired": False,
        "chromeConfirmationRequired": True,
        "actions": [
            {
                "tool": "chrome_devtools",
                "payload": {
                    "tool": "chrome_devtools_list_pages",
                    "args": {},
                },
            }
        ],
    }


def verify_attachment_surface(
    surface: object,
    *,
    expected_title: str | None = None,
    expected_runtime_mode: str,
) -> dict[str, object]:
    """Reject managed fallbacks and return proof without page-sensitive values."""
    if expected_runtime_mode not in {"headless", "headed"}:
        raise ValueError("expected runtime mode must be headless or headed")
    if not isinstance(surface, dict):
        raise ValueError("attachment surface must be an object")

    user_agent = surface.get("userAgent")
    if not isinstance(user_agent, str) or not user_agent:
        raise ValueError("attachment surface is missing a user agent")
    is_headless = "headlesschrome" in user_agent.lower()
    if is_headless and expected_runtime_mode != "headless":
        raise ValueError("HeadlessChrome managed fallback is not an attached browser")
    if not is_headless and expected_runtime_mode == "headless":
        raise ValueError("attached browser is not the expected headless runtime")

    tabs = surface.get("tabs")
    if not isinstance(tabs, list):
        raise ValueError("attachment surface is missing tabs")
    if not tabs:
        raise ValueError("attachment surface contains no tabs")

    normalized_tabs = []
    for tab in tabs:
        if not isinstance(tab, dict):
            raise ValueError("attachment surface contains an invalid tab")
        title = tab.get("title")
        url = tab.get("url")
        if not isinstance(title, str) or not isinstance(url, str):
            raise ValueError("attachment surface contains an incomplete tab")
        normalized_tabs.append((title, url))

    if all(url == "about:blank" for _title, url in normalized_tabs):
        raise ValueError("attachment surface contains only blank managed tabs")

    expected_match = (
        expected_title is not None
        and any(title == expected_title for title, _url in normalized_tabs)
    )
    if expected_title is not None and not expected_match:
        raise ValueError("expected attached browser tab was not found")

    return {
        "classification": "attached_browser_verified",
        "tabCount": len(normalized_tabs),
        "expectedTabMatched": expected_match,
        "runtimeMode": expected_runtime_mode,
        "managedFallbackRejected": expected_runtime_mode == "headed",
    }


def validate_ownership_url(value: str) -> str:
    if not is_designer_url(value):
        raise ValueError("ownership URL must identify a Webflow Designer")
    unsafe_keys = {
        key
        for key, _item in parse_qsl(
            urlsplit(value).query,
            keep_blank_values=True,
        )
        if key not in SAFE_QUERY_KEYS
    }
    if unsafe_keys:
        raise ValueError(
            f"ownership URL contains unsupported query keys: {sorted(unsafe_keys)}"
        )
    return sanitize_url(value)


def fetch_json(url: str, timeout: float) -> object:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def discover(host: str, port: int, timeout: float) -> dict[str, object]:
    if host.lower() not in LOOPBACK_HOSTS:
        raise ValueError("CDP discovery host must be loopback")
    base = f"http://{host}:{port}"
    version = fetch_json(f"{base}/json/version", timeout)
    targets = fetch_json(f"{base}/json/list", timeout)
    if not isinstance(version, dict) or not isinstance(targets, list):
        raise ValueError("CDP endpoint returned an unexpected response shape")

    tabs = []
    for target in targets:
        if not isinstance(target, dict) or target.get("type") != "page":
            continue
        url = target.get("url")
        if not isinstance(url, str) or not is_designer_url(url):
            continue
        title = target.get("title")
        tabs.append(
            {
                "id": target.get("id"),
                "title": title[:200] if isinstance(title, str) else "",
                "sanitizedUrl": sanitize_url(url),
            }
        )

    return {
        "browser": version.get("Browser"),
        "protocolVersion": version.get("Protocol-Version"),
        "endpoint": f"{host}:{port}",
        "designerTabs": tabs,
    }


def diagnose_ownership(
    sessions: list[dict[str, object]],
    expected_url: str,
    current_session: str,
    *,
    unavailable_sessions: int = 0,
) -> dict[str, object]:
    sanitized_url = validate_ownership_url(expected_url)
    matches = []
    for session in sessions:
        name = session.get("name")
        tabs = session.get("tabs")
        if not isinstance(name, str) or not isinstance(tabs, list):
            raise ValueError("ownership session data has an unexpected shape")
        for tab in tabs:
            if not isinstance(tab, dict):
                raise ValueError("ownership tab data has an unexpected shape")
            url = tab.get("url")
            if isinstance(url, str) and sanitize_url(url) == sanitized_url:
                matches.append(name)

    current_controls = current_session in matches
    another_controls = any(name != current_session for name in matches)
    ownership_known = unavailable_sessions == 0 and len(matches) == 1
    if unavailable_sessions:
        recommendation = "complete_session_inspection"
    elif len(matches) > 1:
        recommendation = "resolve_ambiguous_matches"
    elif current_controls:
        recommendation = "reuse_current_session"
    elif another_controls:
        recommendation = "orchestrator_handoff"
    else:
        recommendation = "no_known_owner"

    return {
        "ownershipDiagnostic": {
            "mode": "read_only",
            "designerTab": {
                "sanitizedUrl": sanitized_url,
                "exactMatchCount": len(matches),
            },
            "currentSessionControls": current_controls,
            "anotherKnownSessionControls": another_controls,
            "ownershipKnown": ownership_known,
            "sessionsInspected": len(sessions),
            "sessionsUnavailable": unavailable_sessions,
            "recommendation": recommendation,
        }
    }


def run_agent_browser_json(command: list[str]) -> object:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("agent-browser session inspection timed out") from error
    if completed.returncode:
        raise RuntimeError("agent-browser session inspection failed")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("agent-browser returned invalid JSON") from error


def inspect_agent_browser_sessions() -> tuple[list[dict[str, object]], int]:
    if shutil.which("agent-browser") is None:
        raise RuntimeError("agent-browser is not installed or not on PATH")
    listing = run_agent_browser_json(["agent-browser", "session", "list", "--json"])
    if not isinstance(listing, dict):
        raise RuntimeError("agent-browser session list has an unexpected shape")
    data = listing.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
        raise RuntimeError("agent-browser session list has an unexpected shape")

    sessions = []
    unavailable = 0
    for name in data["sessions"]:
        if not isinstance(name, str):
            unavailable += 1
            continue
        try:
            tab_listing = run_agent_browser_json(
                [
                    "agent-browser",
                    "--session",
                    name,
                    "tab",
                    "list",
                    "--json",
                ]
            )
        except RuntimeError:
            unavailable += 1
            continue
        if not isinstance(tab_listing, dict):
            unavailable += 1
            continue
        tab_data = tab_listing.get("data")
        if not isinstance(tab_data, dict) or not isinstance(
            tab_data.get("tabs"),
            list,
        ):
            unavailable += 1
            continue
        sessions.append({"name": name, "tabs": tab_data["tabs"]})
    return sessions, unavailable


def load_ownership_fixture(path: Path) -> tuple[list[dict[str, object]], int]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or set(value) != {
        "sessions",
        "unavailable_sessions",
    }:
        raise ValueError(
            "ownership fixture must contain sessions and unavailable_sessions"
        )
    sessions = value["sessions"]
    unavailable = value["unavailable_sessions"]
    if (
        not isinstance(sessions, list)
        or not isinstance(unavailable, int)
        or isinstance(unavailable, bool)
        or unavailable < 0
    ):
        raise ValueError("ownership fixture has an unexpected shape")
    return sessions, unavailable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9333)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--ownership-url")
    parser.add_argument("--current-session")
    parser.add_argument("--ownership-fixture", type=Path)
    parser.add_argument("--attachment-config", type=Path)
    parser.add_argument("--surface-fixture", type=Path)
    parser.add_argument("--expected-title")
    parser.add_argument(
        "--expected-runtime-mode",
        choices=("headless", "headed"),
    )
    parser.add_argument(
        "--endpoint-kind",
        choices=(
            "direct_cdp",
            "chrome_remote_debugging_broker",
        ),
    )
    parser.add_argument("--transport", choices=("native", "cli"), default="native")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.attachment_config:
            config = json.loads(args.attachment_config.read_text())
            if args.surface_fixture:
                if not args.expected_runtime_mode:
                    raise ValueError(
                        "--expected-runtime-mode is required with --surface-fixture"
                    )
                surface = json.loads(args.surface_fixture.read_text())
                result = verify_attachment_surface(
                    surface,
                    expected_title=args.expected_title,
                    expected_runtime_mode=args.expected_runtime_mode,
                )
            else:
                result = build_attachment_plan(
                    config,
                    endpoint_kind=args.endpoint_kind,
                    transport=args.transport,
                )
        elif args.ownership_url:
            if not args.current_session:
                raise ValueError(
                    "--current-session is required with --ownership-url"
                )
            if args.ownership_fixture:
                sessions, unavailable = load_ownership_fixture(
                    args.ownership_fixture
                )
            else:
                if args.transport == "native":
                    raise ValueError(
                        "--ownership-fixture is required for native ownership diagnostics"
                    )
                sessions, unavailable = inspect_agent_browser_sessions()
            result = diagnose_ownership(
                sessions,
                args.ownership_url,
                args.current_session,
                unavailable_sessions=unavailable,
            )
        else:
            if args.current_session or args.ownership_fixture:
                raise ValueError(
                    "--ownership-url is required for ownership diagnostics"
                )
            result = discover(args.host, args.port, args.timeout)
    except (
        OSError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as error:
        print(json.dumps({"error": str(error), "endpoint": f"{args.host}:{args.port}"}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
