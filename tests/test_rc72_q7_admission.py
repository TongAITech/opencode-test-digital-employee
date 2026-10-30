from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.case_runtime import HUMAN_GATE_APPROVAL_KIND
from rc7_runtime.rc72_domain import TestObligation
from rc7_runtime.rc72_field_qualification import (
    QUALIFICATION_PROOF_KIND,
    FieldQualificationService,
    install_rc72_field_qualification_overlay,
)
from rc7_runtime.rc72_q7_admission import Q7AdmissionService, install_rc72_q7_admission_overlay
from rc7_runtime.rc72_release_provenance import (
    FIELD_EVIDENCE_KIND,
    ReleaseBatchProvenanceService,
    install_rc72_release_provenance_overlay,
)
from rc7_runtime.rc72_release_scope import (
    ReleaseScopeManifest,
    ReleaseScopeService,
    install_rc72_release_scope_overlay,
)
from rc7_runtime.rc72_truth import append_rc72_entity, install_rc72_truth_overlay
from rc7_runtime.truth_overlay import install_rc7_truth_overlay


RELEASE = "BLOAN-PF1.2.1"
MISSION = "MISSION-BLOAN-PF1.2.1"
BATCH = "RB-BLOAN-PF1.2.1"
COMMIT = "c" * 40
LEVELS = ["L1", "L2", "L3", "L4", "L5", "L6", "L7"]


def _truth(tmp_path: Path) -> TruthRuntime:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_release_scope_overlay()
    install_rc72_release_provenance_overlay()
    install_rc72_field_qualification_overlay()
    install_rc72_q7_admission_overlay()
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
    kind: str,
    source_ref: str,
    subject_refs,
) -> None:
    truth.append_atomic(
        "RC7_EVIDENCE_UPSERTED",
        {
            "evidence_id": evidence_id,
            "release_id": RELEASE,
            "mission_id": MISSION,
            "kind": kind,
            "source_ref": source_ref,
            "content_ref": "state://q7/%s.json" % evidence_id,
            "subject_refs": list(subject_refs),
            "content_hash": "sha256:" + evidence_id,
            "created_at": 1,
            "artifact_version": 1,
        },
    )


def _scope(truth: TruthRuntime, *, complete: bool = True):
    service = ReleaseScopeService(truth, release_id=RELEASE)
    manifest = ReleaseScopeManifest(
        manifest_id="MANIFEST-BLOAN-121",
        mission_id=MISSION,
        release_batch_id=BATCH,
        requirement_ssts={"REQ-1": ["SST-1"]},
        required_levels_by_sst={"SST-1": LEVELS},
        source_refs=["r1://release-scope/BLOAN-PF1.2.1"],
        created_at=1,
    )
    service.persist_manifest(manifest)
    levels = LEVELS if complete else ["L1"]
    for level in levels:
        append_rc72_entity(
            truth,
            TestObligation(
                obligation_id="OBL-%s" % level,
                release_batch_id=BATCH,
                requirement_id="REQ-1",
                sst_id="SST-1",
                application_id="BLOAN",
                business_scenario="scenario-%s" % level,
                business_rule="rule-%s" % level,
                risk_level="HIGH",
                test_level=level,
                code_slice_refs=["code://%s" % level],
                change_refs=["change://%s" % level],
                oracle_refs=["oracle://%s" % level],
                coverage_targets=["coverage://%s" % level],
                status="READY",
                mission_id=MISSION,
            ),
            release_id=RELEASE,
            artifact_version=1,
        )
    return service.evaluate_denominator(manifest_id=manifest.manifest_id)


def _provenance(truth: TruthRuntime, *, field: bool = True):
    if field:
        _evidence(
            truth,
            evidence_id="EVD-PROVENANCE-FIELD",
            kind=FIELD_EVIDENCE_KIND,
            source_ref="provider://bank-field/release",
            subject_refs=[BATCH],
        )
    return ReleaseBatchProvenanceService(truth, release_id=RELEASE).evaluate(BATCH)


def _qualifications(truth: TruthRuntime, *, gates=LEVELS[:0] + ["Q3", "Q4", "Q5", "Q6"], source_commit: str = COMMIT):
    service = FieldQualificationService(truth, release_id=RELEASE)
    receipts = []
    for gate in gates:
        evidence_id = "EVD-%s" % gate
        if gate == "Q6":
            kind = HUMAN_GATE_APPROVAL_KIND
            source = "human://trusted-bank-verifier"
        else:
            kind = QUALIFICATION_PROOF_KIND
            source = "provider://field-qualifier/%s" % gate.lower()
        _evidence(
            truth,
            evidence_id=evidence_id,
            kind=kind,
            source_ref=source,
            subject_refs=[BATCH, gate, source_commit],
        )
        receipts.append(
            service.record(
                release_batch_id=BATCH,
                gate=gate,
                source_commit=source_commit,
                requested_status="PASS",
                evidence_refs=[evidence_id],
                platform_family="BANK_FIELD",
                platform_release="TARGET",
                architecture="x86_64",
                python_version="3.8.10",
            )
        )
    return receipts


def _admit(truth, provenance, snapshot, receipts, *, source_commit: str = COMMIT):
    return Q7AdmissionService(truth, release_id=RELEASE).evaluate(
        release_batch_id=BATCH,
        source_commit=source_commit,
        provenance_id=provenance["provenance_id"],
        scope_snapshot_id=snapshot.snapshot_id,
        qualification_receipt_ids=[row["qualification_receipt_id"] for row in receipts],
    )


def test_field_provenance_complete_denominator_and_q3_q6_field_pass_admits_q7(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    provenance = _provenance(truth)
    snapshot = _scope(truth)
    receipts = _qualifications(truth)

    admission = _admit(truth, provenance, snapshot, receipts)

    assert admission["status"] == "ADMITTED"
    assert admission["hold_reasons"] == []
    assert admission["field_verified"] is False
    assert admission["bank_final"] is False
    assert "q7_pass" not in admission


def test_release_name_alone_with_unknown_provenance_never_admits(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    provenance = _provenance(truth, field=False)
    snapshot = _scope(truth)
    receipts = _qualifications(truth)

    admission = _admit(truth, provenance, snapshot, receipts)

    assert admission["status"] == "HOLD"
    assert any(reason.startswith("PROVENANCE_NOT_FIELD") for reason in admission["hold_reasons"])


def test_missing_one_mandatory_q_gate_holds(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    provenance = _provenance(truth)
    snapshot = _scope(truth)
    receipts = _qualifications(truth, gates=["Q3", "Q4", "Q5"])

    admission = _admit(truth, provenance, snapshot, receipts)

    assert admission["status"] == "HOLD"
    assert "QUALIFICATION_MISSING:Q6" in admission["hold_reasons"]


def test_source_commit_mismatch_holds_even_when_receipts_are_field_pass(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    provenance = _provenance(truth)
    snapshot = _scope(truth)
    receipts = _qualifications(truth, source_commit="d" * 40)

    admission = _admit(truth, provenance, snapshot, receipts, source_commit=COMMIT)

    assert admission["status"] == "HOLD"
    assert all(
        "QUALIFICATION_SOURCE_COMMIT_MISMATCH:%s" % gate in admission["hold_reasons"]
        for gate in ("Q3", "Q4", "Q5", "Q6")
    )


def test_incomplete_requirement_sst_obligation_denominator_holds(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    provenance = _provenance(truth)
    snapshot = _scope(truth, complete=False)
    receipts = _qualifications(truth)

    admission = _admit(truth, provenance, snapshot, receipts)

    assert admission["status"] == "HOLD"
    assert "SCOPE_DENOMINATOR_INCOMPLETE" in admission["hold_reasons"]


def test_identical_q7_admission_is_idempotent(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    provenance = _provenance(truth)
    snapshot = _scope(truth)
    receipts = _qualifications(truth)
    service = Q7AdmissionService(truth, release_id=RELEASE)
    kwargs = {
        "release_batch_id": BATCH,
        "source_commit": COMMIT,
        "provenance_id": provenance["provenance_id"],
        "scope_snapshot_id": snapshot.snapshot_id,
        "qualification_receipt_ids": [row["qualification_receipt_id"] for row in receipts],
    }

    first = service.evaluate(**kwargs)
    second = service.evaluate(**kwargs)

    assert first == second
    assert first["artifact_version"] == 1
    assert len(truth.query("rc72_q7_admission", admission_id=first["admission_id"])) == 1
