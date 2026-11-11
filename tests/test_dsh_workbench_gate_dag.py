"""Negative-first checks that WB-FG15 circular dependency stays eliminated."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "dsh_workbench"))
from w0_dependency_gate import GateViolation, validate_gate_graph

MANIFEST = ROOT / "docs" / "dsh-workbench" / "W0-W1-GATE-MANIFEST.json"


def data():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def by_id(d, gid):
    return next(g for g in d["gates"] if g["id"] == gid)


class TestW0W1GateDAG(unittest.TestCase):
    def assert_gate_error(self, expected, d):
        with self.assertRaises(GateViolation) as ctx:
            validate_gate_graph(d)
        self.assertEqual(str(ctx.exception), expected)

    def test_canonical_dag_is_acyclic_and_complete(self):
        order = validate_gate_graph(data())
        self.assertEqual(len(order), len(data()["gates"]))
        self.assertLess(order.index("WB-A03_CONTRACT_SIGNED"), order.index("WB-B01_IMPLEMENTATION_QA_PASS"))
        self.assertLess(order.index("WB-A02_LICENSE_RELEASE_APPROVED"), order.index("WB-W4_BANK_RELEASE_APPROVED"))

    def test_finding_fg15_cross_phase_circular_dependency(self):
        d = data()
        by_id(d, "WB-A03_CONTRACT_SIGNED")["depends_on"].append("WB-B01_IMPLEMENTATION_QA_PASS")
        self.assert_gate_error("PHASE_BACK_EDGE", d)

    def test_no_w1_implementation_as_w0_design_evidence(self):
        d = data()
        by_id(d, "WB-A03_CONTRACT_SIGNED")["depends_on"].append("WB-F01_INTEGRATION_QA_PASS")
        self.assert_gate_error("PHASE_BACK_EDGE", d)

    def test_reject_unknown_requirement(self):
        d = data()
        by_id(d, "WB-B01_IMPLEMENTATION_QA_PASS")["depends_on"].append("UNDEFINED")
        self.assert_gate_error("UNKNOWN_DEPENDENCY", d)

    def test_reject_repeated_gate(self):
        d = data()
        d["gates"].append(copy.deepcopy(d["gates"][0]))
        self.assert_gate_error("INVALID_GATE", d)

    def test_reject_same_phase_cycle(self):
        d = data()
        by_id(d, "WB-B01_IMPLEMENTATION_QA_PASS")["depends_on"].append("WB-B02_IMPLEMENTATION_QA_PASS")
        by_id(d, "WB-B02_IMPLEMENTATION_QA_PASS")["depends_on"].append("WB-B01_IMPLEMENTATION_QA_PASS")
        self.assert_gate_error("GATE_CYCLE", d)

    def test_refuse_releasing_without_license(self):
        d = data()
        by_id(d, "WB-W4_BANK_RELEASE_APPROVED")["depends_on"].remove("WB-A02_LICENSE_RELEASE_APPROVED")
        self.assert_gate_error("RELEASE_LICENSE_OR_FIELD_GATE_MISSING", d)

    def test_refuse_release_without_field_evidence(self):
        d = data()
        by_id(d, "WB-W4_BANK_RELEASE_APPROVED")["depends_on"].remove("WB-F04_FIELD_QA_PASS")
        self.assert_gate_error("RELEASE_LICENSE_OR_FIELD_GATE_MISSING", d)

    def test_w1_requires_design_signature(self):
        d = data()
        by_id(d, "WB-B01_IMPLEMENTATION_QA_PASS")["depends_on"].remove("WB-A03_CONTRACT_SIGNED")
        self.assert_gate_error("DESIGN_SIGNOFF_NOT_PREREQUISITE", d)

    def test_f02_f03_d04_and_original_pages_are_release_predecessors(self):
        d = data()
        self.assertIn("WB-F02_FUNCTIONAL_QA_PASS", [g["id"] for g in d["gates"]])
        self.assertIn("WB-F03_AUTONOMOUS_QA_PASS",
                      by_id(d, "WB-F04_FIELD_QA_PASS")["depends_on"])
        self.assertIn("WB-D04_OFFLINE_QUALIFICATION_PASS",
                      by_id(d, "WB-F04_FIELD_QA_PASS")["depends_on"])
        self.assertIn("WB-F02_FUNCTIONAL_QA_PASS",
                      by_id(d, "WB-W4_BANK_RELEASE_APPROVED")["depends_on"])
        self.assertEqual(len(validate_gate_graph(d)), len(d["gates"]))

    def test_fg16_remove_f02_gate_even_when_field_and_license_remain(self):
        d = data()
        d["gates"] = [g for g in d["gates"] if g["id"] != "WB-F02_FUNCTIONAL_QA_PASS"]
        self.assert_gate_error("UNKNOWN_DEPENDENCY", d)

    def test_fg16_duplicated_release_f02_edge_is_not_required(self):
        # F02 is still transitively required through A04.
        d = data()
        by_id(d, "WB-W4_BANK_RELEASE_APPROVED")["depends_on"].remove("WB-F02_FUNCTIONAL_QA_PASS")
        self.assertEqual(len(validate_gate_graph(d)), len(d["gates"]))

    def test_fg16_bypass_both_f02_release_paths(self):
        # Keep F04 and LICENSE but disconnect F02 and A04 entirely.
        d = data()
        release = by_id(d, "WB-W4_BANK_RELEASE_APPROVED")
        release["depends_on"].remove("WB-F02_FUNCTIONAL_QA_PASS")
        release["depends_on"].remove("WB-A04_FINAL_INTEGRATION_ACCEPTED")
        self.assert_gate_error("RELEASE_PREDECESSOR_CLOSURE_INCOMPLETE", d)

    def test_fg16_drop_f03_from_field_qa(self):
        d = data()
        by_id(d, "WB-F04_FIELD_QA_PASS")["depends_on"].remove("WB-F03_AUTONOMOUS_QA_PASS")
        self.assert_gate_error("RELEASE_PREDECESSOR_MISSING", d)

    def test_fg16_drop_d04_from_field_qa(self):
        d = data()
        by_id(d, "WB-F04_FIELD_QA_PASS")["depends_on"].remove("WB-D04_OFFLINE_QUALIFICATION_PASS")
        self.assert_gate_error("RELEASE_PREDECESSOR_MISSING", d)

    def test_fg16_remove_original_functional_qa_gate(self):
        d = data()
        by_id(d, "WB-A04_FINAL_INTEGRATION_ACCEPTED")["depends_on"].remove("WB-F02_FUNCTIONAL_QA_PASS")
        self.assert_gate_error("RELEASE_PREDECESSOR_MISSING", d)

    def test_fg16_remove_autonomous_qa_gate_entirely(self):
        d = data()
        d["gates"] = [g for g in d["gates"] if g["id"] != "WB-F03_AUTONOMOUS_QA_PASS"]
        self.assert_gate_error("UNKNOWN_DEPENDENCY", d)

    def test_fg16_cannot_skip_any_mandatory_w2_subchain(self):
        d = data()
        by_id(d, "WB-F02_FUNCTIONAL_QA_PASS")["depends_on"].remove("WB-B08_IMPLEMENTATION_QA_PASS")
        self.assert_gate_error("RELEASE_PREDECESSOR_MISSING", d)

    def test_fg16_optional_replay_is_not_mandatory_to_release(self):
        d = data()
        self.assertIn("WB-E07_OPTIONAL_REPLAY_QA_PASS", [g["id"] for g in d["gates"]])
        self.assertEqual(len(validate_gate_graph(d)), len(d["gates"]))


if __name__ == "__main__":
    unittest.main()
