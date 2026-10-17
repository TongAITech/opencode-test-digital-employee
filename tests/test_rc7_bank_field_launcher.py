from __future__ import annotations

import json
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_release.bank_field_launcher import resolve_context
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.models import Evidence
from rc7_runtime.truth_overlay import append_entity


def _qual(root: Path) -> Path:
    path = root / "qualification"
    path.mkdir(parents=True, exist_ok=True)
    for name in ("engineering.json", "admin.json", "delivery.json"):
        (path / name).write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    return path


def _mission(root: Path, mission_id: str, target_id: str) -> Path:
    r1 = root / "runtime-state" / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id="REL-1",
        goal="field qualification",
        graph_version="v2",
    )
    truth = TruthRuntime(r1)
    record_path = root / "runtime-state" / "formal-execution" / mission_id / "attempt.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps({"record": {"target_id": target_id}}, sort_keys=True),
        encoding="utf-8",
    )
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-FORMAL-" + mission_id,
            mission_id=mission_id,
            kind="RUNTIME_EXECUTION_RECORD",
            source_ref="runtime://formal-execution",
            content_ref="file://" + str(record_path),
            subject_refs=["TASK-X", "ATTEMPT-X", "TC-X", target_id],
        ),
        release_id="REL-1",
        artifact_version=1,
    )
    return r1


def test_launcher_auto_resolves_only_unique_mission_and_formal_target(tmp_path: Path) -> None:
    _qual(tmp_path)
    r1 = _mission(tmp_path, "MISSION-ONE", "TARGET-ONE")

    result = resolve_context(package_root=str(tmp_path))

    assert result["status"] == "PASS"
    assert result["stage"] == "READY_FOR_BANK_FINAL"
    assert result["mission_id"] == "MISSION-ONE"
    assert result["bank_target_id"] == "TARGET-ONE"
    assert result["target_proven_by_formal_execution"] is True
    assert Path(result["r1_path"]) == r1.resolve()
    assert result["selection_policy"] == "UNIQUE_ONLY_NEVER_LATEST_WINS"


def test_launcher_refuses_to_guess_between_multiple_bank_missions(tmp_path: Path) -> None:
    _qual(tmp_path)
    r1 = _mission(tmp_path, "MISSION-A", "TARGET-A")
    start_or_resume(
        r1_path=str(r1),
        mission_id="MISSION-B",
        release_id="REL-1",
        goal="field qualification",
        graph_version="v2",
    )

    result = resolve_context(package_root=str(tmp_path))

    assert result["status"] == "HOLD"
    assert result["reason"] == "BANK_MISSION_CONTEXT_AMBIGUOUS"
    assert {row["mission"]["mission_id"] for row in result["candidates"]} == {"MISSION-A", "MISSION-B"}


def test_launcher_accepts_explicit_mission_but_rejects_unproven_target(tmp_path: Path) -> None:
    _qual(tmp_path)
    r1 = _mission(tmp_path, "MISSION-A", "TARGET-A")
    start_or_resume(
        r1_path=str(r1),
        mission_id="MISSION-B",
        release_id="REL-1",
        goal="field qualification",
        graph_version="v2",
    )

    selected = resolve_context(
        package_root=str(tmp_path),
        mission_id="MISSION-A",
    )
    assert selected["status"] == "PASS"
    assert selected["bank_target_id"] == "TARGET-A"

    rejected = resolve_context(
        package_root=str(tmp_path),
        mission_id="MISSION-A",
        target_id="TARGET-WRONG",
    )
    assert rejected["status"] == "HOLD"
    assert rejected["reason"] == "BANK_TARGET_NOT_PROVEN_BY_MISSION_EXECUTION"
    assert rejected["target_candidates"] == ["TARGET-A"]


def test_launcher_requires_complete_delivery_qualification(tmp_path: Path) -> None:
    _mission(tmp_path, "MISSION-ONE", "TARGET-ONE")
    partial = tmp_path / "qualification"
    partial.mkdir()
    (partial / "engineering.json").write_text("{}", encoding="utf-8")

    result = resolve_context(package_root=str(tmp_path))

    assert result["status"] == "FIELD_REQUIRED"
    assert result["reason"] == "DELIVERY_QUALIFICATION_DIRECTORY_NOT_READY"
    assert "admin.json" in result["qualification_candidates"][0]["missing"]
