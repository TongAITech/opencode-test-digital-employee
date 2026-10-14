import unittest

from rc6_runtime.authority import AuthorityRuntime
from rc6_runtime.design import DesignContextBuilder, DesignRuntimeError, DesignTaskPlanner, LayerApplicabilityRouter


def condition(signals=None):
    signals = signals or {
        "code_change": True,
        "db_or_component_impact": True,
        "api_impact": True,
        "ui_impact": True,
        "cross_system_impact": False,
        "performance_risk": False,
        "security_risk": False,
    }
    return {
        "id": "COND-322-01",
        "signals": signals,
        "signal_evidence": {
            k: ([f"evidence://signal/{k}"] if v else []) for k, v in signals.items()
        },
    }


def candidate(task):
    return {
        "tc_id": f"TC-{task.layer}-001",
        "case_version": 1,
        "release_id": "BLOAN-PF1.2.0",
        "requirement_id": "STBB19-322",
        "sst_id": "STB913-14130",
        "condition_id": task.condition_id,
        "layer": task.layer,
        "objective": f"professional {task.layer} case",
        "preconditions": ["target ready"],
        "test_data": {"id": "D1"},
        "steps": ["execute layer-specific action"],
        "expected": "layer-specific expected outcome",
        "oracle": {"type": "layer", "assert": "expected"},
        "evidence_requirements": ["actual_result", "tool_call_ref"],
        "status": "CANDIDATE",
        "worker_id": task.worker_id,
        "lease_id": task.lease_id,
    }


class LayerRoutingTests(unittest.TestCase):
    def test_router_always_returns_seven_explicit_decisions(self):
        decisions = LayerApplicabilityRouter().route(condition())
        self.assertEqual([d.layer for d in decisions], [f"L{i}" for i in range(1, 8)])
        self.assertEqual(len(decisions), 7)

    def test_l2_l3_l4_are_separate_tasks_not_combined_worker(self):
        authority = AuthorityRuntime(b"0123456789abcdef-rc6")
        decisions = LayerApplicabilityRouter().route(condition())
        tasks = DesignTaskPlanner(authority).plan("COND-322-01", decisions)
        self.assertEqual([t.layer for t in tasks], ["L1", "L2", "L3", "L4"])
        self.assertNotIn("L2|L3|L4", [t.layer for t in tasks])
        self.assertEqual([t.role for t in tasks], ["L1_DESIGN", "L2_DESIGN", "L3_DESIGN", "L4_DESIGN"])
        self.assertEqual(len({t.worker_id for t in tasks}), 4)

    def test_applicable_layer_requires_evidence(self):
        c = condition()
        c["signal_evidence"]["api_impact"] = []
        with self.assertRaises(DesignRuntimeError) as ctx:
            LayerApplicabilityRouter().route(c)
        self.assertIn("APPLICABLE_LAYER_EVIDENCE_MISSING:L3", str(ctx.exception))


class ContextTests(unittest.TestCase):
    def test_design_context_is_reference_only(self):
        ctx = DesignContextBuilder().build(
            condition_ref="artifact://condition/1",
            requirement_analysis_ref="artifact://req/1",
            code_analysis_ref="artifact://code/1",
            code_impact_refs=["artifact://impact/1"],
            risk_refs=["artifact://risk/1"],
        )
        self.assertEqual(ctx["condition_ref"], "artifact://condition/1")
        self.assertNotIn("raw_diff", ctx)

    def test_raw_diff_or_chat_payload_is_forbidden(self):
        with self.assertRaises(DesignRuntimeError):
            DesignContextBuilder().validate_external_payload({"raw_diff": "100KB"})
        with self.assertRaises(DesignRuntimeError):
            DesignContextBuilder().validate_external_payload({"chat_history": ["..."]})


class DesignTaskTests(unittest.TestCase):
    def setUp(self):
        self.authority = AuthorityRuntime(b"0123456789abcdef-rc6")
        self.planner = DesignTaskPlanner(self.authority)
        self.tasks = self.planner.plan("COND-322-01", LayerApplicabilityRouter().route(condition()))

    def test_each_task_has_layer_specific_artifact_lease(self):
        for task in self.tasks:
            self.assertEqual(task.artifact_type, f"case_candidate_{task.layer.lower()}")
            self.assertEqual(task.role, f"{task.layer}_DESIGN")

    def test_wrong_layer_candidate_is_rejected(self):
        task = self.tasks[2]
        c = candidate(task)
        c["layer"] = "L2"
        with self.assertRaises(DesignRuntimeError) as ctx:
            self.planner.validate_candidate(c, task)
        self.assertEqual(str(ctx.exception), "CASE_LAYER_TASK_MISMATCH")

    def test_wrong_worker_provenance_is_rejected(self):
        task = self.tasks[0]
        c = candidate(task)
        c["worker_id"] = "coordinator"
        with self.assertRaises(DesignRuntimeError) as ctx:
            self.planner.validate_candidate(c, task)
        self.assertEqual(str(ctx.exception), "CASE_PROVENANCE_MISMATCH")

    def test_valid_candidate_is_accepted_only_as_candidate(self):
        task = self.tasks[1]
        canonical = self.planner.validate_candidate(candidate(task), task)
        self.assertEqual(canonical["layer"], "L2")
        self.assertEqual(canonical["status"], "CANDIDATE")

    def test_context_overflow_rotates_same_role_and_layer_only(self):
        task = self.tasks[2]
        rotated = self.planner.rotate_after_context_overflow(task, "successor-session")
        self.assertEqual(rotated.role, task.role)
        self.assertEqual(rotated.layer, task.layer)
        self.assertEqual(rotated.condition_id, task.condition_id)
        self.assertEqual(rotated.generation, task.generation + 1)
        self.assertNotEqual(rotated.worker_id, task.worker_id)


if __name__ == "__main__":
    unittest.main()
