#!/usr/bin/env python3
"""Run the offline Webflow hardening benchmark.

The benchmark deliberately measures the current acceptance boundaries.  A
non-zero safety metric is a useful baseline failure, not a reason to weaken
the oracle.  Fixtures contain only synthetic names and canaries.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from itertools import combinations
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
FIXTURE_DIR = SKILL_DIR / "tests" / "fixtures" / "hardening"
SAFETY_METRICS = {
    "semantic_false_merges",
    "semantic_unanchored_violations",
    "artifact_tamper_accepted",
    "discovery_tamper_accepted",
    "unsafe_positive_evidence",
    "holdout_lineage_overlap",
    "explicit_trusted_route",
    "schema_invalid_accepted",
    "empty_runner_pass",
    "runner_false_passes",
    "stopped_with_lease_clean",
    "privacy_canary_acceptance",
}


def load_module(filename: str, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_fixture(name: str) -> dict[str, Any]:
    path = FIXTURE_DIR / name
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError(f"invalid hardening fixture: {name}")
    return value


def make_repo(files: dict[str, str]) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    holder: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
    repo = Path(holder.name)
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "benchmark@example.invalid"],
        ["git", "config", "user.name", "Webflow Hardening Benchmark"],
        ["git", "config", "core.hooksPath", "/dev/null"],
        ["git", "add", "."],
        ["git", "commit", "-qm", "synthetic benchmark fixture"],
    ]
    for command in commands:
        subprocess.run(command, cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return holder, repo


def corpus_policy(corpus: Any) -> dict[str, Any]:
    return {
        "version": 1,
        "sources": [{
            "framework": "playwright",
            "roots": ["entrypoints/playwright-tests"],
            "patterns": ["*.spec.ts"],
        }],
        "operationSource": "entrypoints/playwright-tests/utils/designerUtils/index.ts",
        "locatorSource": "entrypoints/playwright-tests/utils/designerUtils/testIds.ts",
        "selection": {
            "minimumConfidence": 55,
            "maximumEvidencePerOperation": 5,
            "holdoutEvidencePerOperation": 1,
        },
        "discovery": {"helperSources": []},
        "operations": [{
            "id": "designer.panel.pages.open",
            "symbol": "openPagesPanel",
            "intent": "Open Pages",
            "capabilities": ["panel-management"],
            "contexts": ["designer-ready"],
            "parameters": [],
            "locatorKeys": ["Sidebar.PAGES_BUTTON", "Panels.PAGES"],
            "actions": [{"verb": "click", "target": "Sidebar.PAGES_BUTTON"}],
            "postconditions": ["Panels.PAGES is visible"],
            "guardrails": ["Do not click when already visible"],
        }],
    }


def corpus_files(fixture: dict[str, Any]) -> dict[str, str]:
    files = dict(fixture["files"])
    files["policy.json"] = "{}\n"
    return files


def semantic_metrics(corpus: Any, fixture: dict[str, Any]) -> dict[str, int | float]:
    cases = fixture["cases"]
    observed: dict[str, dict[str, Any]] = {}
    for offset, case in enumerate(cases, start=1):
        features = corpus.fragment_features(case["source"])
        observed[case["id"]] = corpus.semantic_identity(
            features,
            relative_path=f"fixture/{case['id']}.spec.ts",
            line_start=offset,
            line_end=offset,
        )
    bound = [case for case in cases if case["expectBound"]]
    pairs = [
        pair
        for group in {case["group"] for case in bound}
        for pair in combinations([case for case in bound if case["group"] == group], 2)
    ]
    recovered = sum(
        observed[left["id"]]["bound"]
        and observed[right["id"]]["bound"]
        and observed[left["id"]]["digest"] == observed[right["id"]]["digest"]
        for left, right in pairs
    )
    false_merges = sum(
        observed[left["id"]]["bound"]
        and observed[right["id"]]["bound"]
        and observed[left["id"]]["digest"] == observed[right["id"]]["digest"]
        for left, right in combinations(bound, 2)
        if left["group"] != right["group"]
    )
    unanchored = sum(
        observed[case["id"]]["bound"]
        for case in cases
        if not case["expectBound"]
    )
    return {
        "semantic_safe_recall": round(recovered / len(pairs), 6) if pairs else 0.0,
        "semantic_false_merges": false_merges,
        "semantic_unanchored_violations": unanchored,
        "semantic_positive_pairs": len(pairs),
    }


def corpus_metrics(corpus: Any, fixture: dict[str, Any]) -> dict[str, int]:
    holder, repo = make_repo(corpus_files(fixture))
    try:
        policy = corpus_policy(corpus)
        index = corpus.build_index(repo, policy)
        discovery = corpus.build_discovery(repo, policy)

        tampered_index = copy.deepcopy(index)
        tampered_index["cards"][0][fixture["cardTamperField"]] = "tampered synthetic value"
        try:
            corpus.validate_index(tampered_index, repo, policy)
        except corpus.CorpusError:
            index_tamper_accepted = 0
        else:
            index_tamper_accepted = 1

        tampered_discovery = copy.deepcopy(discovery)
        tampered_discovery["candidates"][0]["dimensions"][fixture["discoveryTamperField"]] = 0
        try:
            corpus.validate_discovery(tampered_discovery, repo, policy)
        except corpus.CorpusError:
            discovery_tamper_accepted = 0
        else:
            discovery_tamper_accepted = 1

        unsafe_records = corpus.operation_evidence(
            repo, policy, policy["operations"][0], {}
        )
        positive_paths = {
            record["path"]
            for record in [*index["cards"][0]["evidence"], *index["cards"][0]["holdoutEvidence"]]
        }
        unsafe_positive = sum(
            not record["signals"]["quarantined"]
            and any(record["signals"][key] for key in ("rawWait", "destructive", "fixtureDependent"))
            and record["path"] in positive_paths
            for record in unsafe_records
        )

        card = index["cards"][0]
        records = []
        for path, framework in corpus.discover_sources(repo, policy):
            relative = path.relative_to(repo).as_posix()
            for fragment in corpus.structural_fragments(path.read_text(), relative, framework):
                record = corpus.fragment_record(repo, fragment, {})
                if record is not None:
                    records.append(record)
        lineage_by_path = {record["path"]: record["lineage"] for record in records}
        training_lineages = {
            lineage_by_path[path]
            for item in card["evidence"]
            for path in [item["path"]]
            if path in lineage_by_path
        }
        holdout_lineages = {
            lineage_by_path[path]
            for item in card["holdoutEvidence"]
            for path in [item["path"]]
            if path in lineage_by_path
        }
        return {
            "artifact_tamper_accepted": index_tamper_accepted,
            "discovery_tamper_accepted": discovery_tamper_accepted,
            "unsafe_positive_evidence": unsafe_positive,
            "holdout_lineage_overlap": int(bool(training_lineages & holdout_lineages)),
            "corpus_records": len(records),
        }
    finally:
        holder.cleanup()


def validation_candidate(validate_change: Any, context: dict[str, Any]) -> dict[str, Any]:
    nearby = context["nearbyContracts"][0]
    runner_id = nearby["runnerId"]
    operation_id = nearby["operationIds"][0]
    return {
        "version": 1,
        "id": "designer.pages-panel.synthetic-candidate",
        "mode": "candidate",
        "surfaceAdapter": "webflow-designer",
        "source": {
            "commit": context["changeSet"]["sourceCommit"],
            "changeSetDigest": context["changeSet"]["digest"],
        },
        "evidenceRefs": nearby["evidenceRefs"],
        "riskClass": "reversible-ui",
        "determinism": "bounded",
        "runnerId": runner_id,
        "inputs": {},
        "constraints": ["Use only the reviewed synthetic fixture."],
        "target": {"fixture": "isolated-designer-test", "document": "main"},
        "preconditions": ["Synthetic Designer fixture is ready."],
        "facts": [{"id": "panel-visible", "type": "boolean", "source": "playwright-assertion"}],
        "actions": [
            {"id": "open-panel", "op": "invoke_operation", "dependsOn": [], "operationId": operation_id},
            {"id": "assert-panel", "op": "assert", "dependsOn": ["open-panel"], "fact": "panel-visible", "expected": True, "selectorKey": nearby["selectorKeys"][0]},
        ],
        "oracle": {"kind": "semantic-fact", "fact": "panel-visible", "expected": True},
        "recovery": [],
        "cleanup": ["adapter-teardown"],
        "budget": {
            "timeoutSeconds": 900,
            "maxRetries": context["candidatePolicy"]["maximumRetries"],
            "maxActions": context["candidatePolicy"]["maximumActions"],
        },
        "receipt": {"requireSemanticOracle": True, "requireCleanupProof": True},
    }


def validation_metrics(validate_change: Any, fixture: dict[str, Any], policy: dict[str, Any]) -> dict[str, int]:
    files = {fixture["mappedPath"]: "export const pages = true;\n", fixture["unknownPath"]: "export const pages = true;\n"}
    holder, repo = make_repo(files)
    try:
        try:
            clean_explicit = validate_change.validate_change(
                repo, policy, changed_files=[fixture["mappedPath"]]
            )
        except validate_change.ValidationError:
            explicit_trusted = 0
        else:
            explicit_trusted = int(clean_explicit[1]["status"] == "trusted")
        (repo / fixture["mappedPath"]).write_text("export const pages = changed;\n", encoding="utf-8")
        (repo / fixture["unknownPath"]).write_text("export const pages = changed;\n", encoding="utf-8")
        explicit = validate_change.validate_change(repo, policy, changed_files=[fixture["mappedPath"]])
        proposed = validate_change.validate_change(repo, policy, changed_files=[fixture["unknownPath"]])
        context = proposed[2]["proposalContext"]
        candidate = validation_candidate(validate_change, context)
        accepted = 0
        for mutation in fixture["invalidCandidateMutations"]:
            mutated = copy.deepcopy(candidate)
            target: Any = mutated
            path = mutation["path"]
            for key in path[:-1]:
                target = target[key] if isinstance(key, int) else target[key]
            target[path[-1]] = mutation["value"]
            try:
                validate_change.validate_candidate_contract(mutated, context, policy)
            except validate_change.ValidationError:
                continue
            accepted += 1

        change_set = explicit[0]
        empty_receipt = validate_change.execute_runner(repo, policy, [], change_set)
        return {
            "explicit_trusted_route": explicit_trusted,
            "schema_invalid_accepted": accepted,
            "empty_runner_pass": int(empty_receipt["status"] == "passed"),
        }
    finally:
        holder.cleanup()


def runner_metrics(validate_change: Any, fixture: dict[str, Any], policy: dict[str, Any]) -> dict[str, int]:
    mapped_path = "public/js/designer-flux/components/PagesPanel/PagesPanel.tsx"
    holder, repo = make_repo({mapped_path: "export const pages = true;\n"})
    try:
        (repo / mapped_path).write_text("export const pages = changed;\n", encoding="utf-8")
        changes = validate_change.collect_change_set(
            repo, policy["changeValidation"]["limits"], changed_files=[mapped_path]
        )
        false_passes = 0
        for case in fixture["cases"]:
            output = case["output"].encode("utf-8")
            markers = validate_change.output_failure_markers(output)
            calls = 0

            def runner(_command: list[str], _cwd: Path, _timeout: int) -> Any:
                nonlocal calls
                calls += 1
                if calls == 1:
                    return validate_change.CommandResult(0)
                return validate_change.CommandResult(
                    case["returncode"],
                    timed_out=case["timedOut"],
                    failure_markers=markers,
                )

            receipt = validate_change.execute_runner(
                repo, policy, ["designer-pages-panel-focused"], changes, runner=runner
            )
            if not case["expectPass"] and receipt["status"] == "passed":
                false_passes += 1
        return {"runner_false_passes": false_passes}
    finally:
        holder.cleanup()


def lifecycle_metrics(runtime: Any, fixture: dict[str, Any]) -> dict[str, int]:
    return {
        "stopped_with_lease_clean": sum(
            runtime.runtime_is_stopped(state)
            for state in fixture["states"]
            if state["leasePresent"]
        )
    }


def privacy_metrics(automation_evidence: Any, fixture: dict[str, Any]) -> dict[str, int]:
    canary = " ".join(item["value"] for item in fixture["canaries"])
    checks = [{"name": name, "state": "ready"} for name in sorted(automation_evidence.READINESS_CHECKS)]
    transaction = "synthetic-privacy-transaction"
    value = {
        "report": {
            "mode": "attached",
            "sanitized_url": canary,
            "ownership_boundary": canary,
            "target_frame": canary,
            "verification": {
                "status": "verified",
                "transactionId": transaction,
                "readiness": {
                    "checks": checks,
                    "blockers": [],
                    "cleanup": {"runtimeStopped": False, "runtimeHeld": True},
                },
                "qaLaunchAllowed": True,
            },
            "observations": {"before": canary, "after": canary},
            "authorized_actions": [canary],
            "diagnostics": {name: [canary] for name in sorted(automation_evidence.DIAGNOSTIC_FIELDS)},
            "artifacts": [canary],
            "blockers": [],
            "assumptions": [canary],
            "finish": {
                "transactionId": transaction,
                "status": "finished",
                "runtimeStopped": True,
                "cleanup": {"runtimeOwned": False, "cdpReady": False, "consumer": None, "leasePresent": False, "status": "stopped"},
            },
            "scope_claim": automation_evidence.SCOPE_CLAIMS["attached"],
        }
    }
    try:
        automation_evidence.validate_report(value)
    except ValueError:
        accepted = 0
    else:
        accepted = len(fixture["canaries"])
    return {"privacy_canary_acceptance": accepted}


def run(repo: Path) -> dict[str, int | float]:
    corpus = load_module("test-corpus-index.py", "hardening_corpus")
    validate_change = load_module("validate-change.py", "hardening_validate_change")
    runtime = load_module("browser-runtime.py", "hardening_runtime")
    automation_evidence = load_module("automation-evidence.py", "hardening_evidence")
    semantic = read_fixture("semantic-identity.json")
    provenance = read_fixture("provenance-lineage.json")
    routing = read_fixture("routing-contracts.json")
    runners = read_fixture("runner-results.json")
    lifecycle = read_fixture("lifecycle-states.json")
    privacy = read_fixture("privacy-canaries.json")
    scale = read_fixture("scale-profiles.json")
    policy = validate_change.validate_policy(json.loads((SKILL_DIR / "test-corpus-policy.json").read_text()))
    metrics: dict[str, int | float] = {}
    metrics.update(semantic_metrics(corpus, semantic))
    metrics.update(corpus_metrics(corpus, provenance))
    metrics.update(validation_metrics(validate_change, routing, policy))
    metrics.update(runner_metrics(validate_change, runners, policy))
    metrics.update(lifecycle_metrics(runtime, lifecycle))
    metrics.update(privacy_metrics(automation_evidence, privacy))
    metrics["bounded_scale_cases"] = sum(scale["counts"])
    metrics["deterministic_runs"] = int(metrics == {
        **metrics,
    })
    if not repo.is_dir():
        raise ValueError("benchmark repository is invalid")
    return metrics


def verification_failures(metrics: dict[str, int | float]) -> dict[str, int | float]:
    return {
        key: metrics[key]
        for key in sorted(SAFETY_METRICS)
        if metrics.get(key) != 0
    } | ({"deterministic_runs": metrics.get("deterministic_runs", 0)} if metrics.get("deterministic_runs") != 1 else {})


def verified(metrics: dict[str, int | float]) -> bool:
    return not verification_failures(metrics)


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
        return 0 if verified(first) else 1
    else:
        for key in sorted(first):
            print(f"METRIC {key}={first[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
