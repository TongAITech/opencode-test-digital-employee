"""Adversarial A01 bilingual scope contract tests (not C01/C02 implementation QA)."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "dsh_workbench"))
from w0_i18n_contract import DELTA, REGISTER, problems, read


class TestA01BilingualDesign(unittest.TestCase):
    def setUp(self):
        self.manifest = read()
        self.register = REGISTER.read_text(encoding="utf-8")
        self.delta = DELTA.read_text(encoding="utf-8")

    def rejects(self, code, change):
        source = copy.deepcopy(self.manifest)
        change(source)
        self.assertIn(code, problems(source, self.register, self.delta))

    def test_original_zh_en_target_is_retained_but_not_claimed_as_product_pass(self):
        self.assertEqual(problems(self.manifest, self.register, self.delta), [])
        self.assertEqual(set(self.manifest["feature_requirements"]), {"P05-03", "X01-01"})
        self.assertEqual(self.manifest["ui_implementation_status"], "NOT_RUN")

    def test_english_cannot_be_silently_removed(self):
        self.rejects("A01_I18N_LOCALE_CHOICES_OR_ISOLATION_LOST",
                     lambda p: p["locale_policy"].update(accepted=["zh"]))

    def test_default_language_and_auth_theme_separation_must_remain(self):
        self.rejects("A01_I18N_LOCALE_CHOICES_OR_ISOLATION_LOST",
                     lambda p: p["locale_policy"].update(default="en"))
        self.rejects("A01_I18N_LOCALE_CHOICES_OR_ISOLATION_LOST",
                     lambda p: p["locale_policy"].update(
                         persist_locale_separately_from_auth_and_theme=False))

    def test_missing_english_must_report_translation_gap(self):
        self.rejects("A01_I18N_FALLBACK_OR_INVALID_INPUT_NOT_SAFE",
                     lambda p: p["locale_policy"].update(missing_english="SILENT_RAW_KEY"))
        self.rejects("A01_I18N_FALLBACK_OR_INVALID_INPUT_NOT_SAFE",
                     lambda p: p["locale_policy"].update(invalid_input="TRUST_UNVALIDATED"))

    def test_language_toggle_cannot_mutate_release_batch_or_sst_identity(self):
        self.rejects("A01_I18N_BUSINESS_SCOPE_MUTATION_ALLOWED",
                     lambda p: p["scope_must_remain_unchanged"].remove("batch_id"))
        self.rejects("A01_I18N_BUSINESS_SCOPE_MUTATION_ALLOWED",
                     lambda p: p["scope_must_remain_unchanged"].remove("sst_ids"))

    def test_r1_nodegate_human_gate_and_session_identity_survive_toggle(self):
        for key in ("truth_revision", "nodegate_state", "approval_state", "host_session_id"):
            with self.subTest(key=key):
                self.rejects("A01_I18N_BUSINESS_SCOPE_MUTATION_ALLOWED",
                             lambda p: p["scope_must_remain_unchanged"].remove(key))

    def test_six_pages_ten_sections_and_error_text_must_all_be_in_scope(self):
        self.rejects("A01_I18N_PAGE_OR_MESSAGE_COVERAGE_LOST",
                     lambda p: p["all_page_ids"].pop())
        self.rejects("A01_I18N_PAGE_OR_MESSAGE_COVERAGE_LOST",
                     lambda p: p["all_detail_section_ids"].pop())
        self.rejects("A01_I18N_PAGE_OR_MESSAGE_COVERAGE_LOST",
                     lambda p: p["visible_message_classes"].remove("errors"))

    def test_theme_and_layout_cannot_be_conflated_with_locale(self):
        self.rejects("A01_I18N_THEME_OR_LAYOUT_COUPLED",
                     lambda p: p["independent_presentation_controls"].remove("theme"))

    def test_original_source_provenance_and_polyform_cannot_be_erased(self):
        self.rejects("A01_I18N_SOURCE_PROVENANCE_OR_LICENSE_LOST",
                     lambda p: p["upstream"].update(license="MIT"))
        self.rejects("A01_I18N_SOURCE_PROVENANCE_OR_LICENSE_LOST",
                     lambda p: p["upstream"]["sources"].remove("public/i18n.js#L700-L722"))

    def test_design_green_is_never_claimed_as_ui_field_or_bank_release_pass(self):
        self.rejects("A01_I18N_PREMATURE_PRODUCT_PASS",
                     lambda p: p.update(ui_implementation_status="QA_PASS"))
        self.rejects("A01_I18N_FALSE_QA_OR_RELEASE_ALLOWED",
                     lambda p: p["forbidden_claims"].remove("BANK_PACKAGE_READY"))

    def test_both_registered_features_must_remain_not_run_in_c_delta(self):
        bad_delta = self.delta.replace(
            "| P05-03 | O |", "| P05-03 | N |", 1
        )
        self.assertIn(
            "A01_I18N_DELTA_CLAIMS_COMPLETE_OR_MISSING:P05-03",
            problems(self.manifest, self.register, bad_delta),
        )
        bad_delta = self.delta.replace(
            "| X01-01 | O |", "| X01-01 | N |", 1
        )
        self.assertIn(
            "A01_I18N_DELTA_CLAIMS_COMPLETE_OR_MISSING:X01-01",
            problems(self.manifest, self.register, bad_delta),
        )

    def test_unknown_language_or_fake_decision_is_rejected(self):
        self.rejects("A01_I18N_DECISION_NOT_SIGNED",
                     lambda p: p.update(product_decision="CHINESE_ONLY"))
        self.rejects("A01_I18N_LOCALE_CHOICES_OR_ISOLATION_LOST",
                     lambda p: p["locale_policy"].update(accepted=["zh", "en", "unknown"]))


if __name__ == "__main__":
    unittest.main()
