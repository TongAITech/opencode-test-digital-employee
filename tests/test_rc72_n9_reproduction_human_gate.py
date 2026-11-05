"""C04 canonical Host HumanGate and original N8/N9 reproduction chain.

These tests use an isolated deterministic *contract* verifier; they do not
claim bank human attestation, new execution Attempt, RCA or defect closure.
"""
from dataclasses import fields, replace
import json
import sys
import time

import pytest

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError
from rc7_runtime.rc72_authority import RC72AuthorityRuntime
from rc7_runtime.rc72_n8_product_recovery import NativeN8ProductRecoveryService
from rc7_runtime.rc72_n9_reproduction_authorization import (
    N9ReproductionAuthorizationRequestService,
)
from rc7_runtime.rc72_n9_reproduction_human_gate import (
    N9ReproductionHumanGateService, request_scope_digest,
)
from rc7_runtime.rc72_release_driver import ReleaseBatchDriver
from rc7_runtime.rc72_n9_accepted_scope import AcceptedScopeN9Service
from rc7_runtime.dsh_requirement_evaluator import DshRequirementEvaluator
from rc72_n2_test_support import BATCH
from rc72_pip_field_test_support import provider as field_provider
from test_rc72_n9_captain_signed_dsh_bridge import _route


class ContractHumanGateVerifier:
    verifier_kind = "BANK_HUMAN_GATE"

    def __init__(self):
        self.rows = {}

    def resolve(self, ref):
        return dict(self.rows[ref])


def _approval(truth, request_id, *, verifier, decision="APPROVED",
              effects="SAFE_TO_REPRODUCE", **changes):
    row = truth.query(
        "rc72_n9_reproduction_authorization_request", request_id=request_id)[0]
    contract = truth.query(
        "rc72_n6_executable_contract", contract_id=row["original_contract_id"])[0]
    now = int(time.time())
    att = dict(
        attestation_ref="human-gate://independent-n9-reproduction-approval",
        actor_type="HUMAN",
        human_actor_ref="bank-employee://independent-reviewer",
        decision=decision,
        request_id=request_id,
        release_batch_id=row["release_batch_id"],
        mission_id=row["mission_id"],
        original_attempt_id=row["original_attempt_id"],
        original_case_id=row["original_case_id"],
        original_gap_id=row["original_gap_id"],
        analysis_id=row["analysis_id"],
        scope_digest=request_scope_digest(row, contract),
        side_effects_disposition=effects,
        rationale="Original side effect evidence was reviewed independently",
        evidence_refs=["bank-review-evidence://side-effect-reconciliation"],
        field_verified=True,
        issued_at=now,
        expires_at=now+300)
    att.update(changes)
    verifier.rows[att["attestation_ref"]] = att
    return att


def _setup_gate(tmp_path, monkeypatch, *, finding="POSSIBLE_PRODUCT_CAUSE"):
    truth, plan, prep, server, pipeline, route, calls, _, owner = _route(
        tmp_path, monkeypatch, finding=finding)
    original = pipeline.complete(release_batch_id=BATCH)
    assert original["failure_class"] == "VALID_TEST_FAILURE"
    qualified = route.complete(release_batch_id=BATCH)
    assert qualified["reproduction_request_id"].startswith("N9REPRO-")
    verifier = ContractHumanGateVerifier()
    requests = N9ReproductionAuthorizationRequestService(route.professional_dsh)
    gate = N9ReproductionHumanGateService(
        requests, approval_verifier=verifier,
        trusted_field_verifier_kinds=("BANK_HUMAN_GATE",))
    return truth, pipeline, route, server, calls, verifier, gate, qualified, owner


def test_real_n8_to_n9_signed_request_independent_human_decision_and_cold_r1(
        tmp_path, monkeypatch):
    truth, pipeline, route, server, calls, verifier, gate, qualified, owner = _setup_gate(
        tmp_path, monkeypatch)
    try:
        request_id = qualified["reproduction_request_id"]
        att = _approval(truth, request_id, verifier=verifier)
        prior_business = len(server.calls)
        prior_attempts = truth.query("execution_attempt")
        before = truth.store.path.read_bytes()
        decision = gate.review(
            request_id=request_id, attestation_ref=att["attestation_ref"])
        assert decision["status"] == "HOLD"
        assert decision["reason"] == "N9_FRESH_REPRODUCTION_EXECUTION_NOT_YET_PROVEN"
        assert decision["human_decision"] == "APPROVED"
        assert decision["defect_confirmed"] is decision["reproduction_completed"] is False
        assert decision["field_verified"] is decision["bank_final"] is False
        rows = truth.query("rc72_n9_reproduction_human_decision")
        assert len(rows) == 1
        approved = rows[0]
        assert approved["request_id"] == request_id
        assert approved["original_attempt_id"] == qualified["original_attempt_id"]
        assert approved["scope_digest"] == request_scope_digest(
            truth.query("rc72_n9_reproduction_authorization_request")[0],
            truth.query("rc72_n6_executable_contract")[0])
        assert approved["decision"] == "APPROVED"
        assert approved["side_effects_disposition"] == "SAFE_TO_REPRODUCE"
        assert gate.assert_fresh_approved(request_id=request_id) == approved
        assert not truth.query("rc7_defect")
        assert truth.query("execution_attempt") == prior_attempts
        assert not truth.query("rc7_task", task_type="DEFECT_REPRODUCTION")
        assert len(server.calls) == prior_business
        assert len(calls) == 1
        after = truth.store.path.read_bytes()
        assert after != before
        assert gate.review(request_id=request_id, attestation_ref=att["attestation_ref"]) == decision
        assert truth.store.path.read_bytes() == after

        cold = TruthRuntime(truth.store.path)
        fresh_request_service = N9ReproductionAuthorizationRequestService(route.professional_dsh)
        fresh_request_service.truth = cold
        # Cold audit uses original signed raw bytes and actual independent
        # N8/DSH object; R1 is verified by its canonical projection.
        reloaded = cold.query("rc72_n9_reproduction_human_decision", request_id=request_id)
        assert len(reloaded) == 1
        assert reloaded[0] == approved
        assert len(server.calls) == prior_business
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("mutation,reason", [
    ("worker", "INDEPENDENT_FIELD_EVIDENCE_REQUIRED"),
    ("no_field", "INDEPENDENT_FIELD_EVIDENCE_REQUIRED"),
    ("wrong_case", "STALE_OR_FOREIGN_SCOPE_FORBIDDEN"),
    ("wrong_attempt", "STALE_OR_FOREIGN_SCOPE_FORBIDDEN"),
    ("wrong_digest", "STALE_OR_FOREIGN_SCOPE_FORBIDDEN"),
    ("unknown_effect", "POSSIBLE_BUSINESS_WRITE_NO_REEXECUTION"),
    ("stale_time", "FRESH_ATTESTATION_REQUIRED"),
])
def test_human_reproduction_must_bind_original_r1_or_fail_without_new_io(
        tmp_path, monkeypatch, mutation, reason):
    truth, pipeline, route, server, calls, verifier, gate, qualified, owner = _setup_gate(
        tmp_path, monkeypatch)
    try:
        request_id = qualified["reproduction_request_id"]
        att = _approval(truth, request_id, verifier=verifier)
        if mutation == "worker":
            att["actor_type"] = "WORKER"
        elif mutation == "no_field":
            att["field_verified"] = False
        elif mutation == "wrong_case":
            att["original_case_id"] = "FOREIGN-CASE"
        elif mutation == "wrong_attempt":
            att["original_attempt_id"] = "OLD-ATTEMPT"
        elif mutation == "wrong_digest":
            att["scope_digest"] = "sha256:" + "0"*64
        elif mutation == "unknown_effect":
            att["side_effects_disposition"] = "UNKNOWN_OR_POSSIBLY_COMMITTED"
        elif mutation == "stale_time":
            att["issued_at"] -= 1000
        verifier.rows[att["attestation_ref"]] = att
        before = truth.store.path.read_bytes()
        prior_business = len(server.calls)
        with pytest.raises(ContractError, match="N9_HUMAN_" + reason):
            gate.review(request_id=request_id, attestation_ref=att["attestation_ref"])
        assert truth.store.path.read_bytes() == before
        assert len(server.calls) == prior_business
        assert len(calls) == 1
        assert not truth.query("rc72_n9_reproduction_human_decision")
    finally:
        server.shutdown()
        server.server_close()


def test_rejected_human_or_unsafe_prior_business_side_effect_stays_hold(
        tmp_path, monkeypatch):
    truth, pipeline, route, server, calls, verifier, gate, qualified, owner = _setup_gate(
        tmp_path, monkeypatch)
    try:
        request_id = qualified["reproduction_request_id"]
        att = _approval(truth, request_id, verifier=verifier,
                        decision="REJECTED",
                        effects="UNKNOWN_OR_POSSIBLY_COMMITTED")
        prior_business = len(server.calls)
        result = gate.review(request_id=request_id, attestation_ref=att["attestation_ref"])
        assert result["reason"] == "N9_HUMAN_REPRODUCTION_REJECTED"
        with pytest.raises(ContractError, match="N9_HUMAN_FRESH_APPROVAL_REQUIRED"):
            gate.assert_fresh_approved(request_id=request_id)
        assert len(server.calls) == prior_business and len(calls) == 1
        assert not truth.query("rc7_defect")
        # Consent cannot be upgraded on same request, even if external Host
        # later returns a different disposition with the same reference.
        att["decision"] = "APPROVED"
        att["side_effects_disposition"] = "SAFE_TO_REPRODUCE"
        verifier.rows[att["attestation_ref"]] = att
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="N9_HUMAN_DECISION_IMMUTABLE"):
            gate.review(request_id=request_id, attestation_ref=att["attestation_ref"])
        assert truth.store.path.read_bytes() == before
    finally:
        server.shutdown()
        server.server_close()


def test_forged_signed_human_receipt_denied_even_after_real_approval(
        tmp_path, monkeypatch):
    truth, pipeline, route, server, calls, verifier, gate, qualified, owner = _setup_gate(
        tmp_path, monkeypatch)
    try:
        request_id = qualified["reproduction_request_id"]
        att = _approval(truth, request_id, verifier=verifier)
        gate.review(request_id=request_id, attestation_ref=att["attestation_ref"])
        row = dict(truth.query("rc72_n9_reproduction_human_decision")[0])
        row["signature"] = "0" * 64
        row["artifact_version"] += 1
        truth.append_atomic("RC72_N9_REPRODUCTION_HUMAN_DECISION_RECORDED", row)
        before = truth.store.path.read_bytes()
        with pytest.raises(ContractError, match="N9_HUMAN_FRESH_APPROVAL_REQUIRED"):
            gate.assert_fresh_approved(request_id=request_id)
        with pytest.raises(ContractError, match="N9_HUMAN_DECISION_SIGNATURE_CHANGED"):
            gate.review(request_id=request_id, attestation_ref=att["attestation_ref"])
        assert truth.store.path.read_bytes() == before
        assert len(calls) == len(server.calls) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_public_release_batch_driver_review_is_real_host_gate_not_n7_rerun(
        tmp_path, monkeypatch):
    truth, pipeline, route, server, calls, verifier, gate, qualified, owner = _setup_gate(
        tmp_path, monkeypatch)
    try:
        patch = tmp_path / "human-driver-patch.json"
        patch.write_text("{}", encoding="utf-8")
        def launcher(role):
            def forbidden(*args, **kwargs):
                pytest.fail("Human review must not invoke DSH worker")
            return DshHeadlessWorkerLauncher(
                dsh_bin=sys.executable, patch_path=str(patch), cwd=str(tmp_path),
                truth=truth,
                authority=RC72AuthorityRuntime(("human-review-" + role).encode()),
                coordinator_instance_id="test-review-controller",
                release_id=pipeline.release_id,
                state_root=str(tmp_path / ("human-role-" + role)),
                command_runner=forbidden)
        routed = NativeN8ProductRecoveryService(
            pipeline, professional_dsh=route.professional_dsh,
            reproduction_human_gate=gate)
        driver = ReleaseBatchDriver(
            truth, source_commit=pipeline.source_commit,
            bank_pip_mirror=field_provider(truth, source_commit=pipeline.source_commit),
            n1_launcher=launcher("n1"), n1_tools=["reality"],
            n2_launcher=launcher("n2"), n2_tools=["requirement"],
            n2_evaluator=DshRequirementEvaluator(
                launcher("review"), allowed_tools=["requirement-review"]),
            n7_pipeline=pipeline, n8_pipeline=routed,
            n9_pipeline=AcceptedScopeN9Service(pipeline))
        att = _approval(truth, qualified["reproduction_request_id"], verifier=verifier)
        before_calls = len(server.calls)
        before_attempts = truth.query("execution_attempt")
        result = driver.review_reproduction(
            release_batch_id=BATCH,
            request_id=qualified["reproduction_request_id"],
            attestation_ref=att["attestation_ref"])
        assert result["human_decision"] == "APPROVED"
        assert result["status"] == "HOLD"
        assert not truth.query("rc7_defect")
        assert truth.query("execution_attempt") == before_attempts
        assert len(server.calls) == before_calls and len(calls) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_factory_requires_explicit_typed_bank_human_verifier_binding(
        tmp_path):
    from rc7_runtime.rc72_mission_factory import (
        MissionProfessionalDshBinding, MissionReproductionHumanBinding,
        create_mission_driver,
    )
    from test_rc72_mission_factory import _setup
    truth, options = _setup(tmp_path)
    patch = tmp_path / "patch.json"
    verified = ContractHumanGateVerifier()
    analyst = DshHeadlessWorkerLauncher(
        dsh_bin=sys.executable, patch_path=str(patch), cwd=str(tmp_path),
        truth=truth, authority=RC72AuthorityRuntime(b"independent-human-analyst"),
        coordinator_instance_id="test-independent-controller",
        release_id=options["release_id"], state_root=str(tmp_path / "worker-human-review"),
        command_runner=lambda *args,**kwargs: pytest.fail("factory must not invoke DSH"))
    options["professional_dsh_binding"] = MissionProfessionalDshBinding(
        analyst, ("read_only_diagnostic",))
    options["reproduction_human_binding"] = MissionReproductionHumanBinding(
        verified, ("BANK_HUMAN_GATE",))
    before = truth.store.path.read_bytes()
    driver = create_mission_driver(truth, **options)
    assert driver.n8_pipeline.reproduction_human_gate is not None
    assert driver.n8_pipeline.reproduction_human_gate.requests.analyst is (
        driver.n8_pipeline.professional_dsh)
    assert truth.store.path.read_bytes() == before
    assert not truth.query("rc72_n9_reproduction_human_decision")
    assert not truth.query("execution_attempt")
    options["reproduction_human_binding"] = {"approved": True}
    with pytest.raises(ContractError, match="MISSION_FACTORY_N9_HUMAN_TRUSTED_HOST_BINDING_REQUIRED"):
        create_mission_driver(truth, **options)
