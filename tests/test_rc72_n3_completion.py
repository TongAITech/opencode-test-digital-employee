from pathlib import Path

import pytest

from rc7_runtime.dsh_code_evaluator import DshCodeEvaluator
from rc7_runtime.rc72_n3_code_analysis_anchor import N3CodeAnalysisEvidenceAnchorService
from rc7_runtime.rc72_n3_code_analysis_handoff import N3CodeAnalysisDshHandoffService
from rc7_runtime.rc72_n3_code_analysis_promotion import N3CodeAnalysisCandidatePromotionService
from rc7_runtime.rc72_n3_code_analysis_review import N3CodeAnalysisReviewService
from rc7_runtime.rc72_n3_completion import N3CompletionError, N3DeliveryGateService

from rc72_n2_test_support import BATCH, COMMIT, MISSION, RELEASE, REQUIREMENTS
from test_rc72_n3_code_analysis_handoff import _ready
import test_rc72_n3_real_code_gate_integration as gate_support


_ORIGINAL_GATE_READY_CANDIDATE = gate_support._gate_ready_candidate


def _canonical_candidate(row):
    candidate = _ORIGINAL_GATE_READY_CANDIDATE(row)
    candidate["requirement_ids"] = list(REQUIREMENTS)
    candidate["reverse_requirement_mappings"] = [
        {
            "requirement_id": requirement_id,
            "symbol": gate_support._CHANGED_SYMBOL,
            "evidence_ref": "tool://codegraph/%s" % row["target_id"],
        }
        for requirement_id in REQUIREMENTS
    ]
    return candidate


def _promoted_gate_ready(tmp_path: Path, monkeypatch):
    truth, _dispatched, assigned = _ready(tmp_path)
    row = assigned["assignments"][0]
    monkeypatch.setattr(gate_support, "_gate_ready_candidate", _canonical_candidate)
    N3CodeAnalysisDshHandoffService(
        truth,
        source_commit=COMMIT,
        launcher=gate_support._analyzer_launcher(tmp_path, truth, row),
    ).handoff(release_batch_id=BATCH, target_id=row["target_id"])
    N3CodeAnalysisEvidenceAnchorService(
        truth,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n3-code"),
    ).anchor(release_batch_id=BATCH, target_id=row["target_id"])
    promoted = N3CodeAnalysisCandidatePromotionService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        state_root=str(tmp_path / "state-n3-code"),
    ).promote(release_batch_id=BATCH, target_id=row["target_id"])
    return truth, row, promoted


def _review_gate_ready(tmp_path: Path, monkeypatch):
    truth, row, promoted = _promoted_gate_ready(tmp_path, monkeypatch)
    reviewed = N3CodeAnalysisReviewService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        evaluator=DshCodeEvaluator(
            gate_support._reviewer_launcher(tmp_path, truth),
            reviewer_allowed_tools=("git", "codegraph"),
        ),
    ).review(release_batch_id=BATCH, target_id=row["target_id"])
    assert reviewed["task_state"] == "PASS"
    return truth, row, promoted, reviewed


def test_n3_complete_requires_full_real_gate_then_releases_n4(tmp_path: Path, monkeypatch):
    truth, row, promoted, reviewed = _review_gate_ready(tmp_path, monkeypatch)
    result = N3DeliveryGateService(
        truth, source_commit=COMMIT
    ).complete(release_batch_id=BATCH)

    assert result["delivery"]["status"] == "DELIVERY_ADMITTED"
    assert result["delivery"]["target_count"] == 1
    assert result["delivery"]["passed_target_count"] == 1
    assert result["gate"]["decision"] == "PASS"
    assert result["gate"]["failed"] == []
    assert result["gate"]["n3_state"] == "PASS"
    assert result["gate"]["n4_state"] == "READY"

    delivery = truth.query(
        "rc72_node_delivery", delivery_id=result["delivery"]["delivery_id"]
    )[0]
    assert delivery["artifact_refs"] == [promoted["artifact_id"]]
    assert delivery["created_by_workitems"] == [promoted["task_id"]]
    assert delivery["known_gaps"] == []
    assert delivery["sufficiency_score"] == 1.0
    assert any(ref.startswith("n3-anchor://") for ref in delivery["input_refs"])
    assert "evaluation://%s" % reviewed["evaluation_id"] in delivery["input_refs"]

    gate = truth.query("rc72_node_gate", gate_id=result["gate"]["gate_id"])[0]
    assert gate["decision"] == "PASS"
    assert gate["failed"] == []
    assert "N3_REAL_GIT_PROOF" in gate["passed"]
    assert "N3_REQUIRED_CODEGRAPH_PROOF" in gate["passed"]
    assert "N3_FRESH_REVIEW_SESSION" in gate["passed"]
    assert "N3_IMPACT_SUFFICIENCY_V2_PASS" in gate["passed"]
    assert "N3_CANONICAL_REQUIREMENT_REVERSE_MAPPING" in gate["passed"]

    n3 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    )[0]
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    assert n3["state"] == "PASS"
    assert n4["state"] == "READY"
    transitions = [
        row
        for row in truth.query("rc72_node_transition", mission_id=MISSION)
        if row.get("from_node_type") == "N3_CODE_ANALYSIS"
        and row.get("to_node_type") == "N4_TEST_DESIGN"
    ]
    assert len(transitions) == 1
    assert transitions[0]["source_gate_id"] == gate["gate_id"]

    replay = N3DeliveryGateService(
        truth, source_commit=COMMIT
    ).complete(release_batch_id=BATCH)
    assert replay["delivery"]["status"] == "RESUMED"
    assert replay["gate"]["status"] == "RESUMED"
    assert replay["gate"]["decision"] == "PASS"
    assert replay["gate"]["n4_state"] == "READY"
    assert len(
        [
            row
            for row in truth.query("rc72_node_transition", mission_id=MISSION)
            if row.get("from_node_type") == "N3_CODE_ANALYSIS"
            and row.get("to_node_type") == "N4_TEST_DESIGN"
        ]
    ) == 1


def test_legacy_shallow_analysis_can_be_delivered_but_n3_needs_revision_and_n4_stays_locked(
    tmp_path: Path,
):
    from test_rc72_n3_code_analysis_review import _ready_for_review

    truth, assignment, _anchor, promoted = _ready_for_review(tmp_path)
    reviewed = N3CodeAnalysisReviewService(
        truth,
        release_id=RELEASE,
        mission_id=MISSION,
        source_commit=COMMIT,
        evaluator=DshCodeEvaluator(
            gate_support._reviewer_launcher(tmp_path, truth),
            reviewer_allowed_tools=("git", "codegraph"),
        ),
    ).review(release_batch_id=BATCH, target_id=assignment["target_id"])
    assert reviewed["task_state"] == "REPAIR_REQUIRED"

    result = N3DeliveryGateService(
        truth, source_commit=COMMIT
    ).complete(release_batch_id=BATCH)

    assert result["delivery"]["status"] == "DELIVERY_ADMITTED"
    assert result["delivery"]["passed_target_count"] == 0
    assert result["gate"]["decision"] == "NEEDS_REVISION"
    assert result["gate"]["n3_state"] == "NEEDS_REVISION"
    assert result["gate"]["n4_state"] == "NOT_STARTED"
    assert "N3_ALL_CODE_TASKS_PASS" in result["gate"]["failed"]
    assert "N3_ALL_CODE_EVALUATIONS_PASS" in result["gate"]["failed"]
    assert "N3_IMPACT_SUFFICIENCY_V2_PASS" in result["gate"]["failed"]
    assert "N3_CANONICAL_REQUIREMENT_REVERSE_MAPPING" in result["gate"]["failed"]
    assert truth.query(
        "rc72_node_transition",
        mission_id=MISSION,
        from_node_type="N3_CODE_ANALYSIS",
        to_node_type="N4_TEST_DESIGN",
    ) == []
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    assert n4["state"] == "NOT_STARTED"


def test_n3_delivery_is_forbidden_until_every_target_has_independent_review(
    tmp_path: Path, monkeypatch
):
    truth, row, promoted = _promoted_gate_ready(tmp_path, monkeypatch)
    assert truth.query(
        "rc7_task", task_id=promoted["task_id"]
    )[0]["state"] == "OUTPUT_PRODUCED"

    with pytest.raises(
        N3CompletionError,
        match="REVIEW_INCOMPLETE",
    ):
        N3DeliveryGateService(
            truth, source_commit=COMMIT
        ).admit_delivery(release_batch_id=BATCH)

    assert truth.query(
        "rc72_node_delivery", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    ) == []
    assert truth.query(
        "rc72_node_gate", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    ) == []
    n3 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N3_CODE_ANALYSIS"
    )[0]
    n4 = truth.query(
        "rc72_mission_node", mission_id=MISSION, node_type="N4_TEST_DESIGN"
    )[0]
    assert n3["state"] == "RUNNING"
    assert n4["state"] == "NOT_STARTED"
