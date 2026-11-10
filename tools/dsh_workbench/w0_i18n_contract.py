"""A01 bilingual W0 design gate. Never treats a prototype as product QA."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/dsh-workbench/WB-A01-I18N-DECISION.json"
REGISTER = ROOT / "docs/dsh-workbench/WB-A01-ATOMIC-FEATURE-REGISTER.md"
DELTA = ROOT / "docs/dsh-workbench/WB-C-W0-50-FEATURE-DELTA.md"

PAGES = ["P01", "P02", "P03", "P04", "P05", "P06"]
DETAILS = ["D%02d" % x for x in range(1, 11)]
IDENTITY = {
    "project_id", "batch_id", "release_date", "requirement_ids",
    "system_version_ids", "sst_ids", "mission_id", "host_session_id",
    "relation_revision", "access_scope_revision", "truth_revision",
    "nodegate_state", "approval_state",
}
FEATS = {"P05-03", "X01-01"}
PROVENANCE = {
    "public/i18n.js#L5-L8", "public/i18n.js#L700-L722",
    "public/app.js#L2048-L2094",
}
MESSAGES = {
    "navigation", "forms", "skills", "statuses", "errors",
    "human_gate", "evidence", "empty_states", "accessibility_labels",
}
FORBIDDEN = {
    "QA_PASS", "W0_DESIGN_FROZEN", "W1_IMPLEMENTATION_QA_PASS",
    "LICENSE_RELEASE_APPROVED", "BANK_PACKAGE_READY",
}


def read() -> Dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def problems(manifest: Dict[str, Any], register: str, delta: str) -> List[str]:
    """Return source/design discrepancies; a clean list is NOT a UI QA_PASS."""
    errors: List[str] = []
    if (
        manifest.get("contract_id") != "WB-A01-I18N-01"
        or manifest.get("product_decision") != "RETAIN_ZH_EN_FULL_PRODUCT_SCOPE"
    ):
        errors.append("A01_I18N_DECISION_NOT_SIGNED")
    if (
        manifest.get("design_state") != "W0_DESIGN_CONTRACT_ONLY"
        or manifest.get("w0_frozen") is not False
        or manifest.get("ui_implementation_status") != "NOT_RUN"
        or manifest.get("field_qa_status") != "NOT_RUN"
    ):
        errors.append("A01_I18N_PREMATURE_PRODUCT_PASS")
    req = manifest.get("feature_requirements") or {}
    if not isinstance(req, dict) or set(req) != FEATS or any(
        not isinstance(req.get(key), dict)
        or req[key].get("category") != "O"
        or req[key].get("product_status") != "NOT_RUN"
        for key in FEATS
    ):
        errors.append("A01_I18N_ORIGINAL_FEATURES_LOST")
    policy = manifest.get("locale_policy") or {}
    if (
        policy.get("accepted") != ["zh", "en"]
        or policy.get("default") != "zh"
        or policy.get("persist_locale_separately_from_auth_and_theme") is not True
    ):
        errors.append("A01_I18N_LOCALE_CHOICES_OR_ISOLATION_LOST")
    if (
        policy.get("missing_english") != "FALLBACK_ZH_WITH_GAP_NOTICE"
        or policy.get("invalid_input") != "REJECT_OR_DEFAULT_ZH_WITH_AUDIT"
    ):
        errors.append("A01_I18N_FALLBACK_OR_INVALID_INPUT_NOT_SAFE")
    if (
        manifest.get("all_page_ids") != PAGES
        or manifest.get("all_detail_section_ids") != DETAILS
        or not MESSAGES.issubset(set(manifest.get("visible_message_classes") or []))
    ):
        errors.append("A01_I18N_PAGE_OR_MESSAGE_COVERAGE_LOST")
    if set(manifest.get("scope_must_remain_unchanged") or []) != IDENTITY:
        errors.append("A01_I18N_BUSINESS_SCOPE_MUTATION_ALLOWED")
    if set(manifest.get("independent_presentation_controls") or []) != {
        "locale", "theme", "sidebar_collapse", "project_radar_width"
    }:
        errors.append("A01_I18N_THEME_OR_LAYOUT_COUPLED")
    source = manifest.get("upstream") or {}
    if (
        source.get("repository") != "naodeng/dsh-qa"
        or source.get("commit") != "fc5a054a48973d004580a3cc1de60da3f701150b"
        or source.get("license") != "PolyForm-Noncommercial-1.0.0"
        or not PROVENANCE.issubset(set(source.get("sources") or []))
        or manifest.get("originals_not_copied") is not True
        or manifest.get("legal_boundary") != "BLOCKED_LICENSE"
    ):
        errors.append("A01_I18N_SOURCE_PROVENANCE_OR_LICENSE_LOST")
    if not FORBIDDEN.issubset(set(manifest.get("forbidden_claims") or [])):
        errors.append("A01_I18N_FALSE_QA_OR_RELEASE_ALLOWED")
    for feature in sorted(FEATS):
        if not re.search(r"(?m)^\|\s*" + feature + r"\s*\|\s*O\s*\|", register):
            errors.append("A01_I18N_FEATURE_NOT_IN_ATOMIC_REGISTER:" + feature)
        row = next(
            (line for line in delta.splitlines() if re.match(
                r"^\|\s*" + feature + r"\s*\|", line
            )), "",
        )
        if not re.search(r"^\|\s*" + feature + r"\s*\|\s*O\s*\|", row) or not re.search(
            r"\|\s*NOT_RUN\s*\|", row
        ):
            errors.append("A01_I18N_DELTA_CLAIMS_COMPLETE_OR_MISSING:" + feature)
    if "BLOCKED_LICENSE" not in register:
        errors.append("A01_I18N_REGISTER_LICENSE_BOUNDARY_LOST")
    return errors


def main() -> int:
    failures = problems(
        read(),
        REGISTER.read_text(encoding="utf-8"),
        DELTA.read_text(encoding="utf-8"),
    )
    for code in failures:
        print("A01_I18N_CONTRACT_BLOCKED: " + code)
    if failures:
        return 2
    print("A01_I18N_W0_DESIGN_CONTRACT_PASS; PRODUCT_NOT_RUN; LICENSE_BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
