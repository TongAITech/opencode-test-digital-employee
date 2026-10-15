from __future__ import annotations

import rc6_runtime.agent_runtime  # noqa: F401
from rc6_runtime.truth import TruthRuntime
from rc7_release.final_qualification import evaluate_final_qualification
from rc7_release.real_mission_qualification import evaluate_real_mission
from rc7_release.real_mission_qualification_strict import evaluate_real_mission_strict
from rc7_runtime.models import (
    Artifact,
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
    GapStatus,
    Mission,
    MissionStatus,
    Task,
    TaskStatus,
)
from rc7_runtime.runtime_identity import attest_runtime_identity
from rc7_runtime.session_continuity import SESSION_EVENT, install_session_overlay
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay


COMMIT = "a" * 40
MISSION = "MISSION-REAL-QUALIFICATION"
RELEASE = "RC7-REAL"
SOURCE_TASK = "TASK-REQ-REAL"
REPAIR_TASK = "TASK-REQ-REPAIR-REAL"
SOURCE_ARTIFACT = "ART-REQ-REAL"
REPAIR_ARTIFACT = "ART-REQ-REPAIR-REAL"
GAP = "GAP-REQ-REAL"
SOURCE_EVAL = "EVAL-REQ-REAL-2"
REPAIR_EVAL = "EVAL-REQ-REPAIR-REAL"
MISSION_EVAL = "EVAL-MISSION-REAL"
FORMAL_EVIDENCE = "EVD-FORMAL-REAL"


def _append_tool_call(truth, *, worker, task_id, number):
    tool_call = {
        "tool_name": "filesystem",
        "call_ref": "tool://real/%s/%d" % (worker, number),
        "arguments": {"task_id": task_id},
    }
    truth.append_atomic(
        "WORKER_TOOL_CALLED",
        {
            "id": "AGENT-EVENT-%s-%d" % (worker, number),
            "release_id": RELEASE,
            "mission_id": MISSION,
            "event_name": "WORKER_TOOL_CALLED",
            "coordinator_instance_id": "coordinator-control-plane",
            "worker_instance_id": worker,
            "agent_id": "requirement-analysis",
            "attempt_id": "ATT-%s-%d" % (worker, number),
            "assignment_id": "ASSIGN-%s-%d" % (worker, number),
            "lease_id": "LEASE-%s-%d" % (worker, number),
            "parent_worker_id": "coordinator-control-plane",
            "scope": "task:%s" % task_id,
            "input_refs": [],
            "tool_calls": [tool_call],
            "tool_call": tool_call,
            "output_refs": [],
            "evidence_refs": [],
            "started_at": number,
            "finished_at": number + 1,
            "result": "PASS",
            "occurred_at": number,
            "artifact_version": 1,
        },
    )


def _dsh_evidence(truth, *, evidence_id, worker, task_id):
    append_entity(
        truth,
        Evidence(
            evidence_id=evidence_id,
            mission_id=MISSION,
            kind="DSH_RUNTIME_PROOF",
            source_ref="dsh://worker/%s" % worker,
            content_ref="file:///field/%s.jsonl" % worker,
            subject_refs=[task_id, "ATT-%s" % worker],
        ),
        release_id=RELEASE,
    )


def _build_r1(tmp_path, *, include_session=True, identity_commit=COMMIT):
    install_rc7_truth_overlay()
    install_session_overlay()
    path = tmp_path / "r1.jsonl"
    truth = TruthRuntime(path)

    # Real runtime ordering: a Mission exists in a non-terminal state while its
    # evidence is produced. CONVERGED is persisted only after the durable
    # Mission Evaluation PASS exists in R1.
    append_entity(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="prove real mission qualification",
            state=MissionStatus.RUNNING,
            sufficiency_state="UNKNOWN",
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    attest_runtime_identity(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        source_commit=identity_commit,
    )

    append_entity(
        truth,
        Artifact(
            artifact_id=SOURCE_ARTIFACT,
            mission_id=MISSION,
            artifact_type="REQUIREMENT_MODEL",
            producer_task_id=SOURCE_TASK,
            content_ref="artifact://requirement/v1",
            version=1,
        ),
        release_id=RELEASE,
        artifact_version=1,
    )
    append_entity(
        truth,
        Artifact(
            artifact_id=SOURCE_ARTIFACT,
            mission_id=MISSION,
            artifact_type="REQUIREMENT_MODEL",
            producer_task_id=SOURCE_TASK,
            content_ref="artifact://requirement/v2",
            version=2,
        ),
        release_id=RELEASE,
        artifact_version=2,
    )
    append_entity(
        truth,
        Artifact(
            artifact_id=REPAIR_ARTIFACT,
            mission_id=MISSION,
            artifact_type="REQUIREMENT_ANALYSIS_OUTPUT",
            producer_task_id=REPAIR_TASK,
            content_ref="artifact://requirement-repair/v1",
        ),
        release_id=RELEASE,
    )

    append_entity(
        truth,
        Evaluation(
            evaluation_id=REPAIR_EVAL,
            mission_id=MISSION,
            node="REQUIREMENT_ANALYSIS",
            artifact_refs=[REPAIR_ARTIFACT],
            result=EvaluationResult.PASS,
            evaluator_ref="independent-repair-evaluator",
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Evaluation(
            evaluation_id=SOURCE_EVAL,
            mission_id=MISSION,
            node="REQUIREMENT_ANALYSIS",
            artifact_refs=[SOURCE_ARTIFACT],
            result=EvaluationResult.PASS,
            evaluator_ref="independent-source-evaluator",
            evidence_refs=["EVD-DSH-SOURCE"],
        ),
        release_id=RELEASE,
    )

    for version, state, resolution in (
        (1, GapStatus.REPAIRING, None),
        (2, GapStatus.EVIDENCE_PENDING, None),
        (3, GapStatus.RESOLVED, SOURCE_EVAL),
    ):
        append_entity(
            truth,
            Gap(
                gap_id=GAP,
                mission_id=MISSION,
                source_node="REQUIREMENT_ANALYSIS",
                category="MISSING_BOUNDARY",
                severity=GapSeverity.HIGH,
                target_node="REQUIREMENT_ANALYSIS",
                description="repair a missing boundary",
                state=state,
                subject_refs=[SOURCE_ARTIFACT],
                evidence_refs=["EVD-DSH-SOURCE"],
                acceptance_criteria=["boundary repaired and independently re-evaluated"],
                resolution_evaluation_id=resolution,
            ),
            release_id=RELEASE,
            artifact_version=version,
        )

    append_entity(
        truth,
        Task(
            task_id=SOURCE_TASK,
            mission_id=MISSION,
            node="REQUIREMENT_ANALYSIS",
            task_type="PRODUCE",
            objective="analyze requirement",
            state=TaskStatus.PASS,
            lease_owner="worker-source",
            gap_refs=[GAP],
            output_artifact_refs=[SOURCE_ARTIFACT],
            evaluation_id=SOURCE_EVAL,
        ),
        release_id=RELEASE,
        artifact_version=8,
    )
    append_entity(
        truth,
        Task(
            task_id=REPAIR_TASK,
            mission_id=MISSION,
            node="REQUIREMENT_ANALYSIS",
            task_type="REPAIR",
            objective="repair requirement gap",
            state=TaskStatus.PASS,
            lease_owner="worker-repair",
            gap_refs=[GAP],
            output_artifact_refs=[REPAIR_ARTIFACT],
            evaluation_id=REPAIR_EVAL,
        ),
        release_id=RELEASE,
        artifact_version=5,
    )

    _dsh_evidence(truth, evidence_id="EVD-DSH-SOURCE", worker="worker-source", task_id=SOURCE_TASK)
    _dsh_evidence(truth, evidence_id="EVD-DSH-REPAIR", worker="worker-repair", task_id=REPAIR_TASK)
    _append_tool_call(truth, worker="worker-source", task_id=SOURCE_TASK, number=10)
    _append_tool_call(truth, worker="worker-repair", task_id=REPAIR_TASK, number=20)

    append_entity(
        truth,
        Evidence(
            evidence_id=FORMAL_EVIDENCE,
            mission_id=MISSION,
            kind="RUNTIME_EXECUTION_RECORD",
            source_ref="runtime://formal-execution",
            content_ref="evidence://formal-execution/real",
            subject_refs=["ATT-REAL", "TC-REAL"],
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Evaluation(
            evaluation_id=MISSION_EVAL,
            mission_id=MISSION,
            node="MISSION_EVALUATION",
            artifact_refs=[SOURCE_ARTIFACT],
            result=EvaluationResult.PASS,
            evaluator_ref="rc7-deterministic-mission-sufficiency-gate",
            evidence_refs=[FORMAL_EVIDENCE],
            dimensions={
                "sufficiency_state": "SUFFICIENT",
                "release_recommendation": "RECOMMENDED",
                "metrics": {"residual_risks_pending_acceptance": 0},
                "report_ready": True,
            },
        ),
        release_id=RELEASE,
    )
    append_entity(
        truth,
        Mission(
            mission_id=MISSION,
            release_id=RELEASE,
            goal="prove real mission qualification",
            state=MissionStatus.CONVERGED,
            sufficiency_state="SUFFICIENT",
            latest_evaluation_id=MISSION_EVAL,
        ),
        release_id=RELEASE,
        artifact_version=2,
    )

    if include_session:
        base = {
            "handoff_id": "HANDOFF-REAL",
            "mission_id": MISSION,
            "release_id": RELEASE,
            "task_id": SOURCE_TASK,
            "generation": 1,
            "predecessor_session_ref": "session-A",
            "task_state": "RUNNING",
            "artifact_refs": [SOURCE_ARTIFACT],
            "gap_refs": [GAP],
        }
        prepared = dict(base)
        prepared.update({"status": "PREPARED", "artifact_version": 1})
        truth.append_atomic(SESSION_EVENT, prepared)
        activated = dict(base)
        activated.update(
            {
                "status": "ACTIVATED",
                "successor_session_ref": "session-B",
                "activated_at": 100,
                "artifact_version": 2,
            }
        )
        truth.append_atomic(SESSION_EVENT, activated)
    return path


def test_real_mission_qualification_passes_only_from_r1_proof(tmp_path):
    path = _build_r1(tmp_path)
    result = evaluate_real_mission(r1_path=str(path), mission_id=MISSION, source_commit=COMMIT)

    assert result["status"] == "PASS"
    assert result["gate"] == "REAL_MISSION_PASS"
    assert result["worker_proof"]["real_dsh"] is True
    assert result["worker_proof"]["director_did_domain_work"] is False
    assert len(result["worker_proof"]["tool_receipts"]) == 2
    assert result["session_continuity"]["session_ids"] == ["session-A", "session-B"]
    assert result["session_continuity"]["same_task_continuity"] is True
    assert result["gap_repair"]["artifact_before_revision"] == 1
    assert result["gap_repair"]["artifact_after_revision"] == 2
    assert result["gap_repair"]["gap_closed_by_independent_evaluation"] is True
    assert result["defect_flow"]["status"] == "NOT_TRIGGERED_NO_TRUSTED_FAIL"
    assert not result["blocking_reasons"]


def test_old_r1_cannot_be_rebound_to_new_source_commit(tmp_path):
    path = _build_r1(tmp_path, identity_commit="b" * 40)
    result = evaluate_real_mission(r1_path=str(path), mission_id=MISSION, source_commit=COMMIT)

    assert result["status"] == "HOLD"
    assert "RUNTIME_IDENTITY_CURRENT_COMMIT_NOT_PROVEN" in result["blocking_reasons"]


def test_missing_session_rotation_holds_real_mission(tmp_path):
    path = _build_r1(tmp_path, include_session=False)
    result = evaluate_real_mission(r1_path=str(path), mission_id=MISSION, source_commit=COMMIT)

    assert result["status"] == "HOLD"
    assert "SESSION_A_TO_B_ROTATION_NOT_PROVEN" in result["blocking_reasons"]


def _delivery_pass():
    return {
        "gate": "DELIVERY_PASS",
        "status": "PASS",
        "source_commit": COMMIT,
        "package_name": "PFC-AITest-DSH-Turnkey-RC7-BANK-WIN10",
        "package_sha256": "c" * 64,
        "clean_windows_unpack": "PASS",
        "package_local_python_verify": "PASS",
        "package_verify": "PASS",
        "package_entrypoint_verify": "PASS",
        "admin_startup_verify": "PASS",
    }


def test_base_real_mission_is_diagnostic_not_final_authority(tmp_path):
    path = _build_r1(tmp_path)
    real = evaluate_real_mission(r1_path=str(path), mission_id=MISSION, source_commit=COMMIT)
    engineering = {"gate": "ENGINEERING_PASS", "status": "PASS", "source_commit": COMMIT}
    admin = {"gate": "ADMIN_PLATFORM_PASS", "status": "PASS", "source_commit": COMMIT}

    final = evaluate_final_qualification(COMMIT, engineering, admin, real, _delivery_pass())
    assert real["status"] == "PASS"
    assert final["status"] == "HOLD"
    assert "REAL_MISSION_PASS:REALITY_KIND_INVALID" in final["blocking_reasons"]
    assert "REAL_MISSION_PASS:TASK_SCOPED_WORKER_PROOF_MISSING" in final["blocking_reasons"]


def test_strict_real_mission_result_is_consumed_by_final_gate(tmp_path):
    path = _build_r1(tmp_path)
    real = evaluate_real_mission_strict(r1_path=str(path), mission_id=MISSION, source_commit=COMMIT)
    engineering = {"gate": "ENGINEERING_PASS", "status": "PASS", "source_commit": COMMIT}
    admin = {"gate": "ADMIN_PLATFORM_PASS", "status": "PASS", "source_commit": COMMIT}

    final = evaluate_final_qualification(COMMIT, engineering, admin, real, _delivery_pass())
    assert real["status"] == "PASS"
    assert real["qualification_kind"] == "BANK_REAL_MISSION_STRICT_TASK_RECEIPTS"
    assert final["status"] == "PASS"
    assert set(final["gates"].values()) == {"PASS"}
