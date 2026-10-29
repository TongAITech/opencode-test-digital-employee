from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_evaluator_amplification import (
    EvaluatorAmplificationAuditService,
    EvaluatorAmplificationProofStatus,
)
from rc7_runtime.rc72_model_usage import TokenUsageAuditService


RELEASE = "RC7.2"
MISSION = "M-1"
NODE = "MN-N4"
DELIVERY = "ND-N4-V1"


def _truth(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    audit = EvaluatorAmplificationAuditService(truth, release_id=RELEASE)
    return truth, audit


def _append_review(
    truth: TruthRuntime,
    *,
    review_id: str,
    worker_id: str,
    session_id: str,
    created_at: int,
    delivery_id: str = DELIVERY,
    node_id: str = NODE,
    runtime_assignment_id=None,
    runtime_attempt_id=None,
    dsh_session_id=None,
):
    context = {
        "mission_id": MISSION,
        "team_id": "TEAM-1",
        "mission_node_id": node_id,
        "delivery_id": delivery_id,
        "criteria": ["evidence backed"],
        "evidence_refs": ["EVD-1"],
    }
    truth.append_atomic(
        "RC72_WORKER_SESSION_UPSERTED",
        {
            "session_id": session_id,
            "worker_id": worker_id,
            "mission_id": MISSION,
            "release_id": RELEASE,
            "release_batch_id": "RB-1",
            "team_id": "TEAM-1",
            "role": "quality-reviewer",
            "purpose": "REVIEW",
            "mission_node_id": node_id,
            "delivery_id": delivery_id,
            "state": "ACTIVE",
            "context_bundle": context,
            "parent_session_id": None,
            "checkpoint_id": None,
            "close_reason": None,
            "runtime_worker_id": worker_id if runtime_assignment_id else None,
            "runtime_assignment_id": runtime_assignment_id,
            "task_lease_ref": None,
            "runtime_attempt_id": runtime_attempt_id,
            "dsh_session_id": dsh_session_id,
            "binding_id": None,
            "created_at": created_at,
            "closed_at": None,
            "artifact_version": 1,
        },
    )
    truth.append_atomic(
        "RC72_REVIEWER_ASSIGNMENT_UPSERTED",
        {
            "review_id": review_id,
            "worker_id": worker_id,
            "session_id": session_id,
            "team_id": "TEAM-1",
            "mission_id": MISSION,
            "release_id": RELEASE,
            "mission_node_id": node_id,
            "delivery_id": delivery_id,
            "criteria": ["evidence backed"],
            "evidence_refs": ["EVD-1"],
            "context_bundle": context,
            "created_at": created_at,
            "artifact_version": 1,
        },
    )


def _observe(
    truth: TruthRuntime,
    *,
    assignment_id: str,
    attempt_id: str,
    dsh_session_id: str,
    total_tokens=None,
):
    usage = TokenUsageAuditService(truth, release_id=RELEASE)
    if total_tokens is None:
        events = [{"type": "response.completed", "message": "usage not exposed"}]
    else:
        input_tokens = max(1, total_tokens - 20)
        output_tokens = total_tokens - input_tokens
        events = [
            {
                "type": "response.completed",
                "provider": "bank-model-provider",
                "model": "bank-model",
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                },
            }
        ]
    return usage.observe(
        mission_id=MISSION,
        attempt_id=attempt_id,
        assignment_id=assignment_id,
        raw_output_ref="file://raw/%s.jsonl" % assignment_id,
        events=events,
        dsh_session_id=dsh_session_id,
    )


def test_repeated_reviewer_assignments_are_degraded_without_guessing_usage(tmp_path: Path):
    truth, audit = _truth(tmp_path)
    _append_review(
        truth,
        review_id="REV-1",
        worker_id="REVWRK-1",
        session_id="REVSES-1",
        created_at=1,
    )
    _append_review(
        truth,
        review_id="REV-2",
        worker_id="REVWRK-2",
        session_id="REVSES-2",
        created_at=2,
    )

    report = audit.report(MISSION)

    assert report.reviewer_assignment_count == 2
    assert report.repeated_subject_count == 1
    assert report.unresolved_assignment_count == 2
    assert report.total_tokens is None
    assert report.qualification.status == "DEGRADED"
    assert report.qualification.reason == "EVALUATOR_ASSIGNMENT_AMPLIFICATION_OBSERVED"
    assert report.qualification.mission_progress_allowed is True
    subject = report.subjects[0]
    assert subject.proof_status == EvaluatorAmplificationProofStatus.UNKNOWN
    assert "REPEATED_EVALUATOR_ASSIGNMENT" in subject.signals
    assert "EVALUATOR_USAGE_LINEAGE_UNRESOLVED" in subject.signals
    assert {row["reason"] for row in report.unresolved_assignments} == {
        "REVIEWER_RUNTIME_ASSIGNMENT_MISSING"
    }


def test_canonical_reviewer_runtime_lineage_measures_token_amplification(tmp_path: Path):
    truth, audit = _truth(tmp_path)
    _append_review(
        truth,
        review_id="REV-1",
        worker_id="REVWRK-1",
        session_id="REVSES-1",
        created_at=1,
        runtime_assignment_id="ASSIGN-1",
        runtime_attempt_id="ATT-1",
        dsh_session_id="DSH-1",
    )
    _append_review(
        truth,
        review_id="REV-2",
        worker_id="REVWRK-2",
        session_id="REVSES-2",
        created_at=2,
        runtime_assignment_id="ASSIGN-2",
        runtime_attempt_id="ATT-2",
        dsh_session_id="DSH-2",
    )
    _observe(
        truth,
        assignment_id="ASSIGN-1",
        attempt_id="ATT-1",
        dsh_session_id="DSH-1",
        total_tokens=100,
    )
    _observe(
        truth,
        assignment_id="ASSIGN-2",
        attempt_id="ATT-2",
        dsh_session_id="DSH-2",
        total_tokens=80,
    )

    report = audit.report(MISSION)
    subject = report.subjects[0]

    assert subject.proof_status == EvaluatorAmplificationProofStatus.MEASURED
    assert subject.resolved_usage_count == 2
    assert subject.measured_usage_count == 2
    assert subject.unresolved_usage_count == 0
    assert subject.measured_total_tokens == 180
    assert subject.total_tokens == 180
    assert subject.first_review_tokens == 100
    assert subject.repeated_review_tokens == 80
    assert subject.token_amplification_factor == 1.8
    assert report.total_tokens == 180
    assert report.qualification.status == "DEGRADED"


def test_unknown_evaluator_usage_remains_unknown_never_zero(tmp_path: Path):
    truth, audit = _truth(tmp_path)
    _append_review(
        truth,
        review_id="REV-1",
        worker_id="REVWRK-1",
        session_id="REVSES-1",
        created_at=1,
        runtime_assignment_id="ASSIGN-1",
        runtime_attempt_id="ATT-1",
        dsh_session_id="DSH-1",
    )
    receipt = _observe(
        truth,
        assignment_id="ASSIGN-1",
        attempt_id="ATT-1",
        dsh_session_id="DSH-1",
        total_tokens=None,
    )
    assert receipt["observation_status"] == "UNKNOWN"
    assert receipt["total_tokens"] is None

    report = audit.report(MISSION)
    subject = report.subjects[0]

    assert subject.proof_status == EvaluatorAmplificationProofStatus.UNKNOWN
    assert subject.unknown_usage_count == 1
    assert subject.total_tokens is None
    assert subject.token_amplification_factor is None
    assert "EVALUATOR_TOKEN_USAGE_UNKNOWN" in subject.signals
    assert report.total_tokens is None
    assert report.qualification.status == "UNKNOWN"
    assert report.qualification.mission_progress_allowed is True


def test_attempt_mismatch_is_unresolved_instead_of_misattributed(tmp_path: Path):
    truth, audit = _truth(tmp_path)
    _append_review(
        truth,
        review_id="REV-1",
        worker_id="REVWRK-1",
        session_id="REVSES-1",
        created_at=1,
        runtime_assignment_id="ASSIGN-1",
        runtime_attempt_id="ATT-EXPECTED",
        dsh_session_id="DSH-1",
    )
    _observe(
        truth,
        assignment_id="ASSIGN-1",
        attempt_id="ATT-OTHER",
        dsh_session_id="DSH-1",
        total_tokens=120,
    )

    report = audit.report(MISSION)

    assert report.resolved_usage_count == 0
    assert report.unresolved_assignment_count == 1
    assert report.total_tokens is None
    assert report.unresolved_assignments[0]["reason"] == "REVIEWER_TOKEN_USAGE_ATTEMPT_MISMATCH"
    assert report.qualification.status == "UNKNOWN"


def test_single_fully_measured_review_passes_without_amplification(tmp_path: Path):
    truth, audit = _truth(tmp_path)
    _append_review(
        truth,
        review_id="REV-1",
        worker_id="REVWRK-1",
        session_id="REVSES-1",
        created_at=1,
        runtime_assignment_id="ASSIGN-1",
        runtime_attempt_id="ATT-1",
        dsh_session_id="DSH-1",
    )
    _observe(
        truth,
        assignment_id="ASSIGN-1",
        attempt_id="ATT-1",
        dsh_session_id="DSH-1",
        total_tokens=90,
    )

    report = audit.report(MISSION)

    assert report.repeated_subject_count == 0
    assert report.total_tokens == 90
    assert report.qualification.status == "PASS"
    assert report.qualification.reason == "EVALUATOR_AMPLIFICATION_NOT_OBSERVED"


def test_non_reviewer_usage_is_not_attributed_to_evaluator_amplification(tmp_path: Path):
    truth, audit = _truth(tmp_path)
    _observe(
        truth,
        assignment_id="EXEC-ASSIGN-1",
        attempt_id="EXEC-ATT-1",
        dsh_session_id="EXEC-DSH-1",
        total_tokens=200,
    )

    report = audit.report(MISSION)

    assert report.reviewer_assignment_count == 0
    assert report.subject_count == 0
    assert report.repeated_subject_count == 0
    assert report.measured_total_tokens == 0
    assert report.total_tokens == 0
    assert report.qualification.status == "PASS"
    assert report.qualification.reason == "NO_EVALUATOR_ASSIGNMENTS_OBSERVED"
