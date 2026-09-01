#!/usr/bin/env python3
"""Sanitize and bound JSON evidence before it leaves the local machine."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[REDACTED]"
SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "storage",
    "token",
)
MAX_STRING = 2000
MAX_ITEMS = 100
MAX_DEPTH = 12
UNSAFE_TEXT = re.compile(
    r"(?:\bbearer\b|\bauthorization\b|\bcookie\b|\bcredential\b|"
    r"\bpassword\b|\bsecret\b|\btoken\b|"
    r"(?:^|[\s=])/(?:Users|home|private)(?:[/\s]|$)|"
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)",
    re.IGNORECASE,
)


def sanitize_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https", "ws", "wss"}:
        return value
    query = [
        (key, REDACTED if sensitive_key(key) else item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def sensitive_key(value: str) -> bool:
    lowered = value.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def is_safe_evidence_text(value: str) -> bool:
    """Return whether a durable report string is already sanitized."""
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        return False
    parts = urlsplit(value)
    if parts.scheme in {"http", "https", "ws", "wss"}:
        if parts.username or parts.password or parts.fragment:
            return False
        if UNSAFE_TEXT.search(parts.netloc) or UNSAFE_TEXT.search(parts.path):
            return False
        for key, item in parse_qsl(parts.query, keep_blank_values=True):
            if sensitive_key(key) and item != REDACTED:
                return False
            if item != REDACTED and UNSAFE_TEXT.search(item):
                return False
        return True
    if UNSAFE_TEXT.search(value):
        return False
    return True


def assert_safe_evidence(value: object, field: str = "evidence") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not is_safe_evidence_text(key):
                raise ValueError(f"{field} contains an unsafe key")
            assert_safe_evidence(item, f"{field}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_safe_evidence(item, f"{field}[{index}]")
    elif isinstance(value, str) and not is_safe_evidence_text(value):
        raise ValueError(f"{field} contains unsanitized text")


def sanitize(value: object, depth: int = 0) -> object:
    if depth >= MAX_DEPTH:
        return "[TRUNCATED_DEPTH]"
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_ITEMS:
                result["[TRUNCATED_ITEMS]"] = len(value) - MAX_ITEMS
                break
            result[key] = REDACTED if sensitive_key(key) else sanitize(item, depth + 1)
        return result
    if isinstance(value, list):
        items = [sanitize(item, depth + 1) for item in value[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            items.append({"[TRUNCATED_ITEMS]": len(value) - MAX_ITEMS})
        return items
    if isinstance(value, str):
        bounded = value if len(value) <= MAX_STRING else value[:MAX_STRING] + "[TRUNCATED]"
        return sanitize_url(bounded)
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.path:
            value = json.loads(args.path.read_text())
        else:
            value = json.load(sys.stdin)
    except (OSError, json.JSONDecodeError) as error:
        print(f"Unable to read JSON evidence: {error}", file=sys.stderr)
        return 2
    print(json.dumps(sanitize(value), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
