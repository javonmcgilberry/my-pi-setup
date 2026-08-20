from __future__ import annotations

import importlib.util
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("designer-code-mode.py")
SPEC = importlib.util.spec_from_file_location("designer_code_mode_tests_target", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
designer_code_mode = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(designer_code_mode)


TARGET = "https://design.webflow.com/projects/synthetic?pageId=synthetic"


class FakeRuntimeFailure(Exception):
    def __init__(self, code: str, phase: str = "runtime", retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.phase = phase
        self.retryable = retryable


class FakeRuntime:
    def __init__(self):
        self.owned = False
        self.ready = False
        self.consumer = None
        self.lease_owner = None
        self.lease_owner_id = None
        self.mode = None
        self.lease_id = None
        self.claimed_at = 2
        self.started_at = 1
        self.fail_start: FakeRuntimeFailure | None = None
        self.fail_claim: FakeRuntimeFailure | None = None
        self.fail_release_once = False
        self.replace_after_release = False
        self.start_timeout = None
        self.transient_unready_after_start = 0
        self.events = []

    def inspect_runtime(self, _config):
        self.events.append("status")
        if self.owned and self.transient_unready_after_start:
            self.transient_unready_after_start -= 1
            return {
                "status": "unhealthy" if self.owned else "stopped",
                "runtimeOwned": self.owned,
                "cdpReady": False,
                "mode": self.mode if self.owned else None,
                "consumer": self.consumer,
                "leasePresent": self.consumer is not None,
                "endpointKind": "direct_cdp",
                "host": "loopback",
                "port": 9333,
            }
        return {
            "status": "ready" if self.ready else "stopped",
            "runtimeOwned": self.owned,
            "cdpReady": self.ready,
            "mode": self.mode if self.owned else None,
            "consumer": self.consumer,
            "leaseOwner": self.lease_owner,
            "leasePresent": self.consumer is not None,
            "endpointKind": "direct_cdp",
            "host": "loopback",
            "port": 9333,
        }

    def read_json(self, path):
        if path.name == "runtime.json" and self.owned:
            return {"pid": 4242, "startedAt": self.started_at}
        if path.name == "consumer-lease.json" and self.consumer:
            return {
                "consumer": self.consumer,
                "claimedAt": self.claimed_at,
                "leaseId": self.lease_id,
                "runtimePid": 4242,
                "runtimeStartedAt": self.started_at,
                **(
                    {"owner": self.lease_owner, "ownerId": self.lease_owner_id}
                    if self.lease_owner is not None
                    else {}
                ),
            }
        return None

    def start_runtime(self, _config, _timeout, *, headless, max_runtime_seconds):
        del max_runtime_seconds
        self.events.append("start")
        self.start_timeout = _timeout
        if self.fail_start:
            raise self.fail_start
        if self.owned and self.mode != ("headless" if headless else "headed"):
            raise FakeRuntimeFailure("runtime_mode_conflict", "runtime_start", True)
        self.owned = True
        self.ready = True
        self.mode = "headless" if headless else "headed"
        return self.inspect_runtime(None)

    def claim_consumer(
        self,
        _config,
        consumer,
        *,
        exclusive=False,
        owner="direct",
        owner_id=None,
    ):
        self.events.append("claim")
        if self.fail_claim:
            raise self.fail_claim
        if self.consumer and (self.consumer != consumer or exclusive):
            raise FakeRuntimeFailure("consumer_conflict", "consumer_claim", True)
        self.consumer = consumer
        self.lease_id = "a" * 32
        self.lease_owner = owner
        self.lease_owner_id = owner_id
        return {"status": "claimed", "consumer": consumer, "leaseId": self.lease_id}

    def release_consumer(self, _config, consumer, *, lease_id=None):
        self.events.append("release")
        if self.fail_release_once:
            self.fail_release_once = False
            raise FakeRuntimeFailure(
                "release_consumer_failed", "consumer_release", True
            )
        if self.consumer and self.consumer != consumer:
            raise FakeRuntimeFailure("consumer_mismatch", "consumer_release")
        if lease_id is not None and lease_id != self.lease_id:
            raise FakeRuntimeFailure("lease_mismatch", "consumer_release")
        self.consumer = None
        self.lease_id = None
        self.lease_owner = None
        self.lease_owner_id = None
        self.owned = False
        self.ready = False
        self.mode = None
        result = self.inspect_runtime(None)
        if self.replace_after_release:
            self.owned = True
            self.ready = True
            self.mode = "headless"
            self.consumer = "agent_browser"
            self.lease_id = "b" * 32
            self.lease_owner = "code_mode"
            self.lease_owner_id = "replacement"
        return result

    def stop_runtime(self, _config):
        self.events.append("stop")
        self.consumer = None
        self.lease_id = None
        self.lease_owner = None
        self.lease_owner_id = None
        self.owned = False
        self.ready = False
        self.mode = None
        return self.inspect_runtime(None)

    def stop_if_unclaimed(self, _config, *, expected_pid, expected_started_at):
        if expected_pid != 4242 or expected_started_at != self.started_at:
            return self.inspect_runtime(None)
        if self.consumer is not None:
            return self.inspect_runtime(None)
        return self.stop_runtime(_config)


def ready_preflight(checks, _timeout):
    return {
        "classification": "prerequisites_ready",
        "ready": True,
        "checks": [
            {
                "label": check["label"],
                "kind": check["kind"],
                "ready": True,
                "expected": (
                    "tcp_listener"
                    if check["kind"] == "tcp"
                    else f"http_status_{check['status']}"
                ),
                "observed": (
                    "listener_available"
                    if check["kind"] == "tcp"
                    else f"http_status_{check['status']}"
                ),
            }
            for check in checks
        ],
    }


def failing_preflight(checks, _timeout):
    result = ready_preflight(checks, _timeout)
    result["ready"] = False
    result["classification"] = "prerequisite_unavailable"
    result["checks"][0]["ready"] = False
    result["checks"][0]["observed"] = "connection_failed"
    return result


class DesignerCodeModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = FakeRuntime()
        self.config = types.SimpleNamespace(
            root=Path(self.temp.name),
            port=9333,
            runtime_path=Path(self.temp.name) / "runtime.json",
            lease_path=Path(self.temp.name) / "consumer-lease.json",
        )

    def tearDown(self):
        self.temp.cleanup()

    def service(self, *, preflight=ready_preflight):
        return designer_code_mode.DesignerCodeMode(
            runtime=self.runtime,
            runtime_config=self.config,
            preflight_runner=preflight,
        )

    def checks(self):
        return [
            {"name": "hud", "kind": "tcp", "host": "127.0.0.1", "port": 4040},
            {
                "name": "designer_service",
                "kind": "tcp",
                "host": "127.0.0.1",
                "port": 1337,
            },
            {"name": "target_http", "kind": "http", "url": TARGET, "status": 200},
        ]

    def prepare_request(self, *, transport="native", runtime_mode=None):
        request = {
            "version": 1,
            "operation": "prepare",
            "transport": transport,
            "mode": "isolated",
            "target": TARGET,
            "surface": "body",
            "checks": self.checks(),
        }
        if runtime_mode is not None:
            request["runtimeMode"] = runtime_mode
        if transport == "cli":
            request["session"] = "synthetic"
        return request

    def verify_request(self, transaction_id, *, transport=None, **overrides):
        surface = {
            "url": TARGET,
            "title": "Webflow Designer",
            "document": "designer",
            "authenticated": True,
            "errorPage": False,
            "scope": "body",
            "scopeObserved": True,
        }
        surface.update(overrides)
        result = {
            "version": 1,
            "operation": "verify",
            "transactionId": transaction_id,
            "surface": surface,
        }
        result["transport"] = transport or "native"
        return result

    def test_help_is_small_and_parser_rejects_unknown_or_sensitive_input(self):
        request = designer_code_mode.parse_request("help")
        result = self.service().handle(request)
        self.assertEqual(
            result["operations"],
            [
                "help",
                "capabilities",
                "test_knowledge",
                "scenario_plan",
                "validate_change",
                "status",
                "reconcile",
                "prepare",
                "verify",
                "finish",
            ],
        )
        self.assertLess(len(str(result)), 2000)
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "unknown_request_field"):
            designer_code_mode.parse_request('{"version":1,"operation":"help","extra":1}')
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "unknown_request_field"):
            designer_code_mode.parse_request(
                '{"version":1,"operation":"validate_change","policyPath":"/tmp/unreviewed.json"}'
            )
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "invalid_operation"):
            designer_code_mode.parse_request('{"version":1,"operation":[] }')
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "invalid_json"):
            designer_code_mode.parse_request(
                '{"version":1,"operation":"help","operation":"status"}'
            )
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "invalid_json"):
            designer_code_mode.parse_request(
                '{"version":1,"operation":"help","limit":NaN}'
            )
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "invalid_request"):
            designer_code_mode.parse_request(
                '{"version":1,"operation":"help","id":"bad\\u0000value"}'
            )
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "sensitive_input_rejected"):
            designer_code_mode.parse_request(
                '{"version":1,"operation":"finish","token":"nope"}'
            )

    def test_status_classifies_clean_active_and_stale_transaction_states(self):
        service = self.service()
        clean = service.handle({"version": 1, "operation": "status"})
        self.assertEqual(clean["state"], "clean_stopped")
        prepared = service.handle(self.prepare_request())
        active = service.handle({"version": 1, "operation": "status"})
        self.assertEqual(active["state"], "active_transaction")
        self.runtime.stop_runtime(None)
        stale = service.handle({"version": 1, "operation": "status"})
        self.assertEqual(stale["state"], "stale_transaction")
        self.assertTrue(stale["safeToRecover"])
        reconciled = service.handle({"version": 1, "operation": "reconcile"})
        self.assertEqual(reconciled["status"], "reconciled")
        self.assertTrue(reconciled["recovered"])
        self.assertIsNone(service.store.load())
        self.assertEqual(
            service.handle({"version": 1, "operation": "status"})["state"],
            "clean_stopped",
        )
        self.assertIsNotNone(prepared["transactionId"])

    def test_test_knowledge_returns_fresh_exact_operation_lookup(self):
        index_path = Path(self.temp.name) / "index.json"
        policy_path = Path(self.temp.name) / "policy.json"
        index_path.write_text("{}")
        policy_path.write_text("{}")
        card = {
            "id": "designer.panel.pages.open",
            "capabilities": ["panel-management"],
        }
        with (
            mock.patch.object(
                designer_code_mode.test_corpus_index,
                "read_json",
                side_effect=[{"version": 1}, {"cards": [card]}],
            ),
            mock.patch.object(
                designer_code_mode.test_corpus_index,
                "validate_index",
                return_value={"valid": True, "commit": "fixture", "cardCount": 1},
            ),
        ):
            result = self.service().handle(
                {
                    "version": 1,
                    "operation": "test_knowledge",
                    "indexPath": str(index_path),
                    "repoPath": self.temp.name,
                    "policyPath": str(policy_path),
                    "operationId": "designer.panel.pages.open",
                }
            )
        self.assertEqual(result["freshness"]["valid"], True)
        self.assertEqual(result["operations"], [card])

    def test_test_knowledge_returns_compact_status_view(self):
        index_path = Path(self.temp.name) / "index.json"
        policy_path = Path(self.temp.name) / "policy.json"
        index_path.write_text("{}")
        policy_path.write_text("{}")
        card = {
            "id": "designer.panel.pages.open",
            "selectionStatus": "include",
            "capabilities": ["panel-management"],
            "scores": {"confidence": 90, "utility": 70, "novelty": 60},
            "evidence": [],
            "holdoutEvidence": [],
            "negativeEvidence": [],
        }
        index = {"cards": [card]}
        with (
            mock.patch.object(
                designer_code_mode.test_corpus_index,
                "read_json",
                side_effect=[{"version": 1}, index],
            ),
            mock.patch.object(
                designer_code_mode.test_corpus_index,
                "validate_index",
                return_value={"valid": True, "commit": "fixture", "cardCount": 1},
            ),
        ):
            result = self.service().handle(
                {
                    "version": 1,
                    "operation": "test_knowledge",
                    "indexPath": str(index_path),
                    "repoPath": self.temp.name,
                    "policyPath": str(policy_path),
                    "view": "status",
                }
            )
        self.assertEqual(result["view"], "status")
        self.assertEqual(result["counts"]["cards"], 1)
        self.assertEqual(result["portfolio"]["uncoveredCapabilities"], [])

    def test_scenario_plan_requires_dry_run_and_returns_plan(self):
        scenario_path = Path(self.temp.name) / "scenario.json"
        operation_path = Path(self.temp.name) / "operation.json"
        policy_path = Path(self.temp.name) / "policy.json"
        for path in (scenario_path, operation_path, policy_path):
            path.write_text("{}")
        with (
            mock.patch.object(
                designer_code_mode.test_scenario_eval,
                "load_json",
                side_effect=[{"version": 1}, {"id": "scenario"}, {"id": "operation"}],
            ),
            mock.patch.object(
                designer_code_mode.test_scenario_eval,
                "validate_contract",
                return_value={"executable": "npx", "argumentPrefix": [], "fixedArguments": []},
            ),
            mock.patch.object(
                designer_code_mode.test_scenario_eval,
                "build_plan",
                return_value={"status": "plan_only"},
            ),
        ):
            result = self.service().handle(
                {
                    "version": 1,
                    "operation": "scenario_plan",
                    "scenarioPath": str(scenario_path),
                    "operationPath": str(operation_path),
                    "policyPath": str(policy_path),
                    "dryRun": True,
                }
            )
        self.assertEqual(result["plan"]["status"], "plan_only")

    def test_validate_change_routes_trusted_work_without_a_model_and_gates_one_candidate(self):
        repo_path = Path(self.temp.name) / "repo"
        repo_path.mkdir()
        change_set = {
            "sourceCommit": "a" * 40,
            "digest": "b" * 64,
            "files": [{"path": "public/js/designer-flux/components/PagesPanel/PagesPanel.tsx"}],
        }
        trusted_route = {
            "status": "trusted",
            "matches": [{"runnerId": "designer-pages-panel-focused"}],
            "operations": ["designer.panel.pages.open"],
        }
        trusted_receipt = {"status": "ready", "modelProposalCount": 0}
        policy = {"changeValidation": {"runners": {}}}
        request = {
            "version": 1,
            "operation": "validate_change",
            "repoPath": str(repo_path),
        }
        with (
            mock.patch.object(designer_code_mode.validate_change, "read_json", return_value={}),
            mock.patch.object(designer_code_mode.validate_change, "validate_policy", return_value=policy),
            mock.patch.object(designer_code_mode.validate_change, "validate_change", return_value=(change_set, trusted_route, trusted_receipt)),
            mock.patch.object(designer_code_mode.validate_change, "execute_runner", return_value={"status": "passed", "modelProposalCount": 0}) as execute,
        ):
            routed = self.service().handle(request)
            self.assertEqual(routed["receipt"]["modelProposalCount"], 0)
            executed = self.service().handle({**request, "phase": "execute_trusted"})
        self.assertEqual(executed["receipt"]["status"], "passed")
        execute.assert_called_once()

        candidate = {
            "source": {"commit": "a" * 40, "changeSetDigest": "b" * 64},
            "target": {"fixture": "isolated-designer-test", "document": "main"},
            "riskClass": "reversible-ui",
            "actions": [],
            "oracle": {"kind": "semantic-fact", "fact": "panel-visible", "expected": True},
            "cleanup": ["adapter-teardown"],
            "budget": {"timeoutSeconds": 900, "maxRetries": 1, "maxActions": 8},
            "runnerId": "designer-pages-panel-focused",
            "evidenceRefs": ["policy:runner:designer-pages-panel-focused"],
        }
        context = {
            "status": "approval_required",
            "changeSet": {"sourceCommit": "a" * 40, "digest": "b" * 64},
            "nearbyContracts": [{"runnerId": "designer-pages-panel-focused"}],
        }
        unknown_route = {"status": "unknown"}
        unknown_result = {"receipt": {"status": "approval_required"}, "proposalContext": context}
        candidate_request = {**request, "phase": "submit_candidate", "candidate": candidate}
        with (
            mock.patch.object(designer_code_mode.validate_change, "read_json", return_value={}),
            mock.patch.object(designer_code_mode.validate_change, "validate_policy", return_value=policy),
            mock.patch.object(designer_code_mode.validate_change, "validate_change", return_value=(change_set, unknown_route, unknown_result)),
            mock.patch.object(designer_code_mode.validate_change, "validate_candidate_contract", return_value=candidate),
            mock.patch.object(designer_code_mode.validate_change, "candidate_digest", return_value="c" * 64),
            mock.patch.object(designer_code_mode.validate_change, "approval_digest", return_value="d" * 64),
            mock.patch.object(designer_code_mode.validate_change, "candidate_run_id", return_value="12345678-1234-1234-1234-123456789abc"),
            mock.patch.object(designer_code_mode.validate_change, "build_receipt", return_value={"status": "approval_required", "modelProposalCount": 1}),
            mock.patch.object(designer_code_mode.validate_change, "consume_host_confirmation"),
            mock.patch.object(designer_code_mode.validate_change, "execute_runner", return_value={"status": "passed", "candidate": {"state": "consumed"}}) as candidate_execute,
        ):
            service = self.service()
            routed_unknown = service.handle(request)
            self.assertEqual(routed_unknown["receipt"]["status"], "approval_required")
            self.assertEqual(routed_unknown["proposalContext"], context)
            proposed = service.handle(candidate_request)
            self.assertEqual(proposed["approval"]["approvalDigest"], "d" * 64)
            with self.assertRaisesRegex(designer_code_mode.ProtocolError, "host_confirmation_required"):
                service.handle({**candidate_request, "phase": "execute_candidate", "approvalDigest": "d" * 64})
            with self.assertRaisesRegex(designer_code_mode.ProtocolError, "approval_digest_mismatch"):
                service.handle({**candidate_request, "phase": "execute_candidate", "approvalDigest": "e" * 64, "hostConfirmation": "a" * 64})
            completed = service.handle({**candidate_request, "phase": "execute_candidate", "approvalDigest": "d" * 64, "hostConfirmation": "a" * 64})
            with self.assertRaisesRegex(designer_code_mode.ProtocolError, "candidate_already_consumed"):
                service.handle({**candidate_request, "phase": "execute_candidate", "approvalDigest": "d" * 64, "hostConfirmation": "a" * 64})
        self.assertEqual(completed["receipt"]["status"], "passed")
        candidate_execute.assert_called_once()

    def test_validate_change_rejects_a_second_candidate_for_the_same_change_set(self):
        service = self.service()
        first = {
            "source": {"commit": "a" * 40, "changeSetDigest": "b" * 64},
            "id": "first",
        }
        second = {
            "source": {"commit": "a" * 40, "changeSetDigest": "b" * 64},
            "id": "second",
        }
        with (
            mock.patch.object(
                designer_code_mode.validate_change,
                "candidate_digest",
                side_effect=lambda candidate: "c" * 64 if candidate["id"] == "first" else "d" * 64,
            ),
            mock.patch.object(designer_code_mode.validate_change, "approval_digest", return_value="e" * 64),
        ):
            service._record_candidate(first)
            with self.assertRaisesRegex(designer_code_mode.ProtocolError, "proposal_limit_reached"):
                service._record_candidate(second)

    def test_standalone_candidate_state_is_compatible_with_code_mode(self):
        service = self.service()
        candidate = {
            "source": {"commit": "a" * 40, "changeSetDigest": "b" * 64},
            "target": {"fixture": "isolated-designer-test", "document": "main"},
            "riskClass": "reversible-ui",
            "actions": [
                {
                    "id": "open-panel",
                    "op": "invoke_operation",
                    "dependsOn": [],
                    "operationId": "designer.panel.pages.open",
                }
            ],
            "oracle": {
                "kind": "semantic-fact",
                "fact": "panel-visible",
                "expected": True,
            },
            "cleanup": ["adapter-teardown"],
            "budget": {"timeoutSeconds": 900, "maxRetries": 1, "maxActions": 8},
        }
        state_path = service._validation_state_path()
        designer_code_mode.validate_change.record_candidate_proposal(
            candidate, state_path
        )
        state = service._load_validation_state()
        self.assertIsNotNone(state)
        self.assertEqual(state["state"], "proposed")
        service._claim_candidate_execution(
            candidate, designer_code_mode.validate_change.approval_digest(candidate)
        )
        service._consume_candidate_execution()
        self.assertEqual(service._load_validation_state()["state"], "consumed")

    def test_status_preserves_direct_owner_and_reconciles_dead_lease(self):
        service = self.service()
        self.runtime.owned = True
        self.runtime.ready = True
        self.runtime.mode = "headless"
        self.runtime.consumer = "agent_browser"
        self.runtime.lease_id = "a" * 32
        self.runtime.lease_owner = "direct"
        direct = service.handle({"version": 1, "operation": "status"})
        self.assertEqual(direct["state"], "active_direct_owner")
        self.assertFalse(direct["safeToRecover"])
        self.runtime.owned = False
        self.runtime.ready = False
        stale = service.handle({"version": 1, "operation": "status"})
        self.assertEqual(stale["state"], "stale_lease")
        reconciled = service.handle({"version": 1, "operation": "reconcile"})
        self.assertTrue(reconciled["recovered"])
        self.assertEqual(
            service.handle({"version": 1, "operation": "status"})["state"],
            "clean_stopped",
        )

    def test_status_defers_active_code_mode_owner_without_receipt(self):
        service = self.service()
        self.runtime.owned = True
        self.runtime.ready = True
        self.runtime.mode = "headless"
        self.runtime.consumer = "agent_browser"
        self.runtime.lease_id = "a" * 32
        self.runtime.lease_owner = "code_mode"
        self.runtime.lease_owner_id = "12345678-1234-4234-8234-123456789abc"
        result = service.handle({"version": 1, "operation": "status"})
        self.assertEqual(result["state"], "active_code_mode_owner_without_receipt")
        self.assertFalse(result["safeToRecover"])
        self.assertEqual(result["action"], "defer")

    def test_prepare_releases_claim_when_receipt_persistence_is_interrupted(self):
        service = self.service()
        failure = designer_code_mode.ProtocolError(
            "transaction_state_write_failed", "transaction", True
        )
        with mock.patch.object(service.store, "write", side_effect=failure):
            with self.assertRaisesRegex(
                designer_code_mode.ProtocolError, "transaction_state_write_failed"
            ):
                service.handle(self.prepare_request())
        self.assertFalse(self.runtime.owned)
        self.assertIsNone(self.runtime.consumer)
        self.assertIsNone(service.store.load())

    def test_prepare_reports_cleanup_failure_instead_of_hiding_it(self):
        service = self.service()
        failure = designer_code_mode.ProtocolError(
            "transaction_state_write_failed", "transaction", True
        )
        self.runtime.fail_release_once = True
        with mock.patch.object(service.store, "write", side_effect=failure):
            with self.assertRaisesRegex(
                designer_code_mode.ProtocolError, "prepare_cleanup_failed"
            ):
                service.handle(self.prepare_request())
        self.assertTrue(self.runtime.owned)
        self.assertEqual(self.runtime.consumer, "agent_browser")

    def test_capability_lookup_is_lazy_and_supports_continuation(self):
        service = self.service()
        page = service.handle(
            {
                "version": 1,
                "operation": "capabilities",
                "category": "designer",
                "limit": 1,
            }
        )
        self.assertEqual(page["count"], 1)
        self.assertGreater(page["total"], 1)
        self.assertEqual(page["nextOffset"], 1)
        self.assertEqual(
            service.handle(
                {
                    "version": 1,
                    "operation": "capabilities",
                    "id": "designer.session",
                }
            )["capabilities"][0]["id"],
            "designer.session",
        )
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "capability_selector_required"):
            service.handle({"version": 1, "operation": "capabilities"})

    def test_prepare_verify_and_finish_bind_one_native_transaction(self):
        service = self.service()
        prepared = service.handle(self.prepare_request())
        self.assertEqual(prepared["status"], "prepared")
        self.assertEqual(self.runtime.start_timeout, 30.0)
        self.assertFalse(prepared["qaLaunchAllowed"])
        self.assertEqual(prepared["actions"][0]["tool"], "agent_browser")
        self.assertEqual(prepared["actions"][0]["args"], ["connect", "9333"])
        self.assertEqual(prepared["actions"][1]["args"], ["open", TARGET])
        self.assertEqual(
            prepared["cleanup"]["order"],
            ["finish", "retire_browser_session"],
        )
        self.assertEqual(
            prepared["cleanup"]["finish"],
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            },
        )
        self.assertNotIn("close", prepared["cleanup"])
        self.assertEqual(
            prepared["cleanup"]["retireAfterFinish"]["args"], ["close"]
        )
        self.assertEqual(self.runtime.consumer, "agent_browser")
        self.assertEqual(self.runtime.lease_owner, "code_mode")
        self.assertEqual(self.runtime.lease_owner_id, prepared["transactionId"])

        verified = service.handle(self.verify_request(prepared["transactionId"]))
        self.assertEqual(verified["status"], "verified")
        self.assertTrue(verified["qaLaunchAllowed"])
        self.assertTrue(verified["readiness"]["cleanup"]["runtimeHeld"])

        finished = service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )
        self.assertTrue(finished["runtimeStopped"])
        self.assertFalse(self.runtime.owned)
        repeated = service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )
        self.assertTrue(repeated["alreadyFinished"])

    def test_prepare_waits_for_post_start_runtime_readiness_to_settle(self):
        self.runtime.transient_unready_after_start = 2
        prepared = self.service().handle(self.prepare_request())
        self.assertEqual(prepared["status"], "prepared")
        self.assertEqual(self.runtime.consumer, "agent_browser")

    def test_readiness_failure_does_not_start_or_claim_runtime(self):
        service = self.service(preflight=failing_preflight)
        result = service.handle(self.prepare_request())
        self.assertEqual(result["classification"], "readiness_blocked")
        self.assertEqual(result["blockers"], ["hud"])
        self.assertEqual(self.runtime.events, [])

    def test_authentication_required_is_a_named_fail_closed_classification(self):
        service = self.service()
        prepared = service.handle(self.prepare_request())
        result = service.handle(
            self.verify_request(
                prepared["transactionId"],
                document="login",
                authenticated=False,
            )
        )
        self.assertEqual(result["classification"], "auth_required")
        self.assertFalse(result["qaLaunchAllowed"])
        self.assertIn("designer_surface", result["readiness"]["blockers"])
        service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )

    def test_login_surface_allows_an_empty_title_and_sanitized_return_url(self):
        service = self.service()
        prepared = service.handle(self.prepare_request())
        result = service.handle(
            self.verify_request(
                prepared["transactionId"],
                url=(
                    "https://wfdev.io:8443/login?r=https%3A%2F%2Fwfdev.io%3A8443"
                    "%2Fexternal%2Fdesigner%2Fsynthetic"
                ),
                title="",
                document="login",
                authenticated=False,
                scopeObserved=False,
            )
        )
        self.assertEqual(result["classification"], "auth_required")
        service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )

    def test_live_designer_title_shape_is_accepted_on_a_designer_origin(self):
        service = self.service()
        prepared = service.handle(self.prepare_request())
        result = service.handle(
            self.verify_request(
                prepared["transactionId"],
                title="Dev: Webflow - Synthetic Site",
            )
        )
        self.assertTrue(result["qaLaunchAllowed"])
        service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )

    def test_transport_consistency_is_enforced_without_silent_fallback(self):
        service = self.service()
        prepared = service.handle(self.prepare_request())
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "transport_mismatch"):
            service.handle(
                self.verify_request(
                    prepared["transactionId"], transport="cli"
                )
            )
        self.assertEqual(self.runtime.consumer, "agent_browser")
        service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )

    def test_follow_up_operations_require_the_original_transport(self):
        service = self.service()
        prepared = service.handle(self.prepare_request())
        request = self.verify_request(prepared["transactionId"])
        del request["transport"]
        with self.assertRaisesRegex(
            designer_code_mode.ProtocolError, "transport_required"
        ):
            service.handle(request)
        service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )

    def test_verify_reprobes_services_and_rejects_a_new_runtime_generation(self):
        calls = []

        def counting_preflight(checks, timeout):
            calls.append((checks, timeout))
            return ready_preflight(checks, timeout)

        service = self.service(preflight=counting_preflight)
        prepared = service.handle(self.prepare_request())
        self.assertEqual(len(calls), 1)
        service.handle(self.verify_request(prepared["transactionId"]))
        self.assertEqual(len(calls), 2)
        self.runtime.started_at = 99
        with self.assertRaisesRegex(
            designer_code_mode.ProtocolError, "runtime_identity_mismatch"
        ):
            service.handle(self.verify_request(prepared["transactionId"]))
        self.assertEqual(len(calls), 3)
        self.runtime.started_at = 1
        service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )

    def test_prepare_rejects_a_preexisting_consumer_lease(self):
        self.runtime.consumer = "chrome_devtools_mcp"
        with self.assertRaisesRegex(
            designer_code_mode.ProtocolError, "consumer_conflict"
        ):
            self.service().handle(self.prepare_request())
        self.assertNotIn("start", self.runtime.events)

    def test_runtime_mode_conflict_is_fail_closed(self):
        self.runtime.fail_start = FakeRuntimeFailure(
            "runtime_mode_conflict", "runtime_start", True
        )
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "runtime_mode_conflict"):
            self.service().handle(self.prepare_request(runtime_mode="headed"))
        self.assertFalse(self.runtime.owned)

    def test_claim_failure_stops_only_a_runtime_started_by_this_transaction(self):
        self.runtime.fail_claim = FakeRuntimeFailure(
            "consumer_conflict", "consumer_claim", True
        )
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "consumer_conflict"):
            self.service().handle(self.prepare_request())
        self.assertIn("stop", self.runtime.events)
        self.assertFalse(self.runtime.owned)

    def test_browser_operation_failure_can_finish_without_verification(self):
        service = self.service()
        prepared = service.handle(self.prepare_request())
        result = service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )
        self.assertEqual(result["classification"], "finished")
        self.assertTrue(result["runtimeStopped"])

    def test_finish_converges_after_runtime_stops_before_lease_release(self):
        service = self.service()
        prepared = service.handle(self.prepare_request())
        self.runtime.owned = False
        self.runtime.ready = False
        self.assertEqual(
            service.handle({"version": 1, "operation": "status"})["state"],
            "stale_transaction_lease",
        )
        finished = service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )
        self.assertEqual(finished["classification"], "finished")
        self.assertIsNone(self.runtime.consumer)
        self.assertIsNone(service.store.load())

    def test_reconcile_converges_after_runtime_stops_before_lease_release(self):
        service = self.service()
        service.handle(self.prepare_request())
        self.runtime.owned = False
        self.runtime.ready = False
        reconciled = service.handle({"version": 1, "operation": "reconcile"})
        self.assertEqual(reconciled["status"], "reconciled")
        self.assertTrue(reconciled["recovered"])
        self.assertIsNone(self.runtime.consumer)
        self.assertIsNone(service.store.load())

    def test_finish_preserves_state_when_release_fails_once(self):
        service = self.service()
        prepared = service.handle(self.prepare_request())
        self.runtime.fail_release_once = True
        with self.assertRaisesRegex(
            designer_code_mode.ProtocolError, "release_consumer_failed"
        ):
            service.handle(
                {
                    "version": 1,
                    "operation": "finish",
                    "transactionId": prepared["transactionId"],
                    "transport": "native",
                }
            )
        self.assertIsNotNone(service.store.load())
        finished = service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )
        self.assertEqual(finished["classification"], "finished")

    def test_finish_rechecks_cleanup_before_removing_transaction_state(self):
        service = self.service()
        prepared = service.handle(self.prepare_request())
        self.runtime.replace_after_release = True
        result = service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )
        self.assertEqual(result["classification"], "cleanup_failed")
        self.assertTrue(self.runtime.owned)
        self.runtime.replace_after_release = False
        self.runtime.consumer = None
        self.runtime.lease_id = None
        self.runtime.owned = False
        self.runtime.ready = False
        self.runtime.mode = None
        finished = service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )
        self.assertEqual(finished["classification"], "finished")

    def test_sensitive_target_and_surface_scope_are_rejected(self):
        request = self.prepare_request()
        request["target"] = TARGET + "&token=secret"
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "unsafe_target"):
            self.service().handle(request)

        service = self.service()
        prepared = service.handle(self.prepare_request())
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "surface_scope_mismatch"):
            service.handle(
                self.verify_request(prepared["transactionId"], scope="main")
            )
        service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "native",
            }
        )

    def test_cli_plan_requires_a_named_session_and_keeps_cli_actions(self):
        service = self.service()
        prepared = service.handle(self.prepare_request(transport="cli"))
        self.assertEqual(prepared["actions"][0]["command"], "agent-browser")
        self.assertEqual(prepared["actions"][0]["args"][1], "synthetic")
        self.assertEqual(
            prepared["actions"][0]["args"][2:], ["connect", "9333"]
        )
        self.assertEqual(
            prepared["cleanup"]["retireAfterFinish"]["args"],
            ["--session", "synthetic", "close"],
        )
        service.handle(
            {
                "version": 1,
                "operation": "finish",
                "transactionId": prepared["transactionId"],
                "transport": "cli",
            }
        )

    def test_invalid_timeout_and_stale_state_fail_closed(self):
        request = self.prepare_request()
        request["timeoutSeconds"] = 31
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "invalid_timeout"):
            self.service().handle(request)

        store = designer_code_mode.TransactionStore(Path(self.temp.name))
        store.path.write_text("not json")
        with self.assertRaisesRegex(designer_code_mode.ProtocolError, "transaction_state_invalid"):
            self.service().handle(self.prepare_request())


if __name__ == "__main__":
    unittest.main()
