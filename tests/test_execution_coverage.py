import unittest

from rc6_runtime.authority import AuthorityRuntime
from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.execution_coverage import (
    DEFAULT_LAYER_COVERAGE_PROFILES,
    CoverageObservationRuntime,
    EmpiricalCoverageEvaluator,
    EmpiricalCoverageRegistry,
    ExecutionCoverageDeltaPlanner,
    ExecutionCoverageError,
)


TARGET = "TARGET-BLOAN-PF1.2.0-FAT1"


def subject(subject_id, layer, dimension, expected, risk="HIGH", required=True, cases=None):
    return {
        "subject_id": subject_id,
        "layer": layer,
        "dimension": dimension,
        "risk": risk,
        "required": required,
        "expected_refs": list(expected),
        "source_refs": [f"source://{subject_id}"],
        "existing_case_refs": list(cases or []),
        # Deliberately ignored by runtime. Self-reported coverage is not truth.
        "claimed_coverage": 1.0,
    }


class EmpiricalExecutionCoverageTests(unittest.TestCase):
    def setUp(self):
        self.authority = AuthorityRuntime(b"0123456789abcdef0123456789abcdef")
        self.broker = ToolCapabilityBroker()

    def _worker_record(self, layer, tc_id, tools, target=TARGET, case_version=1, attempt=None, status="PASS", integrity=True):
        worker = self.authority.issue_identity(f"{layer}_EXECUTE", "EXECUTION", layer, 0, f"session-{layer}")
        lease = self.authority.issue_lease(
            worker.worker_id,
            f"case:{tc_id}@{case_version}",
            ["execution_attempt", "assertion", "evidence", "coverage_observation"],
            tools,
        )
        return ExecutionRecord(
            attempt_id=attempt or f"ATT-{layer}-{tc_id}",
            tc_id=tc_id,
            case_version=case_version,
            target_id=target,
            layer=layer,
            worker_id=worker.worker_id,
            lease_id=lease.lease_id,
            status=status,
            integrity_passed=integrity,
            actual_result={"executed": True} if integrity else None,
            tool_call_refs=(f"toolcall://execution/{tc_id}",),
            evidence_refs=(f"evidence://execution/{tc_id}",),
            assertion_ref=f"assertion://{tc_id}" if integrity else None,
            assertion_passed=True if status == "PASS" and integrity else False if integrity else None,
            reason=None,
        )

    def _ready_tool(self, tool_id, worker_id, target=TARGET):
        self.broker.discover(tool_id, f"D:/tools/{tool_id}")
        self.broker.mark_executable(tool_id, f"exec://{tool_id}")
        self.broker.register(tool_id, f"runtime://{tool_id}")
        self.broker.bind_worker(tool_id, worker_id, visible=True, permitted=True)
        self.broker.record_probe(
            tool_id,
            success=True,
            tool_call_ref=f"toolcall://probe/{tool_id}/{worker_id}",
            evidence_ref=f"evidence://probe/{tool_id}/{worker_id}",
        )
        self.broker.mark_target_ready(tool_id, target, f"evidence://target/{tool_id}/{target}")

    def test_seven_layer_profiles_have_professional_dimensions(self):
        self.assertEqual(set(DEFAULT_LAYER_COVERAGE_PROFILES), {f"L{i}" for i in range(1, 8)})
        self.assertIn("changed_branch", DEFAULT_LAYER_COVERAGE_PROFILES["L1"].dimensions)
        self.assertIn("transaction", DEFAULT_LAYER_COVERAGE_PROFILES["L2"].dimensions)
        self.assertIn("error_path", DEFAULT_LAYER_COVERAGE_PROFILES["L3"].dimensions)
        self.assertIn("network", DEFAULT_LAYER_COVERAGE_PROFILES["L4"].dimensions)
        self.assertIn("system_hop", DEFAULT_LAYER_COVERAGE_PROFILES["L5"].dimensions)
        self.assertIn("latency_slo", DEFAULT_LAYER_COVERAGE_PROFILES["L6"].dimensions)
        self.assertIn("security_control", DEFAULT_LAYER_COVERAGE_PROFILES["L7"].dimensions)

    def test_claimed_100_percent_without_execution_evidence_is_not_sufficient(self):
        registry = EmpiricalCoverageRegistry([
            subject("S-L3-ROUTE", "L3", "route", ["POST:/loan"], risk="CRITICAL", cases=["TC-L3-1"])
        ])
        result = EmpiricalCoverageEvaluator().evaluate(
            registry=registry,
            observations=[],
            target_id=TARGET,
            claimed_metrics={"coverage": 1.0, "covered": 999},
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.status, "NOT_SUFFICIENT")
        self.assertEqual(result.gap_ids, ("S-L3-ROUTE",))
        self.assertEqual(result.critical_high_gap_ids, ("S-L3-ROUTE",))

    def test_real_tool_evidence_computes_coverage_from_observed_refs(self):
        registry = EmpiricalCoverageRegistry([
            subject("S-L3-ROUTE", "L3", "route", ["POST:/loan"], cases=["TC-L3-1"])
        ])
        record = self._worker_record("L3", "TC-L3-1", ["api-runtime"])
        self._ready_tool("api-runtime", record.worker_id)
        runtime = CoverageObservationRuntime(authority=self.authority, tool_broker=self.broker, registry=registry)
        observation = runtime.record(
            execution=record,
            subject_id="S-L3-ROUTE",
            tool_id="api-runtime",
            tool_call_ref="toolcall://api/1",
            evidence_ref="evidence://api/coverage/1",
            observed_refs=["POST:/loan"],
            metrics={"http_status": 200},
        )
        self.assertTrue(observation.covered)
        result = EmpiricalCoverageEvaluator().evaluate(registry=registry, observations=runtime.observations(), target_id=TARGET)
        self.assertTrue(result.passed)
        self.assertEqual(result.covered_required_count, 1)
        self.assertIn("evidence://api/coverage/1", result.evidence_refs)

    def test_partial_observed_refs_leave_explicit_high_risk_gap(self):
        registry = EmpiricalCoverageRegistry([
            subject("S-L4-NET", "L4", "network", ["GET:/a", "POST:/b"], risk="HIGH", cases=["TC-L4-1"])
        ])
        record = self._worker_record("L4", "TC-L4-1", ["browser-skill"])
        self._ready_tool("browser-skill", record.worker_id)
        runtime = CoverageObservationRuntime(authority=self.authority, tool_broker=self.broker, registry=registry)
        observation = runtime.record(
            execution=record,
            subject_id="S-L4-NET",
            tool_id="browser-skill",
            tool_call_ref="toolcall://browser/1",
            evidence_ref="evidence://browser/1",
            observed_refs=["GET:/a"],
        )
        self.assertFalse(observation.covered)
        result = EmpiricalCoverageEvaluator().evaluate(registry=registry, observations=runtime.observations(), target_id=TARGET)
        self.assertFalse(result.passed)
        self.assertEqual(result.critical_high_gap_ids, ("S-L4-NET",))
        self.assertEqual(result.layer_results[0].gaps[0].reason, "EXPECTED_RUNTIME_REF_NOT_OBSERVED")

    def test_cross_layer_evidence_cannot_satisfy_another_layer(self):
        registry = EmpiricalCoverageRegistry([
            subject("S-L3", "L3", "route", ["GET:/x"], cases=["TC-L3-1"])
        ])
        record = self._worker_record("L4", "TC-L4-1", ["browser-skill"])
        self._ready_tool("browser-skill", record.worker_id)
        runtime = CoverageObservationRuntime(authority=self.authority, tool_broker=self.broker, registry=registry)
        with self.assertRaises(ExecutionCoverageError) as ctx:
            runtime.record(
                execution=record,
                subject_id="S-L3",
                tool_id="browser-skill",
                tool_call_ref="toolcall://browser/x",
                evidence_ref="evidence://browser/x",
                observed_refs=["GET:/x"],
            )
        self.assertEqual(str(ctx.exception), "CROSS_LAYER_COVERAGE_FORBIDDEN")

    def test_wrong_tool_for_dimension_is_rejected(self):
        registry = EmpiricalCoverageRegistry([
            subject("S-L1-LINE", "L1", "changed_line", ["Foo.java:42"], cases=["TC-L1-1"])
        ])
        record = self._worker_record("L1", "TC-L1-1", ["junit", "jacoco"])
        self._ready_tool("junit", record.worker_id)
        runtime = CoverageObservationRuntime(authority=self.authority, tool_broker=self.broker, registry=registry)
        with self.assertRaises(ExecutionCoverageError) as ctx:
            runtime.record(
                execution=record,
                subject_id="S-L1-LINE",
                tool_id="junit",
                tool_call_ref="toolcall://junit/1",
                evidence_ref="evidence://junit/1",
                observed_refs=["Foo.java:42"],
            )
        self.assertEqual(str(ctx.exception), "COVERAGE_TOOL_NOT_ALLOWED_FOR_DIMENSION")

    def test_non_integrity_execution_cannot_create_coverage(self):
        registry = EmpiricalCoverageRegistry([
            subject("S-L2-DB", "L2", "db_object", ["T_LOAN"], cases=["TC-L2-1"])
        ])
        record = self._worker_record("L2", "TC-L2-1", ["database"], status="BLOCKED", integrity=False)
        runtime = CoverageObservationRuntime(authority=self.authority, tool_broker=self.broker, registry=registry)
        with self.assertRaises(ExecutionCoverageError) as ctx:
            runtime.record(
                execution=record,
                subject_id="S-L2-DB",
                tool_id="database",
                tool_call_ref="toolcall://db/1",
                evidence_ref="evidence://db/1",
                observed_refs=["T_LOAN"],
            )
        self.assertEqual(str(ctx.exception), "REAL_EXECUTION_INTEGRITY_REQUIRED_FOR_COVERAGE")

    def test_target_identity_isolation_prevents_other_environment_evidence_from_closing_gap(self):
        registry = EmpiricalCoverageRegistry([
            subject("S-L6-WORKLOAD", "L6", "workload", ["100rps-10m"], cases=["TC-L6-1"])
        ])
        other_target = "TARGET-OTHER"
        record = self._worker_record("L6", "TC-L6-1", ["k6"], target=other_target)
        self._ready_tool("k6", record.worker_id, target=other_target)
        runtime = CoverageObservationRuntime(authority=self.authority, tool_broker=self.broker, registry=registry)
        runtime.record(
            execution=record,
            subject_id="S-L6-WORKLOAD",
            tool_id="k6",
            tool_call_ref="toolcall://k6/1",
            evidence_ref="evidence://k6/1",
            observed_refs=["100rps-10m"],
        )
        result = EmpiricalCoverageEvaluator().evaluate(registry=registry, observations=runtime.observations(), target_id=TARGET)
        self.assertFalse(result.passed)
        self.assertEqual(result.gap_ids, ("S-L6-WORKLOAD",))

    def test_optional_mutation_gap_is_reported_but_does_not_block_when_policy_marks_optional(self):
        registry = EmpiricalCoverageRegistry([
            subject("S-L1-BRANCH", "L1", "changed_branch", ["Foo.java:branch:B1"], cases=["TC-L1-1"]),
            subject("S-L1-MUT", "L1", "mutation", ["FooService#approve"], risk="MEDIUM", required=False, cases=["TC-L1-1"]),
        ])
        record = self._worker_record("L1", "TC-L1-1", ["jacoco", "pit"])
        self._ready_tool("jacoco", record.worker_id)
        runtime = CoverageObservationRuntime(authority=self.authority, tool_broker=self.broker, registry=registry)
        runtime.record(
            execution=record,
            subject_id="S-L1-BRANCH",
            tool_id="jacoco",
            tool_call_ref="toolcall://jacoco/1",
            evidence_ref="evidence://jacoco/1",
            observed_refs=["Foo.java:branch:B1"],
        )
        result = EmpiricalCoverageEvaluator().evaluate(registry=registry, observations=runtime.observations(), target_id=TARGET)
        self.assertTrue(result.passed)
        l1 = result.layer_results[0]
        self.assertEqual([g.subject_id for g in l1.optional_gaps], ["S-L1-MUT"])

    def test_delta_planner_routes_existing_case_gap_to_execution_and_orphan_gap_to_design(self):
        registry = EmpiricalCoverageRegistry([
            subject("S-L3-ERR", "L3", "error_path", ["HTTP:500"], cases=["TC-L3-ERR"]),
            subject("S-L7-AUTHZ", "L7", "authz", ["role:forbidden"], cases=[]),
        ])
        result = EmpiricalCoverageEvaluator().evaluate(registry=registry, observations=[], target_id=TARGET)
        requests = ExecutionCoverageDeltaPlanner().plan(result=result, registry=registry)
        view = {(r.layer, r.action): r.subject_ids for r in requests}
        self.assertEqual(view[("L3", "DELTA_EXECUTION")], ("S-L3-ERR",))
        self.assertEqual(view[("L7", "DELTA_DESIGN")], ("S-L7-AUTHZ",))

    def test_delta_evidence_closes_gap_on_re_evaluation(self):
        registry = EmpiricalCoverageRegistry([
            subject("S-L7-CONTROL", "L7", "security_control", ["csrf:enforced"], risk="CRITICAL", cases=["TC-L7-1"])
        ])
        evaluator = EmpiricalCoverageEvaluator()
        before = evaluator.evaluate(registry=registry, observations=[], target_id=TARGET)
        self.assertFalse(before.passed)

        record = self._worker_record("L7", "TC-L7-1", ["zap"])
        self._ready_tool("zap", record.worker_id)
        runtime = CoverageObservationRuntime(authority=self.authority, tool_broker=self.broker, registry=registry)
        runtime.record(
            execution=record,
            subject_id="S-L7-CONTROL",
            tool_id="zap",
            tool_call_ref="toolcall://zap/delta",
            evidence_ref="evidence://zap/delta",
            observed_refs=["csrf:enforced"],
        )
        after = evaluator.evaluate(registry=registry, observations=runtime.observations(), target_id=TARGET)
        self.assertTrue(after.passed)
        self.assertEqual(after.critical_high_gap_ids, ())

    def test_all_seven_layers_can_close_with_layer_specific_real_evidence(self):
        specs = [
            ("L1", "changed_line", "jacoco", "A.java:10"),
            ("L2", "transaction", "database", "tx:commit"),
            ("L3", "schema", "api-runtime", "schema:LoanResponse"),
            ("L4", "control", "browser-skill", "control:submit"),
            ("L5", "system_hop", "e2e-orchestrator", "hop:cfg-center->cfg-data"),
            ("L6", "latency_slo", "k6", "slo:p95<2s"),
            ("L7", "attack_surface", "zap", "surface:/loan"),
        ]
        registry = EmpiricalCoverageRegistry([
            subject(f"S-{layer}", layer, dimension, [ref], cases=[f"TC-{layer}-1"])
            for layer, dimension, tool, ref in specs
        ])
        runtime = CoverageObservationRuntime(authority=self.authority, tool_broker=self.broker, registry=registry)
        for layer, dimension, tool, ref in specs:
            record = self._worker_record(layer, f"TC-{layer}-1", [tool])
            self._ready_tool(tool, record.worker_id)
            runtime.record(
                execution=record,
                subject_id=f"S-{layer}",
                tool_id=tool,
                tool_call_ref=f"toolcall://{tool}/{layer}",
                evidence_ref=f"evidence://{tool}/{layer}",
                observed_refs=[ref],
            )
        result = EmpiricalCoverageEvaluator().evaluate(registry=registry, observations=runtime.observations(), target_id=TARGET)
        self.assertTrue(result.passed)
        self.assertEqual(result.required_subject_count, 7)
        self.assertEqual(result.covered_required_count, 7)
        self.assertEqual([r.layer for r in result.layer_results], [f"L{i}" for i in range(1, 8)])


if __name__ == "__main__":
    unittest.main()
