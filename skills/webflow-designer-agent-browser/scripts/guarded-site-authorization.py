#!/usr/bin/env python3
"""Plan and verify exact-site Webflow authorization from sanitized surfaces."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PAGE_FIELDS = {"checkboxes", "has_next"}
CHECKBOX_FIELDS = {"value", "checked"}
SURFACE_FIELDS = {"pages", "post_selection", "callback_state"}
POST_SELECTION_FIELDS = {"selected_values", "authorize_enabled"}
CALLBACK_STATE_FIELDS = {"site_id"}


def require_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def validate_surface(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != SURFACE_FIELDS:
        raise ValueError(
            f"surface must contain exactly {sorted(SURFACE_FIELDS)}"
        )
    pages = value["pages"]
    if not isinstance(pages, list) or not pages:
        raise ValueError("pages must be a non-empty array")
    for page_index, page in enumerate(pages):
        if not isinstance(page, dict) or set(page) != PAGE_FIELDS:
            raise ValueError(
                f"pages[{page_index}] must contain exactly {sorted(PAGE_FIELDS)}"
            )
        if not isinstance(page["has_next"], bool):
            raise ValueError(f"pages[{page_index}].has_next must be a boolean")
        checkboxes = page["checkboxes"]
        if not isinstance(checkboxes, list):
            raise ValueError(f"pages[{page_index}].checkboxes must be an array")
        for checkbox_index, checkbox in enumerate(checkboxes):
            if not isinstance(checkbox, dict) or set(checkbox) != CHECKBOX_FIELDS:
                raise ValueError(
                    f"pages[{page_index}].checkboxes[{checkbox_index}] "
                    f"must contain exactly {sorted(CHECKBOX_FIELDS)}"
                )
            require_identifier(
                checkbox["value"],
                f"pages[{page_index}].checkboxes[{checkbox_index}].value",
            )
            if not isinstance(checkbox["checked"], bool):
                raise ValueError(
                    f"pages[{page_index}].checkboxes[{checkbox_index}].checked "
                    "must be a boolean"
                )
    return value


def locate_exact_site(
    pages: list[dict[str, object]],
    expected_site_id: str,
) -> dict[str, object]:
    checked_values = []
    checkbox_count = 0
    load_next_actions = 0
    exact_matches = []

    for page_index, page in enumerate(pages):
        checkboxes = page["checkboxes"]
        for checkbox_index, checkbox in enumerate(checkboxes):
            checkbox_count += 1
            if checkbox["checked"]:
                checked_values.append(checkbox["value"])
            if checkbox["value"] == expected_site_id:
                exact_matches.append((page_index, checkbox_index))

        if len(exact_matches) > 1:
            raise ValueError("authorization surface contains duplicate exact matches")
        if exact_matches:
            if page_index != len(pages) - 1:
                raise ValueError(
                    "authorization transcript must stop after the exact match"
                )
            break
        if page["has_next"]:
            if page_index == len(pages) - 1:
                raise ValueError(
                    "authorization transcript ended before the next visible page"
                )
            load_next_actions += 1
        else:
            if page_index != len(pages) - 1:
                raise ValueError(
                    "authorization transcript contains pages after pagination ended"
                )
            break

    if not exact_matches:
        raise ValueError("authorization surface contains no exact site match")
    page_index, checkbox_index = exact_matches[0]
    return {
        "page_index": page_index,
        "checkbox_index": checkbox_index,
        "checkbox_count": checkbox_count,
        "checked_values": checked_values,
        "load_next_actions": load_next_actions,
    }


def verify_post_selection(
    value: object,
    expected_site_id: str,
) -> None:
    if not isinstance(value, dict) or set(value) != POST_SELECTION_FIELDS:
        raise ValueError(
            f"post_selection must contain exactly {sorted(POST_SELECTION_FIELDS)}"
        )
    selected_values = value["selected_values"]
    if not isinstance(selected_values, list) or selected_values != [expected_site_id]:
        raise ValueError("post-selection must contain only the expected site")
    if value["authorize_enabled"] is not True:
        raise ValueError("authorization action is not enabled after selection")


def verify_callback_state(
    value: object,
    expected_site_id: str,
) -> None:
    if not isinstance(value, dict) or set(value) != CALLBACK_STATE_FIELDS:
        raise ValueError(
            f"callback_state must contain exactly {sorted(CALLBACK_STATE_FIELDS)}"
        )
    if value["site_id"] != expected_site_id:
        raise ValueError("callback state does not contain the expected site")


def review_authorization(
    value: object,
    expected_site_id: str,
    *,
    allow_selection: bool,
    allow_authorization: bool,
) -> dict[str, object]:
    require_identifier(expected_site_id, "expected site ID")
    surface = validate_surface(value)
    if allow_authorization and not allow_selection:
        raise ValueError("authorization requires explicit selection permission")
    if not allow_selection and surface["post_selection"] is not None:
        raise ValueError(
            "post_selection requires explicit selection permission"
        )
    if not allow_authorization and surface["callback_state"] is not None:
        raise ValueError(
            "callback_state requires explicit authorization permission"
        )

    location = locate_exact_site(surface["pages"], expected_site_id)
    unexpected_checked = [
        checked
        for checked in location["checked_values"]
        if checked != expected_site_id
    ]
    if allow_selection and unexpected_checked:
        raise ValueError("baseline contains an unexpected selected site")

    selection_verified = False
    if allow_selection:
        verify_post_selection(surface["post_selection"], expected_site_id)
        selection_verified = True

    callback_verified = False
    if allow_authorization:
        verify_callback_state(surface["callback_state"], expected_site_id)
        callback_verified = True

    return {
        "runtimeBoundary": "browser_actions_not_executed",
        "baseline": {
            "captured": True,
            "pagesInspected": location["page_index"] + 1,
            "checkboxesInspected": location["checkbox_count"],
            "initiallySelectedCount": len(location["checked_values"]),
        },
        "pagination": {
            "loadNextActions": location["load_next_actions"],
            "stoppedAtExactMatch": True,
        },
        "selection": {
            "exactMatchCount": 1,
            "targetPageIndex": location["page_index"],
            "targetCheckboxIndex": location["checkbox_index"],
            "browserMutationAllowed": allow_selection,
            "browserMutationPerformedByHelper": False,
            "postconditionVerified": selection_verified,
        },
        "authorization": {
            "browserMutationAllowed": allow_authorization,
            "browserMutationPerformedByHelper": False,
            "callbackVerified": callback_verified,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--expected-site-id", required=True)
    parser.add_argument("--allow-selection", action="store_true")
    parser.add_argument("--allow-authorization", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        value = json.loads(args.path.read_text())
        result = review_authorization(
            value,
            args.expected_site_id,
            allow_selection=args.allow_selection,
            allow_authorization=args.allow_authorization,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Unable to validate site authorization: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
