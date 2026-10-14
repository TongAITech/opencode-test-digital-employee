import unittest

from rc6_runtime.intelligence import CodeSufficiencyEvaluator, RequirementSufficiencyEvaluator


def review(subject, analyzer="worker-a", reviewer="worker-r", decision="PASS", gaps=None):
    return {
        "review_id": f"REV-{subject}",
        "subject_analysis_id": subject,
        "analyzer_worker_id": analyzer,
        "reviewer_worker_id": reviewer,
        "decision": decision,
        "gap_ids": gaps or [],
        "evidence_refs": [f"evidence://review/{subject}"],
    }


def requirement_artifact():
    return {
        "analysis_id": "REQA-1",
        "release_id": "BLOAN-PF1.2.0",
        "requirement_id": "STBB19-320",
        "analyzer_worker_id": "worker-a",
        "source_assertions": [
            {"id": "SRC-1", "text": "rule one", "source_ref": "sst://1#1"},
            {"id": "SRC-2", "text": "rule two", "source_ref": "sst://1#2"},
        ],
        "atomic_statements": [
            {"id": "A-1", "text": "atomic one", "source_ref": "sst://1#1", "testable": True},
            {"id": "A-2", "text": "atomic two", "source_ref": "sst://1#2", "testable": True},
        ],
        "trace_links": [
            {"source_id": "SRC-1", "atomic_id": "A-1", "evidence_ref": "evidence://trace/1"},
            {"source_id": "SRC-2", "atomic_id": "A-2", "evidence_ref": "evidence://trace/2"},
        ],
        "business_rules": ["BR-1"],
        "roles": ["role-1"],
        "preconditions": ["pre-1"],
        "normal_paths": ["normal-1"],
        "negative_paths": ["negative-1"],
        "boundaries": ["boundary-1"],
        "states": ["state-1"],
        "data_constraints": ["data-1"],
        "dependencies": ["dep-1"],
        "side_effects": ["effect-1"],
        "evidence_refs": ["evidence://req/1"],
        "traceability_coverage": 0.01,
        "testability_pass": False,
        "critical_gap_count": 999,
    }


def code_artifact():
    return {
        "analysis_id": "CODEA-1",
        "release_id": "BLOAN-PF1.2.0",
        "analyzer_worker_id": "worker-code-a",
        "requirement_ids": ["STBB19-320", "STBB19-322"],
        "source_revisions": {
            "cfg-data": "a" * 40,
            "cfg-center": "b" * 40,
        },
        "changed_files": ["cfg-data/src/A.java"],
        "changed_symbols": [
            {"id": "SYM-A", "file": "cfg-data/src/A.java", "symbol": "A.save"},
            {"id": "SYM-B", "file": "cfg-data/src/A.java", "symbol": "A.query"},
        ],
        "symbol_explanations": [
            {"symbol_id": "SYM-A", "impact_node_ids": ["N1"], "evidence_refs": ["evidence://cg/A"]},
            {"symbol_id": "SYM-B", "impact_node_ids": ["N2"], "evidence_refs": ["evidence://cg/B"]},
        ],
        "reverse_requirement_mappings": [
            {"requirement_id": "STBB19-320", "symbol_id": "SYM-A", "evidence_ref": "evidence://map/1"},
            {"requirement_id": "STBB19-322", "symbol_id": "SYM-B", "evidence_ref": "evidence://map/2"},
        ],
        "tool_calls": [
            {"tool_id": "codegraph", "target_id": "TARGET-1", "call_ref": "toolcall://cg/1", "evidence_ref": "evidence://cg/1"},
            {"tool_id": "git", "target_id": "TARGET-1", "call_ref": "toolcall://git/1", "evidence_ref": "evidence://git/1"},
        ],
        "codegraph_required": True,
        "evidence_refs": ["evidence://code/1"],
        "coverage": 1.0,
        "critical_gap_count": 0,
    }


class RequirementGateTests(unittest.TestCase):
    def test_gate_ignores_self_reported_metrics_and_recomputes(self):
        art = requirement_artifact()
        result = RequirementSufficiencyEvaluator().evaluate(art, review("REQA-1"))
        self.assertTrue(result.passed)
        self.assertEqual(result.metrics["traceability"], 1.0)
        self.assertEqual(result.metrics["orphan_source_ids"], [])

    def test_missing_trace_link_fails_even_if_artifact_claims_coverage_one(self):
        art = requirement_artifact()
        art["traceability_coverage"] = 1.0
        art["trace_links"] = art["trace_links"][:1]
        result = RequirementSufficiencyEvaluator().evaluate(art, review("REQA-1"))
        self.assertFalse(result.passed)
        self.assertIn("REQ_TRACEABILITY_GAP", result.reasons)
        self.assertIn("REQ_UNSUPPORTED_ASSERTION", result.reasons)

    def test_untestable_atomic_fails(self):
        art = requirement_artifact()
        art["atomic_statements"][1]["testable"] = False
        result = RequirementSufficiencyEvaluator().evaluate(art, review("REQA-1"))
        self.assertFalse(result.passed)
        self.assertIn("REQ_TESTABILITY_GAP", result.reasons)

    def test_reviewer_must_be_independent(self):
        art = requirement_artifact()
        result = RequirementSufficiencyEvaluator().evaluate(art, review("REQA-1", reviewer="worker-a"))
        self.assertFalse(result.passed)
        self.assertIn("REVIEW_INDEPENDENCE_FAIL", result.reasons)


class CodeGateTests(unittest.TestCase):
    def test_complete_code_evidence_passes(self):
        art = code_artifact()
        result = CodeSufficiencyEvaluator().evaluate(
            art,
            review("CODEA-1", analyzer="worker-code-a", reviewer="worker-code-r"),
            target_id="TARGET-1",
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.metrics["codegraph_evidence_calls"], 1)
        self.assertEqual(result.metrics["unmapped_requirement_ids"], [])

    def test_codegraph_missing_real_tool_evidence_fails(self):
        art = code_artifact()
        art["tool_calls"] = [x for x in art["tool_calls"] if x["tool_id"] != "codegraph"]
        result = CodeSufficiencyEvaluator().evaluate(
            art,
            review("CODEA-1", analyzer="worker-code-a", reviewer="worker-code-r"),
            target_id="TARGET-1",
        )
        self.assertFalse(result.passed)
        self.assertIn("CODEGRAPH_REAL_TOOL_EVIDENCE_MISSING", result.reasons)

    def test_codegraph_wrong_target_does_not_count(self):
        art = code_artifact()
        art["tool_calls"][0]["target_id"] = "TARGET-other"
        result = CodeSufficiencyEvaluator().evaluate(
            art,
            review("CODEA-1", analyzer="worker-code-a", reviewer="worker-code-r"),
            target_id="TARGET-1",
        )
        self.assertFalse(result.passed)
        self.assertIn("CODEGRAPH_REAL_TOOL_EVIDENCE_MISSING", result.reasons)

    def test_unexplained_changed_symbol_fails(self):
        art = code_artifact()
        art["symbol_explanations"] = art["symbol_explanations"][:1]
        result = CodeSufficiencyEvaluator().evaluate(
            art,
            review("CODEA-1", analyzer="worker-code-a", reviewer="worker-code-r"),
            target_id="TARGET-1",
        )
        self.assertFalse(result.passed)
        self.assertIn("CODE_UNEXPLAINED_CHANGE", result.reasons)

    def test_reverse_requirement_gap_fails(self):
        art = code_artifact()
        art["reverse_requirement_mappings"] = art["reverse_requirement_mappings"][:1]
        result = CodeSufficiencyEvaluator().evaluate(
            art,
            review("CODEA-1", analyzer="worker-code-a", reviewer="worker-code-r"),
            target_id="TARGET-1",
        )
        self.assertFalse(result.passed)
        self.assertIn("CODE_REVERSE_MAPPING_GAP", result.reasons)


if __name__ == "__main__":
    unittest.main()
