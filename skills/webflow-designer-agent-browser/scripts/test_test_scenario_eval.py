#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "test_scenario_eval", SCRIPT_DIR / "test-scenario-eval.py"
)
assert SPEC is not None and SPEC.loader is not None
scenario_eval = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scenario_eval
SPEC.loader.exec_module(scenario_eval)


SKILL_DIR = SCRIPT_DIR.parent
POLICY = json.loads((SKILL_DIR / "test-corpus-policy.json").read_text())
SCENARIO = json.loads(
    (SKILL_DIR / "tests/fixtures/scenarios/pages-panel.json").read_text()
)
OPERATION = json.loads(
    (SKILL_DIR / "tests/fixtures/test-corpus/pages-open-card.json").read_text()
)


class ScenarioEvalTests(unittest.TestCase):
    def test_fixture_contract_builds_bounded_plan(self):
        adapter = scenario_eval.validate_contract(SCENARIO, POLICY)
        plan = scenario_eval.build_plan(SCENARIO, OPERATION, adapter)

        self.assertEqual(plan["status"], "plan_only")
        self.assertEqual(
            plan["browser"]["lifecycle"],
            ["prepare", "selected-agent-browser-interaction", "verify", "finish"],
        )
        self.assertEqual(plan["setup"]["execution"], "not-run-by-this-command")
        self.assertEqual(plan["teardown"]["requiredAfter"], ["setup", "browser", "assertion"])
        self.assertIn("--workers=1", plan["setup"]["command"])
        serialized = json.dumps(plan)
        self.assertNotIn("https://", serialized)
        self.assertNotIn("/Users/", serialized)

    def test_unknown_adapter_fails_closed(self):
        contract = json.loads(json.dumps(SCENARIO))
        contract["adapter"] = "untrusted-command"
        with self.assertRaisesRegex(scenario_eval.ScenarioError, "not declared"):
            scenario_eval.validate_contract(contract, POLICY)

    def test_spec_outside_adapter_allowlist_fails_closed(self):
        contract = json.loads(json.dumps(SCENARIO))
        contract["specPath"] = "packages/tooling/unsafe.spec.ts"
        with self.assertRaisesRegex(scenario_eval.ScenarioError, "outside"):
            scenario_eval.validate_contract(contract, POLICY)

    def test_operation_not_allowed_fails_closed(self):
        operation = json.loads(json.dumps(OPERATION))
        operation["id"] = "designer.page.switch"
        adapter = scenario_eval.validate_contract(SCENARIO, POLICY)
        with self.assertRaisesRegex(scenario_eval.ScenarioError, "not allowed"):
            scenario_eval.build_plan(SCENARIO, operation, adapter)

    def test_execution_requires_explicit_plan_only_mode(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "test-scenario-eval.py",
                    "plan",
                    "--scenario",
                    str(SKILL_DIR / "tests/fixtures/scenarios/pages-panel.json"),
                    "--operation",
                    str(SKILL_DIR / "tests/fixtures/test-corpus/pages-open-card.json"),
                ],
            ),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(scenario_eval.main(), 2)
        self.assertIn("not implemented", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
