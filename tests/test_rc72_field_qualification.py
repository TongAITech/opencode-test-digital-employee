from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.case_runtime import HUMAN_GATE_APPROVAL_KIND
from rc7_runtime.rc72_field_qualification import (
    QUALIFICATION_PROOF_KIND,
    FieldQualificationService,
    install_rc72_field_qualification_overlay,
)
from rc7_runtime.rc72_truth import install_rc72_truth_overlay
from rc7_runtime.truth_overlay import install_rc7_truth_overlay


RELEASE = "BLOAN-PF1.2.1"
MISSION = "MISSION-BLOAN-PF1.2.1"
BATCH = "RB-BLOAN-PF1.2.1"
COMMIT = "a" * 40


def _truth(tmp_path: Path) -> TruthRuntime:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_field_qualification_overlay()
    return TruthRuntime(tmp_path / "r1.jsonl")


def _batch(truth: TruthRuntime) -> None:
    truth.append_atomic(
        "RC72_RELEASE_BATCH_UPSERTED",
        {
            "release_batch_id": BATCH,
            "release_id": RELEASE,
            "mission_id": MISSION,
            "name": RELEASE,
            "planned_release_time": None,
            "version_ids": [RELEASE],
            "application_ids": ["BLOAN"],
            "requirement_ids": ["REQ-1"],
            "state": "REGISTERED",
            "readiness": "UNKNOWN",
            "created_at": 1,
            "updated_at": 1,
            "artifact_version": 1,
        },
    )


def _evidence(
    truth: TruthRuntime,
    *,
    evidence_id: str,
    gate: str,
    kind: str = QUALIFICATION_PROOF_KIND,
    source_ref: str = "provider://field-qualifier/probe",
    mission_id: str = MISSION,
    release_id: str = RELEASE,
    source_commit: str = COMMIT,
    batch_id: str = BATCH,
) -> None:
    truth.append_atomic(
        "RC7_EVIDENCE_UPSERTED",
        {
            "evidence_id": evidence_id,
            "release_id": release_id,
            "mission_id": mission_id,
            "kind": kind,
            "source_ref": source_ref,
            "content_ref": "state://qualification/%s.json" % evidence_id,
            "subject_refs": [batch_id, gate, source_commit],
            "content_hash": "sha256:" + evidence_id,
            "created_at": 1,
            "artifact_version": 1,
        },
    )


def _record(service: FieldQualificationService, gate: str, evidence_refs):
    return service.record(
        release_batch_id=BATCH,
        gate=gate,
        source_commit=COMMIT,
        requested_status="PASS",
        evidence_refs=evidence_refs,
        platform_family="BANK_FIELD",
        platform_release="TARGET",
        architecture="x86_64",
        python_version="3.8.10",
    )


def test_provider_backed_exact_lineage_proof_becomes_field_pass(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    _evidence(truth, evidence_id="EVD-Q3", gate="Q3")

    receipt = _record(FieldQualificationService(truth, release_id=RELEASE), "Q3", ["EVD-Q3"])

    assert receipt["status"] == "PASS"
    assert receipt["field_verified"] is True
    assert receipt["bank_final"] is False
    assert receipt["evidence_refs"] == ["EVD-Q3"]


def test_github_or_fixture_claim_cannot_become_field_pass(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    _evidence(
        truth,
        evidence_id="EVD-GITHUB-Q3",
        gate="Q3",
        source_ref="github://actions/q3",
    )

    receipt = _record(FieldQualificationService(truth, release_id=RELEASE), "Q3", ["EVD-GITHUB-Q3"])

    assert receipt["status"] == "HOLD"
    assert receipt["field_verified"] is False
    assert receipt["evidence_refs"] == []
    assert receipt["rejected_evidence_refs"] == ["EVD-GITHUB-Q3"]


def test_cross_batch_or_source_commit_evidence_fails_closed(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    _evidence(truth, evidence_id="EVD-WRONG-BATCH", gate="Q4", batch_id="RB-OTHER")
    _evidence(truth, evidence_id="EVD-WRONG-COMMIT", gate="Q4", source_commit="b" * 40)

    receipt = _record(
        FieldQualificationService(truth, release_id=RELEASE),
        "Q4",
        ["EVD-WRONG-BATCH", "EVD-WRONG-COMMIT"],
    )

    assert receipt["status"] == "HOLD"
    assert set(receipt["rejected_evidence_refs"]) == {"EVD-WRONG-BATCH", "EVD-WRONG-COMMIT"}


def test_q6_requires_exact_bound_human_gate_approval(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    _evidence(
        truth,
        evidence_id="EVD-Q6-HUMAN",
        gate="Q6",
        kind=HUMAN_GATE_APPROVAL_KIND,
        source_ref="human://trusted-bank-verifier",
    )

    receipt = _record(FieldQualificationService(truth, release_id=RELEASE), "Q6", ["EVD-Q6-HUMAN"])

    assert receipt["status"] == "PASS"
    assert receipt["field_verified"] is True


def test_identical_qualification_is_idempotent(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    _evidence(truth, evidence_id="EVD-Q5", gate="Q5")
    service = FieldQualificationService(truth, release_id=RELEASE)

    first = _record(service, "Q5", ["EVD-Q5"])
    second = _record(service, "Q5", ["EVD-Q5"])
    rows = truth.query(
        "rc72_field_qualification_receipt",
        qualification_receipt_id=first["qualification_receipt_id"],
    )

    assert first == second
    assert len(rows) == 1
    assert rows[0]["artifact_version"] == 1
