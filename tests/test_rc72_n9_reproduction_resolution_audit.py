"""C04 bridge: actual approved repro and native RCA/fix/impact R1 must match.

All HTTP effects here come from the existing engineering loopback subprocess.
The RC7 native fix/regression fixture emits SHA-backed formal execution files;
none of this counts as a BANK field result or N9 Gate PASS.
"""
from __future__ import annotations

import pytest

from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.defect_loop import DefectClosedLoop
from rc7_runtime.models import ContractError, Gap, GapSeverity, GapStatus
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n9_reproduction_resolution_audit import (
    N9ApprovedReproductionResolutionAudit,
)
from rc7_runtime.truth_overlay import append_entity
from test_rc72_n9_approved_reproduction_execution import (
    _approved_setup, _broker,
)
import test_rc7_defect_resolution_control as native


def _actual_reproduction(tmp_path, monkeypatch):
    truth, pipeline, server, gate, request_id, executor, bundle, prepared, url = (
        _approved_setup(tmp_path, monkeypatch))
    result = executor.execute(
        request_id=request_id, bundle=bundle, prepared=prepared,
        authority=RC72AuthorityRuntime(b"c04-a5-resolution-bridge-real-authority"),
        tool_broker=_broker(), cwd=str(tmp_path), target_base_url=url)
    assert result["reproduced"] is True and result["conclusive"] is True
    assert len(server.calls) == 2
    return truth, pipeline, server, request_id, executor, result


def _qualified_independent_defect(tmp_path, monkeypatch, truth, request_id, result):
    request = truth.query(
        "rc72_n9_reproduction_authorization_request", request_id=request_id)[0]
    monkeypatch.setattr(native, "MISSION", request["mission_id"])
    monkeypatch.setattr(native, "RELEASE", request["release_id"])
    monkeypatch.setattr(native, "ORIGINAL_TC", request["original_case_id"])
    control = ClosedLoopControlPlane(
        truth, request["release_id"], request["mission_id"])
    # The existing native controller owns the real defect lifecycle.
    native._setup(tmp_path, existing_truth=truth, existing_control=control)
    source = truth.query("rc7_gap", gap_id=native.GAP_ID)[0]
    formal_id = next(eid for eid in result["evidence_ids"]
                     if truth.query("rc7_evidence", evidence_id=eid)[0]["kind"]
                     == "RUNTIME_EXECUTION_RECORD")
    gap = Gap(
        gap_id=native.GAP_ID, mission_id=request["mission_id"],
        source_node=source["source_node"], category="PRODUCT_DEFECT",
        severity=GapSeverity.HIGH, target_node="DEFECT",
        description="independently qualified approved C04 product mismatch",
        state=GapStatus.REPAIRING,
        subject_refs=[request["original_gap_id"], result["reproduction_record_id"],
                      result["fresh_attempt_id"], request["original_case_id"]],
        evidence_refs=list(dict.fromkeys(source["evidence_refs"] + [formal_id])),
        acceptance_criteria=["real RCA and fix verification and distinct impact regression"],
    )
    append_entity(truth, gap, release_id=request["release_id"], artifact_version=2)
    defect = native.DefectResolutionControl()._defect(control, native.DEFECT_ID)
    defect.execution_attempt_ids = [
        request["original_attempt_id"], result["fresh_attempt_id"]]
    defect.evidence_refs = list(dict.fromkeys(defect.evidence_refs + [formal_id]))
    DefectClosedLoop.persist(
        truth, release_id=request["release_id"], defect=defect, artifact_version=2)
    return control, formal_id


def test_c04_real_reproduction_handoff_requires_actual_native_fix_and_impact_regression(
        tmp_path, monkeypatch):
    truth, pipeline, server, request_id, executor, reproduced = (
        _actual_reproduction(tmp_path, monkeypatch))
    try:
        control, formal_id = _qualified_independent_defect(
            tmp_path, monkeypatch, truth, request_id, reproduced)
        bridge = N9ApprovedReproductionResolutionAudit(executor)
        batch_id = reproduced["request_id"]
        request = truth.query(
            "rc72_n9_reproduction_authorization_request", request_id=request_id)[0]
        batch_id = request["release_batch_id"]
        with pytest.raises(ContractError, match="REAL_RCA_FIX_REGRESSION_REQUIRED"):
            bridge.audit(release_batch_id=batch_id, request_id=request_id,
                         defect_id=native.DEFECT_ID)
        resolution, fix_revision = native._confirm_and_detect_fix(
            tmp_path, truth, control)
        verification = native._owned_execution(
            tmp_path, control, artifact_id="ART-C04-VERIFIED-FIX",
            attempt_id="ATT-C04-FRESH-FIX-VERIFY",
            tc_id=request["original_case_id"], passed=True,
            task_type=resolution.FIX_VERIFICATION_TASK_TYPE)
        resolution.accept_fix_verification(
            control, native.DEFECT_ID,
            verification_artifact_id=verification.artifact_id)
        impact = native._owned_execution(
            tmp_path, control, artifact_id="ART-C04-IMPACT-REGRESSION",
            attempt_id="ATT-C04-IMPACT-REGRESSION",
            tc_id="TC-C04-DISTINCT-IMPACT", passed=True,
            task_type=resolution.IMPACT_REGRESSION_TASK_TYPE)
        resolution.close_after_verification(
            control, native.DEFECT_ID,
            verification_artifact_id=verification.artifact_id,
            regression_artifact_ids=[impact.artifact_id])
        before = truth.store.path.read_bytes()
        audited = bridge.audit(
            release_batch_id=batch_id, request_id=request_id,
            defect_id=native.DEFECT_ID)
        assert audited["status"] == "VERIFIED_DEFECT_CLOSED"
        assert audited["reproduction_record_id"] == reproduced["reproduction_record_id"]
        assert audited["reproduction_attempt_id"] == reproduced["fresh_attempt_id"]
        assert audited["reproduction_evidence_id"] == formal_id
        assert audited["verification_artifact_id"] == verification.artifact_id
        assert audited["regression_artifact_ids"] == [impact.artifact_id]
        assert audited["n9_gate_pass"] is False
        assert audited["field_verified"] is audited["bank_final"] is False
        assert bridge.audit(
            release_batch_id=batch_id, request_id=request_id,
            defect_id=native.DEFECT_ID) == audited
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == 2, "a read-only audit must never replay bank actions"
    finally:
        server.shutdown()
        server.server_close()


def test_c04_reproduced_failure_does_not_auto_create_or_close_a_defect(
        tmp_path, monkeypatch):
    truth, pipeline, server, request_id, executor, reproduced = (
        _actual_reproduction(tmp_path, monkeypatch))
    try:
        req = truth.query("rc72_n9_reproduction_authorization_request",
                          request_id=request_id)[0]
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="R1_NOT_UNIQUE:rc7_defect"):
            N9ApprovedReproductionResolutionAudit(executor).audit(
                release_batch_id=req["release_batch_id"],
                request_id=request_id, defect_id="UNRELATED-DEFECT")
        assert not truth.query("rc7_defect")
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == 2
    finally:
        server.shutdown()
        server.server_close()


def test_c04_rejects_unrelated_defect_provenance_before_any_rca_acceptance(
        tmp_path, monkeypatch):
    truth, pipeline, server, request_id, executor, reproduced = (
        _actual_reproduction(tmp_path, monkeypatch))
    try:
        control, formal_id = _qualified_independent_defect(
            tmp_path, monkeypatch, truth, request_id, reproduced)
        req = truth.query("rc72_n9_reproduction_authorization_request",
                          request_id=request_id)[0]
        # Rewriting the candidate's relation to a different approved attempt
        # cannot transfer this actual reproduction to another defect.
        defect = native.DefectResolutionControl()._defect(control, native.DEFECT_ID)
        defect.execution_attempt_ids = [req["original_attempt_id"],
                                        "ATT-OTHER-UNAPPROVED-REPRODUCTION"]
        DefectClosedLoop.persist(
            truth, release_id=req["release_id"],
            defect=defect, artifact_version=3)
        prior = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="INDEPENDENT_DEFECT_LINEAGE_REQUIRED"):
            N9ApprovedReproductionResolutionAudit(executor).audit(
                release_batch_id=req["release_batch_id"],
                request_id=request_id, defect_id=native.DEFECT_ID)
        assert truth.store.path.read_bytes() == prior
        assert len(server.calls) == 2
    finally:
        server.shutdown()
        server.server_close()
