from __future__ import annotations

from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_release.real_mission_qualification_strict import evaluate_real_mission_strict
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.models import Task
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay


COMMIT = "e" * 40


def _start(tmp_path: Path, monkeypatch, *, mission_id: str, graph_version: str):
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", COMMIT)
    r1 = tmp_path / mission_id / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id=mission_id,
        release_id="REL-BANK-FIELD",
        goal="qualify bank field contracts",
        graph_version=graph_version,
    )
    return r1


def test_bank_final_strict_mode_requires_real_execution_recovery_before_pass(tmp_path, monkeypatch):
    r1 = _start(tmp_path, monkeypatch, mission_id="MISSION-BANK-V2", graph_version="v2")
    result = evaluate_real_mission_strict(
        r1_path=str(r1),
        mission_id="MISSION-BANK-V2",
        source_commit=COMMIT,
        require_bank_field_conformance=True,
    )

    field = result["bank_field_conformance"]
    assert result["bank_field_conformance_required"] is True
    assert field["mission_conformance"]["status"] == "PASS"
    assert field["node_tool_contract"] == "PASS"
    assert field["execution_recovery_contract"] == "PASS"
    assert field["canonical_execution_task_id"]
    assert field["execution_recovery_conformance"]["status"] == "FAIL"
    assert field["actual_result_oracle_conformance"]["status"] == "FAIL"
    assert field["defect_review_conformance"]["status"] == "PASS"
    assert field["defect_review_conformance"]["triggered"] is False
    assert any(
        reason.startswith("BANK_FIELD_EXECUTION_RECOVERY_FAILED:")
        for reason in result["blocking_reasons"]
    )
    assert result["status"] == "HOLD"


def test_dynamic_defect_execution_tasks_do_not_replace_canonical_graph_execution(tmp_path, monkeypatch):
    mission_id = "MISSION-BANK-V2-DYNAMIC-DEFECT"
    r1 = _start(tmp_path, monkeypatch, mission_id=mission_id, graph_version="v2")
    install_rc7_truth_overlay()
    truth = TruthRuntime(r1)
    append_entity(
        truth,
        Task(
            task_id="TASK-DYNAMIC-DEFECT-REPRODUCTION",
            mission_id=mission_id,
            node="EXECUTION",
            task_type="DEFECT_REPRODUCTION",
            objective="dynamic defect reproduction must not become canonical graph execution",
            gap_refs=["GAP-DYNAMIC-PRODUCT-DEFECT"],
        ),
        release_id="REL-BANK-FIELD",
    )

    result = evaluate_real_mission_strict(
        r1_path=str(r1),
        mission_id=mission_id,
        source_commit=COMMIT,
        require_bank_field_conformance=True,
    )
    field = result["bank_field_conformance"]
    canonical = field["canonical_execution_task_id"]
    assert canonical
    assert canonical != "TASK-DYNAMIC-DEFECT-REPRODUCTION"
    rows = TruthRuntime(r1).query("rc7_task", task_id=canonical)
    assert len(rows) == 1
    assert rows[0]["node"] == "EXECUTION"
    assert not any(
        reason.startswith("BANK_FIELD_EXECUTION_TASK_NOT_UNIQUE")
        for reason in result["blocking_reasons"]
    )


def test_old_v1_mission_remains_resumable_but_cannot_certify_bank_final(tmp_path, monkeypatch):
    r1 = _start(tmp_path, monkeypatch, mission_id="MISSION-BANK-V1", graph_version="v1")

    resumed = start_or_resume(
        r1_path=str(r1),
        mission_id="MISSION-BANK-V1",
        release_id="REL-BANK-FIELD",
        goal="qualify bank field contracts",
    )
    assert resumed["status"] == "RESUMED"
    assert resumed["graph_version"] == "v1"
    assert resumed["node_tool_contract_enabled"] is False
    assert resumed["execution_recovery_contract_enabled"] is False

    result = evaluate_real_mission_strict(
        r1_path=str(r1),
        mission_id="MISSION-BANK-V1",
        source_commit=COMMIT,
        require_bank_field_conformance=True,
    )
    field = result["bank_field_conformance"]
    assert field["node_tool_contract"] == "HOLD"
    assert field["execution_recovery_contract"] == "HOLD"
    assert "BANK_FIELD_NODE_TOOL_CONTRACT_REQUIRED" in result["blocking_reasons"]
    assert "BANK_FIELD_EXECUTION_RECOVERY_CONTRACT_REQUIRED" in result["blocking_reasons"]
    assert result["status"] == "HOLD"


def test_bank_final_entrypoints_enable_field_conformance_only_for_bank_final():
    repo = Path(__file__).resolve().parents[1]
    bank_sh = (repo / "packaging" / "rc7" / "QUALIFY-BANK-FINAL.sh").read_text(encoding="utf-8")
    bank_cmd = (repo / "packaging" / "rc7" / "QUALIFY-BANK-FINAL.cmd").read_text(encoding="utf-8")
    final_sh = (repo / "packaging" / "rc7" / "QUALIFY-FINAL.sh").read_text(encoding="utf-8")
    final_cmd = (repo / "packaging" / "rc7" / "QUALIFY-FINAL.cmd").read_text(encoding="utf-8")

    assert "PFC_RC7_REQUIRE_BANK_FIELD_CONFORMANCE=1" in bank_sh
    assert 'set "PFC_RC7_REQUIRE_BANK_FIELD_CONFORMANCE=1"' in bank_cmd
    assert "--require-bank-field-conformance" in final_sh
    assert "--require-bank-field-conformance" in final_cmd
