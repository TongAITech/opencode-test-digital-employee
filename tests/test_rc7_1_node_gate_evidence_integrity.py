from __future__ import annotations

import pytest

from rc6_runtime.truth import EventValidationError, TruthRuntime
from rc7_runtime.models import Evaluation, EvaluationResult, Evidence, Mission
from rc7_runtime.truth_overlay import append_entity


RELEASE = "RC7.1-NODE-GATE-EVIDENCE"
M1 = "MISSION-NODE-GATE-EVIDENCE-1"
M2 = "MISSION-NODE-GATE-EVIDENCE-2"


def _truth(tmp_path):
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    append_entity(truth, Mission(mission_id=M1, release_id=RELEASE, goal="node gate evidence owner"), release_id=RELEASE)
    append_entity(truth, Mission(mission_id=M2, release_id=RELEASE, goal="foreign evidence owner"), release_id=RELEASE)
    return truth


def _gate_evaluation(evaluation_id: str, mission_id: str, evidence_id: str):
    return Evaluation(
        evaluation_id=evaluation_id,
        mission_id=mission_id,
        node="AUTONOMOUS_NODE_GATE",
        artifact_refs=[],
        result=EvaluationResult.REPAIR_REQUIRED,
        evaluator_ref="director-runtime-authority",
        dimensions={"decision": "REJECT"},
        gap_refs=[],
        evidence_refs=[evidence_id],
    )


def test_node_gate_rejects_nonexistent_evidence(tmp_path) -> None:
    truth = _truth(tmp_path)
    with pytest.raises(EventValidationError, match="NODE_GATE_EVIDENCE_NOT_UNIQUE"):
        append_entity(
            truth,
            _gate_evaluation("EVAL-GATE-MISSING", M1, "EVD-DOES-NOT-EXIST"),
            release_id=RELEASE,
        )


def test_node_gate_rejects_evidence_from_another_mission(tmp_path) -> None:
    truth = _truth(tmp_path)
    evidence = Evidence(
        evidence_id="EVD-FOREIGN",
        mission_id=M2,
        kind="DIRECTOR_REVIEW_PROOF",
        source_ref="runtime://director-review",
        content_ref="runtime://proof/foreign",
        subject_refs=["NODE-N2"],
    )
    append_entity(truth, evidence, release_id=RELEASE)

    with pytest.raises(EventValidationError, match="NODE_GATE_EVIDENCE_MISSION_MISMATCH"):
        append_entity(
            truth,
            _gate_evaluation("EVAL-GATE-FOREIGN", M1, evidence.evidence_id),
            release_id=RELEASE,
        )


def test_node_gate_accepts_current_mission_durable_evidence(tmp_path) -> None:
    truth = _truth(tmp_path)
    evidence = Evidence(
        evidence_id="EVD-CURRENT",
        mission_id=M1,
        kind="DIRECTOR_REVIEW_PROOF",
        source_ref="runtime://director-review",
        content_ref="runtime://proof/current",
        subject_refs=["NODE-N3"],
    )
    append_entity(truth, evidence, release_id=RELEASE)
    append_entity(
        truth,
        _gate_evaluation("EVAL-GATE-CURRENT", M1, evidence.evidence_id),
        release_id=RELEASE,
    )
    rows = truth.query("rc7_evaluation", evaluation_id="EVAL-GATE-CURRENT")
    assert len(rows) == 1
    assert rows[0]["evidence_refs"] == [evidence.evidence_id]
