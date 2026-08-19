#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "validate_change", SCRIPT_DIR / "validate-change.py"
)
assert SPEC is not None and SPEC.loader is not None
validate_change = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validate_change
SPEC.loader.exec_module(validate_change)

POLICY_PATH = SCRIPT_DIR.parent / "test-corpus-policy.json"


class ValidationChangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init")
        self.git("config", "user.email", "validator@example.test")
        self.git("config", "user.name", "Validator")
        self.write("tracked.txt", "base\n")
        self.write("public/js/designer-flux/components/PagesPanel/PagesPanel.tsx", "export const pages = true;\n")
        self.git("add", ".")
        self.git("commit", "-m", "baseline")
        self.policy = validate_change.validate_policy(json.loads(POLICY_PATH.read_text()))

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def changes(self, **kwargs):
        return validate_change.collect_change_set(
            self.repo,
            self.policy["changeValidation"]["limits"],
            ignored_path_globs=self.policy["changeValidation"]["ignoredPathGlobs"],
            **kwargs,
        )

    def candidate_context(self):
        self.write("public/js/designer-flux/components/PagesPanelCandidate.tsx", "export const candidate = true;\n")
        change_set, route, result = validate_change.validate_change(self.repo, self.policy)
        self.assertEqual(route["status"], "unknown")
        return change_set, result["proposalContext"]

    def candidate(self, context):
        source = context["changeSet"]
        return {
            "version": 1,
            "id": "designer.pages-panel.candidate",
            "mode": "candidate",
            "surfaceAdapter": "webflow-designer",
            "source": {"commit": source["sourceCommit"], "changeSetDigest": source["digest"]},
            "evidenceRefs": ["policy:runner:designer-pages-panel-focused", "term:pages"],
            "riskClass": "reversible-ui",
            "determinism": "bounded",
            "runnerId": "designer-pages-panel-focused",
            "inputs": {},
            "constraints": ["Use only the reviewed fixture."],
            "target": {"fixture": "isolated-designer-test", "document": "main"},
            "preconditions": ["Designer test fixture is ready."],
            "facts": [{"id": "panel-visible", "type": "boolean", "source": "playwright-assertion"}],
            "actions": [
                {"id": "open-panel", "op": "invoke_operation", "dependsOn": [], "operationId": "designer.panel.pages.open"},
                {"id": "assert-panel", "op": "assert", "dependsOn": ["open-panel"], "fact": "panel-visible", "expected": True, "selectorKey": "Panels.PAGES"},
            ],
            "oracle": {"kind": "semantic-fact", "fact": "panel-visible", "expected": True},
            "recovery": [],
            "cleanup": ["adapter-teardown"],
            "budget": {"timeoutSeconds": 900, "maxRetries": 1, "maxActions": 8},
            "receipt": {"requireSemanticOracle": True, "requireCleanupProof": True},
        }

    def test_collects_staged_unstaged_untracked_deleted_and_renamed_changes(self):
        self.write("staged.ts", "export const staged = true;\n")
        self.git("add", "staged.ts")
        self.write("tracked.txt", "unstaged\n")
        self.write("untracked.ts", "export const untracked = true;\n")
        self.git("mv", "public/js/designer-flux/components/PagesPanel/PagesPanel.tsx", "public/js/designer-flux/components/PagesPanel/Renamed.tsx")
        changes = self.changes()["files"]
        by_path = {item["path"]: item for item in changes}
        self.assertEqual(by_path["staged.ts"]["status"], "added")
        self.assertIn("staged", by_path["staged.ts"]["sources"])
        self.assertEqual(by_path["tracked.txt"]["status"], "modified")
        self.assertEqual(by_path["untracked.ts"]["status"], "untracked")
        self.assertEqual(by_path["public/js/designer-flux/components/PagesPanel/Renamed.tsx"]["status"], "renamed")
        self.assertEqual(by_path["public/js/designer-flux/components/PagesPanel/Renamed.tsx"]["previousPath"], "public/js/designer-flux/components/PagesPanel/PagesPanel.tsx")

    def test_changed_path_normalization_and_bounded_symlinks_fail_closed(self):
        with self.assertRaisesRegex(validate_change.ValidationError, "normalized"):
            self.changes(changed_files=["../outside.ts"])
        target = self.repo / "linked.ts"
        target.symlink_to(self.repo / "tracked.txt")
        with self.assertRaisesRegex(validate_change.ValidationError, "regular files"):
            self.changes(changed_files=["linked.ts"])

    def test_explicit_base_includes_the_current_worktree_change_set(self):
        self.write("tracked.txt", "changed since base\n")
        changes = self.changes(base="HEAD")
        self.assertEqual(changes["files"], [
            {
                "path": "tracked.txt",
                "status": "modified",
                "sources": ["base"],
                "bytes": len("changed since base\n"),
                "sha256": hashlib.sha256(b"changed since base\n").hexdigest(),
            }
        ])

    def test_ignores_tracked_noise_without_hiding_product_changes(self):
        self.write("package-lock.json", '{"lockfileVersion": 3}\n')
        self.write("packages/designer/tsconfig.json", '{}\n')
        self.write("packages/designer/eslint.config.js", "export default {};\n")
        self.write(
            "public/js/designer-flux/components/PagesPanel/PagesPanel.tsx",
            "export const pages = false;\n",
        )
        changes = self.changes()
        self.assertEqual(
            changes["ignoredFiles"],
            [
                "package-lock.json",
                "packages/designer/eslint.config.js",
                "packages/designer/tsconfig.json",
            ],
        )
        self.assertEqual(
            [item["path"] for item in changes["files"]],
            ["public/js/designer-flux/components/PagesPanel/PagesPanel.tsx"],
        )
        route = validate_change.route_trusted_contracts(changes, self.policy)
        self.assertEqual(route["status"], "trusted")

    def test_noise_only_change_set_reports_ignored_files(self):
        self.write("package-lock.json", '{"lockfileVersion": 3}\n')
        changes = self.changes(changed_files=["package-lock.json"])
        self.assertEqual(changes["files"], [])
        self.assertEqual(changes["ignoredFiles"], ["package-lock.json"])
        route = validate_change.route_trusted_contracts(changes, self.policy)
        self.assertEqual(route["status"], "insufficient_evidence")
        self.assertEqual(route["reason"], "change_set_empty")

    def test_known_mapping_is_deterministic_and_zero_model(self):
        changes = self.changes(changed_files=["public/js/designer-flux/components/PagesPanel/PagesPanel.tsx"])
        route = validate_change.route_trusted_contracts(changes, self.policy)
        self.assertEqual(route["status"], "trusted")
        self.assertEqual(route["operations"], ["designer.panel.pages.open"])
        _, _, receipt = validate_change.validate_change(
            self.repo, self.policy, changed_files=["public/js/designer-flux/components/PagesPanel/PagesPanel.tsx"]
        )
        self.assertEqual(receipt["status"], "ready")
        self.assertEqual(receipt["modelProposalCount"], 0)
        self.assertEqual(receipt["tests"], ["entrypoints/playwright-tests/designer/panels-system/left-sidebar-panel-focus-management.spec.ts"])

    def test_unknown_change_has_bounded_context_or_insufficient_evidence(self):
        _, context = self.candidate_context()
        self.assertEqual(context["status"], "approval_required")
        self.assertEqual(context["candidatePolicy"]["modelProposalLimit"], 1)
        self.assertLessEqual(len(context["nearbyContracts"]), 5)
        self.write("packages/server/unknown.ts", "export const unknown = true;\n")
        changes = self.changes(changed_files=["packages/server/unknown.ts"])
        route = validate_change.route_trusted_contracts(changes, self.policy)
        context = validate_change.build_proposal_context(changes, route, self.policy)
        self.assertEqual(context["status"], "insufficient_evidence")

    def test_candidate_requires_exact_source_and_safe_data_only_ir(self):
        _, context = self.candidate_context()
        candidate = self.candidate(context)
        validated = validate_change.validate_candidate_contract(candidate, context, self.policy)
        self.assertEqual(validated, candidate)
        self.assertRegex(validate_change.candidate_digest(candidate), r"^[0-9a-f]{64}$")
        changed = json.loads(json.dumps(candidate))
        changed["source"]["changeSetDigest"] = "0" * 64
        with self.assertRaisesRegex(validate_change.ValidationError, "source binding"):
            validate_change.validate_candidate_contract(changed, context, self.policy)
        changed = json.loads(json.dumps(candidate))
        changed["constraints"] = ["Run javascript from the page."]
        with self.assertRaisesRegex(validate_change.ValidationError, "forbidden"):
            validate_change.validate_candidate_contract(changed, context, self.policy)
        changed = json.loads(json.dumps(candidate))
        changed["actions"][1]["selectorKey"] = "body > script"
        with self.assertRaisesRegex(validate_change.ValidationError, "not reviewed"):
            validate_change.validate_candidate_contract(changed, context, self.policy)

    def test_candidate_enforces_graph_budget_oracle_cleanup_and_runner_allowlist(self):
        _, context = self.candidate_context()
        candidate = self.candidate(context)
        changed = json.loads(json.dumps(candidate))
        changed["actions"][0]["dependsOn"] = ["assert-panel"]
        with self.assertRaisesRegex(validate_change.ValidationError, "acyclic"):
            validate_change.validate_candidate_contract(changed, context, self.policy)
        changed = json.loads(json.dumps(candidate))
        changed["budget"]["timeoutSeconds"] = 901
        with self.assertRaisesRegex(validate_change.ValidationError, "fixed budget"):
            validate_change.validate_candidate_contract(changed, context, self.policy)
        changed = json.loads(json.dumps(candidate))
        changed["oracle"]["fact"] = "not-a-fact"
        with self.assertRaisesRegex(validate_change.ValidationError, "semantic oracle"):
            validate_change.validate_candidate_contract(changed, context, self.policy)
        changed = json.loads(json.dumps(candidate))
        changed["cleanup"] = ["close-panel"]
        with self.assertRaisesRegex(validate_change.ValidationError, "adapter-teardown"):
            validate_change.validate_candidate_contract(changed, context, self.policy)
        changed = json.loads(json.dumps(candidate))
        changed["runnerId"] = "designer-add-panel-focused"
        with self.assertRaisesRegex(validate_change.ValidationError, "reviewed runner"):
            validate_change.validate_candidate_contract(changed, context, self.policy)

    def test_approval_digest_binds_every_material_candidate_field(self):
        _, context = self.candidate_context()
        candidate = self.candidate(context)
        digest = validate_change.approval_digest(candidate)
        for path, replacement in [
            (("source", "commit"), "0" * 40),
            (("source", "changeSetDigest"), "0" * 64),
            (("target", "document"), "canvas"),
            (("riskClass",), "read-only"),
            (("oracle", "expected"), False),
            (("cleanup",), ["adapter-teardown", "close-panel"]),
            (("budget", "maxRetries"), 0),
        ]:
            changed = json.loads(json.dumps(candidate))
            cursor = changed
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = replacement
            self.assertNotEqual(digest, validate_change.approval_digest(changed))
        changed = json.loads(json.dumps(candidate))
        changed["actions"][1]["expected"] = False
        self.assertNotEqual(digest, validate_change.approval_digest(changed))

    def test_fixed_runner_classifies_preflight_semantic_and_cleanup_failures(self):
        changes = self.changes(changed_files=["public/js/designer-flux/components/PagesPanel/PagesPanel.tsx"])
        runner_id = "designer-pages-panel-focused"
        calls = []

        def passed(command, cwd, timeout):
            calls.append((command, cwd, timeout))
            return validate_change.CommandResult(0)

        receipt = validate_change.execute_runner(self.repo, self.policy, [runner_id], changes, runner=passed)
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["semanticOracle"], "passed")
        self.assertEqual(receipt["cleanup"], "proved")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][0][0:3], ["npx", "playwright", "test"])
        receipt = validate_change.execute_runner(self.repo, self.policy, [runner_id], changes, runner=lambda *_: validate_change.CommandResult(1))
        self.assertEqual(receipt["status"], "infrastructure_failed")
        self.assertEqual(receipt["failureClass"], "preflight_failed")
        calls.clear()

        def semantic_failure(command, _cwd, _timeout):
            calls.append(command)
            return validate_change.CommandResult(
                0 if len(calls) == 1 else 1,
                failure_markers=() if len(calls) == 1 else ("semantic_assertion_failure",),
            )

        receipt = validate_change.execute_runner(self.repo, self.policy, [runner_id], changes, runner=semantic_failure)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["failureClass"], "semantic_assertion_failure")
        self.assertEqual(receipt["cleanup"], "not_proved")
        calls.clear()

        def adapter_timeout(_command, _cwd, _timeout):
            calls.append(None)
            return validate_change.CommandResult(0 if len(calls) == 1 else 124, timed_out=len(calls) > 1)

        receipt = validate_change.execute_runner(self.repo, self.policy, [runner_id], changes, runner=adapter_timeout)
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["cleanup"], "not_proved")

    def test_runner_receipts_classify_bounded_markers_without_leaking_output(self):
        changes = self.changes(changed_files=["public/js/designer-flux/components/PagesPanel/PagesPanel.tsx"])
        runner_id = "designer-pages-panel-focused"

        def result_after_preflight(marker, *, timed_out=False):
            calls = 0

            def runner(_command, _cwd, _timeout):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return validate_change.CommandResult(0)
                return validate_change.CommandResult(
                    124 if timed_out else 1,
                    timed_out=timed_out,
                    failure_markers=(marker,) if marker else (),
                )

            return runner

        cases = [
            ("semantic_assertion_failure", "oracle", "semantic_assertion_failure", "failed", "not_proved"),
            ("scenario_setup_failure", "execute", "scenario_setup_failure", "not_run", "not_proved"),
            ("teardown_failure", "cleanup", "teardown_failure", "not_run", "failed"),
            ("", "execute", "unknown_test_failure", "not_run", "not_proved"),
        ]
        for marker, phase, failure_class, oracle, cleanup in cases:
            receipt = validate_change.execute_runner(
                self.repo, self.policy, [runner_id], changes,
                runner=result_after_preflight(marker),
            )
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["phase"], phase)
            self.assertEqual(receipt["failureClass"], failure_class)
            self.assertEqual(receipt["semanticOracle"], oracle)
            self.assertEqual(receipt["cleanup"], cleanup)
            self.assertNotIn("failure_markers", json.dumps(receipt))

        timeout = validate_change.execute_runner(
            self.repo, self.policy, [runner_id], changes,
            runner=result_after_preflight("", timed_out=True),
        )
        self.assertEqual(timeout["status"], "failed")
        self.assertEqual(timeout["failureClass"], "adapter_timeout")
        self.assertEqual(timeout["cleanup"], "not_proved")

    def test_default_runner_discards_diagnostic_text_after_classification(self):
        result = validate_change.default_runner(
            [sys.executable, "-c", "import sys; print('AssertionError token=private-value'); sys.exit(1)"],
            self.repo,
            10,
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.failure_markers, ("semantic_assertion_failure",))
        self.assertNotIn("private-value", repr(result))

    def test_candidate_execution_receipt_does_not_promote_policy_or_leak_paths(self):
        changes, context = self.candidate_context()
        candidate = validate_change.validate_candidate_contract(self.candidate(context), context, self.policy)
        original = json.loads(json.dumps(self.policy))
        calls = 0

        def passed(_command, _cwd, _timeout):
            nonlocal calls
            calls += 1
            return validate_change.CommandResult(0)

        receipt = validate_change.execute_runner(self.repo, self.policy, [candidate["runnerId"]], changes, candidate=candidate, runner=passed)
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["candidate"]["state"], "consumed")
        self.assertEqual(receipt["modelProposalCount"], 1)
        self.assertEqual(self.policy, original)
        self.assertNotIn(str(self.repo), json.dumps(receipt))
        self.assertEqual(calls, 2)

    def test_standalone_candidate_approval_is_exact_and_one_run_only(self):
        _, context = self.candidate_context()
        candidate = validate_change.validate_candidate_contract(
            self.candidate(context), context, self.policy
        )
        state_path = Path(self.temp.name) / "state" / "candidate.json"
        approval = validate_change.approval_digest(candidate)
        validate_change.record_candidate_proposal(candidate, state_path)
        self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
        prompt = io.StringIO()
        self.assertTrue(
            validate_change.confirm_candidate_execution(
                candidate,
                approval,
                input_fn=lambda _prompt: approval,
                output=prompt,
            )
        )
        self.assertIn("designer.panel.pages.open", prompt.getvalue())
        with self.assertRaisesRegex(validate_change.ValidationError, "digest"):
            validate_change.claim_candidate_execution(
                candidate, "0" * 64, state_path
            )
        validate_change.claim_candidate_execution(candidate, approval, state_path)
        validate_change.consume_candidate_execution(state_path)
        with self.assertRaisesRegex(validate_change.ValidationError, "consumed"):
            validate_change.claim_candidate_execution(candidate, approval, state_path)

    def test_standalone_cli_records_a_candidate_but_requires_a_tty_to_run(self):
        _, context = self.candidate_context()
        candidate_path = Path(self.temp.name) / "candidate.json"
        candidate_path.write_text(json.dumps(self.candidate(context)))
        environment = {**os.environ, "HOME": self.temp.name}
        proposed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "validate-change.py"),
                "validate-candidate",
                "--repo",
                str(self.repo),
                "--candidate",
                str(candidate_path),
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        approval = json.loads(proposed.stdout)["approvalDigest"]
        executed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "validate-change.py"),
                "execute-candidate",
                "--repo",
                str(self.repo),
                "--candidate",
                str(candidate_path),
                "--approval-digest",
                approval,
                "--execute",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        self.assertEqual(executed.returncode, 2)
        self.assertIn("interactive terminal", executed.stderr)


if __name__ == "__main__":
    unittest.main()
