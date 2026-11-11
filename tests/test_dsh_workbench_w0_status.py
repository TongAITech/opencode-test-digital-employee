"""W0 no-fake-freeze status contracts; F must independently sign F00 before W1.

This test checks *only* header consistency and release boundary documents;
it never grants design approval or product QA.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "docs" / "dsh-workbench"
CANDIDATE_DOCS = (
    "00-PRODUCT-BASELINE.md",
    "02-BUSINESS-DOMAIN-CONTRACT.md",
    "03-UI-UX-CONTRACT.md",
    "04-DSH-HOST-INTEGRATION.md",
    "05-RC72-INTEGRATION-CONTRACT.md",
    "07-QUALITY-ACCEPTANCE.md",
)

def document_state_errors(documents):
    issues = []
    for name in CANDIDATE_DOCS:
        text = documents.get(name, "")
        first = text.splitlines()[:3]
        status = first[1] if len(first) >= 2 else ""
        if "W0_DESIGN_IN_PROGRESS" not in status or "W0_NOT_FROZEN" not in status:
            issues.append("PREMATURE_W0_FREEZE:" + name)
        if "W0 候选冻结" in status or "W0_DESIGN_FROZEN" in status:
            issues.append("FALSE_W0_DESIGN_SIGNOFF:" + name)
        if "BLOCKED_LICENSE" not in status:
            issues.append("LICENSE_BOUNDARY_MISSING:" + name)
    return issues

class TestW0NotFrozenState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = {
            path: (ROOT / path).read_text(encoding="utf-8")
            for path in CANDIDATE_DOCS
        }

    def test_all_six_contract_headers_are_truthful(self):
        self.assertEqual([], document_state_errors(self.docs))

    def test_premature_design_freeze_is_rejected(self):
        altered = dict(self.docs)
        key = CANDIDATE_DOCS[2]
        altered[key] = altered[key].replace(
            "W0_DESIGN_IN_PROGRESS / W0_NOT_FROZEN",
            "W0_DESIGN_FROZEN")
        self.assertIn("PREMATURE_W0_FREEZE:" + key,
                      document_state_errors(altered))

    def test_old_ambiguous_candidate_freeze_is_rejected(self):
        altered = dict(self.docs)
        key = CANDIDATE_DOCS[0]
        altered[key] = altered[key].replace(
            "W0_DESIGN_IN_PROGRESS / W0_NOT_FROZEN",
            "W0 候选冻结")
        self.assertIn("FALSE_W0_DESIGN_SIGNOFF:" + key,
                      document_state_errors(altered))

    def test_license_boundary_cannot_disappear(self):
        altered = dict(self.docs)
        key = CANDIDATE_DOCS[3]
        altered[key] = altered[key].replace("BLOCKED_LICENSE", "APPROVED")
        self.assertIn("LICENSE_BOUNDARY_MISSING:" + key,
                      document_state_errors(altered))

if __name__ == "__main__":
    unittest.main()
