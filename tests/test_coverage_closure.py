import unittest

from rc6_runtime.coverage import (
    CaseFreezeGate,
    CoverageContractError,
    CoverageSubjectRegistry,
    DeltaDesignPlanner,
    DesignClosureEvaluator,
    OraclePolicy,
)


def subjects():
    return [
        {"subject_id": "S-L1-REQ", "kind": "REQUIREMENT_ASSERTION", "layer": "L1", "risk": "HIGH", "required": True, "evidence_refs": ["evidence://req/1"]},
        {"subject_id": "S-L2-DB", "kind": "STATE_TRANSITION", "layer": "L2", "risk": "CRITICAL", "required": True, "evidence_refs": ["evidence://db/1"]},
        {"subject_id": "S-L3-NEG", "kind": "NEGATIVE_PATH", "layer": "L3", "risk": "HIGH", "required": True, "evidence_refs": ["evidence://api/neg"]},
        {"subject_id": "S-L4-UI", "kind": "BUSINESS_RULE", "layer": "L4", "risk": "MEDIUM", "required": True, "evidence_refs": ["evidence://ui/1"]},
    ]


def case(tc_id, layer, subject_id, risk="MEDIUM", *, state=False, negative=False, oracle_types=None):
    oracle_types = oracle_types or []
    return {
        "tc_id": tc_id,
        "layer": layer,
        "status": "CANDIDATE",
        "risk": risk,
        "coverage_links": [{"subject_id": subject_id, "evidence_ref": f"evidence://coverage/{tc_id}/{subject_id}"}],
        "action_semantics": {
            "state_changing": state,
            "negative": negative,
            "authorization_sensitive": False,
        },
        "oracle": {"checks": [{"type": typ, "evidence_ref": f"evidence://oracle/{tc_id}/{typ}"} for typ in oracle_types]},
    }


class CoverageClosureTests(unittest.TestCase):
    def setUp(self):
        self.registry = CoverageSubjectRegistry(subjects())

    def complete_cases(self):
        return [
            case("TC-L1", "L1", "S-L1-REQ", "HIGH", oracle_types=["UNIT_ASSERTION", "EVIDENCE_CORRELATION"]),
            case("TC-L2", "L2", "S-L2-DB", "CRITICAL", state=True, oracle_types=["COMPONENT_STATE", "PERSISTENCE", "EVIDENCE_CORRELATION"]),
            case("TC-L3", "L3", "S-L3-NEG", "HIGH", negative=True, oracle_types=["API_RESPONSE", "BUSINESS_RULE", "NEGATIVE_SIDE_EFFECT", "EVIDENCE_CORRELATION"]),
            case("TC-L4", "L4", "S-L4-UI", "MEDIUM", oracle_types=["UI_STATE"]),
        ]

    def test_case_count_does_not_substitute_for_subject_coverage(self):
        many = [case(f"TC-{i}", "L1", "S-L1-REQ", "HIGH", oracle_types=["UNIT_ASSERTION", "EVIDENCE_CORRELATION"]) for i in range(20)]
        result = DesignClosureEvaluator().evaluate(self.registry, many)
        self.assertFalse(result.passed)
        self.assertEqual(result.metrics["case_count"], 20)
        self.assertEqual(set(result.uncovered_subject_ids), {"S-L2-DB", "S-L3-NEG", "S-L4-UI"})
        self.assertEqual(set(result.critical_high_gap_ids), {"S-L2-DB", "S-L3-NEG"})

    def test_complete_subject_and_oracle_coverage_passes(self):
        result = DesignClosureEvaluator().evaluate(self.registry, self.complete_cases())
        self.assertTrue(result.passed)
        self.assertEqual(result.metrics["semantic_coverage"], 1.0)
        self.assertEqual(result.metrics["critical_high_gap_count"], 0)
        self.assertEqual(result.metrics["oracle_gap_count"], 0)

    def test_layer_mismatched_coverage_link_does_not_count(self):
        rows = self.complete_cases()
        rows[0]["coverage_links"] = [{"subject_id": "S-L3-NEG", "evidence_ref": "evidence://wrong"}]
        result = DesignClosureEvaluator().evaluate(self.registry, rows)
        self.assertFalse(result.passed)
        self.assertIn("TC-L1:S-L3-NEG", result.metrics["invalid_coverage_links"])
        self.assertIn("S-L1-REQ", result.uncovered_subject_ids)

    def test_high_risk_case_requires_evidence_correlation_oracle(self):
        rows = self.complete_cases()
        rows[0]["oracle"]["checks"] = [{"type": "UNIT_ASSERTION", "evidence_ref": "evidence://oracle/unit"}]
        result = DesignClosureEvaluator().evaluate(self.registry, rows)
        self.assertFalse(result.passed)
        self.assertIn("TC-L1", result.oracle_gap_case_ids)

    def test_state_change_requires_persistence_oracle(self):
        rows = self.complete_cases()
        rows[1]["oracle"]["checks"] = [
            {"type": "COMPONENT_STATE", "evidence_ref": "evidence://component"},
            {"type": "EVIDENCE_CORRELATION", "evidence_ref": "evidence://correlation"},
        ]
        result = DesignClosureEvaluator().evaluate(self.registry, rows)
        self.assertFalse(result.passed)
        self.assertIn("TC-L2", result.oracle_gap_case_ids)

    def test_negative_case_requires_negative_side_effect_oracle(self):
        rows = self.complete_cases()
        rows[2]["oracle"]["checks"] = [
            {"type": "API_RESPONSE", "evidence_ref": "evidence://api"},
            {"type": "BUSINESS_RULE", "evidence_ref": "evidence://business"},
            {"type": "EVIDENCE_CORRELATION", "evidence_ref": "evidence://correlation"},
        ]
        result = DesignClosureEvaluator().evaluate(self.registry, rows)
        self.assertFalse(result.passed)
        self.assertIn("TC-L3", result.oracle_gap_case_ids)

    def test_delta_design_requests_are_layer_specific(self):
        partial = self.complete_cases()[:1]
        result = DesignClosureEvaluator().evaluate(self.registry, partial)
        requests = DeltaDesignPlanner().plan(self.registry, result)
        self.assertEqual([r.layer for r in requests], ["L2", "L3", "L4"])
        self.assertEqual(requests[0].subject_ids, ("S-L2-DB",))
        self.assertTrue(all(r.reason == "SEMANTIC_COVERAGE_GAP" for r in requests))

    def test_cases_cannot_freeze_before_closure_passes(self):
        result = DesignClosureEvaluator().evaluate(self.registry, self.complete_cases()[:2])
        with self.assertRaises(CoverageContractError) as ctx:
            CaseFreezeGate().freeze(self.complete_cases()[:2], result)
        self.assertEqual(str(ctx.exception), "DESIGN_CLOSURE_NOT_SUFFICIENT")

    def test_successful_closure_can_freeze_candidates(self):
        rows = self.complete_cases()
        result = DesignClosureEvaluator().evaluate(self.registry, rows)
        frozen = CaseFreezeGate().freeze(rows, result)
        self.assertTrue(all(x["status"] == "FROZEN" for x in frozen))


class OraclePolicyTests(unittest.TestCase):
    def test_l5_state_changing_high_risk_oracles_are_derived(self):
        row = {
            "layer": "L5",
            "risk": "HIGH",
            "action_semantics": {"state_changing": True, "negative": False, "authorization_sensitive": False},
        }
        self.assertEqual(
            OraclePolicy.required_oracles(row),
            {"CROSS_SYSTEM_CONSISTENCY", "PERSISTENCE", "EVIDENCE_CORRELATION"},
        )


if __name__ == "__main__":
    unittest.main()
