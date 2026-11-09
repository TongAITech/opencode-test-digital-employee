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


if __name__ == "__main__":
    unittest.main()
