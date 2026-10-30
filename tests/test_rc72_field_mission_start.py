import inspect
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_domain import AutonomousMissionNode
from rc7_runtime.rc72_field_mission_start import (
    FieldMissionStartError,
    ReleaseBatchFieldMissionLauncher,
    install_rc72_field_mission_start_overlay,
    start_release_batch_field_mission,
)
from rc7_runtime.rc72_q7_admission import install_rc72_q7_admission_overlay
from rc7_runtime.rc72_truth import install_rc72_truth_overlay
from rc7_runtime.truth_overlay import install_rc7_truth_overlay


COMMIT = "0123456789abcdef0123456789abcdef01234567"
OTHER_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"


def _truth(tmp_path: Path) -> TruthRuntime:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_q7_admission_overlay()
    install_rc72_field_mission_start_overlay()
    return TruthRuntime(tmp_path / "r1.jsonl")


def _batch(
    truth: TruthRuntime,
    *,
    release_id: str,
    mission_id: str,
    batch_id: str,
    name: str,
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
            "application_ids": [name.split("-")[0]],
            "requirement_ids": ["REQ-%s" % batch_id],
            "state": "REGISTERED",
            "readiness": "READY",
            "created_at": 1,
            "updated_at": 1,
            "artifact_version": 1,
        },
    )


def _admission(
    truth: TruthRuntime,
    *,
    release_id: str,
    mission_id: str,
    batch_id: str,
    source_commit: str = COMMIT,
    status: str = "ADMITTED",
    suffix: str = "A",
) -> str:
    admission_id = "Q7ADM-%s-%s" % (batch_id, suffix)
    truth.append_atomic(
        "RC72_Q7_ADMISSION_UPSERTED",
        {
            "admission_id": admission_id,
            "release_id": release_id,
            "mission_id": mission_id,
            "release_batch_id": batch_id,
            "source_commit": source_commit,
            "status": status,
            "reason": "FIELD_PREREQUISITES_COMPLETE" if status == "ADMITTED" else "FIELD_PREREQUISITES_INCOMPLETE",
            "provenance_id": "PROV-%s" % batch_id,
            "scope_snapshot_id": "SCOPE-%s" % batch_id,
            "qualification_receipt_ids": [
                "QUAL-%s-Q3" % batch_id,
                "QUAL-%s-Q4" % batch_id,
                "QUAL-%s-Q5" % batch_id,
                "QUAL-%s-Q6" % batch_id,
            ],
            "hold_reasons": [] if status == "ADMITTED" else ["Q6_NOT_FIELD_PASS"],
            "input_digest": "a" * 64,
            "field_verified": False,
            "bank_final": False,
            "created_at": 1,
            "updated_at": 1,
            "artifact_version": 1,
        },
    )
    return admission_id


@pytest.mark.parametrize(
    "release_id,mission_id,batch_id,name",
    [
        ("PAYMENT-R2.3.4", "MISSION-PAY-R234", "RB-PAY-R234", "PAYMENT-R2.3.4"),
        ("CFG-X9.4.0", "MISSION-CFG-X940", "RB-CFG-X940", "CFG-X9.4.0"),
    ],
)
def test_generic_admitted_release_batch_bootstraps_canonical_n1_n10(
    tmp_path: Path,
    release_id: str,
    mission_id: str,
    batch_id: str,
    name: str,
):
    truth = _truth(tmp_path)
    _batch(
        truth,
        release_id=release_id,
        mission_id=mission_id,
        batch_id=batch_id,
        name=name,
    )
    admission_id = _admission(
        truth,
        release_id=release_id,
        mission_id=mission_id,
        batch_id=batch_id,
    )

    result = ReleaseBatchFieldMissionLauncher(
        truth,
        source_commit=COMMIT,
    ).start(release_batch_id=batch_id)

    assert result["status"] == "STARTED"
    assert result["release_id"] == release_id
    assert result["mission_id"] == mission_id
    assert result["release_batch_id"] == batch_id
    assert result["q7_admission_id"] == admission_id
    assert len(result["mission_node_ids"]) == 10

    nodes = truth.query("rc72_mission_node", mission_id=mission_id)
    assert len(nodes) == 10
    by_type = {row["node_type"]: row for row in nodes}
    assert set(by_type) == {node.value for node in AutonomousMissionNode.ordered()}
    assert all(row["scope_ref"] == "release-batch://%s" % batch_id for row in nodes)
    assert by_type[AutonomousMissionNode.N1_REALITY.value]["state"] == "READY"
    assert all(
        by_type[node.value]["state"] == "NOT_STARTED"
        for node in AutonomousMissionNode.ordered()[1:]
    )


def test_missing_q7_admission_blocks_before_any_mission_node_side_effect(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(
        truth,
        release_id="ORDER-R1.0.0",
        mission_id="MISSION-ORDER-100",
        batch_id="RB-ORDER-100",
        name="ORDER-R1.0.0",
    )

    with pytest.raises(FieldMissionStartError, match="Q7_ADMISSION_NOT_UNIQUE:0"):
        ReleaseBatchFieldMissionLauncher(truth, source_commit=COMMIT).start(
            release_batch_id="RB-ORDER-100"
        )

    assert truth.query("rc72_mission_node", mission_id="MISSION-ORDER-100") == []
    assert truth.query("rc72_field_mission_start_receipt") == []


def test_hold_admission_blocks_before_bootstrap(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(
        truth,
        release_id="LOAN-R7.0.0",
        mission_id="MISSION-LOAN-700",
        batch_id="RB-LOAN-700",
        name="LOAN-R7.0.0",
    )
    _admission(
        truth,
        release_id="LOAN-R7.0.0",
        mission_id="MISSION-LOAN-700",
        batch_id="RB-LOAN-700",
        status="HOLD",
    )

    with pytest.raises(FieldMissionStartError, match="Q7_ADMISSION_HOLD"):
        ReleaseBatchFieldMissionLauncher(truth, source_commit=COMMIT).start(
            release_batch_id="RB-LOAN-700"
        )

    assert truth.query("rc72_mission_node", mission_id="MISSION-LOAN-700") == []


def test_stale_source_commit_admission_cannot_start_current_source(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(
        truth,
        release_id="CARD-R3.1.0",
        mission_id="MISSION-CARD-310",
        batch_id="RB-CARD-310",
        name="CARD-R3.1.0",
    )
    _admission(
        truth,
        release_id="CARD-R3.1.0",
        mission_id="MISSION-CARD-310",
        batch_id="RB-CARD-310",
        source_commit=OTHER_COMMIT,
    )

    with pytest.raises(FieldMissionStartError, match="EXACT_SOURCE_COMMIT_ADMISSION_REQUIRED"):
        ReleaseBatchFieldMissionLauncher(truth, source_commit=COMMIT).start(
            release_batch_id="RB-CARD-310"
        )

    assert truth.query("rc72_mission_node", mission_id="MISSION-CARD-310") == []


def test_cross_batch_admission_cannot_be_reused(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(
        truth,
        release_id="RISK-R4.0.0",
        mission_id="MISSION-RISK-TARGET",
        batch_id="RB-RISK-TARGET",
        name="RISK-R4.0.0-TARGET",
    )
    _batch(
        truth,
        release_id="RISK-R4.0.0",
        mission_id="MISSION-RISK-OTHER",
        batch_id="RB-RISK-OTHER",
        name="RISK-R4.0.0-OTHER",
    )
    _admission(
        truth,
        release_id="RISK-R4.0.0",
        mission_id="MISSION-RISK-OTHER",
        batch_id="RB-RISK-OTHER",
    )

    with pytest.raises(FieldMissionStartError, match="Q7_ADMISSION_NOT_UNIQUE:0"):
        ReleaseBatchFieldMissionLauncher(truth, source_commit=COMMIT).start(
            release_batch_id="RB-RISK-TARGET"
        )

    assert truth.query("rc72_mission_node", mission_id="MISSION-RISK-TARGET") == []


def test_field_entry_has_no_caller_mission_or_release_override_surface():
    function_parameters = inspect.signature(start_release_batch_field_mission).parameters
    method_parameters = inspect.signature(ReleaseBatchFieldMissionLauncher.start).parameters

    assert "mission_id" not in function_parameters
    assert "release_id" not in function_parameters
    assert "mission_id" not in method_parameters
    assert "release_id" not in method_parameters


def test_repeated_start_is_idempotent_and_resumes_same_canonical_nodes(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(
        truth,
        release_id="DEPOSIT-R5.2.0",
        mission_id="MISSION-DEP-520",
        batch_id="RB-DEP-520",
        name="DEPOSIT-R5.2.0",
    )
    _admission(
        truth,
        release_id="DEPOSIT-R5.2.0",
        mission_id="MISSION-DEP-520",
        batch_id="RB-DEP-520",
    )
    launcher = ReleaseBatchFieldMissionLauncher(truth, source_commit=COMMIT)

    first = launcher.start(release_batch_id="RB-DEP-520")
    second = launcher.start(release_batch_id="RB-DEP-520")

    assert first["status"] == "STARTED"
    assert second["status"] == "RESUMED"
    assert first["mission_node_ids"] == second["mission_node_ids"]
    assert first["start_receipt_id"] == second["start_receipt_id"]
    assert len(truth.query("rc72_mission_node", mission_id="MISSION-DEP-520")) == 10
    receipts = truth.query(
        "rc72_field_mission_start_receipt",
        start_receipt_id=first["start_receipt_id"],
    )
    assert len(receipts) == 1
    assert receipts[0]["q7_admission_id"] == first["q7_admission_id"]


def test_bootstrap_does_not_promote_q7_field_or_bank_final_status(tmp_path: Path):
    truth = _truth(tmp_path)
    _batch(
        truth,
        release_id="CONFIG-R6.6.1",
        mission_id="MISSION-CONFIG-661",
        batch_id="RB-CONFIG-661",
        name="CONFIG-R6.6.1",
    )
    _admission(
        truth,
        release_id="CONFIG-R6.6.1",
        mission_id="MISSION-CONFIG-661",
        batch_id="RB-CONFIG-661",
    )

    result = ReleaseBatchFieldMissionLauncher(truth, source_commit=COMMIT).start(
        release_batch_id="RB-CONFIG-661"
    )
    receipt = truth.query(
        "rc72_field_mission_start_receipt",
        start_receipt_id=result["start_receipt_id"],
    )[0]

    for forbidden in ("field_verified", "bank_final", "q7_pass", "q7_status"):
        assert forbidden not in result
        assert forbidden not in receipt
    assert receipt["status"] == "BOOTSTRAPPED"
