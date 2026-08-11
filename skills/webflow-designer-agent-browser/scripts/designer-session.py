#!/usr/bin/env python3
"""Run a bounded agent-browser Designer session bootstrap."""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, urlsplit
from typing import cast

DEFAULT_READY_SELECTOR = "body"
SENSITIVE_QUERY_PARTS = ("token", "secret", "password", "credential", "code")
SERVICE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$")


def reject_sensitive_url(value: str) -> None:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Designer URL must use HTTP or HTTPS")
    if parts.username is not None or parts.password is not None:
        raise ValueError("Refusing URL with user information")
    host = parts.hostname.lower()
    if not (
        host in {"design.webflow.com", "design.wfdev.io", "wfdev.io", "localhost", "127.0.0.1", "::1"}
        or host.endswith(".design.wfdev.io")
    ):
        raise ValueError("URL is not an approved Designer host")
    for key, _item in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if any(part in lowered for part in SENSITIVE_QUERY_PARTS):
            raise ValueError(f"Refusing URL with sensitive query key: {key}")


def validate_service_label(value: str) -> str:
    if not SERVICE_LABEL.fullmatch(value):
        raise ValueError(
            "service labels must use letters, digits, spaces, hyphens, or underscores"
        )
    lowered = value.lower()
    if any(part in lowered for part in SENSITIVE_QUERY_PARTS):
        raise ValueError("service label contains a sensitive term")
    return value


def validate_timeout(value: str) -> float:
    timeout = float(value)
    if timeout <= 0 or timeout > 30:
        raise argparse.ArgumentTypeError("timeout must be greater than 0 and at most 30")
    return timeout


def build_service_checks(args: argparse.Namespace) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for label, host, port_text in args.tcp_service:
        validate_service_label(label)
        if host.lower() not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError(f"{label}: TCP host must be loopback")
        port = int(port_text)
        if port < 1 or port > 65535:
            raise ValueError(f"{label}: TCP port must be between 1 and 65535")
        checks.append(
            {
                "label": label,
                "kind": "tcp",
                "host": host,
                "port": port,
            }
        )

    for label, url, status_text in args.http_service:
        validate_service_label(label)
        reject_sensitive_url(url)
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError(f"{label}: HTTP endpoint must be an http or https URL")
        if parts.username or parts.password:
            raise ValueError(f"{label}: HTTP endpoint must not contain credentials")
        status = int(status_text)
        if status < 100 or status > 599:
            raise ValueError(f"{label}: HTTP status must be between 100 and 599")
        checks.append(
            {
                "label": label,
                "kind": "http",
                "url": url,
                "status": status,
            }
        )
    return checks


def public_check(
    check: dict[str, object],
    *,
    ready: bool | None,
    observed: str,
) -> dict[str, object]:
    expected = (
        "tcp_listener"
        if check["kind"] == "tcp"
        else f"http_status_{check['status']}"
    )
    return {
        "label": check["label"],
        "kind": check["kind"],
        "required": True,
        "ready": ready,
        "expected": expected,
        "observed": observed,
    }


def check_service(
    check: dict[str, object],
    timeout: float,
) -> dict[str, object]:
    if check["kind"] == "tcp":
        host = cast(str, check["host"])
        port = cast(int, check["port"])
        try:
            connection = socket.create_connection(
                (host, port),
                timeout=timeout,
            )
            connection.close()
        except (OSError, TimeoutError):
            return public_check(check, ready=False, observed="connection_failed")
        return public_check(check, ready=True, observed="listener_available")

    request = urllib.request.Request(
        cast(str, check["url"]),
        headers={"Accept": "*/*"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            observed_status = response.status
    except urllib.error.HTTPError as error:
        observed_status = error.code
    except (OSError, TimeoutError, urllib.error.URLError):
        return public_check(check, ready=False, observed="connection_failed")

    return public_check(
        check,
        ready=observed_status == check["status"],
        observed=f"http_status_{observed_status}",
    )


def run_preflight(
    checks: list[dict[str, object]],
    timeout: float,
) -> dict[str, object]:
    results = [check_service(check, timeout) for check in checks]
    ready = all(result["ready"] for result in results)
    return {
        "classification": (
            "prerequisites_ready" if ready else "prerequisite_unavailable"
        ),
        "ready": ready,
        "checks": results,
    }


def describe_preflight(checks: list[dict[str, object]]) -> dict[str, object]:
    return {
        "classification": "not_run",
        "ready": None,
        "checks": [
            public_check(check, ready=None, observed="not_run")
            for check in checks
        ],
    }


def build_commands(args: argparse.Namespace) -> list[dict[str, object]]:
    commands: list[dict[str, object]] = []
    if args.port is not None and not 1 <= args.port <= 65535:
        raise ValueError("--port must be between 1 and 65535")
    if args.transport == "cli" and not args.session:
        raise ValueError("--session is required for cli transport")

    def browser_action(
        action_args: list[str], *, fresh: bool = False
    ) -> dict[str, object]:
        if args.transport == "native":
            action: dict[str, object] = {
                "tool": "agent_browser",
                "args": action_args,
            }
            if fresh:
                action["sessionMode"] = "fresh"
            return action
        if args.transport == "cli":
            return {
                "command": "agent-browser",
                "args": ["--session", args.session, *action_args],
            }
        raise ValueError("transport must be native or cli")

    if args.mode == "attached":
        if not args.port:
            raise ValueError("--port is required for attached direct CDP mode")
        commands.append(browser_action(["connect", str(args.port)], fresh=True))
        commands.append(browser_action(["tab"]))
        if args.tab:
            commands.append(browser_action(["tab", args.tab]))
    else:
        if not args.url:
            raise ValueError("--url is required for isolated mode")
        reject_sensitive_url(args.url)
        launch = []
        if args.user_agent:
            launch.extend(["--user-agent", args.user_agent])
        host = (urlsplit(args.url).hostname or "").lower()
        if host in {"127.0.0.1", "::1", "localhost"}:
            launch.append("--ignore-https-errors")
        launch.extend(["open", args.url])
        commands.append(browser_action(launch, fresh=True))

    commands.append(browser_action(["wait", args.ready_selector]))
    commands.append(browser_action(["snapshot", "-i", "-c", "-s", args.surface]))
    return commands


def run(
    commands: list[dict[str, object]],
    checks: list[dict[str, object]],
    *,
    timeout: float,
    preflight_only: bool,
    dry_run: bool,
    transport: str,
) -> int:
    if transport == "native":
        browser_cleanup = {"tool": "agent_browser", "args": ["close"]}
    elif commands:
        browser_cleanup = {
            "command": "agent-browser",
            "args": ["--session", commands[0]["args"][1], "close"],
        }
    else:
        browser_cleanup = {
            "command": "agent-browser",
            "args": ["close"],
            "when": "session-created",
        }
    cleanup = [
        browser_cleanup,
        {
            "helper": "scripts/browser-runtime.py",
            "args": ["release", "--consumer", "agent_browser"],
            "when": "attached",
        },
        {
            "helper": "scripts/browser-runtime.py",
            "args": ["status"],
            "require": {
                "runtimeOwned": False,
                "cdpReady": False,
                "consumer": None,
                "status": "stopped",
            },
            "when": "attached",
        },
    ]
    if checks and not dry_run:
        preflight = run_preflight(checks, timeout)
        if not preflight["ready"]:
            print(
                json.dumps(
                    {"preflight": preflight, "cleanup": cleanup[1:]},
                    sort_keys=True,
                )
            )
            return 1
    else:
        preflight = describe_preflight(checks)
    print(
        json.dumps(
            {
                "transport": transport,
                "preflight": preflight,
                "actions": [] if preflight_only else commands,
                "cleanup": [] if preflight_only else cleanup,
            },
            indent=2,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("attached", "isolated"))
    parser.add_argument("--transport", choices=("native", "cli"), default="native")
    parser.add_argument("--session")
    parser.add_argument("--port", type=int)
    parser.add_argument("--tab")
    parser.add_argument("--url")
    parser.add_argument("--ready-selector", default=DEFAULT_READY_SELECTOR)
    parser.add_argument("--surface", default="body")
    parser.add_argument("--user-agent")
    parser.add_argument(
        "--tcp-service",
        action="append",
        default=[],
        nargs=3,
        metavar=("LABEL", "HOST", "PORT"),
    )
    parser.add_argument(
        "--http-service",
        action="append",
        default=[],
        nargs=3,
        metavar=("LABEL", "URL", "STATUS"),
    )
    parser.add_argument(
        "--preflight-timeout",
        type=validate_timeout,
        default=2.0,
    )
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        checks = build_service_checks(args)
        if args.preflight_only and not checks:
            raise ValueError(
                "at least one explicit service check is required"
            )
        commands = [] if args.preflight_only else build_commands(args)
    except (TypeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return run(
        commands,
        checks,
        timeout=args.preflight_timeout,
        preflight_only=args.preflight_only,
        dry_run=args.dry_run,
        transport=args.transport,
    )


if __name__ == "__main__":
    sys.exit(main())
