#!/usr/bin/env python3
"""Validate and plan scenario-backed Designer evaluation.

This command intentionally plans the handoff instead of running Playwright.
Webflow's current scenario helpers create and own a Playwright browser context;
they do not expose a safe external resource lease for a separate agent-browser
session.  A tracked adapter may consume this plan later, but generated JSON
never contains arbitrary executable commands or credentials.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
POLICY_PATH = SKILL_DIR / "test-corpus-policy.json"
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ScenarioError(ValueError):
    """A fail-closed scenario contract or plan error."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ScenarioError(f"unable to read JSON: {path}") from error
    if not isinstance(value, dict):
        raise ScenarioError(f"JSON root must be an object: {path}")
    return value


def load_corpus_module():
    path = SCRIPT_DIR / "test-corpus-index.py"
    spec = importlib.util.spec_from_file_location("test_corpus_index", path)
    if spec is None or spec.loader is None:
        raise ScenarioError("unable to load corpus index validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise ScenarioError(f"{field} must be a relative path")
    path = Path(value)
    if ".." in path.parts:
        raise ScenarioError(f"{field} may not contain parent traversal")
    return value


def validate_contract(contract: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    required = {
        "version", "id", "mode", "sourceCommit", "adapter", "specPath",
        "target", "setup", "expected", "allowedOperations", "teardown",
    }
    if set(contract) - required - {"grep"} or not required <= set(contract):
        raise ScenarioError("scenario contract has unsupported or missing fields")
    if contract["version"] != 1 or not isinstance(contract["id"], str) or not IDENTIFIER.fullmatch(contract["id"]):
        raise ScenarioError("scenario contract version or id is invalid")
    if contract["mode"] not in {"fixture", "external"}:
        raise ScenarioError("scenario mode must be fixture or external")
    if contract["mode"] == "fixture":
        if contract["sourceCommit"] != "fixture":
            raise ScenarioError("fixture scenario sourceCommit must be fixture")
    elif not isinstance(contract["sourceCommit"], str) or not COMMIT.fullmatch(contract["sourceCommit"]):
        raise ScenarioError("external scenario sourceCommit must be a full commit")
    adapter_name = contract["adapter"]
    if not isinstance(adapter_name, str) or not IDENTIFIER.fullmatch(adapter_name):
        raise ScenarioError("scenario adapter name is invalid")
    adapters = policy.get("scenarioAdapters", {})
    if not isinstance(adapters, dict):
        raise ScenarioError("scenario adapter policy is invalid")
    adapter = adapters.get(adapter_name)
    if not isinstance(adapter, dict):
        raise ScenarioError(f"scenario adapter is not declared by policy: {adapter_name}")
    executable = adapter.get("executable")
    if not isinstance(executable, str) or not executable or "\x00" in executable:
        raise ScenarioError("scenario adapter executable is invalid")
    for argument_field in ("argumentPrefix", "fixedArguments", "allowedSpecRoots"):
        values = adapter.get(argument_field)
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value or "\x00" in value
            for value in values
        ):
            raise ScenarioError(f"scenario adapter {argument_field} is invalid")
    spec_path = ensure_relative(contract["specPath"], "specPath")
    allowed_roots = [ensure_relative(root, "allowedSpecRoot") for root in adapter.get("allowedSpecRoots", [])]
    if not allowed_roots:
        raise ScenarioError("scenario adapter has no allowed spec roots")
    if not any(spec_path == root or spec_path.startswith(root.rstrip("/") + "/") for root in allowed_roots):
        raise ScenarioError("scenario spec is outside the adapter allowlist")
    grep = contract.get("grep")
    if grep is not None:
        if not isinstance(grep, str) or not grep.strip() or len(grep) > 160 or "\x00" in grep:
            raise ScenarioError("scenario grep is invalid")
    target = contract["target"]
    if not isinstance(target, dict) or set(target) != {"origin", "pathTemplate", "document"}:
        raise ScenarioError("scenario target shape is invalid")
    if target["origin"] not in {"local-designer", "designer-test"}:
        raise ScenarioError("scenario target origin is invalid")
    path_template = target["pathTemplate"]
    if not isinstance(path_template, str) or not path_template.startswith("/design/") or "?" in path_template:
        raise ScenarioError("scenario target must be a query-free design path template")
    if target["document"] not in {"main", "canvas", "frame"}:
        raise ScenarioError("scenario target document is invalid")
    for phase in ("setup", "teardown"):
        if not isinstance(contract[phase], dict):
            raise ScenarioError(f"scenario {phase} must be an object")
        if contract[phase].get("adapter") != adapter_name:
            raise ScenarioError(f"scenario {phase} adapter must match the declared adapter")
        if contract[phase].get("artifact") != "sanitized-designer-target":
            raise ScenarioError(f"scenario {phase} must use the sanitized target artifact")
    expected = contract["expected"]
    if (
        not isinstance(expected, dict)
        or set(expected) != {"initialState", "success"}
        or not isinstance(expected["initialState"], list)
        or not expected["initialState"]
        or not isinstance(expected["success"], list)
        or not expected["success"]
    ):
        raise ScenarioError("scenario expected-state shape is invalid")
    allowed = contract["allowedOperations"]
    valid_allowed = isinstance(allowed, list) and all(
        isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in allowed
    )
    if not valid_allowed or not allowed or len(set(allowed)) != len(allowed):
        raise ScenarioError("scenario allowedOperations must be a non-empty string list")
    return adapter


def validate_operation(operation: dict[str, Any], contract: dict[str, Any]) -> None:
    operation_id = operation.get("id")
    if not isinstance(operation_id, str) or operation_id not in contract["allowedOperations"]:
        raise ScenarioError(f"operation is not allowed by scenario: {operation_id}")
    if operation.get("selectionStatus") not in {"include", "candidate"}:
        raise ScenarioError(f"operation is not executable knowledge: {operation_id}")
    provenance = operation.get("provenance")
    if not isinstance(provenance, dict) or not isinstance(provenance.get("sourceCommit"), str):
        raise ScenarioError(f"operation provenance is invalid: {operation_id}")
    source_commit = provenance["sourceCommit"]
    if contract["sourceCommit"] != "fixture" and source_commit != contract["sourceCommit"]:
        raise ScenarioError("scenario and operation source commits do not match")
    if not operation.get("actions") or not operation.get("postconditions"):
        raise ScenarioError(f"operation lacks executable actions or semantic postconditions: {operation_id}")


def build_adapter_command(adapter: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    command = [adapter["executable"], *adapter.get("argumentPrefix", []), contract["specPath"]]
    grep = contract.get("grep")
    if grep:
        command.extend(["-g", grep])
    command.extend(adapter.get("fixedArguments", []))
    if any(not isinstance(item, str) or not item or "\x00" in item for item in command):
        raise ScenarioError("adapter generated an invalid command argument")
    return command


def build_plan(contract: dict[str, Any], operation: dict[str, Any], adapter: dict[str, Any]) -> dict[str, Any]:
    validate_operation(operation, contract)
    command = build_adapter_command(adapter, contract)
    return {
        "version": 1,
        "status": "plan_only",
        "scenario": {
            "id": contract["id"],
            "mode": contract["mode"],
            "sourceCommit": contract["sourceCommit"],
            "target": contract["target"],
        },
        "setup": {
            "kind": "external-adapter",
            "adapter": contract["adapter"],
            "command": command,
            "artifact": "sanitized-designer-target",
            "execution": "not-run-by-this-command",
        },
        "browser": {
            "kind": "managed-agent-browser",
            "lifecycle": ["prepare", "selected-agent-browser-interaction", "verify", "finish"],
            "operationId": operation["id"],
            "document": contract["target"]["document"],
            "actions": operation["actions"],
            "guardrails": operation["guardrails"],
        },
        "assertion": {
            "initialState": contract["expected"]["initialState"],
            "success": [*operation["postconditions"], *contract["expected"]["success"]],
        },
        "teardown": {
            "kind": "external-adapter",
            "adapter": contract["adapter"],
            "artifact": "sanitized-designer-target",
            "requiredAfter": ["setup", "browser", "assertion"],
            "execution": "not-run-by-this-command",
        },
        "blockers": [
            "existing-playwright-scenario-owns-its-browser-context",
            "external-adapter-must-provide-a-sanitized-target-handoff",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "validate"))
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--operation", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        corpus = load_corpus_module()
        policy = load_json(args.policy)
        contract = load_json(args.scenario)
        operation = load_json(args.operation)
        adapter = validate_contract(contract, policy)
        if args.command == "validate":
            print(json.dumps({"valid": True, "scenarioId": contract["id"]}, sort_keys=True))
            return 0
        if not args.dry_run:
            raise ScenarioError("scenario execution is not implemented; use --dry-run for a bounded plan")
        plan = build_plan(contract, operation, adapter)
        corpus.assert_safe_payload(plan)
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    except (ScenarioError, OSError, AttributeError, KeyError, TypeError) as error:
        print(json.dumps({"status": "error", "code": "scenario_contract_invalid", "message": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
