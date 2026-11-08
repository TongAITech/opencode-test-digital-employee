"""P2 C04: professional N9 routing cannot downgrade before reproduction.

These tests check the true ReleaseBatchDriver product selector. The ordinary
AcceptedScope service cannot run after signed N9 discrepancy work appears.
They are synthetic R1 routing guards, NOT real bank reproduction evidence.
"""
import pytest
from rc7_runtime.rc72_release_driver import ReleaseBatchDriver


class ReadOnlyObservedTruth:
    def __init__(self, rows):
        self.rows = rows
        self.reads = []

    def query(self, kind, **where):
        self.reads.append((kind, dict(where)))
        return [row for row in self.rows.get(kind, [])
                if all(row.get(k) == v for k, v in where.items())]


class RecordingGate:
    def __init__(self, result):
        self.calls = []
        self.result = result

    def complete(self, *, release_batch_id):
        self.calls.append(release_batch_id)
        return dict(self.result)


BATCH = {"release_batch_id": "P2-BATCH", "mission_id": "P2-MISSION"}


def _driver(rows, *, specialist=True):
    driver = object.__new__(ReleaseBatchDriver)
    driver.truth = ReadOnlyObservedTruth(rows)
    driver.n9_pipeline = RecordingGate({"status": "PASS", "unsafe_clean_route": True})
    driver.n9_professional_pipeline = (
        RecordingGate({"status": "HOLD", "reason": "N9_POST_FIX_REVIEW_NOT_YET_COMPLETE"})
        if specialist else None)
    return driver


@pytest.mark.parametrize("rows", [
    {"rc7_task": [{"mission_id": "P2-MISSION",
                    "task_type": "N9_DISCREPANCY_QUALIFICATION", "node": "N9_DEFECT"}]},
    {"rc7_gap": [{"mission_id": "P2-MISSION", "category": "VALID_TEST_FAILURE",
                  "target_node": "N9_DEFECT"}]},
    {"rc72_n9_reproduction_authorization_request": [
        {"release_batch_id": "P2-BATCH", "request_id": "P2-AUTH-PENDING"}]},
    {"rc72_n9_professional_dsh_analysis": [
        {"release_batch_id": "P2-BATCH", "analysis_id": "P2-CANDIDATE"}]},
    {"rc72_n9_approved_reproduction_execution": [
        {"release_batch_id": "P2-BATCH", "execution_id": "P2-FRESH"}]},
    {"rc72_n9_professional_disposition_review": [
        {"release_batch_id": "P2-BATCH", "review_id": "P2-REVIEW"}]},
])
def test_professional_n9_history_requires_specialist_from_first_observed_signal(rows):
    driver = _driver(rows)
    before = repr(rows)
    out = driver._complete_gate("N9_DEFECT", BATCH)
    assert out["status"] == "HOLD"
    assert driver.n9_pipeline.calls == []
    assert driver.n9_professional_pipeline.calls == ["P2-BATCH"]
    assert repr(rows) == before


def test_missing_specialist_is_explicit_hold_never_clean_fallback():
    rows = {"rc7_task": [{"mission_id": "P2-MISSION",
                          "task_type": "N9_DISCREPANCY_QUALIFICATION"}]}
    driver = _driver(rows, specialist=False)
    assert driver._has_gate("N9_DEFECT") is True
    out = driver._complete_gate("N9_DEFECT", BATCH)
    assert out["status"] == "HOLD"
    assert out["reason"] == "N9_PROFESSIONAL_DISPOSITION_PROVIDER_REQUIRED"
    assert out["field_verified"] is False and out["bank_final"] is False
    assert driver.n9_pipeline.calls == []


def test_clean_n9_scope_still_uses_native_clearance_without_specialist():
    driver = _driver({})
    out = driver._complete_gate("N9_DEFECT", BATCH)
    assert out["status"] == "PASS"
    assert driver.n9_pipeline.calls == ["P2-BATCH"]
    assert driver.n9_professional_pipeline.calls == []


def test_n9_professional_only_has_gate_and_remains_hold():
    driver = _driver({"rc7_gap": [{"mission_id": "P2-MISSION",
                                  "category": "PRODUCT_DEFECT"}]})
    driver.n9_pipeline = None
    assert driver._has_gate("N9_DEFECT") is True
    assert driver._complete_gate("N9_DEFECT", BATCH)["status"] == "HOLD"
    assert driver.n9_professional_pipeline.calls == ["P2-BATCH"]


def test_n9_without_any_provider_cannot_claim_pass():
    driver = _driver({}, specialist=False)
    driver.n9_pipeline = None
    assert driver._has_gate("N9_DEFECT") is False
    out = driver._complete_gate("N9_DEFECT", BATCH)
    assert out["status"] == "HOLD"
    assert out["reason"] == "N9_NATIVE_GATE_PROVIDER_REQUIRED"
