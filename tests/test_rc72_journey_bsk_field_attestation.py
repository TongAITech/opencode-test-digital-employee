"""C09 external bank Field authority contract (mock signer is not bank proof)."""
import json
import time
from pathlib import Path
from rc72_file_uri_test_support import local_file_evidence_ref

import pytest

from rc7_runtime.rc72_journey_bsk_field import (
    JourneyBSKCertifiedFieldAdapter, bsk_field_scope_digest)
from rc7_runtime.rc72_journey_replay import JourneyReplayService
from test_rc72_phase9_journey_replay_contract import _setup as replay_setup
from test_rc72_journey_bsk_native_adapter import TestBSK, _adapter


def _certified(tmp_path, *, change=None, trusted=True):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    runner = TestBSK()
    native = _adapter(pool, tmp_path, runner)

    def external_b_group_verifier(scope):
        instance_id = pool.lease(scope["browser_lease_id"])["browser_instance_id"]
        instance = truth.query(
            "rc72_browser_instance", browser_instance_id=instance_id)[0]
        owned = native.session_for(scope, instance)
        now = int(time.time())
        proof = {
            "attestation_kind": "BANK_BSK_FIELD_SESSION",
            "verifier_kind": "BANK_EXTERNAL_BSK_AUTHORITY",
            "signature_verified": True, "field_verified": True,
            "attestation_ref": "r1://signed-external-bank-bsk",
            "evidence_refs": ["evidence://bank-field-session"],
            "issued_at": now - 1, "expires_at": now + 300,
            "scope_digest": bsk_field_scope_digest(scope),
            "bsk_session_id": owned["bsk_session_id"],
            "tab_id": owned["tab_id"],
            "browser_instance_id": owned["browser_instance_id"],
            "auth_asset_ref": owned["auth_asset_ref"],
            "browser_lease_id": scope["browser_lease_id"],
            "attempt_id": scope["attempt_id"],
            "case_id": scope["case_id"],
        }
        if change:
            change(proof)
        return proof

    adapter = JourneyBSKCertifiedFieldAdapter(
        browser_pool=pool, evidence_root=tmp_path / "certified-bsk",
        bsk_executable=tmp_path / "bsk.exe",
        session_resolver=native.session_for,
        session_receipt_verifier=native.verify_session,
        reference_resolver=native.resolve,
        runner=runner,
        field_attestation_verifier=external_b_group_verifier,
        trusted_verifier_kinds=("BANK_EXTERNAL_BSK_AUTHORITY",))
    service = JourneyReplayService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=adapter,
        trusted_field_adapter_kinds=(
            ("BROWSERSKILL_FIELD_ATTESTED",) if trusted else ()))
    return truth, lease, service, runner


def _replay(service, lease):
    return service.replay(
        replay_id="JRP-BSK-CERTIFIED", candidate_id="JC-1",
        workitem_id="WI-R1", attempt_id="ATT-R1",
        worker_id="WORKER-R1", session_id="SESSION-R1",
        browser_lease_id=lease.browser_lease_id)


def test_signed_field_trust_contract_marks_only_attested_attempt(tmp_path):
    # This tests the proof validation contract with a simulated B signer.
    # Real B/4A/BSK/Field verification remains a separate bank acceptance.
    truth, lease, service, runner = _certified(tmp_path)
    assert _replay(service, lease).state.value == "PASSED"
    receipt = truth.query(
        "rc72_journey_replay", replay_id="JRP-BSK-CERTIFIED")[0]
    assert receipt["field_verified"] is True
    assert receipt["adapter_kind"] == "BROWSERSKILL_FIELD_ATTESTED"
    rows = truth.query(
        "rc72_journey_replay_step", replay_id="JRP-BSK-CERTIFIED")
    assert rows and all(row["status"] == "PASSED" for row in rows)
    for row in rows:
        actual = json.loads(local_file_evidence_ref(row["actual_refs"][0]).read_text())
        assert actual["field_verified"] is True


@pytest.mark.parametrize("mutation,code", [
    (lambda p: p.update(signature_verified=False),
     "JOURNEY_BSK_FIELD_PROOF_NOT_TRUSTED"),
    (lambda p: p.update(verifier_kind="worker-self"),
     "JOURNEY_BSK_FIELD_PROOF_NOT_TRUSTED"),
    (lambda p: p.update(attempt_id="ATT-SOMEONE-ELSE"),
     "JOURNEY_BSK_FIELD_PROOF_SCOPE_MISMATCH"),
    (lambda p: p.update(tab_id=999),
     "JOURNEY_BSK_FIELD_PROOF_SCOPE_MISMATCH"),
    (lambda p: p.update(expires_at=0),
     "JOURNEY_BSK_FIELD_PROOF_EXPIRED"),
    (lambda p: p.update(evidence_refs=[]),
     "JOURNEY_BSK_FIELD_PROOF_EVIDENCE_REQUIRED"),
])
def test_unsigned_expired_cross_scope_proof_fails_before_sut(
        tmp_path, mutation, code):
    truth, lease, service, runner = _certified(tmp_path, change=mutation)
    with pytest.raises(Exception, match=code):
        _replay(service, lease)
    assert runner.calls == []
    assert not truth.query(
        "rc72_journey_replay", replay_id="JRP-BSK-CERTIFIED")


def test_non_allowlisted_field_adapter_cannot_self_authorize(tmp_path):
    truth, lease, service, runner = _certified(tmp_path, trusted=False)
    assert _replay(service, lease).state.value == "FAILED"
    receipt = truth.query(
        "rc72_journey_replay", replay_id="JRP-BSK-CERTIFIED")[0]
    assert receipt["field_verified"] is False
    assert not runner.calls


def test_bsk_field_attestation_expiring_mid_action_cannot_pass_replay(tmp_path):
    truth, lease, service, runner = _certified(tmp_path)
    original = service.adapter.runner

    def expiring_runner(argv):
        response = original(argv)
        if "step" in argv:
            service.adapter._proof_expires_at = 0
        return response

    service.adapter.runner = expiring_runner
    result = _replay(service, lease)
    assert result.state.value == "FAILED"
    records = truth.query(
        "rc72_journey_replay_step", replay_id="JRP-BSK-CERTIFIED")
    assert len(records) == 1
    assert records[0]["status"] == "FAILED"
    assert records[0]["failure_code"] == "JOURNEY_BSK_FIELD_PROOF_EXPIRED_DURING_STEP"
    actual = json.loads(local_file_evidence_ref(records[0]["actual_refs"][0]).read_text())
    assert actual["field_verified"] is False
    assert actual["status"] == "FAILED"
