from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_domain import ReleaseBatch, TestObligation
from rc7_runtime.rc72_release_scope import (
    ReleaseScopeManifest,
    ReleaseScopeService,
)
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.rc72_state_machine import RC72StateMachine


def _base(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    runtime = RC72StateMachine(truth, release_id="RC7.2")
    runtime.bootstrap_release_batch(
        ReleaseBatch(
            release_batch_id="RB-1",
            mission_id="M-1",
            name="batch",
            application_ids=["cfg-center"],
            requirement_ids=["REQ-1", "REQ-2"],
        )
    )
    return truth, CanonicalRC72Repository(truth, release_id="RC7.2"), ReleaseScopeService(truth, release_id="RC7.2")


def _manifest():
    return ReleaseScopeManifest(
        manifest_id="SCOPE-1",
        mission_id="M-1",
        release_batch_id="RB-1",
        requirement_ssts={
            "REQ-1": ["SST-1", "SST-2"],
            "REQ-2": ["SST-3"],
        },
        required_levels_by_sst={
            "SST-1": ["L3", "L4"],
            "SST-2": ["L3"],
            "SST-3": ["L3", "L5"],
        },
        source_refs=["starlink://release-batch/RB-1"],
    )


def _obligation(oid: str, req: str, sst: str, level: str):
    return TestObligation(
        obligation_id=oid,
        mission_id="M-1",
        release_batch_id="RB-1",
        requirement_id=req,
        sst_id=sst,
        application_id="cfg-center",
        business_scenario=f"{sst}-{level}",
        business_rule=f"{sst}-{level}-rule",
        risk_level="HIGH" if sst == "SST-1" else "MEDIUM",
        test_level=level,
        code_slice_refs=[f"Service#{sst}:{level}"],
        oracle_refs=["HTTP"],
    )


def test_manifest_requirement_denominator_must_equal_release_batch_scope(tmp_path: Path):
    _, _, service = _base(tmp_path)
    bad = ReleaseScopeManifest(
        manifest_id="SCOPE-BAD",
        mission_id="M-1",
        release_batch_id="RB-1",
        requirement_ssts={"REQ-1": ["SST-1"]},
        required_levels_by_sst={"SST-1": ["L3"]},
        source_refs=["starlink://release-batch/RB-1"],
    )
    with pytest.raises(Exception, match="RELEASE_SCOPE_REQUIREMENT_DENOMINATOR_MISMATCH"):
        service.persist_manifest(bad)


def test_same_sst_cannot_silently_belong_to_two_requirements(tmp_path: Path):
    _, _, service = _base(tmp_path)
    bad = ReleaseScopeManifest(
        manifest_id="SCOPE-BAD",
        mission_id="M-1",
        release_batch_id="RB-1",
        requirement_ssts={"REQ-1": ["SST-X"], "REQ-2": ["SST-X"]},
        required_levels_by_sst={"SST-X": ["L3"]},
        source_refs=["starlink://release-batch/RB-1"],
    )
    with pytest.raises(Exception, match="RELEASE_SCOPE_SST_DUPLICATE_OWNERSHIP"):
        service.persist_manifest(bad)


def test_every_expected_sst_requires_explicit_nonempty_l1_l7_denominator(tmp_path: Path):
    _, _, service = _base(tmp_path)
    bad = ReleaseScopeManifest(
        manifest_id="SCOPE-BAD",
        mission_id="M-1",
        release_batch_id="RB-1",
        requirement_ssts={"REQ-1": ["SST-1"], "REQ-2": ["SST-3"]},
        required_levels_by_sst={"SST-1": ["L3"], "SST-3": []},
        source_refs=["starlink://release-batch/RB-1"],
    )
    with pytest.raises(Exception, match="RELEASE_SCOPE_REQUIRED_LEVELS_INVALID"):
        service.persist_manifest(bad)


def test_missing_sst_cannot_disappear_from_denominator(tmp_path: Path):
    truth, repo, service = _base(tmp_path)
    service.persist_manifest(_manifest())
    repo.persist(_obligation("TO-1-L3", "REQ-1", "SST-1", "L3"))
    repo.persist(_obligation("TO-1-L4", "REQ-1", "SST-1", "L4"))
    repo.persist(_obligation("TO-3-L3", "REQ-2", "SST-3", "L3"))
    repo.persist(_obligation("TO-3-L5", "REQ-2", "SST-3", "L5"))

    snapshot = service.evaluate_denominator(manifest_id="SCOPE-1")
    assert snapshot.denominator_complete is False
    assert snapshot.expected_requirement_count == 2
    assert snapshot.expected_sst_count == 3
    assert snapshot.missing_ssts == ["SST-2"]
    assert "SST-2" not in {row["sst_id"] for row in truth.query("rc72_test_obligation")}


def test_missing_required_level_is_visible_even_when_sst_has_other_cases(tmp_path: Path):
    _, repo, service = _base(tmp_path)
    service.persist_manifest(_manifest())
    repo.persist(_obligation("TO-1-L3", "REQ-1", "SST-1", "L3"))
    repo.persist(_obligation("TO-2-L3", "REQ-1", "SST-2", "L3"))
    repo.persist(_obligation("TO-3-L3", "REQ-2", "SST-3", "L3"))
    repo.persist(_obligation("TO-3-L5", "REQ-2", "SST-3", "L5"))

    snapshot = service.evaluate_denominator(manifest_id="SCOPE-1")
    assert snapshot.denominator_complete is False
    assert snapshot.missing_ssts == []
    assert snapshot.missing_required_levels == {"SST-1": ["L4"]}


def test_out_of_scope_obligation_is_not_ignored(tmp_path: Path):
    _, repo, service = _base(tmp_path)
    service.persist_manifest(_manifest())
    for args in (
        ("TO-1-L3", "REQ-1", "SST-1", "L3"),
        ("TO-1-L4", "REQ-1", "SST-1", "L4"),
        ("TO-2-L3", "REQ-1", "SST-2", "L3"),
        ("TO-3-L3", "REQ-2", "SST-3", "L3"),
        ("TO-3-L5", "REQ-2", "SST-3", "L5"),
        ("TO-ORPHAN", "REQ-1", "SST-UNKNOWN", "L3"),
    ):
        repo.persist(_obligation(*args))

    snapshot = service.evaluate_denominator(manifest_id="SCOPE-1")
    assert snapshot.denominator_complete is False
    assert snapshot.out_of_scope_obligation_ids == ["TO-ORPHAN"]


def test_complete_manifest_and_obligation_denominator_is_persisted_and_replayable(tmp_path: Path):
    truth, repo, service = _base(tmp_path)
    service.persist_manifest(_manifest())
    for args in (
        ("TO-1-L3", "REQ-1", "SST-1", "L3"),
        ("TO-1-L4", "REQ-1", "SST-1", "L4"),
        ("TO-2-L3", "REQ-1", "SST-2", "L3"),
        ("TO-3-L3", "REQ-2", "SST-3", "L3"),
        ("TO-3-L5", "REQ-2", "SST-3", "L5"),
    ):
        repo.persist(_obligation(*args))

    snapshot = service.evaluate_denominator(manifest_id="SCOPE-1")
    assert snapshot.denominator_complete is True
    assert snapshot.expected_requirement_count == 2
    assert snapshot.expected_sst_count == 3
    assert snapshot.expected_required_level_count == 5
    assert snapshot.missing_ssts == []
    assert snapshot.missing_required_levels == {}
    assert snapshot.out_of_scope_obligation_ids == []

    replay = TruthRuntime(tmp_path / "r1.jsonl")
    service.install_overlay()
    manifest = replay.query("rc72_release_scope_manifest", manifest_id="SCOPE-1")[0]
    persisted = replay.query("rc72_scope_denominator_snapshot", snapshot_id=snapshot.snapshot_id)[0]
    assert manifest["requirement_ssts"]["REQ-1"] == ["SST-1", "SST-2"]
    assert persisted["denominator_complete"] is True
    assert persisted["expected_sst_count"] == 3
