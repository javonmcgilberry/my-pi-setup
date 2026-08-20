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
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
    "lifecycle_false_stopped",
    "lifecycle_missing_stop_proof",
    "privacy_canary_acceptance",
    "privacy_raw_canary_acceptance",
    "privacy_bounds_violations",
    "approval_reuse_accepted",
    "approval_digest_mismatch_accepted",
    "approval_expired_accepted",
    "approval_malformed_accepted",
    "approval_symlink_accepted",
    "mixed_trusted_route",
    "rename_predecessor_ignored",
    "mutation_survivors",
    "canonical_mismatches",
    "scale_private_value_leaks",
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
    files = {
        fixture["mappedPath"]: "export const pages = true;\n",
        fixture["secondMappedPath"]: "export const add = true;\n",
        fixture["unknownPath"]: "export const pages = true;\n",
    }
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
        (repo / fixture["secondMappedPath"]).write_text("export const add = changed;\n", encoding="utf-8")
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
        mixed_change_set = validate_change.collect_change_set(
            repo,
            policy["changeValidation"]["limits"],
            changed_files=[
                fixture["mappedPath"],
                fixture["secondMappedPath"],
                fixture["unknownPath"],
            ],
        )
        mixed_route = validate_change.route_trusted_contracts(mixed_change_set, policy)
        return {
            "explicit_trusted_route": explicit_trusted,
            "schema_invalid_accepted": accepted,
            "empty_runner_pass": int(empty_receipt["status"] == "passed"),
            "mixed_trusted_route": int(mixed_route["status"] == "trusted"),
        }
    finally:
        holder.cleanup()


def rename_routing_metric(validate_change: Any, fixture: dict[str, Any], policy: dict[str, Any]) -> int:
    holder, repo = make_repo({fixture["mappedPath"]: "export const pages = true;\n"})
    try:
        destination = repo / fixture["secondMappedPath"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "mv", fixture["mappedPath"], fixture["secondMappedPath"]],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        change_set = validate_change.collect_change_set(
            repo, policy["changeValidation"]["limits"]
        )
        route = validate_change.route_trusted_contracts(change_set, policy)
        return int(
            not any(
                item.get("runnerId") == "designer-pages-panel-focused"
                for item in route.get("matches", [])
            )
        )
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
    observations = [
        (runtime.runtime_is_stopped(state), state["expectStopped"])
        for state in fixture["states"]
    ]
    return {
        "stopped_with_lease_clean": sum(
            runtime.runtime_is_stopped(state)
            for state in fixture["states"]
            if state.get("leasePresent") is True
        ),
        "lifecycle_false_stopped": sum(
            int(observed and not expected) for observed, expected in observations
        ),
        "lifecycle_missing_stop_proof": sum(
            int(not observed and expected) for observed, expected in observations
        ),
    }


def privacy_report(automation_evidence: Any, fixture: dict[str, Any], *, canary: str) -> dict[str, Any]:
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
    return value


def privacy_metrics(automation_evidence: Any, fixture: dict[str, Any]) -> dict[str, int]:
    canary = " ".join(item["value"] for item in fixture["canaries"])
    raw_acceptance = sum(
        int(automation_evidence.sanitize_evidence.is_safe_evidence_text(item["value"]))
        for item in fixture["canaries"]
    )
    try:
        automation_evidence.validate_report(privacy_report(automation_evidence, fixture, canary=canary))
    except ValueError:
        accepted = 0
    else:
        accepted = len(fixture["canaries"])
    bounds = fixture["bounds"]
    oversized = {
        "deep": "leaf",
        "items": list(range(bounds["maximumItems"] + 1)),
        "string": "x" * (bounds["maximumString"] + 1),
    }
    sanitized = automation_evidence.sanitize_evidence.sanitize(oversized)
    bounds_ok = (
        sanitized["deep"] == "leaf"
        and len(sanitized["items"]) == bounds["maximumItems"] + 1
        and len(sanitized["string"]) <= bounds["maximumString"] + len("[TRUNCATED]")
    )
    return {
        "privacy_canary_acceptance": accepted,
        "privacy_raw_canary_acceptance": raw_acceptance,
        "privacy_bounds_violations": int(not bounds_ok),
    }


def write_confirmation(root: Path, token: str, digest: str, expires_at: int) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{token}.json").write_text(
        json.dumps({"version": 1, "approvalDigest": digest, "expiresAt": expires_at}),
        encoding="utf-8",
    )


def approval_metrics(validate_change: Any, fixture: dict[str, Any]) -> dict[str, int]:
    digest = "a" * 64
    token = "b" * 64
    root_holder = tempfile.TemporaryDirectory()
    root = Path(root_holder.name)
    previous = os.environ.get(validate_change.HOST_CONFIRMATION_ENV)
    os.environ[validate_change.HOST_CONFIRMATION_ENV] = str(root)
    try:
        write_confirmation(root, token, digest, int(time.time()) + 60)
        validate_change.consume_host_confirmation(token, digest)
        try:
            validate_change.consume_host_confirmation(token, digest)
        except validate_change.ValidationError:
            reuse_accepted = 0
        else:
            reuse_accepted = 1

        write_confirmation(root, token, digest, int(time.time()) + 60)
        try:
            validate_change.consume_host_confirmation(token, "c" * 64)
        except validate_change.ValidationError:
            digest_mismatch_accepted = 0
        else:
            digest_mismatch_accepted = 1

        write_confirmation(root, token, digest, int(time.time()) - 1)
        try:
            validate_change.consume_host_confirmation(token, digest)
        except validate_change.ValidationError:
            expired_accepted = 0
        else:
            expired_accepted = 1

        (root / f"{token}.json").write_text("{}", encoding="utf-8")
        try:
            validate_change.consume_host_confirmation(token, digest)
        except validate_change.ValidationError:
            malformed_accepted = 0
        else:
            malformed_accepted = 1

        target = root / "target.json"
        target.write_text(json.dumps({"version": 1, "approvalDigest": digest, "expiresAt": int(time.time()) + 60}), encoding="utf-8")
        symlink_token = root / f"{token}.json"
        symlink_token.symlink_to(target)
        try:
            validate_change.consume_host_confirmation(token, digest)
        except validate_change.ValidationError:
            symlink_accepted = 0
        else:
            symlink_accepted = 1
        symlink_token.unlink(missing_ok=True)

        root_link = root.with_name(root.name + "-link")
        root_link.symlink_to(root, target_is_directory=True)
        os.environ[validate_change.HOST_CONFIRMATION_ENV] = str(root_link)
        try:
            validate_change.consume_host_confirmation(token, digest)
        except validate_change.ValidationError:
            pass
        else:
            symlink_accepted = 1
        root_link.unlink(missing_ok=True)
        return {
            "approval_reuse_accepted": reuse_accepted,
            "approval_digest_mismatch_accepted": digest_mismatch_accepted,
            "approval_expired_accepted": expired_accepted,
            "approval_malformed_accepted": malformed_accepted,
            "approval_symlink_accepted": symlink_accepted,
        }
    finally:
        if previous is None:
            os.environ.pop(validate_change.HOST_CONFIRMATION_ENV, None)
        else:
            os.environ[validate_change.HOST_CONFIRMATION_ENV] = previous
        root_holder.cleanup()


def scale_metrics(corpus: Any, fixture: dict[str, Any]) -> dict[str, int]:
    def measure(count: int) -> tuple[int, int, str]:
        bound = 0
        digests: list[str] = []
        source = (
            "test('scale pages', async () => { await page.getByTestId('fixture-pages-panel').click(); "
            "await expect(page.getByTestId('fixture-pages-panel')).toBeVisible(); });\n"
        )
        for index in range(count):
            features = corpus.fragment_features(source.replace("scale pages", f"scale pages {index}"))
            identity = corpus.semantic_identity(
                features,
                relative_path=f"scale/{index:05d}.spec.ts",
                line_start=1,
                line_end=1,
            )
            bound += int(identity["bound"])
            digests.append(identity["digest"])
        return count, bound, hashlib.sha256("".join(digests).encode()).hexdigest()

    first = {count: measure(count) for count in fixture["counts"]}
    second = {count: measure(count) for count in fixture["counts"]}
    serialized = json.dumps(first, sort_keys=True)
    return {
        **{f"scale_{count}_executed": 1 for count in fixture["counts"]},
        **{f"scale_{count}_fragments": value[0] for count, value in first.items()},
        **{f"scale_{count}_bound": value[1] for count, value in first.items()},
        "scale_cases_executed": sum(fixture["counts"]),
        "canonical_mismatches": int(first != second),
        "scale_private_value_leaks": int(any(token in serialized for token in ("/Users/", "privacy-canary", "Bearer "))),
    }


def load_mutated_module(target: str, old: str, new: str) -> tuple[tempfile.TemporaryDirectory[str], Any]:
    holder: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
    scripts = Path(holder.name) / "scripts"
    scripts.mkdir()
    for source in SCRIPT_DIR.glob("*.py"):
        shutil.copyfile(source, scripts / source.name)
    path = scripts / target
    source = path.read_text(encoding="utf-8")
    if source.count(old) != 1:
        holder.cleanup()
        raise AssertionError(f"mutation is not unique: {target}")
    path.write_text(source.replace(old, new), encoding="utf-8")
    return holder, load_module_from_path(path, f"mutation_{target.replace('-', '_')}_{hash(old)}")


def load_module_from_path(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def mutation_probe(module: Any, mutant: dict[str, Any], fixture: dict[str, Any], policy: dict[str, Any]) -> bool:
    group = mutant["group"]
    if group == "corpus":
        holder, repo = make_repo(corpus_files(fixture["provenance"]))
        try:
            module_policy = corpus_policy(module)
            if mutant["id"] == "unsafe-raw-wait-positive":
                return module.evidence_is_eligible({
                    "signals": {
                        "quarantined": False,
                        "rawWait": True,
                        "fixtureDependent": False,
                        "destructive": False,
                    }
                })
            index = module.build_index(repo, module_policy)
            discovery = module.build_discovery(repo, module_policy)
            if mutant["id"] == "card-source-parity-disabled":
                index["cards"][0]["intent"] = "mutated"
                try:
                    module.validate_index(index, repo, module_policy)
                except module.CorpusError:
                    return False
                return True
            discovery["candidates"][0]["dimensions"][fixture["provenance"]["discoveryTamperField"]] = 0
            try:
                module.validate_discovery(discovery, repo, module_policy)
            except module.CorpusError:
                return False
            return True
        finally:
            holder.cleanup()
    if group == "validation":
        holder, repo = make_repo({fixture["routing"]["mappedPath"]: "export const pages = true;\n"})
        try:
            if mutant["id"] == "explicit-git-proof-disabled":
                try:
                    validate_change_result = module.validate_change(repo, policy, changed_files=[fixture["routing"]["mappedPath"]])
                except module.ValidationError:
                    return False
                return validate_change_result[0]["files"] == []
            change_set = {"sourceCommit": "a" * 40, "digest": "b" * 64, "files": []}
            receipt = module.execute_runner(repo, policy, [], change_set)
            return receipt["status"] == "passed"
        finally:
            holder.cleanup()
    if group == "runner":
        holder, repo = make_repo({fixture["routing"]["mappedPath"]: "export const pages = true;\n"})
        try:
            path = repo / fixture["routing"]["mappedPath"]
            path.write_text("export const pages = changed;\n", encoding="utf-8")
            changes = module.collect_change_set(repo, policy["changeValidation"]["limits"], changed_files=[fixture["routing"]["mappedPath"]])
            markers = module.output_failure_markers(b"semantic assertion failed")
            calls = 0

            def runner(_command: list[str], _cwd: Path, _timeout: int) -> Any:
                nonlocal calls
                calls += 1
                return module.CommandResult(0, failure_markers=markers if calls > 1 else ())

            receipt = module.execute_runner(
                repo,
                policy,
                ["designer-pages-panel-focused"],
                changes,
                runner=runner,
            )
            return receipt["status"] == "passed"
        finally:
            holder.cleanup()
    if group == "approval":
        root_holder = tempfile.TemporaryDirectory()
        root = Path(root_holder.name)
        previous = os.environ.get(module.HOST_CONFIRMATION_ENV)
        os.environ[module.HOST_CONFIRMATION_ENV] = str(root)
        try:
            token = "b" * 64
            write_confirmation(root, token, "a" * 64, int(time.time()) - 1 if mutant["id"] == "confirmation-expiry-disabled" else int(time.time()) + 60)
            digest = "c" * 64 if mutant["id"] == "confirmation-digest-disabled" else "a" * 64
            try:
                module.consume_host_confirmation(token, digest)
            except module.ValidationError:
                return False
            return True
        finally:
            if previous is None:
                os.environ.pop(module.HOST_CONFIRMATION_ENV, None)
            else:
                os.environ[module.HOST_CONFIRMATION_ENV] = previous
            root_holder.cleanup()
    if group == "lifecycle":
        state = {
            "status": "stopped",
            "runtimeOwned": False,
            "cdpReady": False,
            "leasePresent": True if mutant["id"] == "lease-presence-relaxed" else False,
            "leaseValid": True,
            "consumer": "designer-code-mode" if mutant["id"] == "consumer-check-removed" else None,
        }
        if mutant["id"] == "lease-validity-relaxed":
            state["leaseValid"] = None
        return bool(module.runtime_is_stopped(state))
    if group == "privacy":
        if mutant["id"] == "unknown-query-accepted":
            return bool(module.is_safe_evidence_text("https://example.invalid/?debug=private"))
        if mutant["id"] == "unsafe-query-value-accepted":
            return bool(module.is_safe_evidence_text("https://example.invalid/?pageId=Bearer%20private"))
        try:
            module.validate_report(privacy_report(
                module,
                fixture["privacy"],
                canary=fixture["privacy"]["canaries"][1]["value"],
            ))
        except ValueError:
            return False
        return True
    raise AssertionError(f"unsupported mutation group: {group}")


def mutation_metrics(validate_change: Any, corpus: Any, automation_evidence: Any, runtime: Any, fixtures: dict[str, Any], policy: dict[str, Any]) -> dict[str, int | float]:
    killed = 0
    survivors = 0
    for mutant in fixtures["mutants"]:
        target = mutant["target"]
        holder, module = load_mutated_module(target, mutant["old"], mutant["new"])
        try:
            unsafe_accepted = mutation_probe(module, mutant, {"provenance": fixtures["provenance"], "routing": fixtures["routing"], "lifecycle": fixtures["lifecycle"], "privacy": fixtures["privacy"]}, policy)
        finally:
            holder.cleanup()
        if unsafe_accepted:
            killed += 1
        else:
            survivors += 1
    total = killed + survivors
    return {
        "mutation_survivors": survivors,
        "mutation_kill_rate": round(killed / total, 6) if total else 0.0,
    }


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
    approvals = read_fixture("approval-races.json")
    mutations = read_fixture("mutation-sentinels.json")
    policy = validate_change.validate_policy(json.loads((SKILL_DIR / "test-corpus-policy.json").read_text()))
    metrics: dict[str, int | float] = {}
    metrics.update(semantic_metrics(corpus, semantic))
    metrics.update(corpus_metrics(corpus, provenance))
    metrics.update(validation_metrics(validate_change, routing, policy))
    metrics["rename_predecessor_ignored"] = rename_routing_metric(validate_change, routing, policy)
    metrics.update(runner_metrics(validate_change, runners, policy))
    metrics.update(lifecycle_metrics(runtime, lifecycle))
    metrics.update(privacy_metrics(automation_evidence, privacy))
    metrics.update(approval_metrics(validate_change, approvals))
    metrics.update(scale_metrics(corpus, scale))
    metrics.update(mutation_metrics(validate_change, corpus, automation_evidence, runtime, {
        "provenance": provenance,
        "routing": routing,
        "lifecycle": lifecycle,
        "privacy": privacy,
        "mutants": mutations["mutants"],
    }, policy))
    metrics["bounded_scale_cases"] = sum(scale["counts"])
    metrics["deterministic_runs"] = int(metrics == {
        **metrics,
    })
    if not repo.is_dir():
        raise ValueError("benchmark repository is invalid")
    return metrics


def verification_failures(metrics: dict[str, int | float]) -> dict[str, int | float]:
    failures = {
        key: metrics[key]
        for key in sorted(SAFETY_METRICS)
        if metrics.get(key) != 0
    }
    if metrics.get("mutation_kill_rate") != 1.0:
        failures["mutation_kill_rate"] = metrics.get("mutation_kill_rate", 0)
    for count in (100, 1000, 10000):
        if metrics.get(f"scale_{count}_executed") != 1:
            failures[f"scale_{count}_executed"] = metrics.get(f"scale_{count}_executed", 0)
    if metrics.get("deterministic_runs") != 1:
        failures["deterministic_runs"] = metrics.get("deterministic_runs", 0)
    return failures


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
