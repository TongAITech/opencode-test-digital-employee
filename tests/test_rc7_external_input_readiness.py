from __future__ import annotations

from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.control_plane import TaskScheduler
from rc7_runtime.models import Artifact, ArtifactStatus
from rc7_runtime.truth_overlay import append_entity


def _scheduler(tmp_path: Path) -> TaskScheduler:
    return TaskScheduler(TruthRuntime(tmp_path / "r1.jsonl"), "REL-EXT-INPUT")


def test_governed_external_mission_refs_are_ready_inputs(tmp_path: Path) -> None:
    scheduler = _scheduler(tmp_path)
    assert scheduler._inputs_valid(
        [
            "file:///requirements/design.md",
            "git://didi/AgileTC@8604b4bedb55b3611035aa4ba3781df4118aa4f2",
            "git-empty-tree://4b825dc642cb6eb9a060e54bf8d69288fbee4904",
            "sst://STB913-14130",
            "starlink://release/BLOAN-PF1.2.0",
        ]
    )


def test_unknown_or_bare_external_refs_fail_closed(tmp_path: Path) -> None:
    scheduler = _scheduler(tmp_path)
    assert not scheduler._inputs_valid(["ART-NOT-PERSISTED"])
    assert not scheduler._inputs_valid(["README.md"])
    assert not scheduler._inputs_valid(["ftp://uncontrolled/source"])
    assert not scheduler._inputs_valid(["file://"])


def test_persisted_artifact_must_still_be_valid(tmp_path: Path) -> None:
    scheduler = _scheduler(tmp_path)
    artifact = Artifact(
        artifact_id="ART-VALID",
        mission_id="MISSION-EXT",
        artifact_type="SOURCE",
        producer_task_id="TASK-SOURCE",
        content_ref="file:///tmp/source.json",
    )
    append_entity(scheduler.truth, artifact, release_id="REL-EXT-INPUT", artifact_version=1)
    assert scheduler._inputs_valid(["ART-VALID"])

    stale = Artifact(
        artifact_id="ART-STALE",
        mission_id="MISSION-EXT",
        artifact_type="SOURCE",
        producer_task_id="TASK-SOURCE",
        content_ref="file:///tmp/stale.json",
        state=ArtifactStatus.STALE,
    )
    append_entity(scheduler.truth, stale, release_id="REL-EXT-INPUT", artifact_version=1)
    assert not scheduler._inputs_valid(["ART-STALE"])
