"""Adversarial A01 i18n scope test; intentionally not a W1 UI implementation test."""
from __future__ import annotations
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "dsh_workbench"))
from a01_locale_scope import errors

DOCS = ROOT / "docs" / "dsh-workbench"


class TestA01LocaleDecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads((DOCS / "WB-A01-LOCALE-SCOPE.json").read_text(encoding="utf-8"))
        cls.a01 = (DOCS / "WB-A01-ATOMIC-FEATURE-REGISTER.md").read_text(encoding="utf-8")
        cls.delta = (DOCS / "WB-C-W0-50-FEATURE-DELTA.md").read_text(encoding="utf-8")

    def reject(self, mutation, code):
        damaged = copy.deepcopy(self.spec)
        mutation(damaged)
        self.assertIn(code, errors(damaged, self.a01, self.delta))

    def test_original_fifty_and_bilingual_scope_preserved(self):
        self.assertEqual(errors(self.spec, self.a01, self.delta), [])

    def test_english_removed_would_fail_closed(self):
        self.reject(lambda s: s.update(w1_required_locales=["zh-CN"]),
                    "A01_BILINGUAL_SILENTLY_REMOVED")

    def test_w0_chinese_prototype_cannot_be_promoted_to_w1_pass(self):
        self.reject(lambda s: s.update(w1_ui_qa_state="QA_PASS"),
                    "A01_W0_PROTOTYPE_FAKE_PRODUCT_PASS")

    def test_f_acceptance_must_not_be_forged(self):
        self.reject(lambda s: s.update(decision_state="W0_DESIGN_FROZEN"),
                    "A01_DESIGN_APPROVAL_FORGED")

    def test_commercial_license_status_must_remain_blocked(self):
        self.reject(lambda s: s.update(license_release_state="APPROVED"),
                    "A01_LICENSE_OR_F_GATE_BYPASS")

    def test_skills_language_requirement_cannot_disappear(self):
        self.reject(lambda s: s["requirements"].pop(0),
                    "A01_W1_LOCALE_REQUIREMENT_DROPPED")

    def test_theme_and_full_navigation_requirement_cannot_disappear(self):
        self.reject(lambda s: s["requirements"].pop(1),
                    "A01_W1_LOCALE_REQUIREMENT_DROPPED")

    def test_missing_translation_negative_case_required(self):
        self.reject(lambda s: s["acceptance_cases"].pop(2),
                    "A01_NEGATIVE_ACCEPTANCE_COVERAGE_REMOVED")

    def test_change_to_fake_case_pass_rejected(self):
        self.reject(lambda s: s["acceptance_cases"][4].update(state="QA_PASS"),
                    "A01_LOCALE_CASE_FAKE_PASS_OR_EMPTY_ORACLE")

    def test_original_register_entry_deletion_is_detected(self):
        import re
        damaged = re.sub(r"^\| P05-03 \|.*\n", "", self.a01, count=1, flags=re.M)
        self.assertIn("A01_LOCALE_ORIGINAL_FEATURE_TRACE_MISSING:P05-03",
                      errors(self.spec, damaged, self.delta))

    def test_c_feature_delta_fake_qa_pass_is_detected(self):
        altered = self.delta.replace("| X01-01 | O |", "| X01-01 | O |", 1)
        line = next(line for line in altered.splitlines() if line.startswith("| X01-01 |"))
        self.assertIn("| NOT_RUN |", line)
        altered = altered.replace(line, line.replace("| NOT_RUN |", "| QA_PASS |"))
        self.assertIn("A01_LOCALE_REAL_PRODUCT_QA_FAKED:X01-01",
                      errors(self.spec, self.a01, altered))

    def test_en_ten_sections_coverage_cannot_be_dropped(self):
        self.reject(lambda s: s["acceptance_cases"][0].update(assertion="Localized six-page nav only without details or sections is not acceptable"),
                    "A01_TEN_SECTION_LOCALE_ORACLE_MISSING")


if __name__ == "__main__":
    unittest.main()
