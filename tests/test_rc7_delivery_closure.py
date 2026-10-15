import json
from pathlib import Path

from rc7_release.final_qualification import evaluate_final_qualification
from rc7_release.package import PACKAGE_NAME, build_package, verify_package


COMMIT = "a" * 40


def _gate(name):
    return {"gate": name, "status": "PASS", "source_commit": COMMIT}


def _real_mission():
    payload = _gate("REAL_MISSION_PASS")
    payload.update(
        {
            "qualification_kind": "BANK_REAL_MISSION",
            "mission_id": "M-BANK-RC7-QUALIFICATION",
            "mission_state": "CONVERGED",
            "test_sufficiency": "SUFFICIENT",
            "residual_risk_dispositioned": True,
            "r1_event_stream_ref": "evidence/r1/mission.jsonl",
            "evidence_refs": ["EVIDENCE-001", "EVIDENCE-002"],
            "worker_proof": {
                "real_dsh": True,
                "tool_receipts": ["TOOL-RECEIPT-001"],
                "director_did_domain_work": False,
            },
            "session_continuity": {
                "session_ids": ["SESSION-A", "SESSION-B"],
                "same_mission": True,
                "same_task_continuity": True,
                "rotation_observed": True,
            },
            "gap_repair": {
                "gap_id": "GAP-001",
                "repair_task_id": "TASK-REPAIR-001",
                "artifact_before_revision": 1,
                "artifact_after_revision": 2,
                "independent_evaluation_ref": "EVAL-002",
                "gap_closed_by_independent_evaluation": True,
            },
            "defect_flow": {"status": "NOT_TRIGGERED_NO_TRUSTED_FAIL"},
        }
    )
    return payload


def _delivery():
    payload = _gate("DELIVERY_PASS")
    payload.update(
        {
            "package_name": PACKAGE_NAME + "-aaaaaaaaaaaa.zip",
            "package_sha256": "b" * 64,
            "clean_windows_unpack": "PASS",
            "package_verify": "PASS",
            "package_entrypoint_verify": "PASS",
            "admin_startup_verify": "PASS",
        }
    )
    return payload


def test_final_qualification_holds_without_real_mission_and_delivery():
    result = evaluate_final_qualification(
        COMMIT,
        _gate("ENGINEERING_PASS"),
        _gate("ADMIN_PLATFORM_PASS"),
        None,
        None,
    )
    assert result["status"] == "HOLD"
    assert result["gates"]["ENGINEERING_PASS"] == "PASS"
    assert result["gates"]["ADMIN_PLATFORM_PASS"] == "PASS"
    assert result["gates"]["REAL_MISSION_PASS"] == "HOLD"
    assert result["gates"]["DELIVERY_PASS"] == "HOLD"


def test_final_qualification_rejects_stale_commit_evidence():
    mission = _real_mission()
    mission["source_commit"] = "c" * 40
    result = evaluate_final_qualification(
        COMMIT,
        _gate("ENGINEERING_PASS"),
        _gate("ADMIN_PLATFORM_PASS"),
        mission,
        _delivery(),
    )
    assert result["status"] == "HOLD"
    assert "REAL_MISSION_PASS:SOURCE_COMMIT_MISMATCH" in result["blocking_reasons"]


def test_final_qualification_requires_real_session_rotation_and_gap_repair():
    mission = _real_mission()
    mission["session_continuity"]["session_ids"] = ["SESSION-A"]
    mission["session_continuity"]["rotation_observed"] = False
    mission["gap_repair"]["artifact_after_revision"] = 1
    mission["gap_repair"]["gap_closed_by_independent_evaluation"] = False
    result = evaluate_final_qualification(
        COMMIT,
        _gate("ENGINEERING_PASS"),
        _gate("ADMIN_PLATFORM_PASS"),
        mission,
        _delivery(),
    )
    assert result["status"] == "HOLD"
    assert "REAL_MISSION_PASS:SESSION_ROTATION_NOT_PROVEN" in result["blocking_reasons"]
    assert "REAL_MISSION_PASS:ROTATION_EVENT_NOT_PROVEN" in result["blocking_reasons"]
    assert "REAL_MISSION_PASS:ARTIFACT_REVISION_DID_NOT_ADVANCE" in result["blocking_reasons"]
    assert "REAL_MISSION_PASS:GAP_NOT_CLOSED_BY_EVALUATION" in result["blocking_reasons"]


def test_final_qualification_passes_only_with_all_current_reality_evidence():
    result = evaluate_final_qualification(
        COMMIT,
        _gate("ENGINEERING_PASS"),
        _gate("ADMIN_PLATFORM_PASS"),
        _real_mission(),
        _delivery(),
    )
    assert result["status"] == "PASS"
    assert set(result["gates"].values()) == {"PASS"}
    assert result["blocking_reasons"] == []
    assert result["durable_truth"] == "R1_EVENT_STREAM"
    assert result["plan_complete_is_test_sufficient"] is False
    assert result["workflow_complete_is_mission_complete"] is False


def test_rc7_turnkey_package_preserves_launcher_layout_and_never_forges_bank_pass(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    package_root = build_package(repo, tmp_path, COMMIT, make_zip=True)
    result = verify_package(package_root)
    assert result["status"] == "PASS"
    assert result["source_commit"] == COMMIT
    assert (package_root / "packaging" / "rc7" / "QUALIFY-FINAL.cmd").is_file()
    assert (package_root / "packaging" / "rc7" / "QUALIFY-EXECUTION.sh").is_file()
    assert (package_root / ".dsh" / "skills" / "pfc-full-chain-test" / "SKILL.md").is_file()

    manifest = json.loads((package_root / "PACKAGE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["source_commit"] == COMMIT
    assert manifest["durable_truth"] == "R1_EVENT_STREAM"
    assert manifest["version_policy"] == "CAPABILITY_BASED_NO_EXACT_VERSION_PIN"
    assert manifest["real_mission_pass"] is False
    assert manifest["delivery_pass"] is False
    assert manifest["bank_field_pass"] is False

    zip_path = tmp_path / (PACKAGE_NAME + "-aaaaaaaaaaaa.zip")
    checksum_path = Path(str(zip_path) + ".sha256")
    assert zip_path.is_file()
    assert checksum_path.is_file()
