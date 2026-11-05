"""C04: actual approved HTTP reproduction -> reviewed professional N9 Gate.

Uses real subprocess + parent HTTP proxy from the production C04 fixture, real
signed DSH raw output from N8, and native RCA/fix/impact R1 files. The bank
review verifier here is a CONTRACT fixture, not bank Field evidence.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_n8_product_recovery import NativeN8ProductRecoveryService
from rc7_runtime.rc72_n9_professional_disposition_gate import (
    N9ProfessionalDispositionGateService,
)
from rc7_runtime.rc72_n9_reproduction_resolution_audit import (
    N9ApprovedReproductionResolutionAudit,
)
from rc7_runtime.rc72_n7_execution_admission import _hash
from test_rc72_n9_reproduction_resolution_audit import (
    _actual_reproduction, _qualified_independent_defect,
)
import test_rc7_defect_resolution_control as native


class ContractProfessionalVerifier:
    verifier_kind = "BANK_N9_PROFESSIONAL_REVIEW"
    def __init__(self):
        self.rows = {}
    def resolve(self, ref):
        return dict(self.rows[ref])


def _closed(tmp_path, monkeypatch):
    truth, pipeline, server, request_id, executor, reproduced = (
        _actual_reproduction(tmp_path, monkeypatch))
    control, formal = _qualified_independent_defect(
        tmp_path, monkeypatch, truth, request_id, reproduced)
    request = truth.query("rc72_n9_reproduction_authorization_request",
                          request_id=request_id)[0]
    resolution, revision = native._confirm_and_detect_fix(
        tmp_path, truth, control)
    verify = native._owned_execution(
        tmp_path, control, artifact_id="ART-N9-FORMAL-FIX",
        attempt_id="ATT-N9-FRESH-FIX",
        tc_id=request["original_case_id"], passed=True,
        task_type=resolution.FIX_VERIFICATION_TASK_TYPE)
    resolution.accept_fix_verification(
        control, native.DEFECT_ID, verification_artifact_id=verify.artifact_id)
    impact = native._owned_execution(
        tmp_path, control, artifact_id="ART-N9-FORMAL-IMPACT",
        attempt_id="ATT-N9-FRESH-IMPACT",
        tc_id="TC-N9-FORMAL-DISTINCT-IMPACT", passed=True,
        task_type=resolution.IMPACT_REGRESSION_TASK_TYPE)
    resolution.close_after_verification(
        control, native.DEFECT_ID,
        verification_artifact_id=verify.artifact_id,
        regression_artifact_ids=[impact.artifact_id])
    n8 = NativeN8ProductRecoveryService(
        pipeline, professional_dsh=executor.gate.requests.analyst,
        reproduction_human_gate=executor.gate,
        reproduction_executor=executor)
    verifier = ContractProfessionalVerifier()
    gate = N9ProfessionalDispositionGateService(n8, review_verifier=verifier)
    proof = N9ApprovedReproductionResolutionAudit(executor).audit(
        release_batch_id=request["release_batch_id"],
        request_id=request_id, defect_id=native.DEFECT_ID)
    closure = truth.query(
        "rc7_evaluation", evaluation_id=proof["closure_evaluation_id"])[0]
    now = int(time.time())
    att = dict(
        actor_type="HUMAN",
        decision="APPROVED_POST_FIX_PROFESSIONAL_REVIEW",
        attestation_ref="bank-review://n9/independent-closing-review",
        reviewer_ref="bank-employee://independent-n9-quality-reviewer",
        release_batch_id=request["release_batch_id"],
        request_id=request_id,
        defect_id=native.DEFECT_ID,
        original_gap_id=proof["original_gap_id"],
        reproduction_record_id=proof["reproduction_record_id"],
        closure_evaluation_id=proof["closure_evaluation_id"],
        proof_sha256=_hash(proof),
        rationale="Examined original N8 failure, new signed N9 reproduction, RCA, revised source, fresh fix and independent impact",
        evidence_refs=list(dict.fromkeys(
            [proof["reproduction_evidence_id"]] + closure["evidence_refs"])),
        issued_at=now, expires_at=now + 300)
    verifier.rows[att["attestation_ref"]] = att
    return truth, pipeline, server, request, gate, att, proof


def test_c04_real_causal_chain_requires_separate_professional_review_and_original_gap_adjudication(
        tmp_path, monkeypatch):
    truth, pipeline, server, request, gate, att, proof = _closed(
        tmp_path, monkeypatch)
    try:
        calls = len(server.calls)
        assert calls == 2
        original_gap = truth.query("rc7_gap", gap_id=proof["original_gap_id"])[0]
        original_status = original_gap["state"]
        assert original_status != "RESOLVED"
        orig_attempt = truth.query("rc72_n7_execution_preparation",
                                   preparation_id=request["preparation_id"])[0]
        assert orig_attempt["attempt_id"] == proof["original_attempt_id"]
        before = truth.store.path.read_bytes()
        hold = gate.complete(release_batch_id=request["release_batch_id"])
        assert hold["status"] == "HOLD"
        assert not truth.query("rc72_node_gate", node_type="N9_DEFECT")
        assert truth.store.path.read_bytes() == before

        accepted = gate.review(
            release_batch_id=request["release_batch_id"],
            request_id=request["request_id"], defect_id=native.DEFECT_ID,
            attestation_ref=att["attestation_ref"])
        assert accepted["status"] == "HOLD"
        assert truth.query("rc7_gap", gap_id=proof["original_gap_id"])[0]["state"] == original_status
        assert truth.query("rc7_task",
                           task_id=request["qualification_workitem_id"])[0]["state"] == "RUNNING"
        assert not truth.query("rc72_node_gate", node_type="N9_DEFECT")
        assert gate.complete(release_batch_id=request["release_batch_id"])["status"] == "HOLD"

        settled = gate.accept_reviewed_resolution(
            release_batch_id=request["release_batch_id"],
            request_id=request["request_id"], defect_id=native.DEFECT_ID)
        assert settled["status"] == "ADJUDICATED"
        original_gap = truth.query("rc7_gap", gap_id=proof["original_gap_id"])[0]
        assert original_gap["state"] == "RESOLVED"
        assert original_gap["resolution_evaluation_id"] == settled["original_gap_evaluation_id"]
        original_resolution = truth.query(
            "rc7_evaluation", evaluation_id=settled["original_gap_evaluation_id"])[0]
        assert original_resolution["dimensions"]["proof_sha256"] == _hash(proof)
        assert original_resolution["evaluator_ref"] == att["reviewer_ref"]
        assert truth.query(
            "rc7_task", task_id=request["qualification_workitem_id"])[0]["state"] == "PASS"
        # The original failed Attempt stays immutable; source resolution has
        # a separate signed Evaluation instead of altering the failed result.
        assert truth.query(
            "execution_attempt", attempt_id=proof["original_attempt_id"])[0]["status"] == "BLOCKED"
        assert len(server.calls) == calls
        n7 = truth.query("rc72_mission_node", node_type="N7_EXECUTION")[0]
        assert n7["state"] != "PASS"

        result = gate.complete(release_batch_id=request["release_batch_id"])
        assert result["state"] == "N9_PASS"
        assert result["n9_gate_pass"] is True
        assert result["field_verified"] is result["bank_final"] is False
        n9 = truth.query("rc72_mission_node", node_type="N9_DEFECT")[0]
        assert n9["state"] == "PASS"
        n10 = truth.query("rc72_mission_node", node_type="N10_RELEASE_CONVERGENCE")[0]
        assert n10["state"] == "READY"
        assert len(truth.query("rc72_node_gate", gate_id=result["gate_id"])) == 1
        assert len(server.calls) == calls
        before = truth.store.path.read_bytes()
        assert gate.complete(release_batch_id=request["release_batch_id"]) == result
        assert truth.store.path.read_bytes() == before
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("change", ["wrong_proof", "wrong_reviewer", "old_attestation", "wrong_gap"])
def test_c04_professional_review_rejects_attestation_scope_before_any_side_effect(
        tmp_path, monkeypatch, change):
    truth, pipeline, server, request, gate, att, proof = _closed(
        tmp_path, monkeypatch)
    try:
        changed = dict(att)
        if change == "wrong_proof":
            changed["proof_sha256"] = "0" * 64
        elif change == "wrong_reviewer":
            changed["reviewer_ref"] = request["analysis_worker_id"]
        elif change == "old_attestation":
            changed["issued_at"] -= 2000
        else:
            changed["original_gap_id"] = "GAP-UNRELATED"
        gate.reviewer.rows[att["attestation_ref"]] = changed
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="N9_PROFESSIONAL_FRESH_INDEPENDENT_REVIEW_REQUIRED"):
            gate.review(
                release_batch_id=request["release_batch_id"],
                request_id=request["request_id"], defect_id=native.DEFECT_ID,
                attestation_ref=att["attestation_ref"])
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == 2
        assert not truth.query("rc72_node_gate", node_type="N9_DEFECT")
    finally:
        server.shutdown()
        server.server_close()


def test_c04_professional_review_signature_forgery_blocks_original_gap_settlement(
        tmp_path, monkeypatch):
    truth, pipeline, server, request, gate, att, proof = _closed(
        tmp_path, monkeypatch)
    try:
        gate.review(
            release_batch_id=request["release_batch_id"],
            request_id=request["request_id"], defect_id=native.DEFECT_ID,
            attestation_ref=att["attestation_ref"])
        row = dict(truth.query("rc72_n9_professional_disposition_review")[0])
        row["reviewer_ref"] = "forged://other-actor"
        row["artifact_version"] += 1
        truth.append_atomic("RC72_N9_PROFESSIONAL_DISPOSITION_REVIEW_UPSERTED", row)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="N9_PROFESSIONAL_REVIEW_SIGNATURE_CHANGED"):
            gate.accept_reviewed_resolution(
                release_batch_id=request["release_batch_id"],
                request_id=request["request_id"], defect_id=native.DEFECT_ID)
        assert truth.store.path.read_bytes() == before
        assert truth.query("rc7_gap", gap_id=proof["original_gap_id"])[0]["state"] != "RESOLVED"
        assert len(server.calls) == 2
    finally:
        server.shutdown()
        server.server_close()


def test_c04_professional_gate_rejects_provenance_change_after_pass_without_new_io(
        tmp_path, monkeypatch):
    truth, pipeline, server, request, gate, att, proof = _closed(
        tmp_path, monkeypatch)
    try:
        gate.review(
            release_batch_id=request["release_batch_id"],
            request_id=request["request_id"], defect_id=native.DEFECT_ID,
            attestation_ref=att["attestation_ref"])
        gate.accept_reviewed_resolution(
            release_batch_id=request["release_batch_id"],
            request_id=request["request_id"], defect_id=native.DEFECT_ID)
        passed = gate.complete(release_batch_id=request["release_batch_id"])
        assert passed["n9_gate_pass"]
        artifact = truth.query(
            "rc7_artifact", artifact_id=proof["verification_artifact_id"])[0]
        path = Path(artifact["content_ref"][len("file://"):])
        path.write_bytes(path.read_bytes() + b"\nchanged original fix execution")
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError):
            gate.complete(release_batch_id=request["release_batch_id"])
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == 2
    finally:
        server.shutdown()
        server.server_close()
