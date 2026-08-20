#!/usr/bin/env python3
"""Measure deterministic corpus work on synthetic 100/1,000/10,000-file repos."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
COUNTS = (100, 1_000, 10_000)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def corpus_module() -> Any:
    return load_module(SCRIPT_DIR / "test-corpus-index.py", "scale_corpus")


def policy_for(corpus: Any) -> dict[str, Any]:
    benchmark = load_module(
        SCRIPT_DIR / "webflow-hardening-benchmark.py", "scale_hardening_benchmark"
    )
    return benchmark.corpus_policy(corpus)


def make_repo(count: int) -> tuple[tempfile.TemporaryDirectory[str], Path, int]:
    holder: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
    repo = Path(holder.name)
    files = {
        "entrypoints/playwright-tests/utils/designerUtils/index.ts": (
            "export async function openPagesPanel(page, locators) {\n"
            "  await locators.Sidebar.PAGES_BUTTON.click();\n"
            "  await expect(locators.Panels.PAGES).toBeVisible();\n"
            "}\n"
        ),
        "entrypoints/playwright-tests/utils/designerUtils/testIds.ts": (
            "const locators = {\n"
            "  Sidebar: {PAGES_BUTTON: page.getByTestId('fixture-pages-button')},\n"
            "  Panels: {PAGES: page.getByTestId('fixture-pages-panel')}\n"
            "};\n"
        ),
    }
    source_template = (
        "test('opens pages {index}', async () => {{\n"
        "  await openPagesPanel(page);\n"
        "  await page.getByTestId('fixture-pages-panel').click();\n"
        "  await expect(page.getByTestId('fixture-pages-panel')).toBeVisible();\n"
        "}});\n"
    )
    total_bytes = 0
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        total_bytes += len(content.encode("utf-8"))
    for index in range(count):
        relative = f"entrypoints/playwright-tests/scale/case-{index:05d}.spec.ts"
        content = source_template.format(index=index)
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        total_bytes += len(content.encode("utf-8"))
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "benchmark@example.invalid"],
        ["git", "config", "user.name", "Webflow Scale Benchmark"],
        ["git", "config", "core.hooksPath", "/dev/null"],
        ["git", "add", "."],
        ["git", "commit", "-qm", "synthetic scale fixture"],
    ]
    for command in commands:
        subprocess.run(
            command,
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    return holder, repo, total_bytes


def workload(corpus: Any, policy: dict[str, Any], repo: Path, count: int, total_bytes: int) -> dict[str, int | float]:
    counters = {
        "git_calls": 0,
        "file_reads": 0,
        "bytes_read": 0,
        "bytes_hashed": 0,
        "fragment_calls": 0,
        "fragment_records": 0,
        "file_git_metadata_calls": 0,
        "file_git_metadata_misses": 0,
        "operation_evidence_calls": 0,
        "operation_evidence_records": 0,
        "build_discovery_calls": 0,
        "build_card_calls": 0,
    }
    originals = {
        name: getattr(corpus, name)
        for name in (
            "run_git",
            "structural_fragments",
            "file_git_metadata",
            "operation_evidence",
            "build_discovery",
            "build_card",
        )
    }
    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes

    def is_fixture_path(path: Path) -> bool:
        try:
            path.relative_to(repo)
        except ValueError:
            return False
        return True

    def run_git(repo_path: Path, *arguments: str) -> str:
        counters["git_calls"] += 1
        if arguments == ("rev-parse", "HEAD"):
            return "1" * 40
        if arguments[:4] == ("log", "-1", "--format=%H%x00%cI", "--"):
            return f"{'1' * 40}\x002026-01-01T00:00:00+00:00"
        return originals["run_git"](repo_path, *arguments)

    def read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        value = original_read_text(path, *args, **kwargs)
        if is_fixture_path(path):
            counters["file_reads"] += 1
            counters["bytes_read"] += len(value.encode("utf-8"))
        return value

    def read_bytes(path: Path) -> bytes:
        value = original_read_bytes(path)
        if is_fixture_path(path):
            counters["file_reads"] += 1
            counters["bytes_read"] += len(value)
            counters["bytes_hashed"] += len(value)
        return value

    def structural_fragments(path: Path, relative: str, framework: str) -> list[Any]:
        counters["fragment_calls"] += 1
        result = originals["structural_fragments"](path, relative, framework)
        counters["fragment_records"] += len(result)
        return result

    def file_git_metadata(repo_path: Path, relative: str, cache: dict[str, dict[str, str]]) -> dict[str, str]:
        counters["file_git_metadata_calls"] += 1
        if relative not in cache:
            counters["file_git_metadata_misses"] += 1
        return originals["file_git_metadata"](repo_path, relative, cache)

    def operation_evidence(repo_path: Path, value: dict[str, Any], operation: dict[str, Any], cache: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
        counters["operation_evidence_calls"] += 1
        result = originals["operation_evidence"](repo_path, value, operation, cache)
        counters["operation_evidence_records"] += len(result)
        return result

    def build_discovery(repo_path: Path, value: dict[str, Any]) -> dict[str, Any]:
        counters["build_discovery_calls"] += 1
        return originals["build_discovery"](repo_path, value)

    def build_card(repo_path: Path, value: dict[str, Any], operation: dict[str, Any], commit: str, policy_hash: str, cache: dict[str, dict[str, str]]) -> dict[str, Any]:
        counters["build_card_calls"] += 1
        return originals["build_card"](repo_path, value, operation, commit, policy_hash, cache)

    corpus.run_git = run_git
    corpus.structural_fragments = structural_fragments
    corpus.file_git_metadata = file_git_metadata
    corpus.operation_evidence = operation_evidence
    corpus.build_discovery = build_discovery
    corpus.build_card = build_card
    Path.read_text = read_text
    Path.read_bytes = read_bytes
    try:
        operation = policy["operations"][0]
        index = corpus.build_index(repo, policy)
        discovery = corpus.build_discovery(repo, policy)
        corpus.validate_index(index, repo, policy)
        corpus.validate_discovery(discovery, repo, policy)
        evidence = corpus.operation_evidence(repo, policy, operation, {})
        repeat_index = corpus.build_index(repo, policy)
        repeat_discovery = corpus.build_discovery(repo, policy)
        canonical_mismatches = int(
            corpus.canonical_json(index) != corpus.canonical_json(repeat_index)
            or corpus.canonical_json(discovery) != corpus.canonical_json(repeat_discovery)
        )
    finally:
        Path.read_text = original_read_text
        Path.read_bytes = original_read_bytes
        for name, original in originals.items():
            setattr(corpus, name, original)

    serialized = json.dumps(
        {
            "index": index,
            "discovery": discovery,
            "evidenceCount": len(evidence),
        },
        sort_keys=True,
    )
    private_value_leaks = int(
        any(value in serialized for value in ("/Users/", "/private/", "@example", "Bearer ", "token="))
    )
    work_units = (
        counters["git_calls"]
        + counters["file_reads"]
        + counters["fragment_calls"]
        + counters["file_git_metadata_calls"]
        + counters["operation_evidence_records"]
        + count
    )
    return {
        f"scale_{count}_executed": 1,
        f"scale_{count}_files": count,
        f"scale_{count}_fixture_bytes": total_bytes,
        f"scale_{count}_file_reads": counters["file_reads"],
        f"scale_{count}_bytes_read": counters["bytes_read"],
        f"scale_{count}_bytes_hashed": counters["bytes_hashed"],
        f"scale_{count}_git_calls": counters["git_calls"],
        f"scale_{count}_fragment_calls": counters["fragment_calls"],
        f"scale_{count}_fragment_records": counters["fragment_records"],
        f"scale_{count}_file_git_metadata_calls": counters["file_git_metadata_calls"],
        f"scale_{count}_file_git_metadata_misses": counters["file_git_metadata_misses"],
        f"scale_{count}_operation_evidence_calls": counters["operation_evidence_calls"],
        f"scale_{count}_operation_evidence_records": counters["operation_evidence_records"],
        f"scale_{count}_build_discovery_calls": counters["build_discovery_calls"],
        f"scale_{count}_build_card_calls": counters["build_card_calls"],
        f"scale_{count}_canonical_mismatches": canonical_mismatches,
        f"scale_{count}_private_value_leaks": private_value_leaks,
        f"scale_{count}_work_units": work_units,
    }


def run(repo: Path) -> dict[str, int | float]:
    if not repo.is_dir():
        raise ValueError("benchmark repository is invalid")
    corpus = corpus_module()
    policy = policy_for(corpus)
    metrics: dict[str, int | float] = {}
    holders: list[tempfile.TemporaryDirectory[str]] = []
    try:
        for count in COUNTS:
            holder, scale_repo, total_bytes = make_repo(count)
            holders.append(holder)
            metrics.update(workload(corpus, policy, scale_repo, count, total_bytes))
    finally:
        for holder in holders:
            holder.cleanup()
    metrics["scale_cases_executed"] = sum(COUNTS)
    metrics["canonical_mismatches"] = sum(
        int(metrics[f"scale_{count}_canonical_mismatches"]) for count in COUNTS
    )
    metrics["private_value_leaks"] = sum(
        int(metrics[f"scale_{count}_private_value_leaks"]) for count in COUNTS
    )
    metrics["work_units"] = sum(int(metrics[f"scale_{count}_work_units"]) for count in COUNTS)
    metrics["deterministic_runs"] = 1
    return metrics


def verification_failures(metrics: dict[str, int | float]) -> dict[str, int | float]:
    failures: dict[str, int | float] = {}
    for count in COUNTS:
        for suffix in ("executed", "canonical_mismatches", "private_value_leaks"):
            key = f"scale_{count}_{suffix}"
            expected = 1 if suffix == "executed" else 0
            if metrics.get(key) != expected:
                failures[key] = metrics.get(key, 0)
        if metrics.get(f"scale_{count}_files") != count:
            failures[f"scale_{count}_files"] = metrics.get(f"scale_{count}_files", 0)
        for suffix in ("file_reads", "bytes_hashed", "work_units"):
            key = f"scale_{count}_{suffix}"
            if metrics.get(key, 0) <= 0:
                failures[key] = metrics.get(key, 0)
    if metrics.get("scale_cases_executed") != sum(COUNTS):
        failures["scale_cases_executed"] = metrics.get("scale_cases_executed", 0)
    work = [metrics.get(f"scale_{count}_work_units", 0) for count in COUNTS]
    if work != sorted(work):
        failures["work_units_monotonic"] = 0
    if metrics.get("canonical_mismatches") != 0:
        failures["canonical_mismatches"] = metrics.get("canonical_mismatches", 0)
    if metrics.get("private_value_leaks") != 0:
        failures["private_value_leaks"] = metrics.get("private_value_leaks", 0)
    if metrics.get("deterministic_runs") != 1:
        failures["deterministic_runs"] = metrics.get("deterministic_runs", 0)
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--format", choices=("metrics", "json", "verify"), default="metrics")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    first = run(args.repo)
    second = run(args.repo)
    first["deterministic_runs"] = int(first == second)
    if args.format == "json":
        print(json.dumps(first, sort_keys=True))
    elif args.format == "verify":
        return 0 if not verification_failures(first) else 1
    else:
        for key in sorted(first):
            print(f"METRIC {key}={first[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
