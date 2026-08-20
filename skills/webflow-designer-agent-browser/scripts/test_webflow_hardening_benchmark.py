#!/usr/bin/env python3
"""Tests for the offline hardening benchmark and its frozen fixtures."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "webflow_hardening_benchmark", SCRIPT_DIR / "webflow-hardening-benchmark.py"
)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


class WebflowHardeningBenchmarkTests(unittest.TestCase):
    def test_all_frozen_fixtures_are_versioned_and_bounded(self):
        names = {
            "semantic-identity.json",
            "provenance-lineage.json",
            "routing-contracts.json",
            "runner-results.json",
            "lifecycle-states.json",
            "privacy-canaries.json",
            "scale-profiles.json",
            "approval-races.json",
            "mutation-sentinels.json",
        }
        self.assertEqual(
            {path.name for path in benchmark.FIXTURE_DIR.glob("*.json")}, names
        )
        for name in sorted(names):
            value = benchmark.read_fixture(name)
            self.assertEqual(value["version"], 1)
            self.assertLess(len(json.dumps(value, sort_keys=True)), 100_000)

        scale = benchmark.read_fixture("scale-profiles.json")
        self.assertEqual(scale["counts"], [100, 1000, 10000])
        self.assertLessEqual(max(scale["counts"]), 10_000)

    def test_benchmark_is_deterministic_and_has_complete_metrics(self):
        expected = {
            "semantic_safe_recall",
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
            "privacy_raw_canary_acceptance",
            "privacy_bounds_violations",
            "approval_reuse_accepted",
            "approval_digest_mismatch_accepted",
            "approval_expired_accepted",
            "approval_malformed_accepted",
            "approval_symlink_accepted",
            "mixed_trusted_route",
            "rename_predecessor_ignored",
            "lifecycle_false_stopped",
            "lifecycle_missing_stop_proof",
            "mutation_survivors",
            "mutation_kill_rate",
            "canonical_mismatches",
            "scale_private_value_leaks",
            "scale_100_executed",
            "scale_100_fragments",
            "scale_100_bound",
            "scale_1000_executed",
            "scale_1000_fragments",
            "scale_1000_bound",
            "scale_10000_executed",
            "scale_10000_fragments",
            "scale_10000_bound",
            "scale_cases_executed",
            "bounded_scale_cases",
            "deterministic_runs",
            "semantic_positive_pairs",
            "corpus_records",
        }
        first = benchmark.run(Path.cwd())
        second = benchmark.run(Path.cwd())
        self.assertEqual(set(first), expected)
        self.assertEqual(first, second)
        self.assertEqual(first["deterministic_runs"], 1)
        self.assertEqual(first["semantic_false_merges"], 0)
        self.assertEqual(first["semantic_unanchored_violations"], 0)
        self.assertGreater(first["semantic_safe_recall"], 0)
        self.assertEqual(first["bounded_scale_cases"], 11_100)
        self.assertEqual(first["mutation_kill_rate"], 1.0)
        self.assertEqual(first["mutation_survivors"], 0)
        self.assertEqual(first["scale_cases_executed"], 11_100)
        for key in benchmark.SAFETY_METRICS:
            self.assertEqual(first[key], 0, key)
        self.assertEqual(
            {first[f"scale_{count}_executed"] for count in (100, 1000, 10000)},
            {1},
        )

    def test_verify_predicate_rejects_unsafe_and_accepts_safe_metrics(self):
        unsafe = {key: 0 for key in benchmark.SAFETY_METRICS}
        unsafe["explicit_trusted_route"] = 1
        unsafe["deterministic_runs"] = 1
        unsafe["mutation_kill_rate"] = 1.0
        unsafe.update({f"scale_{count}_executed": 1 for count in (100, 1000, 10000)})
        safe = {key: 0 for key in benchmark.SAFETY_METRICS}
        safe["deterministic_runs"] = 1
        safe["mutation_kill_rate"] = 1.0
        safe.update({f"scale_{count}_executed": 1 for count in (100, 1000, 10000)})
        self.assertFalse(benchmark.verified(unsafe))
        self.assertTrue(benchmark.verified(safe))

    def test_json_cli_output_is_byte_deterministic(self):
        command = [
            sys.executable,
            "-B",
            str(SCRIPT_DIR / "webflow-hardening-benchmark.py"),
            "--repo",
            str(Path.cwd()),
            "--format",
            "json",
        ]
        first = subprocess.run(command, check=True, capture_output=True).stdout
        second = subprocess.run(command, check=True, capture_output=True).stdout
        self.assertEqual(first, second)

    def test_metrics_do_not_echo_private_or_canary_fixture_values(self):
        metrics = benchmark.run(Path.cwd())
        serialized = json.dumps(metrics, sort_keys=True)
        for name in ("privacy-canaries.json", "provenance-lineage.json"):
            fixture = benchmark.read_fixture(name)
            self.assertNotIn("/Users/private", serialized)
            self.assertNotIn("privacy-canary", serialized)
            self.assertNotIn("deleteFixture", serialized)
            self.assertIsInstance(fixture, dict)


if __name__ == "__main__":
    unittest.main()
