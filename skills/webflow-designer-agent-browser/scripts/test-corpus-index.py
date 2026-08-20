#!/usr/bin/env python3
"""Discover and curate a provenance-preserving Designer test corpus index.

The Webflow monorepo is an input-only source for this command.  The generated
index contains candidate behavior and operation facts with bounded provenance,
never test bodies or runtime credentials. Discovery is repository-wide within
the allowlisted roots; policy-driven curation remains the only path to trusted
executable knowledge.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, TypedDict


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
UNSAFE_EVIDENCE_SIGNALS = ("quarantined", "rawWait", "fixtureDependent", "destructive")
HEX_COMMIT = re.compile(r"^[0-9a-f]{40}$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
METADATA_BATCH_MARKER = "\x00metadata-batch-loaded"
SOURCE_TEXTS_KEY = "\x00source-texts"
SOURCE_COMMIT_KEY = "\x00source-commit"
_INDEX_CACHE_KEY: tuple[str, str, str, str] | None = None
_INDEX_CACHE_VALUE: dict[str, Any] | None = None
_DISCOVERY_CACHE_KEY: tuple[str, str, str, str] | None = None
_DISCOVERY_CACHE_VALUE: dict[str, Any] | None = None
_SOURCE_MANIFEST_CACHE_KEY: tuple[str, str, str] | None = None
_SOURCE_MANIFEST_CACHE_PATHS: frozenset[str] | None = None
_SOURCE_MANIFEST_CACHE_VALUE: str | None = None
_SOURCE_MANIFEST_CACHE_TEXTS: dict[str, bytes] | None = None
_METADATA_BATCH_CACHE_KEY: tuple[str, str] | None = None
_METADATA_BATCH_CACHE_VALUE: dict[str, dict[str, str]] | None = None
_SOURCE_STATE_KEY: tuple[str, str] | None = None
_SOURCE_STATE_CLEAN = False
SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|credential|password|secret|storage.?state|token)",
    re.IGNORECASE,
)
SENSITIVE_VALUE = re.compile(
    r"(?:https?://|file://|/Users/|/private/var/|/tmp/|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b)",
    re.IGNORECASE,
)
ACTION_METHODS = {
    "check", "clear", "click", "dblclick", "dragTo", "fill", "focus",
    "goto", "hover", "press", "selectOption", "setInputFiles", "tap",
    "trigger", "type", "uncheck",
}
SELECTOR_METHODS = {
    "get", "getByLabel", "getByPlaceholder", "getByRole", "getByTestId",
    "getByText", "locator",
}
IGNORED_CALLS = {
    "afterAll", "afterEach", "beforeAll", "beforeEach", "describe", "expect",
    "async", "forEach", "it", "map", "reduce", "setTimeout", "step", "test",
    *ACTION_METHODS,
    *SELECTOR_METHODS,
}
ACTION_TARGET = re.compile(
    r"\.(getByLabel|getByPlaceholder|getByRole|getByTestId|getByText|locator)\s*"
    r"\(\s*(['\"`])([^'\"`\r\n]{1,120})\2\s*\)\s*"
    r"\.([A-Za-z_$][\w$]*)\s*\("
)
CSS_TEST_ID_TARGET = re.compile(
    r"\.locator\s*\(\s*(['\"])[ \t]*\[\s*data-testid\s*=\s*"
    r"(['\"])([^'\"\r\n]{1,120})\2\s*\][ \t]*\1\s*\)\s*"
    r"\.([A-Za-z_$][\w$]*)\s*\("
)
ROLE_ACTION_TARGET = re.compile(
    r"\.getByRole\s*\(\s*(['\"])([^'\"\r\n]{1,80})\1\s*,\s*"
    r"\{\s*name\s*:\s*(['\"])([^'\"\r\n]{1,120})\3"
    r"(?:\s*,\s*exact\s*:\s*(?:true|false))?\s*\}\s*\)\s*"
    r"\.([A-Za-z_$][\w$]*)\s*\("
)
ROLE_ACTION_TARGET_SHAPE = re.compile(
    r"\.getByRole\s*\(\s*,\s*\{\s*name\s*:\s*"
    r"(?:\s*,\s*exact\s*:\s*(?:true|false))?\s*\}\s*\)\s*"
    r"\.([A-Za-z_$][\w$]*)\s*\("
)
LOCAL_TEST_ID_ALIAS = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:[A-Za-z_$][\w$]*\.)?getByTestId\s*\(\s*(['\"`])"
    r"([^'\"`\r\n]{1,120})\2\s*\)\s*;"
)
LOCAL_TEST_ID_ALIAS_SHAPE = re.compile(
    r"\b(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*"
    r"(?:[A-Za-z_$][\w$]*\.)?getByTestId\s*\(\s*\)\s*;"
)
ACTION_TARGET_SHAPE = re.compile(
    r"\.(?:getByLabel|getByPlaceholder|getByRole|getByTestId|getByText|locator)\s*"
    r"\(\s*\)\s*\.([A-Za-z_$][\w$]*)\s*\("
)


class CorpusError(ValueError):
    """A fail-closed corpus or provenance error."""


class FragmentFeatures(TypedDict):
    actions: list[str]
    selectors: list[str]
    helperCalls: list[str]
    semanticAssertion: bool
    cleanup: bool
    rawWait: bool
    frameContext: bool
    fixtureDependent: bool
    quarantined: bool
    destructive: bool
    actionTargets: list[str]


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


def source_state(repo: Path) -> tuple[str, bool]:
    global _SOURCE_STATE_KEY, _SOURCE_STATE_CLEAN
    output = run_git(repo, "status", "--porcelain=v2", "--branch", "--untracked-files=all")
    commit = None
    clean = True
    for line in output.splitlines():
        if line.startswith("# branch.oid "):
            commit = line.removeprefix("# branch.oid ").strip()
        elif not line.startswith("#"):
            clean = False
    if not isinstance(commit, str):
        raise CorpusError("source repository did not return a HEAD commit")
    if not HEX_COMMIT.fullmatch(commit):
        raise CorpusError("source repository did not return a full commit hash")
    _SOURCE_STATE_KEY = (repo.resolve().as_posix(), commit)
    _SOURCE_STATE_CLEAN = clean
    return commit, clean


def source_commit(repo: Path) -> str:
    return source_state(repo)[0]


def metadata_cache_key(repo: Path, cache: dict[str, Any]) -> tuple[str, str] | None:
    commit = cache.get(SOURCE_COMMIT_KEY)
    if not isinstance(commit, str) or not HEX_COMMIT.fullmatch(commit):
        return None
    return (repo.resolve().as_posix(), commit)


def prime_file_metadata_cache(repo: Path, cache: dict[str, Any]) -> None:
    if (
        METADATA_BATCH_MARKER in cache
        or _METADATA_BATCH_CACHE_KEY is None
        or _METADATA_BATCH_CACHE_VALUE is None
        or metadata_cache_key(repo, cache) != _METADATA_BATCH_CACHE_KEY
    ):
        return
    cache.update(_METADATA_BATCH_CACHE_VALUE)
    cache[METADATA_BATCH_MARKER] = {}


def file_git_metadata(repo: Path, relative_path: str, cache: dict[str, Any]) -> dict[str, str]:
    global _METADATA_BATCH_CACHE_KEY, _METADATA_BATCH_CACHE_VALUE
    if relative_path in cache:
        return cache[relative_path]
    if METADATA_BATCH_MARKER not in cache:
        metadata_key = metadata_cache_key(repo, cache)
        if metadata_key is not None and _METADATA_BATCH_CACHE_KEY == metadata_key and _METADATA_BATCH_CACHE_VALUE is not None:
            cache.update(_METADATA_BATCH_CACHE_VALUE)
        else:
            output = run_git(repo, "log", "-M", "--name-status", "--format=%H%x00%cI", "--")
            loaded: dict[str, dict[str, str]] = {}
            current: tuple[str, str] | None = None
            for line in output.splitlines():
                if "\x00" in line:
                    commit, changed_at = line.split("\x00", 1)
                    if HEX_COMMIT.fullmatch(commit):
                        current = (commit, changed_at)
                    continue
                if not line or current is None:
                    continue
                fields = line.split("\t")
                if len(fields) < 2:
                    continue
                paths = fields[1:] if fields[0].startswith(("R", "C")) else fields[1:2]
                for path in paths:
                    if path and path not in loaded:
                        loaded[path] = {
                            "lastChangedCommit": current[0],
                            "lastChangedAt": current[1],
                        }
            cache.update(loaded)
            if metadata_key is not None:
                _METADATA_BATCH_CACHE_KEY = metadata_key
                _METADATA_BATCH_CACHE_VALUE = loaded
        cache[METADATA_BATCH_MARKER] = {}
    if relative_path in cache:
        return cache[relative_path]
    cache[relative_path] = {}
    return cache[relative_path]


def source_paths_are_cacheable(
    repo: Path,
    paths: set[str],
    known_tracked: bool = False,
    commit: str | None = None,
) -> bool:
    if any((repo / relative).is_symlink() for relative in paths):
        return False
    try:
        state_is_clean = (
            commit is not None
            and _SOURCE_STATE_KEY == (repo.resolve().as_posix(), commit)
            and _SOURCE_STATE_CLEAN
        )
        if not state_is_clean and run_git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
            return False
        if known_tracked:
            return True
        tracked = set(run_git(repo, "ls-files", "--error-unmatch", "--", *sorted(paths)).splitlines())
    except CorpusError:
        return False
    return tracked == paths


def source_manifest_paths(repo: Path, policy: dict[str, Any]) -> set[str]:
    paths = {
        ensure_relative(policy["operationSource"], "operationSource"),
        ensure_relative(policy["locatorSource"], "locatorSource"),
    }
    paths.update(path.relative_to(repo).as_posix() for path, _ in discover_sources(repo, policy))
    for helper_source in policy.get("discovery", {}).get("helperSources", []):
        paths.add(ensure_relative(helper_source, "discovery helper source"))
    return paths


def source_manifest(
    repo: Path,
    policy: dict[str, Any],
    source_texts: dict[str, bytes] | None = None,
    commit: str | None = None,
) -> str:
    global _SOURCE_MANIFEST_CACHE_KEY, _SOURCE_MANIFEST_CACHE_PATHS
    global _SOURCE_MANIFEST_CACHE_VALUE, _SOURCE_MANIFEST_CACHE_TEXTS
    paths = source_manifest_paths(repo, policy)
    policy_hash = sha256_json(policy)
    cache_key = (repo.resolve().as_posix(), commit or "", policy_hash)
    cache_identity_matches = (
        commit is not None
        and _SOURCE_MANIFEST_CACHE_KEY == cache_key
        and _SOURCE_MANIFEST_CACHE_PATHS == frozenset(paths)
    )
    cacheable = commit is not None and source_paths_are_cacheable(
        repo, paths, cache_identity_matches, commit
    )
    if (
        cacheable
        and cache_identity_matches
        and _SOURCE_MANIFEST_CACHE_VALUE is not None
        and (source_texts is None or _SOURCE_MANIFEST_CACHE_TEXTS is not None)
    ):
        if source_texts is not None and _SOURCE_MANIFEST_CACHE_TEXTS is not None:
            source_texts.update(_SOURCE_MANIFEST_CACHE_TEXTS)
        return _SOURCE_MANIFEST_CACHE_VALUE
    entries = []
    snapshot: dict[str, bytes] = {}
    for relative in sorted(paths):
        path = repo / relative
        if not path.is_file():
            raise CorpusError(f"source manifest file is missing: {relative}")
        content = path.read_bytes()
        snapshot[relative] = content
        if source_texts is not None:
            source_texts[relative] = content
        entries.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest()})
    manifest_hash = sha256_json(entries)
    if cacheable:
        _SOURCE_MANIFEST_CACHE_KEY = cache_key
        _SOURCE_MANIFEST_CACHE_PATHS = frozenset(paths)
        _SOURCE_MANIFEST_CACHE_VALUE = manifest_hash
        _SOURCE_MANIFEST_CACHE_TEXTS = snapshot if source_texts is not None else None
    return manifest_hash


def read_source_text(
    repo: Path,
    relative_path: str,
    source_texts: dict[str, bytes] | None = None,
) -> str:
    if source_texts is not None and relative_path in source_texts:
        return source_texts[relative_path].decode()
    return (repo / relative_path).read_text()


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
    discovery = policy.get("discovery", {})
    if not isinstance(discovery, dict):
        raise CorpusError("corpus policy discovery is invalid")
    helper_sources = discovery.get("helperSources", [])
    if not isinstance(helper_sources, list):
        raise CorpusError("corpus policy discovery helperSources is invalid")
    for helper_source in helper_sources:
        ensure_relative(helper_source, "discovery helper source")
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


def masked_source(text: str) -> str:
    """Mask strings and comments while preserving offsets and line numbers.

    This is intentionally a small lexical layer, not a TypeScript evaluator. It
    lets the compiler locate balanced callback bodies without treating text in a
    comment or string literal as an action. Unsupported or unbalanced input is
    ignored by the callers rather than guessed at.
    """
    output = list(text)
    index = 0
    state = "code"
    quote = ""
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if state == "code" and char == "/" and next_char == "/":
            output[index] = output[index + 1] = " "
            index += 2
            state = "line-comment"
            continue
        if state == "code" and char == "/" and next_char == "*":
            output[index] = output[index + 1] = " "
            index += 2
            state = "block-comment"
            continue
        if state == "code" and char in {"'", '"', "`"}:
            output[index] = " "
            quote = char
            index += 1
            state = "string"
            continue
        if state == "line-comment":
            if char == "\n":
                state = "code"
            else:
                output[index] = " "
            index += 1
            continue
        if state == "block-comment":
            if char == "*" and next_char == "/":
                output[index] = output[index + 1] = " "
                index += 2
                state = "code"
            else:
                if char != "\n":
                    output[index] = " "
                index += 1
            continue
        if state == "string":
            if char == "\\":
                output[index] = " "
                if index + 1 < len(text):
                    if text[index + 1] != "\n":
                        output[index + 1] = " "
                    index += 2
                else:
                    index += 1
            elif char == quote:
                output[index] = " "
                index += 1
                state = "code"
            else:
                if char != "\n":
                    output[index] = " "
                index += 1
            continue
        index += 1
    return "".join(output)


def balanced_body(masked: str, opening_brace: int) -> int | None:
    """Return the closing brace for one brace-delimited callback body."""
    if opening_brace >= len(masked) or masked[opening_brace] != "{":
        return None
    depth = 0
    for index in range(opening_brace, len(masked)):
        if masked[index] == "{":
            depth += 1
        elif masked[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def structural_fragments(text: str, relative_path: str, framework: str) -> list[dict[str, Any]]:
    """Extract bounded test and helper bodies without executing source code.

    A fragment is the narrowest balanced test callback or named function body.
    Nesting is retained because a `test.step` can carry a distinct assertion,
    but a parent test is not allowed to borrow signals from another test.
    """
    masked = masked_source(text)
    fragments: list[dict[str, Any]] = []
    patterns = (
        ("test", re.compile(r"\b(?:test|it)(?:\.(?:only|skip|fixme))?\s*\(", re.MULTILINE)),
        ("helper", re.compile(r"\b(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", re.MULTILINE)),
    )
    for source_kind, pattern in patterns:
        for match in pattern.finditer(masked):
            search_start = match.end()
            if source_kind == "test":
                arrow = masked.find("=>", search_start)
                if arrow < 0:
                    continue
                opening = masked.find("{", arrow + 2)
            else:
                opening = masked.find("{", search_start)
            if opening < 0:
                continue
            closing = balanced_body(masked, opening)
            if closing is None:
                continue
            # A callback's opening brace must occur before the next declaration.
            next_match = pattern.search(masked, match.end())
            if next_match is not None and opening > next_match.start():
                continue
            name = match.group(1) if source_kind == "helper" else "test"
            fragments.append(
                {
                    "path": relative_path,
                    "framework": framework,
                    "sourceKind": source_kind,
                    "symbol": name or "test",
                    "start": match.start(),
                    "end": closing + 1,
                    "lineStart": line_for_offset(text, match.start()),
                    "lineEnd": line_for_offset(text, closing),
                    "text": text[match.start(): closing + 1],
                }
            )
    return sorted(fragments, key=lambda item: (item["start"], item["end"], item["sourceKind"]))


def selector_target_key(selector: str, value: object, action: str) -> str:
    """Normalize only selector forms that identify the same stable target."""
    family = "testid" if selector == "getByTestId" else selector
    return canonical_json({"action": action, "family": family, "value": value}).decode("utf-8")


def stable_selector_literal(quote: str, value: str) -> bool:
    """Reject interpolated template values instead of binding them as literals."""
    return quote != "`" or "${" not in value


def fragment_features(fragment_text: str) -> FragmentFeatures:
    """Produce non-sensitive structural facts for one test or helper fragment."""
    masked = masked_source(fragment_text)
    method_names = [
        match.group(1)
        for match in re.finditer(r"\.([A-Za-z_$][\w$]*)\s*\(", masked)
    ]
    action_methods = sorted({name for name in method_names if name in ACTION_METHODS})
    selector_methods = sorted({name for name in method_names if name in SELECTOR_METHODS})
    calls = sorted(
        {
            match.group(1)
            for match in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*\(", masked)
            if match.group(1) not in IGNORED_CALLS
        }
    )
    action_targets = []
    for match in ACTION_TARGET.finditer(fragment_text):
        masked_target = masked[match.start():match.end()]
        shape = ACTION_TARGET_SHAPE.fullmatch(masked_target)
        if (
            shape is not None
            and shape.group(1) in ACTION_METHODS
            and stable_selector_literal(match.group(2), match.group(3))
        ):
            action_targets.append(
                selector_target_key(match.group(1), match.group(3), match.group(4))
            )
    for match in CSS_TEST_ID_TARGET.finditer(fragment_text):
        masked_target = masked[match.start():match.end()]
        shape = ACTION_TARGET_SHAPE.fullmatch(masked_target)
        if shape is not None and shape.group(1) in ACTION_METHODS:
            action_targets.append(
                selector_target_key("getByTestId", match.group(3), match.group(4))
            )
    for match in ROLE_ACTION_TARGET.finditer(fragment_text):
        masked_target = masked[match.start():match.end()]
        shape = ROLE_ACTION_TARGET_SHAPE.fullmatch(masked_target)
        if shape is not None and shape.group(1) in ACTION_METHODS:
            action_targets.append(
                selector_target_key(
                    "getByRole",
                    {"name": match.group(4), "role": match.group(2)},
                    match.group(5),
                )
            )
    for match in LOCAL_TEST_ID_ALIAS.finditer(fragment_text):
        masked_alias = masked[match.start():match.end()]
        if (
            LOCAL_TEST_ID_ALIAS_SHAPE.fullmatch(masked_alias) is None
            or not stable_selector_literal(match.group(2), match.group(3))
        ):
            continue
        alias = re.escape(match.group(1))
        for action_match in re.finditer(
            rf"\b{alias}\s*\.\s*([A-Za-z_$][\w$]*)\s*\(", masked
        ):
            action = action_match.group(1)
            if action in ACTION_METHODS:
                action_targets.append(
                    selector_target_key("getByTestId", match.group(3), action)
                )
    action_targets = sorted(set(action_targets))
    return {
        "actions": action_methods,
        "selectors": selector_methods,
        "helperCalls": calls,
        "semanticAssertion": bool(
            re.search(r"\bexpect\s*\(|\.should\s*\(|\bassert(?:\.\w+)?\s*\(", masked)
        ),
        "cleanup": bool(re.search(r"\b(?:afterEach|afterAll|finally)\b|\.close\s*\(", masked)),
        "rawWait": bool(re.search(r"waitForTimeout\s*\(|cy\.wait\s*\(\s*\d+", masked)),
        "frameContext": bool(re.search(r"frameLocator|site-iframe|\.frame\s*\(", masked)),
        "fixtureDependent": bool(re.search(r"ScenarioSpecBuilder|snapshots\.|snapshot\s*:|\bfixture\b|\bmock\b", masked, re.IGNORECASE)),
        "quarantined": bool(re.search(r"\b(?:test|describe|it)\.(?:skip|fixme)\b", masked)),
        "destructive": bool(re.search(r"\b(?:delete|publish|save|create)\b|add.*canvas", masked, re.IGNORECASE)),
        "actionTargets": action_targets,
    }


def subsystem_for_path(relative_path: str) -> str:
    """Derive a bounded subsystem label from an allowlisted test path."""
    parts = Path(relative_path).parts
    ignored = {"entrypoints", "playwright-tests", "designer", "client-ui-tests", "specs", "tests"}
    for part in parts[:-1]:
        normalized = re.sub(r"[^a-z0-9]+", "-", part.lower()).strip("-")
        if normalized and normalized not in ignored and not normalized.startswith("index"):
            return normalized[:48]
    return "unclassified"


def discovery_dimensions(features: FragmentFeatures, source_kind: str) -> dict[str, int]:
    """Keep promotion evidence dimensions separate instead of hiding them in one score."""
    action_count = len(features["actions"])
    selector_count = len(features["selectors"])
    return {
        "semanticDirectness": 100 if features["semanticAssertion"] and action_count else 0,
        "selectorStability": 100 if selector_count else 25 if action_count else 0,
        "fixtureRepresentativeness": 20 if features["fixtureDependent"] else 100,
        "cleanupStrength": 100 if features["cleanup"] else 0,
        "mutationRisk": 100 if features["destructive"] else 0,
        "recoveryCoverage": 100 if features["cleanup"] else 0,
        "sourceDirectness": 100 if source_kind == "test" else 75,
    }


def lineage_for_features(features: FragmentFeatures, relative_path: str, framework: str) -> str:
    helper_calls = [call for call in features["helperCalls"] if call not in features["actions"]]
    lineage_seed = (
        f"helpers:{','.join(helper_calls)}"
        if helper_calls
        else f"family:{framework}:{Path(relative_path).parent.as_posix()}"
    )
    return hashlib.sha256(lineage_seed.encode("utf-8")).hexdigest()[:16]


def evidence_is_eligible(record: dict[str, Any]) -> bool:
    signals = record.get("signals")
    return isinstance(signals, dict) and not any(
        signals.get(key) is True for key in UNSAFE_EVIDENCE_SIGNALS
    )


def semantic_identity(
    features: FragmentFeatures,
    *,
    relative_path: str,
    line_start: int,
    line_end: int,
) -> dict[str, str | bool]:
    """Return a privacy-preserving behavior anchor for conservative clustering.

    Action target literals stay in the source only.  The report stores their
    deterministic digest, while fragments without an anchor are deliberately
    unique so generic action shape cannot create corroboration.
    """
    if features["actionTargets"]:
        kind = "selector-target"
        seed: object = features["actionTargets"]
        bound = True
    elif features["helperCalls"]:
        kind = "helper-call"
        seed = features["helperCalls"]
        bound = True
    else:
        kind = "unanchored"
        seed = {"path": relative_path, "lineStart": line_start, "lineEnd": line_end}
        bound = False
    return {
        "kind": kind,
        "bound": bound,
        "digest": sha256_json(seed)[:16],
    }


def fragment_record(
    repo: Path,
    fragment: dict[str, Any],
    cache: dict[str, Any],
) -> dict[str, Any] | None:
    features = fragment_features(fragment["text"])
    if not features["actions"]:
        return None
    signature = {
        "actions": features["actions"],
        "selectors": features["selectors"],
        "semanticAssertion": features["semanticAssertion"],
        "frameContext": features["frameContext"],
    }
    identity = semantic_identity(
        features,
        relative_path=fragment["path"],
        line_start=fragment["lineStart"],
        line_end=fragment["lineEnd"],
    )
    metadata = cache.get(fragment["path"])
    if metadata is None:
        metadata = file_git_metadata(repo, fragment["path"], cache)
    return {
        "path": fragment["path"],
        "lineStart": fragment["lineStart"],
        "lineEnd": fragment["lineEnd"],
        "framework": fragment["framework"],
        "sourceKind": fragment["sourceKind"],
        "symbol": fragment["symbol"],
        "subsystem": subsystem_for_path(fragment["path"]),
        "signature": signature,
        "semanticIdentity": identity,
        "lineage": lineage_for_features(features, fragment["path"], fragment["framework"]),
        "dimensions": discovery_dimensions(features, fragment["sourceKind"]),
        "signals": {
            key: features[key]
            for key in ("quarantined", "rawWait", "fixtureDependent", "destructive", "cleanup")
        },
        **metadata,
    }


def candidate_id(record: dict[str, Any]) -> str:
    signature = record["signature"]
    seed = canonical_json(
        {
            "framework": record["framework"],
            "subsystem": record["subsystem"],
            "signature": signature,
            "semanticIdentity": record["semanticIdentity"],
        }
    )
    return f"candidate.{hashlib.sha256(seed).hexdigest()[:16]}"


def build_discovery(repo: Path, policy: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic, data-only inventory of candidate interactions.

    Discovery deliberately does not create operation cards or promotion state.
    It is an offline review input whose source ranges are bounded to one
    structurally extracted fragment.
    """
    global _DISCOVERY_CACHE_KEY, _DISCOVERY_CACHE_VALUE
    validate_policy(policy)
    commit = source_commit(repo)
    policy_hash = sha256_json(policy)
    source_texts: dict[str, bytes] = {}
    manifest_hash = source_manifest(repo, policy, source_texts, commit)
    cache_key = (repo.resolve().as_posix(), commit, policy_hash, manifest_hash)
    if _DISCOVERY_CACHE_KEY == cache_key and _DISCOVERY_CACHE_VALUE is not None:
        return copy.deepcopy(_DISCOVERY_CACHE_VALUE)
    cache: dict[str, Any] = {SOURCE_TEXTS_KEY: source_texts, SOURCE_COMMIT_KEY: commit}
    prime_file_metadata_cache(repo, cache)
    records: list[dict[str, Any]] = []
    for path, framework in discover_sources(repo, policy):
        relative_path = path.relative_to(repo).as_posix()
        text = read_source_text(repo, relative_path, source_texts)
        for fragment in structural_fragments(text, relative_path, framework):
            record = fragment_record(repo, fragment, cache)
            if record is not None:
                records.append(record)
    for helper_source in policy.get("discovery", {}).get("helperSources", []):
        relative_path = ensure_relative(helper_source, "discovery helper source")
        helper_path = repo / relative_path
        if not helper_path.is_file():
            raise CorpusError(f"discovery helper source is missing: {relative_path}")
        for fragment in structural_fragments(
            read_source_text(repo, relative_path, source_texts),
            relative_path,
            "source-helper",
        ):
            if fragment["sourceKind"] != "helper":
                continue
            record = fragment_record(repo, fragment, cache)
            if record is not None:
                records.append(record)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(candidate_id(record), []).append(record)
    candidates = []
    for identifier, evidence in sorted(grouped.items()):
        evidence = sorted(evidence, key=lambda item: (item["path"], item["lineStart"], item["sourceKind"]))
        lineages = sorted({item["lineage"] for item in evidence})
        eligible = [item for item in evidence if evidence_is_eligible(item)]
        holdout = next(
            (
                item
                for item in reversed(eligible)
                if sum(candidate["lineage"] == item["lineage"] for candidate in eligible) == 1
                and any(candidate["lineage"] != item["lineage"] for candidate in eligible)
            ),
            None,
        )
        training = [item for item in eligible if item is not holdout]
        average = {
            key: sum(item["dimensions"][key] for item in training) // len(training) if training else 0
            for key in ("semanticDirectness", "selectorStability", "fixtureRepresentativeness", "cleanupStrength", "mutationRisk", "recoveryCoverage", "sourceDirectness")
        }
        semantic_identity_value = evidence[0]["semanticIdentity"]
        semantic_identity_bound = bool(semantic_identity_value["bound"])
        promotion_checks = {
            "semanticIdentityBound": semantic_identity_bound,
            "semanticDirectness": average["semanticDirectness"] == 100,
            "independentCorroboration": semantic_identity_bound and len(lineages) >= 2,
            "holdoutIndependent": semantic_identity_bound and holdout is not None,
            "noUnsafeEvidence": len(eligible) == len(evidence),
            "notRuntimePromoted": True,
        }
        candidates.append(
            {
                "id": identifier,
                "reviewState": "quarantined" if not eligible else "discovered",
                "framework": evidence[0]["framework"],
                "subsystem": evidence[0]["subsystem"],
                "signature": evidence[0]["signature"],
                "semanticIdentity": semantic_identity_value,
                "dimensions": average,
                "promotionChecks": promotion_checks,
                "evidence": training,
                "holdoutEvidence": [holdout] if holdout is not None else [],
                "excludedEvidence": [item for item in evidence if item not in training and item is not holdout],
            }
        )
    by_subsystem: dict[str, int] = {}
    by_framework: dict[str, int] = {}
    by_identity = {"anchored": 0, "unanchored": 0}
    gaps = {
        "missingSemanticIdentity": 0,
        "missingSemanticAssertion": 0,
        "missingSelector": 0,
        "missingIndependentLineage": 0,
        "missingHoldout": 0,
    }
    for candidate in candidates:
        by_subsystem[candidate["subsystem"]] = by_subsystem.get(candidate["subsystem"], 0) + 1
        by_framework[candidate["framework"]] = by_framework.get(candidate["framework"], 0) + 1
        identity_bucket = "anchored" if candidate["semanticIdentity"]["bound"] else "unanchored"
        by_identity[identity_bucket] += 1
        checks = candidate["promotionChecks"]
        if not checks["semanticIdentityBound"]:
            gaps["missingSemanticIdentity"] += 1
        if not checks["semanticDirectness"]:
            gaps["missingSemanticAssertion"] += 1
        if candidate["dimensions"]["selectorStability"] == 0:
            gaps["missingSelector"] += 1
        if not checks["independentCorroboration"]:
            gaps["missingIndependentLineage"] += 1
        if not checks["holdoutIndependent"]:
            gaps["missingHoldout"] += 1
    result = {
        "version": 2,
        "source": {"name": "webflow-monorepo", "commit": commit},
        "policySha256": policy_hash,
        "sourceManifestSha256": manifest_hash,
        "counts": {"fragments": len(records), "candidates": len(candidates)},
        "coverage": {
            "bySubsystem": dict(sorted(by_subsystem.items())),
            "byFramework": dict(sorted(by_framework.items())),
            "byIdentity": by_identity,
            "gaps": gaps,
        },
        "candidates": candidates,
    }
    assert_safe_payload(result, "discovery")
    _DISCOVERY_CACHE_KEY = cache_key
    _DISCOVERY_CACHE_VALUE = copy.deepcopy(result)
    return result


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
    cache: dict[str, Any],
    canonical_helper: bool = False,
) -> dict[str, Any]:
    start_line = line_for_offset(text, offset)
    features = fragment_features(text)
    signals = classify_signals(text, relative_path, framework)
    signals["canonicalHelper"] = canonical_helper
    metadata = cache.get(relative_path)
    if metadata is None:
        metadata = file_git_metadata(repo, relative_path, cache)
    return {
        "path": relative_path,
        "lineStart": start_line,
        "lineEnd": bounded_end(text, start_line),
        "framework": framework,
        "sourceKind": source_kind,
        "symbol": symbol,
        "lineage": lineage_for_features(features, relative_path, framework),
        "signals": signals,
        **metadata,
    }


def operation_evidence(
    repo: Path,
    policy: dict[str, Any],
    operation: dict[str, Any],
    cache: dict[str, Any],
) -> list[dict[str, Any]]:
    symbol = operation["symbol"]
    evidence: list[dict[str, Any]] = []
    source_texts = cache.get(SOURCE_TEXTS_KEY)
    if not isinstance(source_texts, dict):
        source_texts = None
    if source_texts is None and _SOURCE_MANIFEST_CACHE_KEY is not None and _SOURCE_MANIFEST_CACHE_TEXTS is not None:
        cached_repo, cached_commit, cached_policy = _SOURCE_MANIFEST_CACHE_KEY
        if cached_repo == repo.resolve().as_posix() and cached_policy == sha256_json(policy):
            current_commit = source_commit(repo)
            cache[SOURCE_COMMIT_KEY] = current_commit
            current_paths = source_manifest_paths(repo, policy)
            if (
                current_commit == cached_commit
                and _SOURCE_MANIFEST_CACHE_PATHS == frozenset(current_paths)
                and source_paths_are_cacheable(
                    repo, current_paths, known_tracked=True, commit=current_commit
                )
            ):
                source_texts = _SOURCE_MANIFEST_CACHE_TEXTS
    prime_file_metadata_cache(repo, cache)
    helper_relative = ensure_relative(policy["operationSource"], "operationSource")
    helper_path = repo / helper_relative
    if helper_path.is_file():
        helper_text = read_source_text(repo, helper_relative, source_texts)
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
        relative_path = path.relative_to(repo).as_posix()
        text = read_source_text(repo, relative_path, source_texts)
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
                    relative_path=relative_path,
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
    if not evidence_is_eligible(record):
        return 0
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
    positive = [record for record in evidence if evidence_is_eligible(record)]
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
    positive = [record for record in evidence if evidence_is_eligible(record)]
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
    cache: dict[str, Any],
) -> dict[str, Any]:
    locator_path = repo / ensure_relative(policy["locatorSource"], "locatorSource")
    if not locator_path.is_file():
        raise CorpusError(f"locator source is missing: {policy['locatorSource']}")
    source_texts = cache.get(SOURCE_TEXTS_KEY)
    if not isinstance(source_texts, dict):
        source_texts = None
    locator_relative = locator_path.relative_to(repo).as_posix()
    locator_text = read_source_text(repo, locator_relative, source_texts)
    selectors = [locator_selector(locator_text, key) for key in operation["locatorKeys"]]
    all_evidence = operation_evidence(repo, policy, operation, cache)
    positive = [record for record in all_evidence if evidence_is_eligible(record)]
    negative = [record for record in all_evidence if not evidence_is_eligible(record)]
    holdout_limit = int(policy["selection"].get("holdoutEvidencePerOperation", 1))
    holdout_candidates = [record for record in positive if record["sourceKind"] == "test"]
    lineage_counts = {
        lineage: sum(record["lineage"] == lineage for record in holdout_candidates)
        for lineage in {record["lineage"] for record in holdout_candidates}
    }
    holdout = []
    if holdout_limit:
        holdout = [
            record
            for record in reversed(holdout_candidates)
            if lineage_counts[record["lineage"]] == 1
            and any(other["lineage"] != record["lineage"] for other in holdout_candidates)
        ][:holdout_limit]
    holdout_ids = {id(record) for record in holdout}
    training = [record for record in positive if id(record) not in holdout_ids]
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
    global _INDEX_CACHE_KEY, _INDEX_CACHE_VALUE
    validate_policy(policy)
    commit = source_commit(repo)
    policy_hash = sha256_json(policy)
    source_texts: dict[str, bytes] = {}
    manifest_hash = source_manifest(repo, policy, source_texts, commit)
    cache_key = (repo.resolve().as_posix(), commit, policy_hash, manifest_hash)
    if _INDEX_CACHE_KEY == cache_key and _INDEX_CACHE_VALUE is not None:
        return copy.deepcopy(_INDEX_CACHE_VALUE)
    cache: dict[str, Any] = {SOURCE_TEXTS_KEY: source_texts, SOURCE_COMMIT_KEY: commit}
    prime_file_metadata_cache(repo, cache)
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
    _INDEX_CACHE_KEY = cache_key
    _INDEX_CACHE_VALUE = copy.deepcopy(index)
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
        if not isinstance(record.get("lineage"), str) or not re.fullmatch(r"[0-9a-f]{16}", record["lineage"]):
            raise CorpusError(f"evidence lineage is invalid: {path}")
    evidence_paths = {record["path"] for record in card["evidence"]}
    holdout_paths = {record["path"] for record in card["holdoutEvidence"]}
    if evidence_paths & holdout_paths:
        raise CorpusError(f"holdout evidence leaked into positive evidence: {card['id']}")
    training_lineages = {record["lineage"] for record in card["evidence"]}
    holdout_lineages = {record["lineage"] for record in card["holdoutEvidence"]}
    if training_lineages & holdout_lineages:
        raise CorpusError(f"holdout lineage leaked into positive evidence: {card['id']}")
    if len(card["holdoutEvidence"]) > 1:
        raise CorpusError(f"operation card has multiple holdouts: {card['id']}")
    if holdout_lineages and (
        len(holdout_lineages) != 1
        or sum(record["lineage"] in holdout_lineages for record in [*card["evidence"], *card["holdoutEvidence"]]) != 1
    ):
        raise CorpusError(f"operation card holdout lineage is not independent: {card['id']}")
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
    policy_hash = sha256_json(policy)
    source = index.get("source")
    if not isinstance(source, dict) or source.get("commit") != commit:
        raise CorpusError("corpus index is stale for the current source commit")
    if index.get("policySha256") != policy_hash:
        raise CorpusError("corpus index policy hash is stale")
    manifest_hash = source_manifest(repo, policy, commit=commit)
    if index.get("sourceManifestSha256") != manifest_hash:
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
    cache_key = (repo.resolve().as_posix(), commit, policy_hash, manifest_hash)
    cached_cards = None
    if _INDEX_CACHE_KEY == cache_key and _INDEX_CACHE_VALUE is not None:
        candidate_cards = _INDEX_CACHE_VALUE.get("cards")
        if isinstance(candidate_cards, list) and all(
            isinstance(card, dict) and isinstance(card.get("id"), str)
            for card in candidate_cards
        ):
            cached_cards = {card["id"]: card for card in candidate_cards}
    expected_cards = cached_cards or {
        operation["id"]: build_card(
            repo,
            policy,
            operation,
            commit,
            policy_hash,
            {},
        )
        for operation in policy["operations"]
    }
    for card in cards:
        if canonical_json(card) != canonical_json(expected_cards[card["id"]]):
            raise CorpusError(f"operation card does not match source compilation: {card['id']}")
    assert_safe_payload(index)
    return {"valid": True, "commit": commit, "cardCount": len(cards)}


def validate_discovery(discovery: object, repo: Path, policy: dict[str, Any]) -> dict[str, Any]:
    """Reject stale, unsafe, or structurally inconsistent discovery output."""
    validate_policy(policy)
    if not isinstance(discovery, dict) or discovery.get("version") != 2:
        raise CorpusError("unsupported discovery report")
    source = discovery.get("source")
    commit = source_commit(repo)
    if not isinstance(source, dict) or source.get("commit") != commit:
        raise CorpusError("discovery report is stale for the current source commit")
    if discovery.get("policySha256") != sha256_json(policy):
        raise CorpusError("discovery report policy hash is stale")
    if discovery.get("sourceManifestSha256") != source_manifest(repo, policy, commit=commit):
        raise CorpusError("discovery report source manifest is stale")
    candidates = discovery.get("candidates")
    if not isinstance(candidates, list):
        raise CorpusError("discovery report candidates are invalid")
    expected_dimensions = {
        "semanticDirectness", "selectorStability", "fixtureRepresentativeness",
        "cleanupStrength", "mutationRisk", "recoveryCoverage", "sourceDirectness",
    }
    expected_checks = {
        "semanticIdentityBound", "semanticDirectness", "independentCorroboration",
        "holdoutIndependent", "noUnsafeEvidence", "notRuntimePromoted",
    }
    observed_subsystems: dict[str, int] = {}
    observed_frameworks: dict[str, int] = {}
    observed_identity = {"anchored": 0, "unanchored": 0}
    observed_gaps = {
        "missingSemanticIdentity": 0,
        "missingSemanticAssertion": 0,
        "missingSelector": 0,
        "missingIndependentLineage": 0,
        "missingHoldout": 0,
    }
    observed_fragments = 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise CorpusError("discovery candidate is invalid")
        required = {
            "id", "reviewState", "framework", "subsystem", "signature", "semanticIdentity", "dimensions",
            "promotionChecks", "evidence", "holdoutEvidence", "excludedEvidence",
        }
        if not required <= set(candidate):
            raise CorpusError("discovery candidate is missing fields")
        if not isinstance(candidate["id"], str) or not re.fullmatch(r"candidate\.[0-9a-f]{16}", candidate["id"]):
            raise CorpusError("discovery candidate id is invalid")
        if candidate["reviewState"] not in {"discovered", "quarantined"}:
            raise CorpusError("discovery candidate state is invalid")
        if candidate["framework"] not in {"playwright", "cypress", "source-helper"}:
            raise CorpusError("discovery candidate framework is invalid")
        identity = candidate["semanticIdentity"]
        if (
            not isinstance(identity, dict)
            or set(identity) != {"kind", "bound", "digest"}
            or identity.get("kind") not in {"selector-target", "helper-call", "unanchored"}
            or type(identity.get("bound")) is not bool
            or not isinstance(identity.get("digest"), str)
            or not re.fullmatch(r"[0-9a-f]{16}", identity["digest"])
        ):
            raise CorpusError("discovery candidate semantic identity is invalid")
        if (identity["kind"] == "unanchored") != (not identity["bound"]):
            raise CorpusError("discovery candidate semantic identity binding is invalid")
        dimensions = candidate["dimensions"]
        if not isinstance(dimensions, dict) or set(dimensions) != expected_dimensions:
            raise CorpusError("discovery candidate dimensions are invalid")
        if any(type(value) is not int or not 0 <= value <= 100 for value in dimensions.values()):
            raise CorpusError("discovery candidate dimension value is invalid")
        checks = candidate["promotionChecks"]
        if (
            not isinstance(checks, dict)
            or set(checks) != expected_checks
            or any(type(value) is not bool for value in checks.values())
        ):
            raise CorpusError("discovery candidate promotion checks are invalid")
        if checks["semanticIdentityBound"] != identity["bound"]:
            raise CorpusError("discovery candidate identity promotion check is inconsistent")
        if not identity["bound"] and (checks["independentCorroboration"] or checks["holdoutIndependent"]):
            raise CorpusError("unanchored discovery candidate cannot corroborate evidence")
        for evidence_name in ("evidence", "holdoutEvidence", "excludedEvidence"):
            if not isinstance(candidate[evidence_name], list):
                raise CorpusError("discovery candidate evidence is invalid")
        records = [
            *candidate["evidence"],
            *candidate["holdoutEvidence"],
            *candidate["excludedEvidence"],
        ]
        if not records or any(not isinstance(item, dict) for item in records):
            raise CorpusError("discovery candidate contains no valid evidence")
        observed_fragments += len(records)
        for record in records:
            ensure_relative(record.get("path"), "discovery evidence path")
            if not isinstance(record.get("lineStart"), int) or not isinstance(record.get("lineEnd"), int):
                raise CorpusError("discovery evidence range is invalid")
            if record["lineStart"] > record["lineEnd"]:
                raise CorpusError("discovery evidence range is reversed")
            if not isinstance(record.get("signature"), dict) or record["signature"] != candidate["signature"]:
                raise CorpusError("discovery candidate signature is inconsistent")
            if record.get("semanticIdentity") != identity:
                raise CorpusError("discovery candidate semantic identity is inconsistent")
            if not isinstance(record.get("lineage"), str) or not re.fullmatch(r"[0-9a-f]{16}", record["lineage"]):
                raise CorpusError("discovery evidence lineage is invalid")
            if candidate_id(record) != candidate["id"]:
                raise CorpusError("discovery candidate identity is inconsistent")
        training_lineages = {item.get("lineage") for item in candidate["evidence"] if isinstance(item, dict)}
        holdout_lineages = {item.get("lineage") for item in candidate["holdoutEvidence"] if isinstance(item, dict)}
        if training_lineages & holdout_lineages:
            raise CorpusError("discovery holdout lineage leaked into training evidence")
        if len(candidate["holdoutEvidence"]) > 1:
            raise CorpusError("discovery candidate has multiple holdouts")
        if not identity["bound"] and len(records) != 1:
            raise CorpusError("unanchored discovery candidate grouped multiple fragments")
        observed_subsystems[candidate["subsystem"]] = observed_subsystems.get(candidate["subsystem"], 0) + 1
        observed_frameworks[candidate["framework"]] = observed_frameworks.get(candidate["framework"], 0) + 1
        observed_identity["anchored" if identity["bound"] else "unanchored"] += 1
        if not checks["semanticIdentityBound"]:
            observed_gaps["missingSemanticIdentity"] += 1
        if not checks["semanticDirectness"]:
            observed_gaps["missingSemanticAssertion"] += 1
        if dimensions["selectorStability"] == 0:
            observed_gaps["missingSelector"] += 1
        if not checks["independentCorroboration"]:
            observed_gaps["missingIndependentLineage"] += 1
        if not checks["holdoutIndependent"]:
            observed_gaps["missingHoldout"] += 1
    counts = discovery.get("counts")
    coverage = discovery.get("coverage")
    if counts != {"fragments": observed_fragments, "candidates": len(candidates)}:
        raise CorpusError("discovery report counts are invalid")
    expected_coverage = {
        "bySubsystem": dict(sorted(observed_subsystems.items())),
        "byFramework": dict(sorted(observed_frameworks.items())),
        "byIdentity": observed_identity,
        "gaps": observed_gaps,
    }
    if coverage != expected_coverage:
        raise CorpusError("discovery report coverage is invalid")
    expected_discovery = build_discovery(repo, policy)
    if canonical_json(discovery) != canonical_json(expected_discovery):
        raise CorpusError("discovery report does not match source compilation")
    assert_safe_payload(discovery, "discovery")
    return {"valid": True, "commit": commit, "candidateCount": len(candidates)}


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
    parser.add_argument("command", choices=("build", "discover", "validate-discovery", "validate", "lookup", "status", "evaluate"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--discovery", type=Path)
    parser.add_argument("--operation")
    parser.add_argument("--category")
    parser.add_argument("--limit", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        policy = read_json(args.policy)
        validate_policy(policy)
        if args.command in {"build", "discover"}:
            if args.output is None:
                raise CorpusError(f"{args.command} requires --output")
            if args.command == "discover":
                discovery = build_discovery(args.repo.resolve(), policy)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(discovery, indent=2, sort_keys=True) + "\n")
                print(json.dumps({"status": "ok", "candidateCount": len(discovery["candidates"]), "commit": discovery["source"]["commit"]}))
                return 0
            index = build_index(args.repo.resolve(), policy)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
            print(json.dumps({"status": "ok", "cardCount": len(index["cards"]), "commit": index["source"]["commit"]}))
            return 0
        if args.command == "validate-discovery":
            if args.discovery is None:
                raise CorpusError("validate-discovery requires --discovery")
            discovery = read_json(args.discovery)
            print(json.dumps(validate_discovery(discovery, args.repo.resolve(), policy), sort_keys=True))
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
