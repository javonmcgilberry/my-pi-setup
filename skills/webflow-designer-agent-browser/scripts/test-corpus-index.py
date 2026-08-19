#!/usr/bin/env python3
"""Build and query a small, provenance-preserving Designer test corpus index.

The Webflow monorepo is an input-only source for this command.  The generated
index contains operation facts and bounded provenance, never test bodies or
runtime credentials.  It is deliberately policy-driven: adding a source file
does not automatically make it executable knowledge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_POLICY = SKILL_DIR / "test-corpus-policy.json"
SELECTION_STATUSES = {
    "include",
    "candidate",
    "negative_evidence",
    "holdout",
    "exclude",
}
HEX_COMMIT = re.compile(r"^[0-9a-f]{40}$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|credential|password|secret|storage.?state|token)",
    re.IGNORECASE,
)
SENSITIVE_VALUE = re.compile(
    r"(?:https?://|file://|/Users/|/private/var/|/tmp/|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b)",
    re.IGNORECASE,
)


class CorpusError(ValueError):
    """A fail-closed corpus or provenance error."""


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise CorpusError(f"unable to read JSON: {path}") from error
    if not isinstance(value, dict):
        raise CorpusError(f"JSON root must be an object: {path}")
    return value


def run_git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "git command failed"
        raise CorpusError(f"{detail}: git {' '.join(arguments)}")
    return result.stdout.strip()


def source_commit(repo: Path) -> str:
    commit = run_git(repo, "rev-parse", "HEAD")
    if not HEX_COMMIT.fullmatch(commit):
        raise CorpusError("source repository did not return a full commit hash")
    return commit


def file_git_metadata(repo: Path, relative_path: str, cache: dict[str, dict[str, str]]) -> dict[str, str]:
    if relative_path in cache:
        return cache[relative_path]
    output = run_git(repo, "log", "-1", "--format=%H%x00%cI", "--", relative_path)
    parts = output.split("\x00", 1)
    metadata = {}
    if len(parts) == 2 and HEX_COMMIT.fullmatch(parts[0]):
        metadata = {"lastChangedCommit": parts[0], "lastChangedAt": parts[1]}
    cache[relative_path] = metadata
    return metadata


def source_manifest(repo: Path, policy: dict[str, Any]) -> str:
    paths = {
        ensure_relative(policy["operationSource"], "operationSource"),
        ensure_relative(policy["locatorSource"], "locatorSource"),
    }
    paths.update(path.relative_to(repo).as_posix() for path, _ in discover_sources(repo, policy))
    entries = []
    for relative in sorted(paths):
        path = repo / relative
        if not path.is_file():
            raise CorpusError(f"source manifest file is missing: {relative}")
        entries.append({"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return sha256_json(entries)


def ensure_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise CorpusError(f"{field} must be a relative path")
    path = Path(value)
    if ".." in path.parts:
        raise CorpusError(f"{field} may not contain parent traversal")
    return value


def validate_policy(policy: object) -> dict[str, Any]:
    if not isinstance(policy, dict) or policy.get("version") != 1:
        raise CorpusError("unsupported corpus policy")
    sources = policy.get("sources")
    if not isinstance(sources, list) or not sources:
        raise CorpusError("corpus policy sources are invalid")
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("framework"), str):
            raise CorpusError("corpus policy source framework is invalid")
        roots = source.get("roots")
        patterns = source.get("patterns")
        if not isinstance(roots, list) or not roots or not isinstance(patterns, list) or not patterns:
            raise CorpusError("corpus policy source roots or patterns are invalid")
        for root in roots:
            ensure_relative(root, "source root")
        if any(not isinstance(pattern, str) or not pattern for pattern in patterns):
            raise CorpusError("corpus policy source pattern is invalid")
    ensure_relative(policy.get("operationSource"), "operationSource")
    ensure_relative(policy.get("locatorSource"), "locatorSource")
    selection = policy.get("selection")
    if not isinstance(selection, dict):
        raise CorpusError("corpus policy selection is invalid")
    for field in ("minimumConfidence", "maximumEvidencePerOperation", "holdoutEvidencePerOperation"):
        value = selection.get(field)
        if type(value) is not int or value < 0:
            raise CorpusError(f"corpus policy selection field is invalid: {field}")
    evaluation = policy.get("evaluation", {})
    if not isinstance(evaluation, dict):
        raise CorpusError("corpus policy evaluation is invalid")
    minimum_holdout = evaluation.get("minimumHoldoutEvidence", 1)
    if type(minimum_holdout) is not int or minimum_holdout < 0:
        raise CorpusError("corpus policy minimumHoldoutEvidence is invalid")
    if not isinstance(evaluation.get("requireSemanticAssertion", True), bool):
        raise CorpusError("corpus policy requireSemanticAssertion is invalid")
    operations = policy.get("operations")
    if not isinstance(operations, list) or not operations:
        raise CorpusError("corpus policy operations are invalid")
    seen_ids: set[str] = set()
    operation_fields = {
        "id", "symbol", "intent", "capabilities", "contexts", "parameters",
        "locatorKeys", "actions", "postconditions", "guardrails",
    }
    for operation in operations:
        if not isinstance(operation, dict) or not operation_fields <= set(operation):
            raise CorpusError("corpus policy operation shape is invalid")
        operation_id = operation["id"]
        if not isinstance(operation_id, str) or not IDENTIFIER.fullmatch(operation_id) or operation_id in seen_ids:
            raise CorpusError("corpus policy operation id is invalid or duplicated")
        seen_ids.add(operation_id)
        if not isinstance(operation["symbol"], str) or not operation["symbol"]:
            raise CorpusError(f"corpus policy symbol is invalid: {operation_id}")
        for field in ("capabilities", "contexts", "parameters", "locatorKeys", "actions", "postconditions", "guardrails"):
            if not isinstance(operation[field], list):
                raise CorpusError(f"corpus policy operation field is invalid: {operation_id}.{field}")
        patterns = operation.get("evidencePatterns", [])
        if not isinstance(patterns, list) or any(not isinstance(pattern, str) or not pattern for pattern in patterns):
            raise CorpusError(f"corpus policy evidence patterns are invalid: {operation_id}")
        try:
            for pattern in patterns:
                re.compile(pattern, re.IGNORECASE)
        except re.error as error:
            raise CorpusError(f"corpus policy evidence pattern is invalid: {operation_id}") from error
        if operation.get("evidencePatternMode", "any") not in {"any", "all"}:
            raise CorpusError(f"corpus policy evidence pattern mode is invalid: {operation_id}")
    return policy


def discover_sources(repo: Path, policy: dict[str, Any]) -> list[tuple[Path, str]]:
    found: dict[str, tuple[Path, str]] = {}
    for source in policy.get("sources", []):
        if not isinstance(source, dict):
            raise CorpusError("each source policy must be an object")
        framework = source.get("framework")
        if not isinstance(framework, str) or not framework:
            raise CorpusError("source framework is required")
        for root_value in source.get("roots", []):
            root_value = ensure_relative(root_value, "source root")
            root = repo / root_value
            if not root.is_dir():
                continue
            for pattern in source.get("patterns", []):
                if not isinstance(pattern, str) or not pattern:
                    raise CorpusError("source pattern is required")
                for path in root.rglob(pattern):
                    if path.is_file():
                        relative = path.relative_to(repo).as_posix()
                        found.setdefault(relative, (path, framework))
    return [found[key] for key in sorted(found)]


def line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def bounded_end(text: str, start_line: int, maximum: int = 15) -> int:
    return min(len(text.splitlines()), start_line + maximum - 1)


def classify_signals(text: str, relative_path: str, framework: str) -> dict[str, bool | str]:
    lower_path = relative_path.lower()
    return {
        "framework": framework,
        "quarantined": bool(
            re.search(
                r"quarantined|(?:test|describe|it)\.(?:skip|fixme)|\bskip\s*\(",
                lower_path + "\n" + text,
                re.IGNORECASE,
            )
        ),
        "stableSelector": bool(
            re.search(r"getByTestId|getByRole|data-automation-id|createLocators|DesignerUtils", text)
        ),
        "sharedHelper": bool(
            re.search(
                r"designerUtils|createDesignerUtils|cypress-app-controls|support/commands|Workspace/",
                text,
                re.IGNORECASE,
            )
        ),
        "rawWait": bool(re.search(r"waitForTimeout\s*\(|cy\.wait\s*\(\s*\d+", text)),
        "semanticAssertion": bool(
            re.search(
                r"\bexpect\s*\(|\.should\s*\(|toBeVisible|toContainText|toHaveText|toBeFocused|toHaveCount|throw new Error",
                text,
            )
        ),
        "frameContext": bool(re.search(r"frameLocator|site-iframe|\.frame\s*\(", text)),
        "fixtureDependent": bool(
            re.search(r"ScenarioSpecBuilder|snapshots\.|snapshot\s*:|fixture|mock", text, re.IGNORECASE)
        ),
        "cleanup": bool(re.search(r"afterEach|finally|\.close\s*\(\s*\)", text)),
        "destructive": bool(
            re.search(r"\b(?:delete|publish|save|create)\b|add.*canvas", text, re.IGNORECASE)
        ),
    }


def evidence_record(
    *,
    repo: Path,
    relative_path: str,
    framework: str,
    source_kind: str,
    symbol: str,
    text: str,
    offset: int,
    cache: dict[str, dict[str, str]],
    canonical_helper: bool = False,
) -> dict[str, Any]:
    start_line = line_for_offset(text, offset)
    signals = classify_signals(text, relative_path, framework)
    signals["canonicalHelper"] = canonical_helper
    return {
        "path": relative_path,
        "lineStart": start_line,
        "lineEnd": bounded_end(text, start_line),
        "framework": framework,
        "sourceKind": source_kind,
        "symbol": symbol,
        "signals": signals,
        **file_git_metadata(repo, relative_path, cache),
    }


def operation_evidence(
    repo: Path,
    policy: dict[str, Any],
    operation: dict[str, Any],
    cache: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    symbol = operation["symbol"]
    evidence: list[dict[str, Any]] = []
    helper_relative = ensure_relative(policy["operationSource"], "operationSource")
    helper_path = repo / helper_relative
    if helper_path.is_file():
        helper_text = helper_path.read_text()
        helper_match = re.search(
            rf"(?:export\s+)?(?:async\s+)?function\s+{re.escape(symbol)}\b",
            helper_text,
        )
        if helper_match:
            evidence.append(
                evidence_record(
                    repo=repo,
                    relative_path=helper_relative,
                    framework="playwright-helper",
                    source_kind="shared-helper",
                    symbol=symbol,
                    text=helper_text,
                    offset=helper_match.start(),
                    cache=cache,
                    canonical_helper=True,
                )
            )

    symbol_call = re.compile(rf"\b{re.escape(symbol)}\s*\(")
    evidence_patterns = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in operation.get("evidencePatterns", [])
    ]
    evidence_pattern_mode = operation.get("evidencePatternMode", "any")
    for path, framework in discover_sources(repo, policy):
        text = path.read_text()
        match = symbol_call.search(text)
        if match is None and evidence_patterns:
            pattern_matches = [pattern.search(text) for pattern in evidence_patterns]
            matches = [candidate for candidate in pattern_matches if candidate is not None]
            pattern_matched = (
                bool(matches)
                if evidence_pattern_mode == "any"
                else len(matches) == len(evidence_patterns)
            )
            if pattern_matched:
                match = matches[0]
        if match:
            evidence.append(
                evidence_record(
                    repo=repo,
                    relative_path=path.relative_to(repo).as_posix(),
                    framework=framework,
                    source_kind="test",
                    symbol=symbol,
                    text=text,
                    offset=match.start(),
                    cache=cache,
                )
            )
    return evidence


def locator_selector(locator_text: str, key: str) -> dict[str, str]:
    leaf = key.rsplit(".", 1)[-1]
    escaped = re.escape(leaf)
    patterns = (
        (rf"\b{escaped}\s*:\s*page\.getByTestId\(\s*['\"]([^'\"]+)", "data-automation-id"),
        (rf"\b{escaped}\s*:\s*page\.getByRole\([^\n]+?name\s*:\s*['\"]([^'\"]+)", "role"),
        (rf"\b{escaped}\s*:\s*page\.frameLocator\(\s*['\"]([^'\"]+)", "frame-selector"),
        (rf"\b{escaped}\s*:\s*page\.locator\(\s*['\"]([^'\"]+)", "css-or-attribute"),
    )
    for pattern, strategy in patterns:
        match = re.search(pattern, locator_text)
        if match:
            return {"key": key, "strategy": strategy, "selector": match.group(1)}
    raise CorpusError(f"locator key is absent or not statically represented: {key}")


def score_evidence(record: dict[str, Any]) -> int:
    signals = record["signals"]
    score = 40
    score += 15 if signals["stableSelector"] else 0
    score += 15 if signals["sharedHelper"] else 0
    score += 15 if signals["semanticAssertion"] else 0
    score += 5 if signals["cleanup"] else 0
    score -= 15 if signals["rawWait"] else 0
    score -= 100 if signals["quarantined"] else 0
    return max(0, min(100, score))


def score_card(operation: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, int]:
    positive = [record for record in evidence if not record["signals"]["quarantined"]]
    best = max((score_evidence(record) for record in positive), default=0)
    frameworks = {record["framework"] for record in positive}
    confidence = min(100, best + (8 if len(frameworks) > 1 else 0))
    if not operation["postconditions"]:
        confidence = min(confidence, 54)
    utility = min(
        100,
        30
        + 12 * len(operation["capabilities"])
        + (12 if any(record["signals"]["sharedHelper"] for record in positive) else 0)
        + (10 if len(frameworks) > 1 else 0),
    )
    novelty = min(
        100,
        25
        + 15 * len(operation["capabilities"])
        + (10 if any(record["signals"]["frameContext"] for record in positive) else 0)
        + (10 if operation["guardrails"] else 0),
    )
    return {"confidence": confidence, "utility": utility, "novelty": novelty}


def reason_codes(operation: dict[str, Any], evidence: list[dict[str, Any]]) -> list[str]:
    positive = [record for record in evidence if not record["signals"]["quarantined"]]
    codes: set[str] = set()
    if any(record["signals"]["canonicalHelper"] for record in positive):
        codes.add("canonical-helper")
    if any(record["signals"]["stableSelector"] for record in positive):
        codes.add("stable-selector-evidence")
    if any(record["signals"]["sharedHelper"] for record in positive):
        codes.add("shared-helper-evidence")
    if any(record["signals"]["semanticAssertion"] for record in positive):
        codes.add("semantic-assertion-evidence")
    if any(record["signals"]["cleanup"] for record in positive):
        codes.add("cleanup-evidence")
    if any(record["signals"]["rawWait"] for record in evidence):
        codes.add("fixed-duration-wait")
    if any(record["signals"]["quarantined"] for record in evidence):
        codes.add("quarantined-evidence")
    if len({record["framework"] for record in positive}) > 1:
        codes.add("cross-framework-corroboration")
    if not any(record["sourceKind"] == "test" for record in positive):
        codes.add("missing-direct-test-evidence")
    if not operation["postconditions"]:
        codes.add("missing-semantic-postcondition")
    return sorted(codes)


def build_card(
    repo: Path,
    policy: dict[str, Any],
    operation: dict[str, Any],
    commit: str,
    policy_hash: str,
    cache: dict[str, dict[str, str]],
) -> dict[str, Any]:
    locator_path = repo / ensure_relative(policy["locatorSource"], "locatorSource")
    if not locator_path.is_file():
        raise CorpusError(f"locator source is missing: {policy['locatorSource']}")
    locator_text = locator_path.read_text()
    selectors = [locator_selector(locator_text, key) for key in operation["locatorKeys"]]
    all_evidence = operation_evidence(repo, policy, operation, cache)
    positive = [record for record in all_evidence if not record["signals"]["quarantined"]]
    negative = [record for record in all_evidence if record["signals"]["quarantined"]]
    holdout_limit = int(policy["selection"].get("holdoutEvidencePerOperation", 1))
    holdout_candidates = [record for record in positive if record["sourceKind"] == "test"]
    holdout = holdout_candidates[-holdout_limit:] if holdout_limit else []
    holdout_paths = {record["path"] for record in holdout}
    training = [record for record in positive if record["path"] not in holdout_paths]
    evidence_limit = int(policy["selection"].get("maximumEvidencePerOperation", 5))
    usable = sorted(
        training,
        key=lambda record: (record["sourceKind"] != "shared-helper", record["path"]),
    )[:evidence_limit]
    scoring_evidence = [*training, *negative]
    scores = score_card(operation, scoring_evidence)
    minimum = int(policy["selection"].get("minimumConfidence", 55))
    if not positive and negative:
        status = "negative_evidence"
    elif scores["confidence"] >= minimum and operation["postconditions"]:
        status = "include"
    else:
        status = "candidate"
    return {
        "id": operation["id"],
        "symbol": operation["symbol"],
        "intent": operation["intent"],
        "selectionStatus": status,
        "reasonCodes": reason_codes(operation, scoring_evidence),
        "capabilities": operation["capabilities"],
        "contexts": operation["contexts"],
        "parameters": operation["parameters"],
        "document": "main",
        "selectors": selectors,
        "actions": operation["actions"],
        "postconditions": operation["postconditions"],
        "guardrails": operation["guardrails"],
        "scores": scores,
        "provenance": {
            "sourceCommit": commit,
            "policySha256": policy_hash,
            "operationSource": policy["operationSource"],
            "locatorSource": policy["locatorSource"],
        },
        "evidence": usable,
        "holdoutEvidence": holdout,
        "negativeEvidence": negative,
    }


def choose_portfolio(cards: list[dict[str, Any]]) -> dict[str, Any]:
    remaining = set(
        capability
        for card in cards
        for capability in card["capabilities"]
    )
    selected: list[str] = []
    available = [card for card in cards if card["selectionStatus"] in {"include", "candidate"}]
    while remaining and available:
        card = max(
            available,
            key=lambda item: (
                len(set(item["capabilities"]) & remaining),
                item["scores"]["confidence"],
                item["scores"]["utility"],
            ),
        )
        selected.append(card["id"])
        remaining -= set(card["capabilities"])
        available.remove(card)
    return {"operationIds": selected, "uncoveredCapabilities": sorted(remaining)}


def summarize_cards(cards: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cards": len(cards),
        "evidence": sum(len(card["evidence"]) for card in cards),
        "holdoutEvidence": sum(len(card["holdoutEvidence"]) for card in cards),
        "negativeEvidence": sum(len(card["negativeEvidence"]) for card in cards),
        "byStatus": {
            status: sum(card["selectionStatus"] == status for card in cards)
            for status in sorted(SELECTION_STATUSES)
        },
    }


def build_index(repo: Path, policy: dict[str, Any]) -> dict[str, Any]:
    validate_policy(policy)
    commit = source_commit(repo)
    policy_hash = sha256_json(policy)
    manifest_hash = source_manifest(repo, policy)
    cache: dict[str, dict[str, str]] = {}
    cards = [build_card(repo, policy, operation, commit, policy_hash, cache) for operation in policy["operations"]]
    index = {
        "version": 1,
        "source": {
            "name": "webflow-monorepo",
            "commit": commit,
            "roots": [
                root
                for source in policy["sources"]
                for root in source["roots"]
            ],
        },
        "policySha256": policy_hash,
        "sourceManifestSha256": manifest_hash,
        "cards": cards,
        "portfolio": choose_portfolio(cards),
        "counts": summarize_cards(cards),
    }
    assert_safe_payload(index)
    return index


def assert_safe_payload(value: object, field: str = "index") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SENSITIVE_KEY.search(str(key)):
                raise CorpusError(f"sensitive field is not allowed in generated corpus: {field}.{key}")
            assert_safe_payload(child, f"{field}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_safe_payload(child, f"{field}[{index}]")
    elif isinstance(value, str) and SENSITIVE_VALUE.search(value):
        raise CorpusError(f"sensitive or absolute value is not allowed in generated corpus: {field}")


def validate_card(card: object, policy: dict[str, Any], commit: str) -> None:
    if not isinstance(card, dict):
        raise CorpusError("operation card must be an object")
    required = {
        "id", "symbol", "intent", "selectionStatus", "reasonCodes", "capabilities",
        "contexts", "parameters", "document", "selectors", "actions", "postconditions",
        "guardrails", "scores", "provenance", "evidence", "holdoutEvidence",
        "negativeEvidence",
    }
    if not required <= set(card):
        raise CorpusError(f"operation card is missing fields: {sorted(required - set(card))}")
    if not isinstance(card["id"], str) or not IDENTIFIER.fullmatch(card["id"]):
        raise CorpusError("operation card id is invalid")
    if not isinstance(card["selectionStatus"], str) or card["selectionStatus"] not in SELECTION_STATUSES:
        raise CorpusError("operation card selection status is invalid")
    if not isinstance(card["document"], str) or card["document"] not in {"main", "canvas", "frame"}:
        raise CorpusError("operation card document is invalid")
    if not isinstance(card["provenance"], dict):
        raise CorpusError(f"operation card provenance is invalid: {card['id']}")
    if not isinstance(card["scores"], dict):
        raise CorpusError(f"operation card scores are invalid: {card['id']}")
    for field in (
        "reasonCodes", "capabilities", "contexts", "parameters", "selectors",
        "actions", "postconditions", "guardrails",
    ):
        if not isinstance(card[field], list):
            raise CorpusError(f"operation card {field} is invalid: {card['id']}")
    if card["provenance"].get("sourceCommit") != commit:
        raise CorpusError(f"stale operation provenance: {card['id']}")
    for score_name in ("confidence", "utility", "novelty"):
        score = card["scores"].get(score_name)
        if not isinstance(score, int) or not 0 <= score <= 100:
            raise CorpusError(f"invalid {score_name} score: {card['id']}")
    for evidence_name in ("evidence", "holdoutEvidence", "negativeEvidence"):
        if not isinstance(card[evidence_name], list):
            raise CorpusError(f"operation card {evidence_name} is invalid: {card['id']}")
    for record in [*card["evidence"], *card["holdoutEvidence"], *card["negativeEvidence"]]:
        if not isinstance(record, dict):
            raise CorpusError(f"invalid evidence record: {card['id']}")
        path = ensure_relative(record.get("path"), f"{card['id']}.evidence.path")
        if not isinstance(record.get("lineStart"), int) or not isinstance(record.get("lineEnd"), int):
            raise CorpusError(f"evidence line range is invalid: {path}")
        if record["lineStart"] > record["lineEnd"]:
            raise CorpusError(f"evidence line range is reversed: {path}")
        if not isinstance(record.get("signals"), dict):
            raise CorpusError(f"evidence signals are invalid: {path}")
    evidence_paths = {record["path"] for record in card["evidence"]}
    holdout_paths = {record["path"] for record in card["holdoutEvidence"]}
    if evidence_paths & holdout_paths:
        raise CorpusError(f"holdout evidence leaked into positive evidence: {card['id']}")
    allowed_locator_keys = {
        key
        for operation in policy["operations"]
        for key in operation["locatorKeys"]
    }
    for selector in card["selectors"]:
        if not isinstance(selector, dict):
            raise CorpusError(f"invalid selector in card: {card['id']}")
        if selector.get("key") not in allowed_locator_keys:
            raise CorpusError(f"unknown selector key in card: {card['id']}")


def validate_index(index: dict[str, Any], repo: Path, policy: dict[str, Any]) -> dict[str, Any]:
    validate_policy(policy)
    if not isinstance(index, dict):
        raise CorpusError("corpus index root must be an object")
    if index.get("version") != 1:
        raise CorpusError("unsupported corpus index version")
    commit = source_commit(repo)
    source = index.get("source")
    if not isinstance(source, dict) or source.get("commit") != commit:
        raise CorpusError("corpus index is stale for the current source commit")
    if index.get("policySha256") != sha256_json(policy):
        raise CorpusError("corpus index policy hash is stale")
    if index.get("sourceManifestSha256") != source_manifest(repo, policy):
        raise CorpusError("corpus index source manifest is stale")
    cards = index.get("cards")
    if not isinstance(cards, list) or not cards:
        raise CorpusError("corpus index contains no operation cards")
    expected_ids = {operation["id"] for operation in policy["operations"]}
    actual_ids = {card.get("id") for card in cards if isinstance(card, dict)}
    if len(cards) != len(actual_ids) or expected_ids != actual_ids:
        raise CorpusError("corpus index operation set does not match policy")
    for card in cards:
        validate_card(card, policy, commit)
    assert_safe_payload(index)
    return {"valid": True, "commit": commit, "cardCount": len(cards)}


def evaluate_index(index: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    validate_policy(policy)
    evaluation_policy = policy.get("evaluation", {})
    minimum_holdout = evaluation_policy.get("minimumHoldoutEvidence", 1)
    require_semantic = evaluation_policy.get("requireSemanticAssertion", True)
    results = []
    for card in index.get("cards", []):
        positive_paths = {record["path"] for record in card["evidence"]}
        holdout = card["holdoutEvidence"]
        holdout_paths = {record["path"] for record in holdout}
        has_semantic_assertion = any(
            record["signals"].get("semanticAssertion") for record in holdout
        )
        checks = {
            "holdoutEvidenceMinimum": len(holdout) >= minimum_holdout,
            "semanticAssertion": not require_semantic or has_semantic_assertion,
            "semanticPostcondition": bool(card["postconditions"]),
            "noPositiveHoldoutOverlap": not positive_paths & holdout_paths,
        }
        results.append(
            {
                "id": card["id"],
                "selectionStatus": card["selectionStatus"],
                "holdoutEvidence": len(holdout),
                "positiveEvidence": len(card["evidence"]),
                "checks": checks,
                "status": "pass" if all(checks.values()) else "review",
            }
        )
    passed = sum(result["status"] == "pass" for result in results)
    report = {
        "status": "pass" if results and passed == len(results) else "review",
        "evaluated": len(results),
        "passed": passed,
        "results": results,
    }
    assert_safe_payload(report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "validate", "lookup", "status", "evaluate"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--operation")
    parser.add_argument("--category")
    parser.add_argument("--limit", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        policy = read_json(args.policy)
        validate_policy(policy)
        if args.command == "build":
            if args.output is None:
                raise CorpusError("build requires --output")
            index = build_index(args.repo.resolve(), policy)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
            print(json.dumps({"status": "ok", "cardCount": len(index["cards"]), "commit": index["source"]["commit"]}))
            return 0
        if args.index is None:
            raise CorpusError(f"{args.command} requires --index")
        index = read_json(args.index)
        validation = validate_index(index, args.repo.resolve(), policy)
        if args.command == "validate":
            print(json.dumps(validation, sort_keys=True))
            return 0
        if args.command == "status":
            print(json.dumps({"status": "ok", **validation, "counts": summarize_cards(index["cards"])}, sort_keys=True))
            return 0
        if args.command == "evaluate":
            print(json.dumps({"status": "ok", **validation, "evaluation": evaluate_index(index, policy)}, sort_keys=True))
            return 0
        if args.limit < 1 or args.limit > 20:
            raise CorpusError("--limit must be between 1 and 20")
        cards = index["cards"]
        if args.operation:
            cards = [card for card in cards if card["id"] == args.operation]
            if not cards:
                raise CorpusError(f"operation not found: {args.operation}")
        if args.category:
            cards = [card for card in cards if args.category in card["capabilities"]]
        if not cards:
            raise CorpusError("no operation cards match the lookup")
        print(json.dumps({"status": "ok", "operations": cards[: args.limit]}, indent=2, sort_keys=True))
        return 0
    except (CorpusError, OSError) as error:
        print(json.dumps({"status": "error", "code": "corpus_index_invalid", "message": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
