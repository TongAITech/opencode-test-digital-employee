"""F independent negative acceptance for release dependency completeness.

Runs against A group's manifest when merged with work/dsh-wb-w0. An isolated
QA branch may not contain that candidate manifest; skip is explicit then.
Do not interpret a local skip or static DAG pass as real field QA.
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "dsh-workbench" / "W0-W1-GATE-MANIFEST.json"


def ancestry(index, node):
    seen = set()
    def walk(gid):
        if gid in seen:
            return
        seen.add(gid)
        for dep in index[gid]["depends_on"]:
            if dep in index:
                walk(dep)
    walk(node)
    return seen


class TestWorkbenchReleaseDependenciesF(unittest.TestCase):
    def setUp(self):
        if not MANIFEST.is_file():
            self.skipTest("A group's W0-W1-GATE-MANIFEST.json absent from isolated F branch")
        self.index = {
            gate["id"]: gate
            for gate in json.loads(MANIFEST.read_text(encoding="utf-8"))["gates"]
        }

    def test_w4_field_gate_requires_autonomous_closed_loop_and_offline_proof(self):
        """WB-F04 is a final QA task; 08-CONSTRUCTION-PLAN requires F03 and D04."""
        self.assertIn("WB-F04_FIELD_QA_PASS", self.index)
        before_field = ancestry(self.index, "WB-F04_FIELD_QA_PASS")
        missing = [prefix for prefix in ("WB-F03_", "WB-D04_")
                   if not any(x.startswith(prefix) for x in before_field)]
        self.assertFalse(
            missing,
            "FG16 RELEASE_GATE_BYPASS: F04_FIELD_QA_PASS lacks W3 F03 and W4 D04 "
            "predecessor gates: " + ", ".join(missing)
        )

    def test_w4_bank_release_requires_original_six_page_ten_section_regression(self):
        """W2 F02 is required before a final commercial workbench release."""
        self.assertIn("WB-W4_BANK_RELEASE_APPROVED", self.index)
        before_release = ancestry(self.index, "WB-W4_BANK_RELEASE_APPROVED")
        self.assertTrue(
            any(x.startswith("WB-F02_") for x in before_release),
            "FG16 RELEASE_GATE_BYPASS: bank release DAG does not require F02 "
            "original six-page/ten-section functional regression"
        )


if __name__ == "__main__":
    unittest.main()
