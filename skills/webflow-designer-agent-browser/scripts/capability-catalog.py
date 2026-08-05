#!/usr/bin/env python3
"""Validate and render the deferred Webflow Designer capability catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).parent.parent / "capabilities.json"
ENTRY_FIELDS = {
    "id", "category", "implementation", "owner", "purpose", "inputs",
    "postconditions", "sensitivity", "maturity", "disposition", "loadWhen",
}
DISPOSITIONS = {"keep", "merge", "delete"}
MATURITY = {"provisional", "stable", "exceptional", "deprecated"}


def slug(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 120:
        raise ValueError(f"{field} must contain 1 to 120 characters")
    if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_." for character in value):
        raise ValueError(f"{field} must be a lowercase semantic identifier")
    return value


def validate_catalog(value: object, root: Path) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"version", "capabilities"}:
        raise ValueError("catalog must contain version and capabilities")
    if value["version"] != 1 or not isinstance(value["capabilities"], list):
        raise ValueError("catalog version or capabilities is unsupported")
    seen = set()
    normalized = []
    for index, entry in enumerate(value["capabilities"]):
        if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
            raise ValueError(f"capabilities[{index}] has an unsupported shape")
        capability_id = slug(entry["id"], f"capabilities[{index}].id")
        if capability_id in seen:
            raise ValueError(f"duplicate capability id: {capability_id}")
        seen.add(capability_id)
        slug(entry["category"], f"capabilities[{index}].category")
        slug(entry["owner"], f"capabilities[{index}].owner")
        if entry["disposition"] not in DISPOSITIONS:
            raise ValueError(f"capabilities[{index}].disposition is unsupported")
        if entry["maturity"] not in MATURITY:
            raise ValueError(f"capabilities[{index}].maturity is unsupported")
        for field in ("purpose", "loadWhen", "sensitivity"):
            if not isinstance(entry[field], str) or not entry[field].strip():
                raise ValueError(f"capabilities[{index}].{field} is required")
        for field in ("inputs", "postconditions"):
            if not isinstance(entry[field], list) or not entry[field]:
                raise ValueError(f"capabilities[{index}].{field} must be non-empty")
            for item in entry[field]:
                slug(item, f"capabilities[{index}].{field}")
        implementation = root / entry["implementation"]
        if not implementation.is_file():
            raise ValueError(f"missing capability implementation: {entry['implementation']}")
        normalized.append(entry)
    return {"version": 1, "capabilityCount": len(normalized), "capabilities": normalized}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "list"))
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--category")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        catalog = validate_catalog(
            json.loads(args.catalog.read_text()), args.catalog.parent
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Unable to load capability catalog: {error}", file=sys.stderr)
        return 2
    if args.command == "validate":
        print(json.dumps({"valid": True, "capabilityCount": catalog["capabilityCount"]}))
        return 0
    entries = [
        {
            "id": entry["id"],
            "category": entry["category"],
            "maturity": entry["maturity"],
            "disposition": entry["disposition"],
            "loadWhen": entry["loadWhen"],
        }
        for entry in catalog["capabilities"]
        if args.category is None or entry["category"] == args.category
    ]
    print(json.dumps({"capabilities": entries}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
