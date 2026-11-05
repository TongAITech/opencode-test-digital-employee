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
        assert result.get("state") == "N9_PASS", result
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
        assert passed.get("n9_gate_pass") is True, passed
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


def test_c04_release_batch_driver_native_professional_gate_cannot_bypass_open_n8_discrepancy(
        tmp_path, monkeypatch):
    """A real ReleaseBatchDriver uses the specialist N9 route, never empty N9."""
    import sys
    from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
    from rc7_runtime.rc72_authority import RC72AuthorityRuntime
    from rc7_runtime.dsh_requirement_evaluator import DshRequirementEvaluator
    from rc7_runtime.rc72_n9_accepted_scope import AcceptedScopeN9Service
    from rc7_runtime.rc72_release_driver import ReleaseBatchDriver
    from rc72_pip_field_test_support import provider as field_provider

    truth, pipeline, server, request, gate, att, proof = _closed(
        tmp_path, monkeypatch)
    try:
        empty = tmp_path / "bank-driver-n9-no-extra-model.json"
        empty.write_text("{}", encoding="utf-8")
        def launcher(role):
            def forbidden(*args, **kwargs):
                pytest.fail("professional N9 review cannot replay DSH or other Mission stages")
            return DshHeadlessWorkerLauncher(
                dsh_bin=sys.executable, patch_path=str(empty),
                cwd=str(tmp_path), truth=truth,
                authority=RC72AuthorityRuntime(("n9-product-proof-"+role+"-signed-host").encode()),
                coordinator_instance_id="n9-native-professional-product",
                release_id=pipeline.release_id,
                state_root=str(tmp_path / ("n9-product-"+role)),
                command_runner=forbidden)
        driver = ReleaseBatchDriver(
            truth, source_commit=pipeline.source_commit,
            bank_pip_mirror=field_provider(
                truth, source_commit=pipeline.source_commit),
            n1_launcher=launcher("n1"), n1_tools=["reality"],
            n2_launcher=launcher("n2"), n2_tools=["requirement"],
            n2_evaluator=DshRequirementEvaluator(
                launcher("review"), allowed_tools=["requirement-review"]),
            n7_pipeline=pipeline, n8_pipeline=gate.n8,
            n9_pipeline=AcceptedScopeN9Service(pipeline),
            n9_professional_pipeline=gate)
        batch = truth.query("rc72_release_batch",
                            release_batch_id=request["release_batch_id"])[0]
        before = truth.store.path.read_bytes()
        assert driver._complete_gate("N9_DEFECT", batch)["status"] == "HOLD"
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == 2
        reviewed = driver.review_professional_resolution(
            release_batch_id=request["release_batch_id"],
            request_id=request["request_id"], defect_id=native.DEFECT_ID,
            attestation_ref=att["attestation_ref"])
        assert reviewed["status"] == "HOLD"
        assert truth.query("rc7_gap", gap_id=proof["original_gap_id"])[0]["state"] != "RESOLVED"
        assert driver._complete_gate("N9_DEFECT", batch)["status"] == "HOLD"
        driver.accept_professional_resolution(
            release_batch_id=request["release_batch_id"],
            request_id=request["request_id"], defect_id=native.DEFECT_ID)
        accepted = driver.complete_professional_n9(
            release_batch_id=request["release_batch_id"])
        assert accepted["state"] == "N9_PASS"
        assert accepted["n9_gate_pass"]
        assert driver._complete_gate("N9_DEFECT", batch) == accepted
        assert truth.query(
            "rc72_mission_node", node_type="N10_RELEASE_CONVERGENCE")[0]["state"] == "READY"
        assert not truth.query(
            "rc72_node_gate", node_type="N10_RELEASE_CONVERGENCE")
        assert len(server.calls) == 2
    finally:
        server.shutdown()
        server.server_close()
