from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_release_provenance import (
    FIELD,
    FIXTURE,
    UNKNOWN,
    FIELD_EVIDENCE_KIND,
    FIXTURE_EVIDENCE_KIND,
    REASON_CONFLICT,
    ReleaseBatchProvenanceService,
    install_rc72_release_provenance_overlay,
)
from rc7_runtime.rc72_truth import install_rc72_truth_overlay
from rc7_runtime.truth_overlay import install_rc7_truth_overlay


RELEASE = "BLOAN-PF1.2.1"
MISSION = "MISSION-BLOAN-PF1.2.1"
BATCH = "RB-BLOAN-PF1.2.1"


def _truth(tmp_path: Path) -> TruthRuntime:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_release_provenance_overlay()
    return TruthRuntime(tmp_path / "r1.jsonl")


def _batch(
    truth: TruthRuntime,
    *,
    batch_id: str = BATCH,
    mission_id: str = MISSION,
    release_id: str = RELEASE,
    name: str = "BLOAN-PF1.2.1",
) -> None:
    truth.append_atomic(
        "RC72_RELEASE_BATCH_UPSERTED",
        {
            "release_batch_id": batch_id,
            "release_id": release_id,
            "mission_id": mission_id,
            "name": name,
            "planned_release_time": None,
            "version_ids": [release_id],
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
    mission_id: str = MISSION,
    release_id: str = RELEASE,
    subject_refs=None,
) -> None:
    truth.append_atomic(
        "RC7_EVIDENCE_UPSERTED",
        {
            "evidence_id": evidence_id,
            "release_id": release_id,
            "mission_id": mission_id,
            "kind": kind,
            "source_ref": source_ref,
            "content_ref": "state://evidence/%s.json" % evidence_id,
            "subject_refs": list(subject_refs or []),
            "content_hash": "sha256:" + evidence_id,
            "created_at": 1,
            "artifact_version": 1,
        },
    )


def test_release_name_alone_never_infers_field(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth, name="BLOAN-PF1.2.1-FIELD")

    receipt = ReleaseBatchProvenanceService(
        truth, release_id=RELEASE
    ).evaluate(BATCH)

    assert receipt["provenance"] == UNKNOWN
    assert receipt["field_evidence_refs"] == []
    assert receipt["fixture_evidence_refs"] == []
    assert receipt["evidence_refs"] == []


def test_explicit_fixture_evidence_establishes_fixture(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    _evidence(
        truth,
        evidence_id="EVD-FIXTURE",
        kind=FIXTURE_EVIDENCE_KIND,
        source_ref="fixture://pytest/release",
        subject_refs=[BATCH],
    )

    receipt = ReleaseBatchProvenanceService(
        truth, release_id=RELEASE
    ).evaluate(BATCH)

    assert receipt["provenance"] == FIXTURE
    assert receipt["fixture_evidence_refs"] == ["EVD-FIXTURE"]
    assert receipt["field_evidence_refs"] == []


def test_provider_backed_bank_field_evidence_bound_to_exact_batch_establishes_field(
    tmp_path: Path,
):
    truth = _truth(tmp_path)
    _batch(truth)
    _evidence(
        truth,
        evidence_id="EVD-FIELD",
        kind=FIELD_EVIDENCE_KIND,
        source_ref="provider://bank-db/BANK_DB_READ",
        subject_refs=["TARGET-FAT1", "BANK_DB_READ", BATCH],
    )

    receipt = ReleaseBatchProvenanceService(
        truth, release_id=RELEASE
    ).evaluate(BATCH)

    assert receipt["provenance"] == FIELD
    assert receipt["field_evidence_refs"] == ["EVD-FIELD"]
    assert receipt["fixture_evidence_refs"] == []


def test_existing_unbound_bank_probe_is_only_accepted_for_unique_canonical_batch(
    tmp_path: Path,
):
    truth = _truth(tmp_path)
    _batch(truth)
    _evidence(
        truth,
        evidence_id="EVD-LEGACY-FIELD",
        kind=FIELD_EVIDENCE_KIND,
        source_ref="provider://bank-cat/BANK_CAT_QUERY",
        subject_refs=["TARGET-FAT1", "BANK_CAT_QUERY"],
    )

    service = ReleaseBatchProvenanceService(truth, release_id=RELEASE)
    first = service.evaluate(BATCH)
    assert first["provenance"] == FIELD

    _batch(truth, batch_id="RB-SECOND")
    second = service.evaluate(BATCH)
    assert second["provenance"] == UNKNOWN
    assert second["field_evidence_refs"] == []
    assert second["rejected_evidence_refs"] == ["EVD-LEGACY-FIELD"]


def test_conflicting_field_and_fixture_evidence_fails_closed_to_unknown(
    tmp_path: Path,
):
    truth = _truth(tmp_path)
    _batch(truth)
    _evidence(
        truth,
        evidence_id="EVD-FIELD",
        kind=FIELD_EVIDENCE_KIND,
        source_ref="provider://bank-auth/BANK_AUTH_4A",
        subject_refs=[BATCH],
    )
    _evidence(
        truth,
        evidence_id="EVD-FIXTURE",
        kind=FIXTURE_EVIDENCE_KIND,
        source_ref="fixture://pytest/release",
        subject_refs=[BATCH],
    )

    receipt = ReleaseBatchProvenanceService(
        truth, release_id=RELEASE
    ).evaluate(BATCH)

    assert receipt["provenance"] == UNKNOWN
    assert receipt["reason"] == REASON_CONFLICT
    assert receipt["field_evidence_refs"] == ["EVD-FIELD"]
    assert receipt["fixture_evidence_refs"] == ["EVD-FIXTURE"]


def test_cross_mission_or_release_evidence_cannot_establish_field(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    _evidence(
        truth,
        evidence_id="EVD-OTHER-MISSION",
        kind=FIELD_EVIDENCE_KIND,
        source_ref="provider://bank-db/BANK_DB_READ",
        mission_id="MISSION-OTHER",
        subject_refs=[BATCH],
    )
    _evidence(
        truth,
        evidence_id="EVD-OTHER-RELEASE",
        kind=FIELD_EVIDENCE_KIND,
        source_ref="provider://bank-db/BANK_DB_READ",
        release_id="BLOAN-PF9.9.9",
        subject_refs=[BATCH],
    )

    receipt = ReleaseBatchProvenanceService(
        truth, release_id=RELEASE
    ).evaluate(BATCH)

    assert receipt["provenance"] == UNKNOWN
    assert receipt["field_evidence_refs"] == []
    assert set(receipt["rejected_evidence_refs"]) == {
        "EVD-OTHER-MISSION",
        "EVD-OTHER-RELEASE",
    }


def test_cross_batch_field_subject_cannot_establish_field(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(truth)
    _batch(truth, batch_id="RB-OTHER")
    _evidence(
        truth,
        evidence_id="EVD-OTHER-BATCH",
        kind=FIELD_EVIDENCE_KIND,
        source_ref="provider://bank-db/BANK_DB_READ",
        subject_refs=["RB-OTHER"],
    )

    receipt = ReleaseBatchProvenanceService(
        truth, release_id=RELEASE
    ).evaluate(BATCH)

    assert receipt["provenance"] == UNKNOWN
    assert receipt["field_evidence_refs"] == []
    assert receipt["rejected_evidence_refs"] == ["EVD-OTHER-BATCH"]


def test_non_provider_field_claim_and_caller_like_subjects_do_not_infer_field(
    tmp_path: Path,
):
    truth = _truth(tmp_path)
    _batch(truth, name="FIELD-TRUE-BLOAN-PF1.2.1")
    _evidence(
        truth,
        evidence_id="EVD-BOOLEAN-LIKE",
        kind=FIELD_EVIDENCE_KIND,
        source_ref="prompt://field=true",
        subject_refs=[BATCH, "field=true", "FIELD"],
    )

    receipt = ReleaseBatchProvenanceService(
        truth, release_id=RELEASE
    ).evaluate(BATCH)

    assert receipt["provenance"] == UNKNOWN
    assert receipt["field_evidence_refs"] == []
    assert receipt["rejected_evidence_refs"] == ["EVD-BOOLEAN-LIKE"]


def test_provenance_persists_canonical_r1_and_identical_evaluation_is_idempotent(
    tmp_path: Path,
):
    truth = _truth(tmp_path)
    _batch(truth)
    _evidence(
        truth,
        evidence_id="EVD-FIELD",
        kind=FIELD_EVIDENCE_KIND,
        source_ref="provider://bank-db/BANK_DB_READ",
        subject_refs=[BATCH],
    )
    service = ReleaseBatchProvenanceService(truth, release_id=RELEASE)

    first = service.evaluate(BATCH)
    second = service.evaluate(BATCH)
    rows = truth.query(
        "rc72_release_batch_provenance",
        provenance_id=first["provenance_id"],
    )

    assert first == second
    assert len(rows) == 1
    assert rows[0]["provenance"] == FIELD
    assert rows[0]["artifact_version"] == 1
    assert len(rows[0]["evidence_digest"]) == 64
