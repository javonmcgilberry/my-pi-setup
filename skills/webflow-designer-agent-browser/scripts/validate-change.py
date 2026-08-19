#!/usr/bin/env python3
"""Fail-closed daily validation router for reviewed Webflow Designer contracts.

This executable never calls a model and never turns source discovery into an
executable instruction.  It compares a bounded Git change set with tracked,
reviewed route mappings, runs only fixed allowlisted adapters, and produces a
sanitized receipt.  Unknown changes receive bounded proposal context; a host
may validate one data-only candidate and, after interactive approval, invoke
the same fixed adapter once.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, NoReturn


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_POLICY = SKILL_DIR / "test-corpus-policy.json"
DEFAULT_PREFLIGHT = SCRIPT_DIR / "ensure-test-aws.py"
VERSION = 1
STATUS_VALUES = {
    "ready",
    "passed",
    "failed",
    "infrastructure_failed",
    "approval_required",
    "insufficient_evidence",
    "routing_ambiguous",
    "cleanup_failed",
}
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{2,119}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_BASE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~^/:-]{0,119}$")
SENSITIVE_KEY = re.compile(r"authorization|cookie|credential|password|secret|token", re.I)
FORBIDDEN_TEXT = re.compile(
    r"javascript|\bshell\b|dynamic\s*(?:import|tool)|\b(?:curl|wget|rm|sudo)\b|"
    r"\b(?:publish|delete|billing|production|customer)\b",
    re.I,
)


class ValidationError(ValueError):
    """Expected invalid input, policy, or safety-boundary error."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    timed_out: bool = False


Runner = Callable[[list[str], Path, int], CommandResult]


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def fail(message: str) -> NoReturn:
    raise ValidationError(message)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"unable to read JSON: {path.name}") from error
    if not isinstance(value, dict):
        fail(f"JSON root must be an object: {path.name}")
    return value


def ensure_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        fail(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.startswith("./"):
        fail(f"{field} must be a normalized relative path")
    normalized = path.as_posix()
    if normalized in {".", ""}:
        fail(f"{field} must name a file")
    return normalized


def require_object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{field} must be an object")
    return value


def require_keys(value: object, allowed: set[str], required: set[str], field: str) -> dict[str, Any]:
    result = require_object(value, field)
    unknown = set(result) - allowed
    missing = required - set(result)
    if unknown or missing:
        detail = ", ".join(sorted(unknown or missing))
        fail(f"{field} has unsupported or missing fields: {detail}")
    return result


def bounded_string(value: object, field: str, maximum: int = 240) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        fail(f"{field} must be a bounded non-empty string")
    return value


def bounded_string_list(
    value: object, field: str, *, minimum: int = 0, maximum: int = 20
) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        fail(f"{field} must be a bounded string list")
    result = [bounded_string(item, field) for item in value]
    if len(set(result)) != len(result):
        fail(f"{field} must not contain duplicates")
    return result


def run_git(repo: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise ValidationError("git command failed")
    return completed.stdout


def source_commit(repo: Path) -> str:
    commit = run_git(repo, "rev-parse", "HEAD").decode("utf-8").strip()
    if not COMMIT.fullmatch(commit):
        fail("repository HEAD is not a full commit")
    return commit


def parse_name_status(raw: bytes, source: str) -> list[dict[str, str]]:
    """Decode NUL-delimited name-status output, including rename/copy records."""
    values = [item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item]
    result: list[dict[str, str]] = []
    index = 0
    while index < len(values):
        status = values[index]
        index += 1
        if not status:
            fail("git change status is malformed")
        kind = status[0]
        if kind in {"R", "C"}:
            if index + 1 >= len(values):
                fail("git rename status is malformed")
            previous = ensure_relative(values[index], "changed path")
            current = ensure_relative(values[index + 1], "changed path")
            index += 2
            result.append({"path": current, "status": "renamed" if kind == "R" else "copied", "source": source, "previousPath": previous})
            continue
        if index >= len(values):
            fail("git change status is malformed")
        path = ensure_relative(values[index], "changed path")
        index += 1
        status_name = {
            "A": "added",
            "D": "deleted",
            "M": "modified",
            "T": "type_changed",
            "U": "unmerged",
        }.get(kind)
        if status_name is None:
            fail("unsupported git change status")
        result.append({"path": path, "status": status_name, "source": source})
    return result


def validate_changed_file(repo: Path, record: dict[str, str], limits: dict[str, int]) -> dict[str, Any]:
    path = ensure_relative(record["path"], "changed path")
    absolute = repo / path
    result: dict[str, Any] = {"path": path, "status": record["status"], "sources": [record["source"]]}
    previous = record.get("previousPath")
    if previous:
        result["previousPath"] = previous
    if record["status"] == "deleted" and not absolute.exists():
        result["sha256"] = None
        result["bytes"] = 0
        return result
    try:
        stat = absolute.lstat()
    except OSError as error:
        raise ValidationError(f"changed file cannot be inspected: {path}") from error
    if absolute.is_symlink() or not absolute.is_file():
        fail("changed paths must be regular files")
    if stat.st_size > limits["maximumFileBytes"]:
        fail("changed file exceeds maximumFileBytes")
    try:
        content = absolute.read_bytes()
    except OSError as error:
        raise ValidationError(f"changed file cannot be read: {path}") from error
    result["bytes"] = len(content)
    result["sha256"] = hashlib.sha256(content).hexdigest()
    return result


def merge_change_records(records: Iterable[dict[str, str]], repo: Path, limits: dict[str, int]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, str]] = {}
    sources: dict[str, list[str]] = {}
    for record in records:
        path = record["path"]
        if path in merged and merged[path]["status"] == "deleted" and record["status"] != "deleted":
            merged[path] = record
        elif path not in merged or record["status"] != "modified":
            merged[path] = record
        sources.setdefault(path, []).append(record["source"])
    if len(merged) > limits["maximumChangedFiles"]:
        fail("change set exceeds maximumChangedFiles")
    result = []
    total = 0
    for path in sorted(merged):
        item = validate_changed_file(repo, merged[path], limits)
        item["sources"] = sorted(set(sources[path]))
        total += int(item["bytes"])
        result.append(item)
    if total > limits["maximumTotalBytes"]:
        fail("change set exceeds maximumTotalBytes")
    return result


def collect_change_set(
    repo: Path,
    limits: dict[str, int],
    *,
    base: str | None = None,
    changed_files: Iterable[str] = (),
) -> dict[str, Any]:
    if not repo.is_dir() or not (repo / ".git").exists():
        fail("repo must be a Git working tree")
    explicit = list(changed_files)
    records: list[dict[str, str]] = []
    if explicit:
        for path in explicit:
            records.append({"path": ensure_relative(path, "changed file"), "status": "explicit", "source": "explicit"})
    elif base is not None:
        if not SAFE_BASE.fullmatch(base):
            fail("base must be a bounded Git revision")
        records.extend(parse_name_status(run_git(repo, "diff", "--name-status", "-z", "--find-renames", base, "--"), "base"))
    else:
        records.extend(parse_name_status(run_git(repo, "diff", "--name-status", "-z", "--find-renames", "--"), "unstaged"))
        records.extend(parse_name_status(run_git(repo, "diff", "--cached", "--name-status", "-z", "--find-renames", "--"), "staged"))
    if not explicit:
        for raw_path in run_git(repo, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
            if raw_path:
                records.append({"path": ensure_relative(raw_path.decode("utf-8", "surrogateescape"), "untracked path"), "status": "untracked", "source": "untracked"})
    files = merge_change_records(records, repo, limits)
    return {"sourceCommit": source_commit(repo), "files": files, "digest": sha256_json(files)}


def validate_limits(value: object) -> dict[str, int]:
    result = require_keys(
        value,
        {"maximumChangedFiles", "maximumFileBytes", "maximumTotalBytes", "maximumProposalEvidence"},
        {"maximumChangedFiles", "maximumFileBytes", "maximumTotalBytes", "maximumProposalEvidence"},
        "changeValidation.limits",
    )
    limits: dict[str, int] = {}
    for key, item in result.items():
        if type(item) is not int or item < 1:
            fail(f"changeValidation.limits.{key} must be a positive integer")
        limits[key] = item
    if limits["maximumTotalBytes"] < limits["maximumFileBytes"]:
        fail("changeValidation maximumTotalBytes must cover maximumFileBytes")
    return limits


def validate_policy(policy: object) -> dict[str, Any]:
    policy = require_object(policy, "policy")
    if policy.get("version") != 1:
        fail("unsupported policy version")
    operations = policy.get("operations")
    adapters = policy.get("scenarioAdapters")
    change_validation = policy.get("changeValidation")
    if not isinstance(operations, list) or not isinstance(adapters, dict):
        fail("policy operations or scenarioAdapters are invalid")
    operation_ids = set()
    for operation in operations:
        item = require_object(operation, "policy operation")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier) or identifier in operation_ids:
            fail("policy operation id is invalid")
        operation_ids.add(identifier)
    section = require_keys(
        change_validation,
        {"version", "limits", "mappings", "runners", "candidate"},
        {"version", "limits", "mappings", "runners", "candidate"},
        "changeValidation",
    )
    if section["version"] != 1:
        fail("unsupported changeValidation version")
    limits = validate_limits(section["limits"])
    raw_runners = require_object(section["runners"], "changeValidation.runners")
    runners: dict[str, dict[str, Any]] = {}
    for runner_id, raw_runner in raw_runners.items():
        if not isinstance(runner_id, str) or not IDENTIFIER.fullmatch(runner_id):
            fail("runner id is invalid")
        runner = require_keys(
            raw_runner,
            {"adapter", "specPath", "grep", "operationIds", "evidenceTerms", "requiresAws", "timeoutSeconds"},
            {"adapter", "specPath", "grep", "operationIds", "evidenceTerms", "requiresAws", "timeoutSeconds"},
            f"runner {runner_id}",
        )
        adapter_id = bounded_string(runner["adapter"], f"runner {runner_id}.adapter", 120)
        adapter = adapters.get(adapter_id)
        if not isinstance(adapter, dict):
            fail(f"runner {runner_id} uses an undeclared adapter")
        spec_path = ensure_relative(runner["specPath"], f"runner {runner_id}.specPath")
        roots = adapter.get("allowedSpecRoots")
        if not isinstance(roots, list) or not roots:
            fail(f"runner {runner_id} adapter has no allowed spec roots")
        allowed_roots = [ensure_relative(root, "allowed spec root") for root in roots]
        if not any(spec_path == root or spec_path.startswith(root.rstrip("/") + "/") for root in allowed_roots):
            fail(f"runner {runner_id} specPath is outside the adapter allowlist")
        grep = bounded_string(runner["grep"], f"runner {runner_id}.grep", 160)
        operation_ids_for_runner = bounded_string_list(runner["operationIds"], f"runner {runner_id}.operationIds", minimum=1)
        if any(identifier not in operation_ids for identifier in operation_ids_for_runner):
            fail(f"runner {runner_id} references an unknown operation")
        evidence_terms = bounded_string_list(runner["evidenceTerms"], f"runner {runner_id}.evidenceTerms", minimum=1)
        if type(runner["requiresAws"]) is not bool:
            fail(f"runner {runner_id}.requiresAws must be boolean")
        timeout = runner["timeoutSeconds"]
        if type(timeout) is not int or not 1 <= timeout <= 900:
            fail(f"runner {runner_id}.timeoutSeconds is invalid")
        runners[runner_id] = {**runner, "adapter": adapter_id, "specPath": spec_path, "grep": grep, "operationIds": operation_ids_for_runner, "evidenceTerms": evidence_terms}
    mappings = section["mappings"]
    if not isinstance(mappings, list) or not mappings:
        fail("changeValidation.mappings must be a non-empty list")
    mapping_ids: set[str] = set()
    validated_mappings = []
    for raw_mapping in mappings:
        mapping = require_keys(raw_mapping, {"id", "pathGlobs", "operationIds", "runnerId"}, {"id", "pathGlobs", "operationIds", "runnerId"}, "changeValidation mapping")
        mapping_id = bounded_string(mapping["id"], "mapping id", 120)
        if not IDENTIFIER.fullmatch(mapping_id) or mapping_id in mapping_ids:
            fail("mapping id is invalid")
        mapping_ids.add(mapping_id)
        globs = bounded_string_list(mapping["pathGlobs"], f"mapping {mapping_id}.pathGlobs", minimum=1)
        if any(glob.startswith("/") or ".." in PurePosixPath(glob).parts or "\x00" in glob for glob in globs):
            fail("mapping path glob is invalid")
        mapped_operations = bounded_string_list(mapping["operationIds"], f"mapping {mapping_id}.operationIds", minimum=1)
        runner_id = bounded_string(mapping["runnerId"], f"mapping {mapping_id}.runnerId", 120)
        if runner_id not in runners or any(identifier not in operation_ids for identifier in mapped_operations):
            fail("mapping references an unknown runner or operation")
        if not set(mapped_operations).issubset(runners[runner_id]["operationIds"]):
            fail("mapping operations must be supported by its runner")
        validated_mappings.append({"id": mapping_id, "pathGlobs": globs, "operationIds": mapped_operations, "runnerId": runner_id})
    candidate = require_keys(
        section["candidate"],
        {"allowedActions", "allowedRiskClasses", "maximumActions", "maximumRetries", "maximumTimeoutSeconds", "allowedSelectorKeys"},
        {"allowedActions", "allowedRiskClasses", "maximumActions", "maximumRetries", "maximumTimeoutSeconds", "allowedSelectorKeys"},
        "changeValidation.candidate",
    )
    allowed_actions = bounded_string_list(candidate["allowedActions"], "candidate.allowedActions", minimum=1, maximum=10)
    if set(allowed_actions) - {"invoke_operation", "assert", "compensate"}:
        fail("candidate allowedActions contains an unsupported opcode")
    risk_classes = bounded_string_list(candidate["allowedRiskClasses"], "candidate.allowedRiskClasses", minimum=1, maximum=4)
    if set(risk_classes) - {"read-only", "reversible-ui"}:
        fail("candidate risk class is unsafe")
    for key in ("maximumActions", "maximumRetries", "maximumTimeoutSeconds"):
        if type(candidate[key]) is not int or candidate[key] < 0:
            fail(f"candidate.{key} must be a non-negative integer")
    if not 2 <= candidate["maximumActions"] <= 8 or candidate["maximumRetries"] > 1 or not 1 <= candidate["maximumTimeoutSeconds"] <= 900:
        fail("candidate limits are outside the supported bounds")
    selector_keys = bounded_string_list(candidate["allowedSelectorKeys"], "candidate.allowedSelectorKeys", maximum=40)
    return {**policy, "changeValidation": {**section, "limits": limits, "mappings": validated_mappings, "runners": runners, "candidate": {**candidate, "allowedActions": allowed_actions, "allowedRiskClasses": risk_classes, "allowedSelectorKeys": selector_keys}}}


def path_matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def route_trusted_contracts(change_set: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    mappings = policy["changeValidation"]["mappings"]
    files = change_set["files"]
    if not files:
        return {"status": "insufficient_evidence", "reason": "change_set_empty", "matches": [], "unmatched": []}
    selected = []
    unmatched = []
    for file in files:
        matches = [mapping for mapping in mappings if path_matches(file["path"], mapping["pathGlobs"])]
        runner_ids = {mapping["runnerId"] for mapping in matches}
        if len(runner_ids) > 1:
            return {"status": "routing_ambiguous", "reason": "multiple_runner_mappings", "matches": [], "unmatched": [file["path"]]}
        if not matches:
            unmatched.append(file["path"])
            continue
        selected.append(matches[0])
    if unmatched:
        return {"status": "unknown", "reason": "unmapped_changed_paths", "matches": selected, "unmatched": unmatched}
    by_runner = {mapping["runnerId"]: mapping for mapping in selected}
    operations = sorted({identifier for mapping in by_runner.values() for identifier in mapping["operationIds"]})
    return {"status": "trusted", "reason": "reviewed_path_mapping", "matches": [by_runner[key] for key in sorted(by_runner)], "unmatched": [], "operations": operations}


def path_terms(files: Iterable[dict[str, Any]]) -> set[str]:
    terms: set[str] = set()
    for file in files:
        expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(file["path"]))
        terms.update(part.lower() for part in re.split(r"[^A-Za-z0-9]+", expanded) if len(part) > 1)
    return terms


def build_proposal_context(change_set: dict[str, Any], route: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    if route["status"] == "routing_ambiguous":
        return {"status": "routing_ambiguous", "missingEvidence": [route["reason"]]}
    terms = path_terms(change_set["files"])
    runners = policy["changeValidation"]["runners"]
    candidates = []
    for runner_id, runner in sorted(runners.items()):
        overlap = sorted(set(term.lower() for term in runner["evidenceTerms"]) & terms)
        if overlap:
            candidates.append({
                "runnerId": runner_id,
                "operationIds": runner["operationIds"],
                "evidenceRefs": [f"policy:runner:{runner_id}", *[f"term:{term}" for term in overlap]],
                "selectorKeys": policy["changeValidation"]["candidate"]["allowedSelectorKeys"],
            })
    maximum = policy["changeValidation"]["limits"]["maximumProposalEvidence"]
    candidates = candidates[:maximum]
    if not candidates:
        return {
            "status": "insufficient_evidence",
            "missingEvidence": ["reviewed_path_mapping_or_nearby_contract"],
            "changeSet": {"sourceCommit": change_set["sourceCommit"], "digest": change_set["digest"], "files": [{"path": item["path"], "status": item["status"]} for item in change_set["files"]]},
        }
    candidate_policy = policy["changeValidation"]["candidate"]
    return {
        "status": "approval_required",
        "changeSet": {"sourceCommit": change_set["sourceCommit"], "digest": change_set["digest"], "files": [{"path": item["path"], "status": item["status"]} for item in change_set["files"]]},
        "nearbyContracts": candidates,
        "candidatePolicy": {
            "allowedActions": candidate_policy["allowedActions"],
            "allowedRiskClasses": candidate_policy["allowedRiskClasses"],
            "maximumActions": candidate_policy["maximumActions"],
            "maximumRetries": candidate_policy["maximumRetries"],
            "maximumTimeoutSeconds": candidate_policy["maximumTimeoutSeconds"],
            "allowedSelectorKeys": candidate_policy["allowedSelectorKeys"],
            "modelProposalLimit": 1,
        },
        "routing": {"reason": route["reason"], "unmatched": route["unmatched"]},
    }


def reject_sensitive_or_executable(value: object, field: str = "candidate") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if SENSITIVE_KEY.search(str(key)):
                fail(f"{field} contains a sensitive key")
            reject_sensitive_or_executable(item, f"{field}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_sensitive_or_executable(item, f"{field}[{index}]")
    elif isinstance(value, str) and FORBIDDEN_TEXT.search(value):
        fail(f"{field} contains forbidden executable or destructive text")


def validate_candidate_contract(candidate: object, context: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    if context.get("status") != "approval_required":
        fail("candidate proposals require bounded proposal context")
    reject_sensitive_or_executable(candidate)
    allowed = {"version", "id", "mode", "surfaceAdapter", "source", "evidenceRefs", "riskClass", "determinism", "runnerId", "inputs", "constraints", "target", "preconditions", "facts", "actions", "oracle", "recovery", "cleanup", "budget", "receipt"}
    contract = require_keys(candidate, allowed, allowed, "candidate")
    if contract["version"] != 1 or contract["mode"] != "candidate" or contract["surfaceAdapter"] != "webflow-designer":
        fail("candidate identity is invalid")
    identifier = bounded_string(contract["id"], "candidate.id", 120)
    if not IDENTIFIER.fullmatch(identifier):
        fail("candidate.id is invalid")
    source = require_keys(contract["source"], {"commit", "changeSetDigest"}, {"commit", "changeSetDigest"}, "candidate.source")
    change_set = context["changeSet"]
    if source.get("commit") != change_set["sourceCommit"] or source.get("changeSetDigest") != change_set["digest"]:
        fail("candidate source binding does not match the current change set")
    if contract["riskClass"] not in policy["changeValidation"]["candidate"]["allowedRiskClasses"] or contract["determinism"] != "bounded":
        fail("candidate risk or determinism is invalid")
    runner_id = bounded_string(contract["runnerId"], "candidate.runnerId", 120)
    nearby = {item["runnerId"]: item for item in context["nearbyContracts"]}
    if runner_id not in nearby:
        fail("candidate runner is not supported by bounded evidence")
    evidence_refs = bounded_string_list(contract["evidenceRefs"], "candidate.evidenceRefs", minimum=1, maximum=5)
    required_evidence = f"policy:runner:{runner_id}"
    if required_evidence not in evidence_refs:
        fail("candidate must cite the selected reviewed runner")
    if not isinstance(contract["inputs"], dict) or len(contract["inputs"]) > 8:
        fail("candidate.inputs is invalid")
    bounded_string_list(contract["constraints"], "candidate.constraints", minimum=1, maximum=12)
    target = require_keys(contract["target"], {"fixture", "document"}, {"fixture", "document"}, "candidate.target")
    if target.get("fixture") != "isolated-designer-test" or target.get("document") not in {"main", "canvas", "frame"}:
        fail("candidate target is invalid")
    bounded_string_list(contract["preconditions"], "candidate.preconditions", minimum=1, maximum=12)
    facts = contract["facts"]
    if not isinstance(facts, list) or not 1 <= len(facts) <= 12:
        fail("candidate.facts is invalid")
    fact_ids: set[str] = set()
    for fact in facts:
        item = require_keys(fact, {"id", "type", "source"}, {"id", "type", "source"}, "candidate fact")
        fact_id = bounded_string(item["id"], "candidate fact id", 80)
        if not re.fullmatch(r"[a-z][a-z0-9._-]{1,79}", fact_id) or fact_id in fact_ids:
            fail("candidate fact id is invalid")
        if item["type"] not in {"boolean", "string", "count"} or item["source"] not in {"trusted-operation", "playwright-assertion"}:
            fail("candidate fact is invalid")
        fact_ids.add(fact_id)
    candidate_policy = policy["changeValidation"]["candidate"]
    actions = contract["actions"]
    if not isinstance(actions, list) or not 2 <= len(actions) <= candidate_policy["maximumActions"]:
        fail("candidate.actions exceeds the bounded limit")
    action_ids: set[str] = set()
    known_operations = set(nearby[runner_id]["operationIds"])
    for action in actions:
        item = require_object(action, "candidate action")
        action_id = bounded_string(item.get("id"), "candidate action id", 80)
        opcode = item.get("op")
        if not re.fullmatch(r"[a-z][a-z0-9._-]{1,79}", action_id) or action_id in action_ids or opcode not in candidate_policy["allowedActions"]:
            fail("candidate action id or opcode is invalid")
        depends_on = item.get("dependsOn")
        if not isinstance(depends_on, list) or len(depends_on) > 7 or any(not isinstance(dependency, str) or dependency not in action_ids for dependency in depends_on):
            fail("candidate action dependencies must be an acyclic prior-action list")
        allowed_action_fields = {"id", "op", "dependsOn", "maximumAttempts"}
        if opcode in {"invoke_operation", "compensate"}:
            allowed_action_fields.add("operationId")
            operation_id = item.get("operationId")
            if operation_id not in known_operations:
                fail("candidate action may invoke only a selected reviewed operation")
        elif opcode == "assert":
            allowed_action_fields.update({"fact", "expected", "selectorKey"})
            if item.get("fact") not in fact_ids or "expected" not in item:
                fail("candidate assertion must use a typed fact and expected value")
            selector_key = item.get("selectorKey")
            if selector_key is not None and selector_key not in candidate_policy["allowedSelectorKeys"]:
                fail("candidate assertion selector key is not reviewed")
        if set(item) - allowed_action_fields:
            fail("candidate action contains an unsupported field")
        attempts = item.get("maximumAttempts", 1)
        if type(attempts) is not int or not 1 <= attempts <= candidate_policy["maximumRetries"] + 1:
            fail("candidate maximumAttempts exceeds retry bound")
        action_ids.add(action_id)
    oracle = require_keys(contract["oracle"], {"kind", "fact", "expected"}, {"kind", "fact", "expected"}, "candidate.oracle")
    if oracle.get("kind") != "semantic-fact" or oracle.get("fact") not in fact_ids:
        fail("candidate requires a typed semantic oracle")
    if not isinstance(contract["recovery"], list) or len(contract["recovery"]) > 4:
        fail("candidate.recovery is invalid")
    cleanup = bounded_string_list(contract["cleanup"], "candidate.cleanup", minimum=1, maximum=4)
    if "adapter-teardown" not in cleanup:
        fail("candidate cleanup must require adapter-teardown")
    budget = require_keys(contract["budget"], {"timeoutSeconds", "maxRetries", "maxActions"}, {"timeoutSeconds", "maxRetries", "maxActions"}, "candidate.budget")
    if budget.get("timeoutSeconds") != policy["changeValidation"]["runners"][runner_id]["timeoutSeconds"] or budget.get("maxRetries") != candidate_policy["maximumRetries"] or budget.get("maxActions") != candidate_policy["maximumActions"]:
        fail("candidate budget must equal the reviewed fixed budget")
    receipt = require_keys(contract["receipt"], {"requireSemanticOracle", "requireCleanupProof"}, {"requireSemanticOracle", "requireCleanupProof"}, "candidate.receipt")
    if receipt != {"requireSemanticOracle": True, "requireCleanupProof": True}:
        fail("candidate receipt requirements are invalid")
    return contract


def candidate_digest(candidate: dict[str, Any]) -> str:
    return sha256_json(candidate)


def approval_digest(candidate: dict[str, Any]) -> str:
    binding = {
        "candidateDigest": candidate_digest(candidate),
        "source": candidate["source"],
        "target": candidate["target"],
        "riskClass": candidate["riskClass"],
        "actions": candidate["actions"],
        "oracle": candidate["oracle"],
        "cleanup": candidate["cleanup"],
        "budget": candidate["budget"],
    }
    return sha256_json(binding)


def candidate_run_id(candidate: dict[str, Any]) -> str:
    return str(uuid.UUID(hex=candidate_digest(candidate)[:32]))


def build_command(policy: dict[str, Any], runner_id: str) -> list[str]:
    runner = policy["changeValidation"]["runners"][runner_id]
    adapter = policy["scenarioAdapters"][runner["adapter"]]
    command = [adapter["executable"], *adapter["argumentPrefix"], runner["specPath"], "-g", runner["grep"], *adapter["fixedArguments"]]
    if any(not isinstance(item, str) or not item or "\x00" in item for item in command):
        fail("fixed runner command is invalid")
    return command


def default_runner(command: list[str], cwd: Path, timeout: int) -> CommandResult:
    try:
        completed = subprocess.run(command, cwd=cwd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        return CommandResult(returncode=124, timed_out=True)
    return CommandResult(returncode=completed.returncode)


def build_receipt(
    *,
    status: str,
    phase: str,
    mode: str,
    change_set: dict[str, Any],
    contracts: Iterable[str] = (),
    tests: Iterable[str] = (),
    model_proposal_count: int = 0,
    preflight: str = "not_required",
    oracle: str = "not_run",
    cleanup: str = "not_run",
    failure_class: str | None = None,
    candidate: dict[str, Any] | None = None,
    candidate_state: str | None = None,
) -> dict[str, Any]:
    if status not in STATUS_VALUES:
        fail("receipt status is invalid")
    candidate_value = None
    if candidate is not None:
        candidate_value = {"state": candidate_state or "proposed", "digest": candidate_digest(candidate), "runId": candidate_run_id(candidate)}
    return {
        "version": VERSION,
        "status": status,
        "phase": phase,
        "mode": mode,
        "sourceCommit": change_set["sourceCommit"],
        "changeSetDigest": change_set["digest"],
        "contracts": sorted(set(contracts)),
        "tests": sorted(set(tests)),
        "modelProposalCount": model_proposal_count,
        "preflight": preflight,
        "semanticOracle": oracle,
        "cleanup": cleanup,
        "failureClass": failure_class,
        "artifacts": [],
        "candidate": candidate_value,
    }


def execute_runner(
    repo: Path,
    policy: dict[str, Any],
    runner_ids: Iterable[str],
    change_set: dict[str, Any],
    *,
    candidate: dict[str, Any] | None = None,
    runner: Runner = default_runner,
) -> dict[str, Any]:
    selected = sorted(set(runner_ids))
    contracts = sorted({identifier for runner_id in selected for identifier in policy["changeValidation"]["runners"][runner_id]["operationIds"]})
    tests = [policy["changeValidation"]["runners"][runner_id]["specPath"] for runner_id in selected]
    preflight_needed = any(policy["changeValidation"]["runners"][runner_id]["requiresAws"] for runner_id in selected)
    if preflight_needed:
        result = runner([sys.executable, str(DEFAULT_PREFLIGHT), "--repo", str(repo)], repo, 180)
        if result.timed_out:
            return build_receipt(status="cleanup_failed", phase="preflight", mode="candidate" if candidate else "trusted", change_set=change_set, contracts=contracts, tests=tests, model_proposal_count=1 if candidate else 0, preflight="failed", cleanup="failed", failure_class="preflight_timeout", candidate=candidate, candidate_state="approved" if candidate else None)
        if result.returncode != 0:
            return build_receipt(status="infrastructure_failed", phase="preflight", mode="candidate" if candidate else "trusted", change_set=change_set, contracts=contracts, tests=tests, model_proposal_count=1 if candidate else 0, preflight="failed", failure_class="preflight_failed", candidate=candidate, candidate_state="approved" if candidate else None)
    for runner_id in selected:
        config = policy["changeValidation"]["runners"][runner_id]
        result = runner(build_command(policy, runner_id), repo, config["timeoutSeconds"])
        if result.timed_out:
            return build_receipt(status="cleanup_failed", phase="execute", mode="candidate" if candidate else "trusted", change_set=change_set, contracts=contracts, tests=tests, model_proposal_count=1 if candidate else 0, preflight="passed" if preflight_needed else "not_required", cleanup="failed", failure_class="adapter_timeout", candidate=candidate, candidate_state="approved" if candidate else None)
        if result.returncode != 0:
            return build_receipt(status="failed", phase="oracle", mode="candidate" if candidate else "trusted", change_set=change_set, contracts=contracts, tests=tests, model_proposal_count=1 if candidate else 0, preflight="passed" if preflight_needed else "not_required", oracle="failed", cleanup="proved", failure_class="semantic_or_test_failure", candidate=candidate, candidate_state="consumed" if candidate else None)
    return build_receipt(status="passed", phase="complete", mode="candidate" if candidate else "trusted", change_set=change_set, contracts=contracts, tests=tests, model_proposal_count=1 if candidate else 0, preflight="passed" if preflight_needed else "not_required", oracle="passed", cleanup="proved", candidate=candidate, candidate_state="consumed" if candidate else None)


def validate_change(
    repo: Path,
    policy: dict[str, Any],
    *,
    base: str | None = None,
    changed_files: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    change_set = collect_change_set(repo, policy["changeValidation"]["limits"], base=base, changed_files=changed_files)
    route = route_trusted_contracts(change_set, policy)
    if route["status"] == "trusted":
        receipt = build_receipt(status="ready", phase="route", mode="trusted", change_set=change_set, contracts=route["operations"], tests=[policy["changeValidation"]["runners"][item["runnerId"]]["specPath"] for item in route["matches"]])
        return change_set, route, receipt
    if route["status"] == "routing_ambiguous":
        return change_set, route, build_receipt(status="routing_ambiguous", phase="route", mode="none", change_set=change_set, failure_class=route["reason"])
    context = build_proposal_context(change_set, route, policy)
    receipt = build_receipt(status=context["status"], phase="proposal" if context["status"] == "approval_required" else "route", mode="none", change_set=change_set, failure_class=None if context["status"] == "approval_required" else ",".join(context["missingEvidence"]))
    return change_set, route, {"receipt": receipt, "proposalContext": context}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["route", "proposal-context", "validate-candidate", "execute-trusted"])
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--base")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        policy = validate_policy(read_json(DEFAULT_POLICY))
        change_set, route, result = validate_change(args.repo.resolve(), policy, base=args.base, changed_files=args.changed_file)
        if args.command == "route":
            output: dict[str, Any] = {"version": VERSION, "changeSet": change_set, "route": route, "result": result}
        elif args.command == "proposal-context":
            output = result if isinstance(result, dict) and "proposalContext" in result else {"receipt": build_receipt(status="insufficient_evidence", phase="proposal", mode="none", change_set=change_set, failure_class="trusted_route_requires_no_proposal"), "proposalContext": {"status": "insufficient_evidence", "missingEvidence": ["trusted_route_requires_no_proposal"]}}
        elif args.command == "validate-candidate":
            if args.candidate is None:
                fail("validate-candidate requires --candidate")
            if not isinstance(result, dict) or "proposalContext" not in result:
                fail("candidate proposals require an unknown route")
            candidate = validate_candidate_contract(read_json(args.candidate), result["proposalContext"], policy)
            output = {"version": VERSION, "status": "approval_required", "candidateDigest": candidate_digest(candidate), "approvalDigest": approval_digest(candidate), "runId": candidate_run_id(candidate), "receipt": build_receipt(status="approval_required", phase="proposal", mode="candidate", change_set=change_set, model_proposal_count=1, candidate=candidate)}
        else:
            if route["status"] != "trusted":
                fail("execute-trusted requires a trusted route")
            if not args.execute:
                fail("execute-trusted requires --execute")
            output = execute_runner(args.repo.resolve(), policy, [item["runnerId"] for item in route["matches"]], change_set)
        print(canonical_json(output))
        return 0
    except ValidationError as error:
        print(canonical_json({"version": VERSION, "status": "error", "error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
