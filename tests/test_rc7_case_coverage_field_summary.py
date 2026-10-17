from types import SimpleNamespace

import rc7_runtime.case_coverage_field_summary as coverage_module
from rc7_runtime.case_coverage_field_summary import CaseCoverageFieldSummaryBuilder


MISSION = "MISSION-COVERAGE-SUMMARY"


class FakeTruth:
    def __init__(self, *, unresolved=True):
        self.unresolved = unresolved

    def query(self, artifact_type, **filters):
        if artifact_type == "recovery_action":
            return [
                {
                    "release_id": "REL-COVERAGE",
                    "verified": True,
                    "prior_attempt_id": "ATT-RETRY-1",
                    "next_attempt_id": "ATT-RETRY-2",
                }
            ]
        if artifact_type == "execution_attempt":
            attempt_id = filters.get("attempt_id")
            rows = {
                "ATT-RETRY-1": {"attempt_id": "ATT-RETRY-1", "tc_id": "TC-RETRY", "status": "FAIL"},
                "ATT-RETRY-2": {"attempt_id": "ATT-RETRY-2", "tc_id": "TC-RETRY", "status": "PASS"},
            }
            return [rows[attempt_id]] if attempt_id in rows else []
        if artifact_type == "rc7_gap":
            if filters.get("mission_id") != MISSION:
                return []
            return [
                {
                    "gap_id": "GAP-PRODUCT-TC-DEFECT",
                    "mission_id": MISSION,
                    "category": "PRODUCT_DEFECT",
                    "state": "PLANNED" if self.unresolved else "RESOLVED",
                }
            ]
        return []


def _patch_complete(monkeypatch, *, unresolved=True):
    monkeypatch.setattr(coverage_module, "contract_enabled", lambda truth, mission_id: True)
    monkeypatch.setattr(
        coverage_module.AcceptedCaseInventoryReader,
        "load",
        lambda self, truth, mission_id: SimpleNamespace(
            design_artifact_id="ART-TD-COVERAGE",
            tc_ids=("TC-PASS", "TC-RETRY", "TC-DEFECT"),
        ),
    )
    monkeypatch.setattr(
        coverage_module,
        "check_script_barrier",
        lambda truth, mission_id: SimpleNamespace(
            status="PASS",
            ready_tc_ids=("TC-PASS", "TC-RETRY", "TC-DEFECT"),
            missing_tc_ids=(),
            receipt_ids=("EVD-SCRIPT-PASS", "EVD-SCRIPT-RETRY", "EVD-SCRIPT-DEFECT"),
        ),
    )
    monkeypatch.setattr(
        coverage_module,
        "check_execution_barrier",
        lambda truth, mission_id: SimpleNamespace(
            status="PASS",
            pass_ready_tc_ids=("TC-PASS", "TC-RETRY", "TC-DEFECT"),
            blocked_tc_ids=(),
            missing_tc_ids=(),
            receipt_ids=("EVD-EXEC-PASS", "EVD-EXEC-RETRY", "EVD-EXEC-DEFECT"),
        ),
    )
    payloads = {
        "EVD-EXEC-PASS": {"tc_id": "TC-PASS", "attempt_id": "ATT-PASS", "outcome": "PASS"},
        "EVD-EXEC-RETRY": {"tc_id": "TC-RETRY", "attempt_id": "ATT-RETRY-2", "outcome": "PASS"},
        "EVD-EXEC-DEFECT": {"tc_id": "TC-DEFECT", "attempt_id": "ATT-DEFECT", "outcome": "PRODUCT_DEFECT"},
    }
    monkeypatch.setattr(
        coverage_module,
        "load_execution_terminal_receipt",
        lambda truth, mission_id, receipt_id: payloads[receipt_id],
    )
    return FakeTruth(unresolved=unresolved)


def test_summary_exposes_three_case_denominator_retry_and_product_defect(monkeypatch):
    truth = _patch_complete(monkeypatch, unresolved=True)
    result = CaseCoverageFieldSummaryBuilder(truth).build(MISSION)

    assert result.status == "HOLD"
    assert result.enforced is True
    assert result.accepted_case_count == 3
    assert result.script_ready_case_count == 3
    assert result.execution_terminal_case_count == 3
    assert result.recovered_case_count == 1
    assert result.recovered_tc_ids == ("TC-RETRY",)
    assert result.product_defect_case_count == 1
    assert result.product_defect_tc_ids == ("TC-DEFECT",)
    assert result.unresolved_product_defect_count == 1
    assert result.unresolved_product_defect_gap_ids == ("GAP-PRODUCT-TC-DEFECT",)
    assert result.missing_script_tc_ids == ()
    assert result.missing_execution_tc_ids == ()
    assert result.blocking_reasons == (
        "PRODUCT_DEFECT_REVIEW_UNRESOLVED:GAP-PRODUCT-TC-DEFECT",
    )


def test_summary_passes_only_after_all_cases_terminal_and_defect_gap_resolved(monkeypatch):
    truth = _patch_complete(monkeypatch, unresolved=False)
    result = CaseCoverageFieldSummaryBuilder(truth).build(MISSION)

    assert result.status == "PASS"
    assert result.accepted_case_count == result.script_ready_case_count == result.execution_terminal_case_count == 3
    assert result.recovered_case_count == 1
    assert result.product_defect_case_count == 1
    assert result.unresolved_product_defect_count == 0
    assert result.blocking_reasons == ()


def test_summary_reports_not_enforced_without_case_fanout_contract(monkeypatch):
    monkeypatch.setattr(coverage_module, "contract_enabled", lambda truth, mission_id: False)
    result = CaseCoverageFieldSummaryBuilder(FakeTruth()).build(MISSION)

    assert result.status == "NOT_ENFORCED"
    assert result.enforced is False
    assert result.accepted_case_count == 0
    assert result.blocking_reasons == ("CASE_FANOUT_CONTRACT_REQUIRED",)


def test_summary_holds_when_script_or_execution_denominator_is_incomplete(monkeypatch):
    monkeypatch.setattr(coverage_module, "contract_enabled", lambda truth, mission_id: True)
    monkeypatch.setattr(
        coverage_module.AcceptedCaseInventoryReader,
        "load",
        lambda self, truth, mission_id: SimpleNamespace(
            design_artifact_id="ART-TD-COVERAGE",
            tc_ids=("TC-1", "TC-2", "TC-3"),
        ),
    )
    monkeypatch.setattr(
        coverage_module,
        "check_script_barrier",
        lambda truth, mission_id: SimpleNamespace(
            status="INCOMPLETE",
            ready_tc_ids=("TC-1", "TC-2"),
            missing_tc_ids=("TC-3",),
            receipt_ids=("EVD-SCRIPT-1", "EVD-SCRIPT-2"),
        ),
    )
    monkeypatch.setattr(
        coverage_module,
        "check_execution_barrier",
        lambda truth, mission_id: SimpleNamespace(
            status="INCOMPLETE",
            pass_ready_tc_ids=("TC-1",),
            blocked_tc_ids=("TC-2",),
            missing_tc_ids=("TC-2", "TC-3"),
            receipt_ids=("EVD-EXEC-1",),
        ),
    )
    monkeypatch.setattr(
        coverage_module,
        "load_execution_terminal_receipt",
        lambda truth, mission_id, receipt_id: {"tc_id": "TC-1", "attempt_id": "ATT-1", "outcome": "PASS"},
    )

    result = CaseCoverageFieldSummaryBuilder(FakeTruth(unresolved=False)).build(MISSION)
    assert result.status == "HOLD"
    assert result.accepted_case_count == 3
    assert result.script_ready_case_count == 2
    assert result.execution_terminal_case_count == 1
    assert result.blocked_execution_tc_ids == ("TC-2",)
    assert result.missing_script_tc_ids == ("TC-3",)
    assert result.missing_execution_tc_ids == ("TC-2", "TC-3")
    assert "SCRIPT_FANOUT_INCOMPLETE:TC-3" in result.blocking_reasons
    assert "EXECUTION_FANOUT_INCOMPLETE:TC-2,TC-3" in result.blocking_reasons
