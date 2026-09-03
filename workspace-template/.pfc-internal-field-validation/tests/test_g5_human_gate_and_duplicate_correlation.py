from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
RUNTIME = WORKSPACE / "ai-test" / "runtime"
sys.path.insert(0, str(RUNTIME))

from aitest_runtime.r2_6.contracts import GATE_KINDS, OUTCOMES, ROUTES
from aitest_runtime.r3_6.service import R36ApplicationService
from aitest_runtime.r4_3.service import R43ApplicationService

EXPECTED_GATE_KINDS = {"APPROVAL", "CHOICE", "ADDITIONAL_INFORMATION", "EXTERNAL_ACTION"}
EXPECTED_OUTCOMES = {"APPROVED", "REJECTED", "CHOICE_SELECTED", "INFORMATION_PROVIDED", "EXTERNAL_ACTION_COMPLETED"}
EXPECTED_ROUTES = {"NONE", "RESUME_EXECUTION", "GOAL_REVISION", "PLAN_REVISION", "BLOCK"}
DUPLICATE_DECISIONS = {"NONE", "SAME_OPEN_CANDIDATE", "SAME_CONFIRMED_LIFECYCLE", "AMBIGUOUS_REVIEW_REQUIRED"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def main() -> int:
    foundation = {
        "r26_gate_kinds_frozen": set(GATE_KINDS) == EXPECTED_GATE_KINDS,
        "r26_outcomes_frozen": set(OUTCOMES) == EXPECTED_OUTCOMES,
        "r26_routes_frozen": set(ROUTES) == EXPECTED_ROUTES,
        "r36_semantic_reuse_available": callable(getattr(R36ApplicationService, "record_semantic_reuse", None)),
        "r43_exact_handoff_available": callable(getattr(R43ApplicationService, "open_confirmed_defect_lifecycle", None)),
        "r43_fix_authority_is_separate": all(callable(getattr(R43ApplicationService, name, None)) for name in ("record_fix_link", "request_fix_detection", "record_fix_detection_assessment")),
    }

    policy_path = RUNTIME / "aitest_runtime" / "g5" / "policy.py"
    service_path = RUNTIME / "aitest_runtime" / "g5" / "service.py"
    contracts_path = RUNTIME / "aitest_runtime" / "g5" / "contracts.py"
    policy = read(policy_path)
    service = read(service_path)
    contracts = read(contracts_path)
    combined = "\n".join((policy, service, contracts))

    contract = {
        "g5_policy_source_present": bool(policy),
        "human_gate_kind_is_choice": bool(policy) and "CHOICE" in policy,
        "human_gate_policy_id_exact": bool(policy) and "g5-defect-confirmation-policy" in policy,
        "human_gate_policy_version_one": bool(policy) and ("decision_policy_version" in policy and "1" in policy),
        "allowed_outcomes_use_frozen_values": bool(policy) and "CHOICE_SELECTED" in policy and "REJECTED" in policy,
        "allowed_routes_cover_frozen_continuations": bool(policy) and all(value in policy for value in ("RESUME_EXECUTION", "PLAN_REVISION", "BLOCK", "NONE")),
        "semantic_choices_are_payload_not_r26_enums": bool(policy) and all(value in policy for value in ("CONFIRM_DEFECT", "REQUEST_MORE_EVIDENCE", "REJECT_DEFECT")),
        "continuation_must_be_allowing_before_confirm": bool(combined) and "is_allowing" in combined,
        "duplicate_decisions_exact": bool(contracts) and all(value in contracts for value in DUPLICATE_DECISIONS),
        "ambiguous_duplicate_has_deterministic_failure": bool(combined) and "G5_DUPLICATE_AMBIGUOUS" in combined,
        "same_mission_reuse_is_explicit": bool(combined) and "SAME_CONFIRMED_LIFECYCLE" in combined and "mission" in combined.lower(),
        "cross_mission_silent_merge_is_blocked": bool(combined) and ("cross" in combined.lower() and "mission" in combined.lower() and "AMBIGUOUS_REVIEW_REQUIRED" in combined),
        "r43_open_lifecycle_is_only_handoff": bool(service) and "open_confirmed_defect_lifecycle" in service,
        "g5_does_not_call_r43_fix_methods": bool(service) and all(name not in service for name in ("record_fix_link(", "request_fix_detection(", "record_fix_detection_assessment(")),
        "human_review_cannot_override_r36_truth": bool(combined) and "CONFIRMED_DEFECT" in combined and any(marker in combined for marker in ("NOT_FALSE_POSITIVE", "unresolved_contradiction", "SUFFICIENT")),
        "ec5_confirmation_policy_co_located_with_confirmation_write": bool(service) and "assess_defect_truth" in service and "g5-defect-confirmation-policy" in combined,
    }

    # Guard against accidentally inventing a custom R2.6 enum while still allowing
    # CONFIRM_DEFECT as a semantic choice carried inside G5 decision payload.
    contract["no_custom_r26_gate_or_outcome"] = bool(policy) and "gate_kind = \"CONFIRM_DEFECT\"" not in policy and "outcome = \"CONFIRM_DEFECT\"" not in policy

    fixture_ok = all(foundation.values())
    missing = [name for name, value in contract.items() if not value]
    status = "PASS" if fixture_ok and not missing else "FAIL"
    truthful_red = fixture_ok and status == "FAIL" and bool(missing)
    out = {
        "suite": "test_g5_human_gate_and_duplicate_correlation",
        "status": status,
        "passed": sum(bool(v) for v in {**foundation, **contract}.values()),
        "total": len(foundation) + len(contract),
        "fixture_ok": fixture_ok,
        "truthful_red": truthful_red,
        "red_kind": "MISSING_G5_INTEGRATION" if truthful_red else None,
        "foundation_checks": foundation,
        "contract_checks": contract,
        "missing_contract_checks": missing,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
