"""A01 W0 scope-decision lint: W1 bilingual is required, never claimed executed.

Only validates the A01 decision and source register. It does NOT translate text,
execute UI/Host, approve legal rights, or satisfy the F design signoff.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any, List

REQUIRED_IDS = ("P05-03", "X01-01")
REQUIRED_CATEGORIES = (
    "NAVIGATION", "SKILL", "FALLBACK", "IDENTITY", "AUTHORIZATION", "DATE",
    "PREFERENCE", "THEME", "MISSING_KEY", "REVIEW", "ACCESSIBILITY",
    "SOURCE_RIGHTS",
)
NO_RELEASE_HOLDS = ("WB-F00_DESIGN_ACCEPTED", "WB-W0_DESIGN_FROZEN",
                    "WB-C01_IMPLEMENTATION_QA_PASS",
                    "WB-C02_IMPLEMENTATION_QA_PASS", "LICENSE_RELEASE_APPROVED")


def row_for(content: str, feature_id: str) -> List[str]:
    rows = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in content.splitlines()
        if line.startswith("| " + feature_id + " |")
    ]
    return rows[0] if len(rows) == 1 else []


def errors(decision: dict, a01_register: str, c_delta: str) -> List[str]:
    out: List[str] = []
    if decision.get("schema") != "dsh-workbench/a01-locale-scope/v1":
        out.append("A01_SCHEMA_MISMATCH")
    if (decision.get("decision") != "KEEP_ZH_EN_W1_REQUIRED" or
            decision.get("w1_required_locales") != ["zh-CN", "en-US"] or
            decision.get("default_locale") != "zh-CN"):
        out.append("A01_BILINGUAL_SILENTLY_REMOVED")
    if (decision.get("decision_owner") != "WB-A01_A" or
            decision.get("decision_state") != "A_SCOPE_RECORDED_F_DESIGN_REVIEW_PENDING"):
        out.append("A01_DESIGN_APPROVAL_FORGED")
    if (decision.get("w0_current") != "ZH_CN_PROTOTYPE_ONLY" or
            decision.get("w1_ui_qa_state") != "NOT_RUN" or
            decision.get("original_implementation_state") != "NOT_RUN" or
            decision.get("original_feature_count") != 50):
        out.append("A01_W0_PROTOTYPE_FAKE_PRODUCT_PASS")
    if (decision.get("license_release_state") != "BLOCKED_LICENSE" or
            decision.get("explicit_holds") != list(NO_RELEASE_HOLDS)):
        out.append("A01_LICENSE_OR_F_GATE_BYPASS")
    if decision.get("required_entrypoints") != list(REQUIRED_IDS):
        out.append("A01_LOCALE_FEATURE_IDS_DRIFT")
    specs = decision.get("requirements")
    if not isinstance(specs, list) or [x.get("feature_id") for x in specs
                                      if isinstance(x, dict)] != list(REQUIRED_IDS):
        out.append("A01_W1_LOCALE_REQUIREMENT_DROPPED")
    else:
        for spec in specs:
            if (spec.get("phase") != "W1" or spec.get("test_state") != "NOT_RUN"
                    or spec.get("owner") != "C_D"
                    or not isinstance(spec.get("success_oracle"), str)
                    or not isinstance(spec.get("negative_oracle"), str)
                    or len(spec["success_oracle"]) < 35
                    or len(spec["negative_oracle"]) < 35):
                out.append("A01_W1_LOCALE_ORACLE_INCOMPLETE")
                break
    for fid in REQUIRED_IDS:
        a = row_for(a01_register, fid)
        c = row_for(c_delta, fid)
        if (len(a) != 7 or a[1] != "O" or not re.search(r"app\.js:L\d+", a[2])
                or len(c) != 5 or c[1] != "O"):
            out.append("A01_LOCALE_ORIGINAL_FEATURE_TRACE_MISSING:" + fid)
        elif c[4] != "NOT_RUN":
            out.append("A01_LOCALE_REAL_PRODUCT_QA_FAKED:" + fid)
    # The theme handler alone is not evidence for bilingual behavior.
    # Pin both the actual original i18n functions and the settings picker.
    # Static provenance checks cannot grant a commercial redistribution right.
    provenance = decision.get("upstream_readonly_provenance") or {}
    reference = {
        "P05-03": ("public/i18n.js#L700-L722", "public/app.js#L2085-L2091"),
        "X01-01": ("public/i18n.js#L700-L722", "public/app.js#L2048-L2094"),
    }
    if (provenance.get("repository") != "naodeng/dsh-qa"
            or provenance.get("pinned_sha") != "fc5a054a48973d004580a3cc1de60da3f701150b"
            or provenance.get("license") != "PolyForm-Noncommercial-1.0.0"
            or provenance.get("copied_source") is not False):
        out.append("A01_BILINGUAL_UPSTREAM_PROVENANCE_OR_LICENSE_INVALID")
    evidence = provenance.get("evidence")
    if not isinstance(evidence, list) or len(evidence) != len(reference):
        out.append("A01_BILINGUAL_ORIGINAL_SOURCE_ANCHOR_MISSING")
    else:
        seen = set()
        for row in evidence:
            if not isinstance(row, dict):
                out.append("A01_BILINGUAL_ORIGINAL_SOURCE_ANCHOR_MISSING")
                continue
            feature = row.get("feature_id")
            if (feature not in reference or feature in seen
                    or (row.get("i18n_anchor"), row.get("ui_anchor")) != reference.get(feature)
                    or row.get("evidence_state") != "ORIGINAL_ENTRYPOINT_OBSERVED_NOT_W1_QA"):
                out.append("A01_BILINGUAL_ORIGINAL_SOURCE_ANCHOR_MISSING")
                continue
            seen.add(feature)
            a = row_for(a01_register, feature)
            if len(a) != 7 or ("i18n.js:L700-L722" not in a[2]
                    or ("app.js:L2085-L2091" if feature == "P05-03"
                        else "app.js:L2048-L2094") not in a[2]):
                out.append("A01_BILINGUAL_REGISTER_ENTRYPOINT_UNVERIFIED:" + feature)
        if seen != set(reference):
            out.append("A01_BILINGUAL_ORIGINAL_SOURCE_ANCHOR_MISSING")
    cases = decision.get("acceptance_cases")
    if (not isinstance(cases, list) or len(cases) != len(REQUIRED_CATEGORIES)
            or [x.get("category") for x in cases if isinstance(x, dict)]
            != list(REQUIRED_CATEGORIES)
            or len({x.get("id") for x in cases if isinstance(x, dict)})
            != len(REQUIRED_CATEGORIES)):
        out.append("A01_NEGATIVE_ACCEPTANCE_COVERAGE_REMOVED")
    else:
        for case in cases:
            if (case.get("phase") != "W1" or case.get("state") != "NOT_RUN"
                    or not isinstance(case.get("assertion"), str)
                    or len(case["assertion"]) < 45):
                out.append("A01_LOCALE_CASE_FAKE_PASS_OR_EMPTY_ORACLE")
                break
    # Verify six-page / ten-section coverage remains explicit, but never claim
    # that checking the text proves any real navigation or localization.
    statements = " ".join(x.get("assertion", "") for x in cases if isinstance(x, dict)) if isinstance(cases, list) else ""
    if "6 main" not in statements and "six-page" not in statements:
        out.append("A01_SIX_PAGE_LOCALE_ORACLE_MISSING")
    if "10 section" not in statements:
        out.append("A01_TEN_SECTION_LOCALE_ORACLE_MISSING")
    return out


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    decision = json.loads((root / "docs/dsh-workbench/WB-A01-LOCALE-SCOPE.json").read_text(encoding="utf-8"))
    a = (root / "docs/dsh-workbench/WB-A01-ATOMIC-FEATURE-REGISTER.md").read_text(encoding="utf-8")
    c = (root / "docs/dsh-workbench/WB-C-W0-50-FEATURE-DELTA.md").read_text(encoding="utf-8")
    issues = errors(decision, a, c)
    for issue in issues:
        print("A01_LOCALE_SCOPE_BLOCKED: " + issue)
    if issues:
        return 2
    print("A01_LOCALE_SCOPE_CONTRACT_PASS: W1 bilingual retained, "
          "W0 prototype Chinese-only, F/QA/license gates NOT MET")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
