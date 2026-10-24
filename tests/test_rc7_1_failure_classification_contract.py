from __future__ import annotations

from rc6_runtime.diagnosis import FailureContext
from rc7_runtime.execution_diagnosis import ExecutionDiagnosisCoordinator


def _context(reason: str) -> FailureContext:
    return FailureContext(
        attempt_id="ATT-1",
        tc_id="TC-1",
        case_version=1,
        target_id="TARGET-1",
        layer="L3",
        execution_status="FAIL",
        preparation_verified=True,
        real_action_executed=False,
        assertion_failed=False,
        execution_evidence_refs=("EVD-1",),
        case_oracle_verified=True,
        executable_spec_verified=True,
        script_validated=True,
        data_verified=True,
        exception_type=reason,
    )


def test_missing_parent_authoritative_business_action_is_script_repair_not_unknown() -> None:
    for reason in (
        "ACTUAL_RESULT_REQUIRED",
        "REQUIRED_REAL_TOOL_CALL_MISSING:api-runtime",
        "CURRENT_EXECUTION_EVIDENCE_REQUIRED",
        "ORACLE_ASSERTION_REQUIRED",
    ):
        result = ExecutionDiagnosisCoordinator._default_classifier(_context(reason), {})
        assert result["failure_class"] == "SCRIPT"
        assert result["rationale"] == "EXECUTION_CONTRACT_NOT_REALIZED"
