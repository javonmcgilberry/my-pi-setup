#!/usr/bin/env python3
"""Fail when a generated workspace module is older than its source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def verify(source: Path, built: Path) -> dict[str, object]:
    if not source.is_file():
        raise ValueError(f"Source file does not exist: {source}")
    if not built.is_file():
        raise ValueError(f"Built file does not exist: {built}")

    current = built.stat().st_mtime_ns >= source.stat().st_mtime_ns
    return {
        "built": str(built),
        "current": current,
        "source": str(source),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--built", type=Path, required=True)
    args = parser.parse_args()

    try:
        result = verify(args.source, args.built)
    except ValueError as error:
        print(str(error))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["current"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
