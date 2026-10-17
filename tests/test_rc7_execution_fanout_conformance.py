import hashlib
import json
from pathlib import Path

import pytest

import rc7_runtime.execution_fanout_conformance as fanout
from rc6_runtime.execution import ExecutionRecord
from rc7_runtime.case_fanout_conformance import AcceptedCase, AcceptedCaseInventory
from rc7_runtime.execution_loop import ExecutionLoopResult
from rc7_runtime.models import Evaluation, EvaluationResult, Gap, GapSeverity


MISSION = "MISSION-EXEC-FANOUT"
DESIGN = "ART-DESIGN-EXEC-FANOUT"
DESIGN_HASH = "sha256:design-current"


class FakeTruth:
    def __init__(self, rows):
        self.rows = list(rows)

    def query(self, artifact_type, **filters):
        assert artifact_type == "rc7_evidence"
        result = []
        for row in self.rows:
            if all(row.get(key) == value for key, value in filters.items() if value is not None):
                result.append(dict(row))
        return result


def _inventory():
    return AcceptedCaseInventory(
        mission_id=MISSION,
        design_task_id="TASK-DESIGN",
        design_artifact_id=DESIGN,
        design_content_hash=DESIGN_HASH,
        cases=(
            AcceptedCase("TC-1", 1, "L2", "sha256:case-1"),
            AcceptedCase("TC-2", 1, "L3", "sha256:case-2"),
        ),
    )


def _record(*, tc_id="TC-1", status="PASS", integrity=True, assertion=True):
    return ExecutionRecord(
        attempt_id="ATT-" + tc_id,
        tc_id=tc_id,
        case_version=1,
        target_id="TARGET-BANK",
        layer="L2" if tc_id == "TC-1" else "L3",
        worker_id="runtime-worker",
        lease_id="runtime-lease",
        status=status,
        integrity_passed=integrity,
        actual_result={"business_code": "OK"},
        tool_call_refs=("tool://real",),
        evidence_refs=("EVD-REAL",),
        assertion_ref="ASSERT-1",
        assertion_passed=assertion,
        reason=None,
    )


def _loop(record, *, result=EvaluationResult.PASS, test_result="PASS", recovery=None, gaps=()):
    evaluation = Evaluation(
        evaluation_id="EVAL-" + record.tc_id,
        mission_id=MISSION,
        node="EXECUTION",
        artifact_refs=["ART-EXEC"],
        result=result,
        evaluator_ref="runtime-execution-gate",
        gap_refs=[gap.gap_id for gap in gaps],
        evidence_refs=["EVD-REAL"],
    )
    return ExecutionLoopResult(
        evaluation=evaluation,
        gaps=tuple(gaps),
        test_result=test_result,
        conclusive=True,
        recovery_action=recovery,
    )


def _receipt(tmp_path: Path, *, evidence_id, tc_id, case_hash, outcome, design_hash=DESIGN_HASH, created_at=1):
    payload = {
        "schema_version": fanout.SCHEMA_VERSION,
        "mission_id": MISSION,
        "design_artifact_id": DESIGN,
        "design_content_hash": design_hash,
        "case_hash": case_hash,
        "tc_id": tc_id,
        "case_version": 1,
        "layer": "L2" if tc_id == "TC-1" else "L3",
        "outcome": outcome,
        "script_receipt_id": "SCRIPT-" + tc_id,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    path = tmp_path / (evidence_id + ".json")
    path.write_bytes(raw)
    return {
        "evidence_id": evidence_id,
        "mission_id": MISSION,
        "kind": fanout.EXECUTION_TERMINAL_KIND,
        "content_ref": "file://" + str(path),
        "content_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "created_at": created_at,
    }


def _patch_inventory(monkeypatch):
    monkeypatch.setattr(fanout, "contract_enabled", lambda truth, mission_id: True)
    monkeypatch.setattr(
        fanout,
        "AcceptedCaseInventoryReader",
        lambda: type("Reader", (), {"load": lambda self, truth, mission_id: _inventory()})(),
    )
    monkeypatch.setattr(fanout, "_script_receipt", lambda *args, **kwargs: {"status": "SCRIPT_READY"})


def test_terminal_pass_requires_real_oracle_integrity():
    record = _record(status="PASS", integrity=True, assertion=True)
    assert fanout._terminal_outcome(record, _loop(record)) == "PASS"

    forged = _record(status="PASS", integrity=False, assertion=True)
    with pytest.raises(fanout.ExecutionFanoutConformanceError, match="PASS_TRUTH_INVALID"):
        fanout._terminal_outcome(forged, _loop(forged))


def test_product_defect_terminal_requires_trusted_fail_and_governed_gap():
    record = _record(status="FAIL", integrity=True, assertion=False)
    gap = Gap(
        gap_id="GAP-PRODUCT",
        mission_id=MISSION,
        source_node="EXECUTION",
        category="PRODUCT_DEFECT",
        severity=GapSeverity.HIGH,
        target_node="DEFECT",
        description="oracle mismatch",
    )
    result = _loop(record, test_result="FAIL", recovery="PRODUCT_DEFECT", gaps=(gap,))
    assert fanout._terminal_outcome(record, result) == "PRODUCT_DEFECT"

    with pytest.raises(fanout.ExecutionFanoutConformanceError, match="PRODUCT_DEFECT_TRUTH_INVALID"):
        fanout._terminal_outcome(record, _loop(record, test_result="FAIL", recovery="PRODUCT_DEFECT"))


def test_blocked_receipt_does_not_satisfy_barrier_but_retry_pass_does(tmp_path, monkeypatch):
    _patch_inventory(monkeypatch)
    rows = [
        _receipt(tmp_path, evidence_id="EVD-BLOCKED-TC1", tc_id="TC-1", case_hash="sha256:case-1", outcome="BLOCKED", created_at=1),
        _receipt(tmp_path, evidence_id="EVD-PASS-TC2", tc_id="TC-2", case_hash="sha256:case-2", outcome="PASS", created_at=1),
    ]
    first = fanout.check_execution_barrier(FakeTruth(rows), MISSION)
    assert first.status == "INCOMPLETE"
    assert first.blocked_tc_ids == ("TC-1",)
    assert first.missing_tc_ids == ("TC-1",)

    rows.append(_receipt(tmp_path, evidence_id="EVD-PASS-TC1", tc_id="TC-1", case_hash="sha256:case-1", outcome="PASS", created_at=2))
    recovered = fanout.check_execution_barrier(FakeTruth(rows), MISSION)
    assert recovered.status == "PASS"
    assert recovered.pass_ready_tc_ids == ("TC-1", "TC-2")
    assert recovered.blocked_tc_ids == ()
    assert set(recovered.receipt_ids) == {"EVD-PASS-TC1", "EVD-PASS-TC2"}


def test_receipt_from_superseded_design_never_satisfies_current_denominator(tmp_path, monkeypatch):
    _patch_inventory(monkeypatch)
    rows = [
        _receipt(tmp_path, evidence_id="EVD-OLD-TC1", tc_id="TC-1", case_hash="sha256:case-1", outcome="PASS", design_hash="sha256:old-design"),
        _receipt(tmp_path, evidence_id="EVD-PASS-TC2", tc_id="TC-2", case_hash="sha256:case-2", outcome="PASS"),
    ]
    result = fanout.check_execution_barrier(FakeTruth(rows), MISSION)
    assert result.status == "INCOMPLETE"
    assert result.missing_tc_ids == ("TC-1",)
