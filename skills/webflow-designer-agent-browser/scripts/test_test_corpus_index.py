#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location(
    "test_corpus_index", SCRIPT_DIR / "test-corpus-index.py"
)
assert SPEC is not None and SPEC.loader is not None
corpus = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = corpus
SPEC.loader.exec_module(corpus)


class CorpusIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)
        self._write(
            "entrypoints/playwright-tests/utils/designerUtils/index.ts",
            """
export async function openPagesPanel(page, locators) {
  await locators.Sidebar.PAGES_BUTTON.click();
  await expect(locators.Panels.PAGES).toBeVisible();
}
""".strip()
            + "\n",
        )
        self._write(
            "entrypoints/playwright-tests/utils/designerUtils/testIds.ts",
            """
const locators = {
  Sidebar: {PAGES_BUTTON: page.getByTestId('left-sidebar-pages-button')},
  Panels: {PAGES: page.getByTestId('pages')}
};
""".strip()
            + "\n",
        )
        self._write(
            "entrypoints/playwright-tests/designer/panels/pages-a.spec.ts",
            """
test('opens pages', async () => {
  await openPagesPanel(page);
  await expect(page.getByTestId('pages')).toBeVisible();
});
""".strip()
            + "\n",
        )
        self._write(
            "entrypoints/playwright-tests/designer/panels/pages-b.spec.ts",
            """
test('opens pages another way', async () => {
  await inspectDesigner(page);
  await openPagesPanel(page);
  await expect(page.getByTestId('pages')).toBeVisible();
});
""".strip()
            + "\n",
        )
        self.policy = {
            "version": 1,
            "sources": [
                {
                    "framework": "playwright",
                    "roots": ["entrypoints/playwright-tests"],
                    "patterns": ["*.spec.ts"],
                }
            ],
            "operationSource": "entrypoints/playwright-tests/utils/designerUtils/index.ts",
            "locatorSource": "entrypoints/playwright-tests/utils/designerUtils/testIds.ts",
            "selection": {
                "minimumConfidence": 55,
                "maximumEvidencePerOperation": 5,
                "holdoutEvidencePerOperation": 1,
            },
            "discovery": {
                "helperSources": ["entrypoints/playwright-tests/utils/designerUtils/index.ts"],
            },
            "operations": [
                {
                    "id": "designer.panel.pages.open",
                    "symbol": "openPagesPanel",
                    "intent": "Open Pages",
                    "capabilities": ["panel-management", "page-navigation"],
                    "contexts": ["designer-ready", "main-document"],
                    "parameters": [],
                    "locatorKeys": ["Sidebar.PAGES_BUTTON", "Panels.PAGES"],
                    "actions": [{"verb": "click-if-hidden", "target": "Sidebar.PAGES_BUTTON"}],
                    "postconditions": ["Panels.PAGES is visible"],
                    "guardrails": ["Do not click when already visible"],
                }
            ],
        }
        self.policy_path = self.repo / "policy.json"
        self.policy_path.write_text(json.dumps(self.policy))
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Corpus Test"], cwd=self.repo, check=True)
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.repo, check=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write(self, relative: str, content: str):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_build_is_deterministic_and_validates_provenance(self):
        first = corpus.build_index(self.repo, self.policy)
        second = corpus.build_index(self.repo, self.policy)

        self.assertEqual(first, second)
        self.assertEqual(corpus.validate_index(first, self.repo, self.policy)["cardCount"], 1)
        card = first["cards"][0]
        self.assertEqual(card["selectionStatus"], "include")
        self.assertEqual(len(card["holdoutEvidence"]), 1)
        self.assertFalse(
            {item["path"] for item in card["evidence"]}
            & {item["path"] for item in card["holdoutEvidence"]}
        )
        serialized = json.dumps(first)
        self.assertNotIn("test@example.invalid", serialized)
        self.assertNotIn("/Users/", serialized)

    def test_uncommitted_source_change_invalidates_index(self):
        index = corpus.build_index(self.repo, self.policy)
        self._write(
            "entrypoints/playwright-tests/designer/panels/pages-a.spec.ts",
            "test('changed', async () => { await openPagesPanel(page); });\n",
        )

        with self.assertRaisesRegex(corpus.CorpusError, "source manifest is stale"):
            corpus.validate_index(index, self.repo, self.policy)

    def test_quarantined_evidence_cannot_score_as_positive(self):
        signals = corpus.classify_signals(
            "test.skip('legacy', async () => { await openPagesPanel(page); });",
            "designer/legacy.quarantined.spec.ts",
            "playwright",
        )
        record = {"signals": signals}
        self.assertTrue(signals["quarantined"])
        self.assertEqual(corpus.score_evidence(record), 0)

    def test_operation_patterns_capture_direct_scenario_without_helper_call(self):
        policy = json.loads(json.dumps(self.policy))
        operation = policy["operations"][0]
        operation["evidencePatternMode"] = "all"
        operation["evidencePatterns"] = [
            r"keyboard\.press\(\s*['\"]p['\"]",
            "pages-panel-visible",
        ]
        direct_path = "entrypoints/playwright-tests/designer/panels/direct-pages.spec.ts"
        self._write(
            direct_path,
            "test('keyboard opens pages', async () => {\n"
            "  await page.keyboard.press('p');\n"
            "  await expect(page.getByText('pages-panel-visible')).toBeVisible();\n"
            "});\n",
        )

        card = corpus.build_index(self.repo, policy)["cards"][0]
        holdout_paths = {record["path"] for record in card["holdoutEvidence"]}
        evidence_paths = {record["path"] for record in card["evidence"]}
        self.assertIn(direct_path, holdout_paths | evidence_paths)

    def test_unknown_locator_key_fails_closed(self):
        policy = json.loads(json.dumps(self.policy))
        policy["operations"][0]["locatorKeys"] = ["Sidebar.MISSING"]
        with self.assertRaisesRegex(corpus.CorpusError, "locator key"):
            corpus.build_index(self.repo, policy)

    def test_portfolio_covers_operation_capabilities(self):
        cards = corpus.build_index(self.repo, self.policy)["cards"]
        portfolio = corpus.choose_portfolio(cards)
        self.assertEqual(portfolio["uncoveredCapabilities"], [])
        self.assertEqual(portfolio["operationIds"], ["designer.panel.pages.open"])

    def test_validation_rejects_schema_shape_drift(self):
        index = corpus.build_index(self.repo, self.policy)

        missing_negative = json.loads(json.dumps(index))
        del missing_negative["cards"][0]["negativeEvidence"]
        with self.assertRaisesRegex(corpus.CorpusError, "missing fields"):
            corpus.validate_index(missing_negative, self.repo, self.policy)

        invalid_provenance = json.loads(json.dumps(index))
        invalid_provenance["cards"][0]["provenance"] = []
        with self.assertRaisesRegex(corpus.CorpusError, "provenance is invalid"):
            corpus.validate_index(invalid_provenance, self.repo, self.policy)

        invalid_evidence = json.loads(json.dumps(index))
        invalid_evidence["cards"][0]["negativeEvidence"] = {}
        with self.assertRaisesRegex(corpus.CorpusError, "negativeEvidence is invalid"):
            corpus.validate_index(invalid_evidence, self.repo, self.policy)

    def test_validation_recomputes_source_derived_card_fields(self):
        index = corpus.build_index(self.repo, self.policy)
        index["cards"][0]["intent"] = "forged source-derived intent"
        with self.assertRaisesRegex(corpus.CorpusError, "source compilation"):
            corpus.validate_index(index, self.repo, self.policy)

    def test_unsafe_operation_evidence_is_negative_only(self):
        unsafe_path = "entrypoints/playwright-tests/designer/panels/unsafe.spec.ts"
        self._write(
            unsafe_path,
            "test('unsafe', async () => {\n"
            "  await openPagesPanel(page);\n"
            "  await page.getByTestId('pages').click();\n"
            "  // fixture mock waitForTimeout(500) and deleteFixture()\n"
            "  await expect(page.getByTestId('pages')).toBeVisible();\n"
            "});\n",
        )
        card = corpus.build_index(self.repo, self.policy)["cards"][0]
        positive_paths = {
            item["path"] for item in [*card["evidence"], *card["holdoutEvidence"]]
        }
        negative_paths = {item["path"] for item in card["negativeEvidence"]}
        self.assertNotIn(unsafe_path, positive_paths)
        self.assertIn(unsafe_path, negative_paths)

    def test_heldout_evaluation_does_not_use_positive_evidence(self):
        with mock.patch.object(corpus, "score_card", wraps=corpus.score_card) as score_card:
            index = corpus.build_index(self.repo, self.policy)
        report = corpus.evaluate_index(index, self.policy)

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["passed"], 1)
        result = report["results"][0]
        self.assertEqual(result["holdoutEvidence"], 1)
        self.assertTrue(result["checks"]["noPositiveHoldoutOverlap"])
        training_paths = {record["path"] for record in score_card.call_args.args[1]}
        holdout_paths = {record["path"] for record in index["cards"][0]["holdoutEvidence"]}
        self.assertFalse(training_paths & holdout_paths)

    def test_discovery_is_fragment_scoped_and_uses_independent_lineage_holdout(self):
        first = "entrypoints/playwright-tests/designer/panels/direct-a.spec.ts"
        second = "entrypoints/playwright-tests/designer/panels/direct-b.spec.ts"
        self._write(
            first,
            "test('direct pages A', async () => {\n"
            "  // page.getByTestId('comment-only').click();\n"
            "  await settleDesigner();\n"
            "  await page.getByTestId('pages').click();\n"
            "  await expect(page.getByTestId('pages')).toBeVisible();\n"
            "});\n",
        )
        self._write(
            second,
            "test('direct pages B', async () => {\n"
            "  await inspectDesigner();\n"
            "  await page.getByTestId('pages').click();\n"
            "  await expect(page.getByTestId('pages')).toBeVisible();\n"
            "});\n",
        )

        first_report = corpus.build_discovery(self.repo, self.policy)
        second_report = corpus.build_discovery(self.repo, self.policy)

        self.assertEqual(first_report, second_report)
        self.assertEqual(
            corpus.validate_discovery(first_report, self.repo, self.policy)["candidateCount"],
            first_report["counts"]["candidates"],
        )
        candidate = next(
            candidate
            for candidate in first_report["candidates"]
            if candidate["subsystem"] == "panels"
            and candidate["signature"]["actions"] == ["click"]
        )
        self.assertTrue(candidate["promotionChecks"]["independentCorroboration"])
        self.assertTrue(candidate["promotionChecks"]["holdoutIndependent"])
        training_lineages = {item["lineage"] for item in candidate["evidence"]}
        holdout_lineages = {item["lineage"] for item in candidate["holdoutEvidence"]}
        self.assertFalse(training_lineages & holdout_lineages)
        self.assertTrue(all(item["lineStart"] <= item["lineEnd"] for item in candidate["evidence"]))
        serialized = json.dumps(first_report)
        self.assertNotIn("comment-only", serialized)
        self.assertNotIn("test@example.invalid", serialized)

    def test_discovery_validation_rejects_holdout_lineage_leakage(self):
        self._write(
            "entrypoints/playwright-tests/designer/panels/direct.spec.ts",
            "test('direct pages', async () => {\n"
            "  await settleDesigner();\n"
            "  await page.getByTestId('pages').click();\n"
            "  await expect(page.getByTestId('pages')).toBeVisible();\n"
            "});\n",
        )
        report = corpus.build_discovery(self.repo, self.policy)
        candidate = next(candidate for candidate in report["candidates"] if candidate["evidence"])
        candidate["holdoutEvidence"] = [dict(candidate["evidence"][0])]

        with self.assertRaisesRegex(corpus.CorpusError, "holdout lineage leaked"):
            corpus.validate_discovery(report, self.repo, self.policy)

    def test_discovery_does_not_merge_generic_actions_with_different_targets(self):
        for directory, target in (("alpha", "pages-private-target"), ("beta", "settings-private-target")):
            self._write(
                f"entrypoints/playwright-tests/designer/panels/{directory}/direct.spec.ts",
                "test('direct action', async () => {\n"
                f"  await page.getByTestId('{target}').click();\n"
                f"  await expect(page.getByTestId('{target}')).toBeVisible();\n"
                "});\n",
            )

        report = corpus.build_discovery(self.repo, self.policy)
        direct = [
            candidate
            for candidate in report["candidates"]
            if candidate["subsystem"] == "panels"
            and candidate["signature"]["actions"] == ["click"]
        ]

        self.assertEqual(len(direct), 2)
        self.assertTrue(all(candidate["semanticIdentity"]["bound"] for candidate in direct))
        self.assertTrue(
            all(not candidate["promotionChecks"]["independentCorroboration"] for candidate in direct)
        )
        serialized = json.dumps(report)
        self.assertNotIn("pages-private-target", serialized)
        self.assertNotIn("settings-private-target", serialized)

    def test_discovery_groups_matching_semantic_targets_deterministically(self):
        for directory, setup_helper in (("alpha", "settleDesigner"), ("beta", "inspectDesigner")):
            self._write(
                f"entrypoints/playwright-tests/designer/panels/{directory}/direct.spec.ts",
                "test('direct action', async () => {\n"
                f"  await {setup_helper}();\n"
                "  await page.getByTestId('shared-private-target').click();\n"
                "  await expect(page.getByTestId('shared-private-target')).toBeVisible();\n"
                "});\n",
            )

        first = corpus.build_discovery(self.repo, self.policy)
        second = corpus.build_discovery(self.repo, self.policy)
        candidate = next(
            item
            for item in first["candidates"]
            if item["subsystem"] == "panels"
            and item["signature"]["actions"] == ["click"]
        )

        self.assertEqual(first, second)
        self.assertEqual(first["version"], 2)
        self.assertEqual(candidate["semanticIdentity"]["kind"], "selector-target")
        self.assertRegex(candidate["semanticIdentity"]["digest"], r"^[0-9a-f]{16}$")
        self.assertTrue(candidate["promotionChecks"]["semanticIdentityBound"])
        self.assertTrue(candidate["promotionChecks"]["independentCorroboration"])
        self.assertNotIn("shared-private-target", json.dumps(first))

    def test_unanchored_fragments_remain_isolated_and_cannot_corroborate(self):
        for directory in ("alpha", "beta"):
            self._write(
                f"entrypoints/playwright-tests/designer/panels/{directory}/keyboard.spec.ts",
                "test('keyboard action', async () => {\n"
                "  await page.keyboard.press('Escape');\n"
                "});\n",
            )

        report = corpus.build_discovery(self.repo, self.policy)
        keyboard = [
            candidate
            for candidate in report["candidates"]
            if candidate["subsystem"] == "panels"
            and candidate["signature"]["actions"] == ["press"]
        ]

        self.assertEqual(len(keyboard), 2)
        self.assertTrue(all(not item["semanticIdentity"]["bound"] for item in keyboard))
        self.assertTrue(
            all(not item["promotionChecks"]["independentCorroboration"] for item in keyboard)
        )
        self.assertEqual(report["coverage"]["byIdentity"]["unanchored"], 2)

    def test_fragment_features_recover_equivalent_literal_target_forms(self):
        def identity(source):
            return corpus.semantic_identity(
                corpus.fragment_features(source),
                relative_path="designer/panels/pages.spec.ts",
                line_start=1,
                line_end=1,
            )

        direct = identity("await page.getByTestId('pages-private-target').click();")
        css = identity(
            "await page.locator('[data-testid=\"pages-private-target\"]').click();"
        )
        alias = identity(
            "const target = page.getByTestId('pages-private-target'); "
            "await target.click();"
        )
        self.assertEqual(direct, css)
        self.assertEqual(direct, alias)

        role = identity(
            "await page.getByRole('button', { name: 'Pages' }).click();"
        )
        exact_role = identity(
            "await page.getByRole('button', { name: 'Pages', exact: true }).click();"
        )
        self.assertEqual(role, exact_role)
        self.assertNotEqual(direct["digest"], role["digest"])

        dynamic_source = "const id = getPanelId(); await page.getByTestId(id).click();"
        dynamic_features = corpus.fragment_features(dynamic_source)
        self.assertEqual(dynamic_features["actionTargets"], [])
        self.assertEqual(identity(dynamic_source)["kind"], "helper-call")

        unanchored = identity("await page.keyboard.press('Escape');")
        self.assertFalse(unanchored["bound"])

    def test_shared_helper_lineage_is_not_independent_corroboration(self):
        for directory in ("alpha", "beta"):
            self._write(
                f"entrypoints/playwright-tests/designer/panels/{directory}/helper.spec.ts",
                "test('helper action', async () => {\n"
                "  await openPagesPanel(page);\n"
                "  await page.getByTestId('shared-helper-private-target').click();\n"
                "});\n",
            )

        report = corpus.build_discovery(self.repo, self.policy)
        helper_candidate = next(
            candidate
            for candidate in report["candidates"]
            if candidate["semanticIdentity"]["kind"] == "selector-target"
            and not candidate["promotionChecks"]["independentCorroboration"]
        )

        self.assertTrue(helper_candidate["semanticIdentity"]["bound"])
        self.assertFalse(helper_candidate["promotionChecks"]["independentCorroboration"])
        self.assertFalse(helper_candidate["promotionChecks"]["holdoutIndependent"])

    def test_discovery_v2_validation_rejects_identity_and_coverage_drift(self):
        self._write(
            "entrypoints/playwright-tests/designer/panels/keyboard.spec.ts",
            "test('keyboard action', async () => {\n"
            "  await page.keyboard.press('Escape');\n"
            "});\n",
        )
        report = corpus.build_discovery(self.repo, self.policy)
        report["version"] = 1
        with self.assertRaisesRegex(corpus.CorpusError, "unsupported"):
            corpus.validate_discovery(report, self.repo, self.policy)

        report = corpus.build_discovery(self.repo, self.policy)
        unanchored = next(
            candidate
            for candidate in report["candidates"]
            if not candidate["semanticIdentity"]["bound"]
        )
        unanchored["promotionChecks"]["independentCorroboration"] = True
        with self.assertRaisesRegex(corpus.CorpusError, "cannot corroborate"):
            corpus.validate_discovery(report, self.repo, self.policy)

        report = corpus.build_discovery(self.repo, self.policy)
        report["coverage"]["gaps"]["missingHoldout"] += 1
        with self.assertRaisesRegex(corpus.CorpusError, "coverage"):
            corpus.validate_discovery(report, self.repo, self.policy)


if __name__ == "__main__":
    unittest.main()
