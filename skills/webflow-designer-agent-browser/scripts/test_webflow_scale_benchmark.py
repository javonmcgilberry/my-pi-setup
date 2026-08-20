#!/usr/bin/env python3
"""Tests for the synthetic end-to-end corpus scale benchmark."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "webflow_scale_benchmark", SCRIPT_DIR / "webflow-scale-benchmark.py"
)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


class WebflowScaleBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metrics = benchmark.run(Path.cwd())

    def test_run_executes_all_bounded_end_to_end_workloads(self):
        metrics = self.metrics
        self.assertEqual(metrics["scale_cases_executed"], 11_100)
        self.assertEqual(metrics["canonical_mismatches"], 0)
        self.assertEqual(metrics["private_value_leaks"], 0)
        self.assertEqual(metrics["deterministic_runs"], 1)
        for count in benchmark.COUNTS:
            self.assertEqual(metrics[f"scale_{count}_executed"], 1)
            self.assertEqual(metrics[f"scale_{count}_files"], count)
            self.assertEqual(metrics[f"scale_{count}_canonical_mismatches"], 0)
            self.assertEqual(metrics[f"scale_{count}_private_value_leaks"], 0)
            self.assertGreater(metrics[f"scale_{count}_fragment_records"], 0)
            self.assertGreater(metrics[f"scale_{count}_git_calls"], 0)
            self.assertGreater(metrics[f"scale_{count}_file_reads"], 0)
            self.assertGreater(metrics[f"scale_{count}_bytes_hashed"], 0)
            self.assertGreater(metrics[f"scale_{count}_work_units"], 0)

    def test_scale_work_is_monotonic_and_verification_is_fail_closed(self):
        metrics = self.metrics
        work = [metrics[f"scale_{count}_work_units"] for count in benchmark.COUNTS]
        self.assertEqual(work, sorted(work))
        safe = {key: 0 for key in (
            "scale_100_canonical_mismatches",
            "scale_1000_canonical_mismatches",
            "scale_10000_canonical_mismatches",
            "scale_100_private_value_leaks",
            "scale_1000_private_value_leaks",
            "scale_10000_private_value_leaks",
            "canonical_mismatches",
            "private_value_leaks",
            "deterministic_runs",
        )}
        safe.update({f"scale_{count}_executed": 1 for count in benchmark.COUNTS})
        safe.update({f"scale_{count}_files": count for count in benchmark.COUNTS})
        safe.update({f"scale_{count}_file_reads": count for count in benchmark.COUNTS})
        safe.update({f"scale_{count}_bytes_hashed": count for count in benchmark.COUNTS})
        safe.update({f"scale_{count}_work_units": count for count in benchmark.COUNTS})
        safe["scale_cases_executed"] = sum(benchmark.COUNTS)
        safe["deterministic_runs"] = 1
        self.assertEqual(benchmark.verification_failures(safe), {})
        unsafe = dict(safe)
        unsafe["scale_1000_canonical_mismatches"] = 1
        self.assertIn("scale_1000_canonical_mismatches", benchmark.verification_failures(unsafe))


if __name__ == "__main__":
    unittest.main()
