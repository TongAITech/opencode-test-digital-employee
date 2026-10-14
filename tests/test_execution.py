import unittest

from rc6_runtime.authority import AuthorityRuntime
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.execution import (
    DEFAULT_EXECUTION_PROFILES,
    ExecutionContractError,
    ExecutionProfileRegistry,
    ExecutionRuntime,
)
from rc6_runtime.preparation import PreparedAttempt


TARGET = "TARGET-BLOAN-PF1.2.0-FAT1"


def frozen_case(layer="L3", version=2):
    return {
        "tc_id": f"TC-{layer}-001",
        "case_version": version,
        "layer": layer,
        "status": "FROZEN",
        "oracle": {"checks": [{"type": "BUSINESS", "expected": "OK"}]},
    }


def prepared(layer="L3", version=2, target=TARGET):
    return PreparedAttempt(
        status="PREPARED",
        attempt_id=f"ATT-{layer}-001",
        tc_id=f"TC-{layer}-001",
        case_version=version,
        target_id=target,
        precondition_evidence=("evidence://pre/1",),
        initial_state_bindings={"state": {"id": "S1"}},
        input_data_bindings={"input": {"value": 1}},
        binding_evidence=("evidence://binding/1",),
        cleanup_policy={"mode": "NONE"},
        oracle_snapshot={"checks": [{"type": "BUSINESS", "expected": "OK"}]},
    )


def oracle_pass(snapshot, actual, context):
    return {
        "passed": actual.get("business") == "OK",
        "assertion_ref": f"assertion://{context['attempt_id']}",
        "evidence_refs": [f"evidence://assertion/{context['attempt_id']}"],
        "details": {"expected": "OK", "actual": actual.get("business")},
    }


class ExecutionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.authority = AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
        self.broker = ToolCapabilityBroker()

    def _ready_tool(self, tool, worker_id, target=TARGET):
        self.broker.discover(tool, f"D:/tools/{tool}")
        self.broker.mark_executable(tool, f"exec://{tool}")
        self.broker.register(tool, f"runtime://{tool}")
        self.broker.bind_worker(tool, worker_id, visible=True, permitted=True)
        self.broker.record_probe(tool, success=True, tool_call_ref=f"toolcall://probe/{tool}", evidence_ref=f"evidence://probe/{tool}")
        self.broker.mark_target_ready(tool, target, f"evidence://target/{tool}")

    def _worker_and_lease(self, layer, tools=None, role=None):
        profile = DEFAULT_EXECUTION_PROFILES[layer]
        worker = self.authority.issue_identity(
            role=role or profile.role,
            phase="EXECUTION",
            layer=layer,
            generation=0,
            session_id=f"session-{layer}",
        )
        lease = self.authority.issue_lease(
            worker.worker_id,
            scope_ref=f"case:TC-{layer}-001@2",
            allowed_artifact_types=["execution_attempt", "assertion", "evidence", "coverage_observation"],
            allowed_tools=list(tools or profile.required_tools),
        )
        return worker, lease

    def _action(self, layer, status="EXECUTED", business="OK", omit_tool=None, mutate=False):
        profile = DEFAULT_EXECUTION_PROFILES[layer]

        def run(case, prepared_attempt, execution_profile):
            if mutate:
                case["status"] = "MUTATED"
                prepared_attempt.input_data_bindings["input"]["value"] = 999
            calls = []
            for tool in profile.required_tools:
                if tool == omit_tool:
                    continue
                calls.append({
                    "tool_id": tool,
                    "call_ref": f"toolcall://{tool}/{prepared_attempt.attempt_id}",
                    "evidence_ref": f"evidence://{tool}/{prepared_attempt.attempt_id}",
                })
            if status != "EXECUTED":
                return {"status": status, "actual_result": None, "tool_calls": calls, "evidence_refs": [], "reason": "not executed"}
            return {
                "status": "EXECUTED",
                "actual_result": {"business": business, "layer": layer},
                "tool_calls": calls,
                "evidence_refs": [f"evidence://actual/{prepared_attempt.attempt_id}"],
            }

        return run

    def test_seven_independent_execution_profiles_exist(self):
        registry = ExecutionProfileRegistry()
        profiles = registry.all()
        self.assertEqual([p.layer for p in profiles], [f"L{i}" for i in range(1, 8)])
        self.assertEqual([p.role for p in profiles], [f"L{i}_EXECUTE" for i in range(1, 8)])
        self.assertEqual(len({p.role for p in profiles}), 7)

    def test_each_layer_can_execute_only_with_its_own_role_tools_and_real_evidence(self):
        for layer in [f"L{i}" for i in range(1, 8)]:
            with self.subTest(layer=layer):
                worker, lease = self._worker_and_lease(layer)
                for tool in DEFAULT_EXECUTION_PROFILES[layer].required_tools:
                    self._ready_tool(tool, worker.worker_id)
                runtime = ExecutionRuntime(authority=self.authority, tool_broker=self.broker, oracle_evaluator=oracle_pass)
                record = runtime.execute(
                    case=frozen_case(layer),
                    prepared=prepared(layer),
                    worker_id=worker.worker_id,
                    lease_id=lease.lease_id,
                    real_action=self._action(layer),
                )
                self.assertEqual(record.status, "PASS")
                self.assertTrue(record.integrity_passed)
                self.assertTrue(record.actual_result)
                self.assertTrue(record.tool_call_refs)
                self.assertTrue(record.evidence_refs)
                self.assertTrue(record.assertion_passed)

    def test_wrong_role_cannot_execute_case(self):
        layer = "L3"
        worker = self.authority.issue_identity("L2_EXECUTE", "EXECUTION", "L2", 0, "s")
        lease = self.authority.issue_lease(
            worker.worker_id,
            scope_ref="case:TC-L3-001@2",
            allowed_artifact_types=["execution_attempt", "assertion", "evidence"],
            allowed_tools=["api-runtime"],
        )
        self._ready_tool("api-runtime", worker.worker_id)
        runtime = ExecutionRuntime(authority=self.authority, tool_broker=self.broker, oracle_evaluator=oracle_pass)
        with self.assertRaises(ExecutionContractError) as ctx:
            runtime.execute(case=frozen_case(layer), prepared=prepared(layer), worker_id=worker.worker_id, lease_id=lease.lease_id, real_action=self._action(layer))
        self.assertEqual(str(ctx.exception), "EXECUTION_WORKER_ROLE_MISMATCH")

    def test_mixed_layer_case_is_rejected(self):
        case = frozen_case("L3")
        case["layer"] = "L2|L3"
        worker, lease = self._worker_and_lease("L3")
        runtime = ExecutionRuntime(authority=self.authority, tool_broker=self.broker, oracle_evaluator=oracle_pass)
        with self.assertRaises(ExecutionContractError) as ctx:
            runtime.execute(case=case, prepared=prepared("L3"), worker_id=worker.worker_id, lease_id=lease.lease_id, real_action=self._action("L3"))
        self.assertEqual(str(ctx.exception), "SINGLE_VALID_LAYER_REQUIRED")

    def test_case_version_mismatch_blocks_execution(self):
        worker, lease = self._worker_and_lease("L3")
        runtime = ExecutionRuntime(authority=self.authority, tool_broker=self.broker, oracle_evaluator=oracle_pass)
        with self.assertRaises(ExecutionContractError) as ctx:
            runtime.execute(case=frozen_case("L3", version=3), prepared=prepared("L3", version=2), worker_id=worker.worker_id, lease_id=lease.lease_id, real_action=self._action("L3"))
        self.assertEqual(str(ctx.exception), "PREPARED_ATTEMPT_CASE_MISMATCH")

    def test_unready_tool_blocks_before_real_action(self):
        worker, lease = self._worker_and_lease("L4")
        called = []

        def should_not_run(case, prepared_attempt, profile):
            called.append(True)
            return {}

        runtime = ExecutionRuntime(authority=self.authority, tool_broker=self.broker, oracle_evaluator=oracle_pass)
        with self.assertRaises(ExecutionContractError) as ctx:
            runtime.execute(case=frozen_case("L4"), prepared=prepared("L4"), worker_id=worker.worker_id, lease_id=lease.lease_id, real_action=should_not_run)
        self.assertIn("EXECUTION_TOOL_ADMISSION_BLOCKED", str(ctx.exception))
        self.assertEqual(called, [])

    def test_missing_required_real_tool_call_cannot_pass(self):
        layer = "L1"
        worker, lease = self._worker_and_lease(layer)
        for tool in DEFAULT_EXECUTION_PROFILES[layer].required_tools:
            self._ready_tool(tool, worker.worker_id)
        runtime = ExecutionRuntime(authority=self.authority, tool_broker=self.broker, oracle_evaluator=oracle_pass)
        missing = DEFAULT_EXECUTION_PROFILES[layer].required_tools[0]
        record = runtime.execute(case=frozen_case(layer), prepared=prepared(layer), worker_id=worker.worker_id, lease_id=lease.lease_id, real_action=self._action(layer, omit_tool=missing))
        self.assertEqual(record.status, "FAIL")
        self.assertFalse(record.integrity_passed)
        self.assertIn("REQUIRED_REAL_TOOL_CALL_MISSING", record.reason)

    def test_blocked_skipped_and_not_run_never_become_pass(self):
        for status in ("BLOCKED", "SKIPPED", "NOT_RUN"):
            with self.subTest(status=status):
                layer = "L3"
                authority = AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
                broker = ToolCapabilityBroker()
                worker = authority.issue_identity("L3_EXECUTE", "EXECUTION", "L3", 0, "s")
                lease = authority.issue_lease(worker.worker_id, "case:TC-L3-001@2", ["execution_attempt", "assertion", "evidence"], ["api-runtime"])
                broker.discover("api-runtime", "x")
                broker.mark_executable("api-runtime", "e")
                broker.register("api-runtime", "r")
                broker.bind_worker("api-runtime", worker.worker_id, visible=True, permitted=True)
                broker.record_probe("api-runtime", success=True, tool_call_ref="p", evidence_ref="pe")
                broker.mark_target_ready("api-runtime", TARGET, "te")
                runtime = ExecutionRuntime(authority=authority, tool_broker=broker, oracle_evaluator=oracle_pass)
                record = runtime.execute(case=frozen_case(layer), prepared=prepared(layer), worker_id=worker.worker_id, lease_id=lease.lease_id, real_action=self._action(layer, status=status))
                self.assertEqual(record.status, status)
                self.assertFalse(record.integrity_passed)
                self.assertIsNone(record.assertion_passed)

    def test_oracle_failure_is_fail_not_retry_to_green(self):
        layer = "L3"
        worker, lease = self._worker_and_lease(layer)
        self._ready_tool("api-runtime", worker.worker_id)
        runtime = ExecutionRuntime(authority=self.authority, tool_broker=self.broker, oracle_evaluator=oracle_pass)
        record = runtime.execute(case=frozen_case(layer), prepared=prepared(layer), worker_id=worker.worker_id, lease_id=lease.lease_id, real_action=self._action(layer, business="WRONG"))
        self.assertEqual(record.status, "FAIL")
        self.assertTrue(record.integrity_passed)
        self.assertFalse(record.assertion_passed)
        self.assertEqual(record.reason, "ORACLE_ASSERTION_FAILED")

    def test_executor_mutation_of_copies_cannot_change_frozen_case_or_binding(self):
        layer = "L3"
        case = frozen_case(layer)
        prep = prepared(layer)
        worker, lease = self._worker_and_lease(layer)
        self._ready_tool("api-runtime", worker.worker_id)
        runtime = ExecutionRuntime(authority=self.authority, tool_broker=self.broker, oracle_evaluator=oracle_pass)
        record = runtime.execute(case=case, prepared=prep, worker_id=worker.worker_id, lease_id=lease.lease_id, real_action=self._action(layer, mutate=True))
        self.assertEqual(record.status, "PASS")
        self.assertEqual(case["status"], "FROZEN")
        self.assertEqual(prep.input_data_bindings["input"]["value"], 1)

    def test_execution_worker_cannot_mutate_case_artifact(self):
        layer = "L3"
        worker, lease = self._worker_and_lease(layer)
        with self.assertRaises(Exception):
            self.authority.authorize_artifact(worker.worker_id, lease.lease_id, "case_candidate_l3")


if __name__ == "__main__":
    unittest.main()
