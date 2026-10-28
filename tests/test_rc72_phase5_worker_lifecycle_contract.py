from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Task
from rc7_runtime.rc72_domain import (
    AutonomousMissionNode,
    ExecutionTaskUnit,
    NodeDelivery,
    ReleaseBatch,
    TestObligation,
)
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.rc72_worker_lifecycle import (
    WorkerLifecyclePolicy,
    WorkerLifecycleService,
    WorkerSessionMetrics,
)
from rc7_runtime.truth_overlay import append_entity


def _runtime(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    repo.persist(
        ReleaseBatch(
            release_batch_id="RB-1",
            mission_id="M-1",
            name="batch",
            application_ids=["cfg-center"],
            requirement_ids=["REQ-1"],
        )
    )
    obligation = TestObligation(
        obligation_id="TO-1",
        mission_id="M-1",
        release_batch_id="RB-1",
        requirement_id="REQ-1",
        sst_id="SST-1",
        application_id="cfg-center",
        business_scenario="guarantor creation",
        business_rule="required fields persist",
        risk_level="HIGH",
        test_level="L3",
        code_slice_refs=["Service#create"],
        oracle_refs=["HTTP", "DB"],
    )
    repo.persist(obligation)
    for idx in (1, 2):
        repo.persist(
            ExecutionTaskUnit(
                etu_id="ETU-%d" % idx,
                mission_id="M-1",
                release_batch_id="RB-1",
                obligation_id="TO-1",
                case_ids=["TC-%d" % idx],
                primary_goal="execute case %d" % idx,
                primary_code_slice="Service#create",
                test_level="L3",
                primary_oracle="HTTP+DB",
                data_domain="guarantor",
                primary_tool_family="api",
                planning_snapshot_ref="PLAN-1",
                cohesion_score=1.0,
                cohesion_explanation="single expensive/high-risk case",
                required_capabilities=["tool:api"],
                estimated_duration_minutes=5,
                estimated_cost=1.0,
            )
        )
        append_entity(
            truth,
            Task(
                task_id="WI-%d" % idx,
                mission_id="M-1",
                node="N7_EXECUTION",
                task_type="ETU_EXECUTION",
                objective="execute ETU-%d" % idx,
                required_capabilities=["api"],
                input_artifact_refs=["ETU-%d" % idx],
                acceptance_criteria=["evidence persisted"],
            ),
            release_id="RC7.2",
        )
    policy = WorkerLifecyclePolicy(
        max_workitems=1,
        max_steps=100,
        max_tokens=50000,
        max_tool_calls=50,
        max_compactions=2,
        max_retries=3,
        max_age_seconds=1800,
        max_context_pressure=0.80,
    )
    return truth, repo, WorkerLifecycleService(truth, release_id="RC7.2", policy=policy)


def _refs(etu_id):
    return {
        "etu_refs": [etu_id],
        "executable_contract_refs": ["EXEC-%s" % etu_id],
        "data_refs": ["DATA-%s" % etu_id],
        "evidence_refs": [],
        "gap_refs": [],
        "coverage_refs": ["COV-LATEST"],
        "lease_refs": [],
    }


def test_default_one_etu_one_fresh_worker_session(tmp_path: Path):
    truth, _, service = _runtime(tmp_path)

    first = service.assign_fresh_worker(
        mission_id="M-1", team_id="TEAM-1", role="test-executor",
        etu_id="ETU-1", workitem_id="WI-1", canonical_refs=_refs("ETU-1"),
    )
    service.checkpoint_and_close(first.session_id, reason="ETU_COMPLETED")
    second = service.assign_fresh_worker(
        mission_id="M-1", team_id="TEAM-1", role="test-executor",
        etu_id="ETU-2", workitem_id="WI-2", canonical_refs=_refs("ETU-2"),
    )

    assert first.worker_id != second.worker_id
    assert first.session_id != second.session_id
    assert truth.query("rc72_worker_session", session_id=first.session_id)[0]["state"] == "CLOSED"
    assert truth.query("rc72_worker_session", session_id=second.session_id)[0]["state"] == "ACTIVE"


def test_fresh_worker_context_contains_only_canonical_refs_not_chat_history(tmp_path: Path):
    _, _, service = _runtime(tmp_path)
    assignment = service.assign_fresh_worker(
        mission_id="M-1", team_id="TEAM-1", role="test-executor",
        etu_id="ETU-1", workitem_id="WI-1", canonical_refs=_refs("ETU-1"),
    )

    context = assignment.context_bundle
    assert context["mission_id"] == "M-1"
    assert context["etu_id"] == "ETU-1"
    assert context["workitem_id"] == "WI-1"
    assert "chat_history" not in context
    assert "messages" not in context
    assert "previous_session_transcript" not in context
    assert set(context) <= {
        "mission_id", "release_batch_id", "team_id", "role", "etu_id", "workitem_id",
        "etu_refs", "executable_contract_refs", "data_refs", "evidence_refs",
        "gap_refs", "coverage_refs", "lease_refs",
    }


def test_closed_worker_session_cannot_be_rebound_to_another_etu(tmp_path: Path):
    _, _, service = _runtime(tmp_path)
    assignment = service.assign_fresh_worker(
        mission_id="M-1", team_id="TEAM-1", role="test-executor",
        etu_id="ETU-1", workitem_id="WI-1", canonical_refs=_refs("ETU-1"),
    )
    service.checkpoint_and_close(assignment.session_id, reason="ETU_COMPLETED")

    with pytest.raises(Exception, match="WORKER_SESSION_CLOSED"):
        service.bind_existing_session(
            session_id=assignment.session_id,
            etu_id="ETU-2",
            workitem_id="WI-2",
            canonical_refs=_refs("ETU-2"),
        )


def test_rotation_threshold_requires_r1_checkpoint_before_old_session_closes(tmp_path: Path):
    truth, _, service = _runtime(tmp_path)
    assignment = service.assign_fresh_worker(
        mission_id="M-1", team_id="TEAM-1", role="test-executor",
        etu_id="ETU-1", workitem_id="WI-1", canonical_refs=_refs("ETU-1"),
    )
    metrics = WorkerSessionMetrics(
        workitem_count=1,
        step_count=101,
        token_usage=51000,
        tool_call_count=10,
        compaction_count=0,
        retry_count=0,
        age_seconds=100,
        context_pressure=0.60,
    )

    decision = service.evaluate_rotation(assignment.session_id, metrics)
    assert decision.required is True
    assert "MAX_STEPS" in decision.reasons
    assert "MAX_TOKENS" in decision.reasons

    rotated = service.rotate_to_fresh_worker(
        session_id=assignment.session_id,
        metrics=metrics,
        next_etu_id="ETU-2",
        next_workitem_id="WI-2",
        canonical_refs=_refs("ETU-2"),
    )

    checkpoint = truth.query("rc72_worker_checkpoint", checkpoint_id=rotated.checkpoint_id)[0]
    old_session = truth.query("rc72_worker_session", session_id=assignment.session_id)[0]
    new_session = truth.query("rc72_worker_session", session_id=rotated.new_assignment.session_id)[0]
    assert checkpoint["session_id"] == assignment.session_id
    assert checkpoint["rotation_decision_id"] == decision.decision_id
    assert old_session["state"] == "CLOSED"
    assert old_session["checkpoint_id"] == rotated.checkpoint_id
    assert new_session["state"] == "ACTIVE"
    assert new_session["parent_session_id"] == assignment.session_id


def test_fresh_reviewer_is_distinct_and_receives_delivery_evidence_not_executor_chat(tmp_path: Path):
    truth, repo, service = _runtime(tmp_path)
    # Reviewer assignment is tied to canonical delivery/evidence refs, not executor transcript.
    # A persisted N4 node is not required for role/session lifecycle identity; delivery identity is.
    from rc7_runtime.rc72_domain import MissionNodeRecord, MissionNodeState
    node = MissionNodeRecord(
        mission_node_id="MN-N4",
        mission_id="M-1",
        node_type=AutonomousMissionNode.N4_TEST_DESIGN,
        scope_ref="RB-1",
        state=MissionNodeState.REVIEW_PENDING,
    )
    repo.persist(node)
    repo.persist(
        NodeDelivery(
            delivery_id="ND-N4-1",
            mission_id="M-1",
            mission_node_id="MN-N4",
            node_type=AutonomousMissionNode.N4_TEST_DESIGN,
            version=1,
            producer_ref="worker://designer",
            artifact_refs=["CASESET-1"],
            evidence_refs=[],
            created_by_workitems=["WI-DESIGN"],
        )
    )
    executor = service.assign_fresh_worker(
        mission_id="M-1", team_id="TEAM-1", role="test-designer",
        etu_id="ETU-1", workitem_id="WI-1", canonical_refs=_refs("ETU-1"),
    )

    review = service.assign_fresh_reviewer(
        mission_id="M-1",
        team_id="TEAM-1",
        mission_node_id="MN-N4",
        delivery_id="ND-N4-1",
        criteria=["TRACEABILITY", "ORACLE", "RISK_DEPTH"],
        evidence_refs=[],
        excluded_session_ids=[executor.session_id],
    )

    assert review.session_id != executor.session_id
    assert review.worker_id != executor.worker_id
    assert review.context_bundle == {
        "mission_id": "M-1",
        "team_id": "TEAM-1",
        "mission_node_id": "MN-N4",
        "delivery_id": "ND-N4-1",
        "criteria": ["TRACEABILITY", "ORACLE", "RISK_DEPTH"],
        "evidence_refs": [],
    }
    assert truth.query("rc72_reviewer_assignment", review_id=review.review_id)[0]["session_id"] == review.session_id


def test_captain_handoff_reuses_same_mission_and_persists_readiness_truth(tmp_path: Path):
    truth, _, service = _runtime(tmp_path)
    worker = service.assign_fresh_worker(
        mission_id="M-1", team_id="TEAM-1", role="test-executor",
        etu_id="ETU-1", workitem_id="WI-1", canonical_refs=_refs("ETU-1"),
    )
    checkpoint = service.create_captain_handoff(
        mission_id="M-1",
        team_id="TEAM-1",
        old_captain_session_id="CAPTAIN-A",
        current_node_refs=["N7_EXECUTION"],
        latest_delivery_refs=[],
        latest_gate_refs=[],
        next_workitem_ids=["WI-2"],
    )

    readiness = service.takeover_captain(
        checkpoint_id=checkpoint.checkpoint_id,
        new_captain_session_id="CAPTAIN-B",
        expected_mission_id="M-1",
        expected_team_id="TEAM-1",
    )

    assert readiness.ready is True
    assert readiness.mission_id == "M-1"
    assert readiness.team_id == "TEAM-1"
    assert readiness.resumable_from_r1 is True
    assert len(truth.query("rc72_release_batch", mission_id="M-1")) == 1
    persisted = truth.query("rc72_captain_takeover", takeover_id=readiness.takeover_id)[0]
    assert persisted["checkpoint_id"] == checkpoint.checkpoint_id
    assert persisted["new_captain_session_id"] == "CAPTAIN-B"
    assert worker.session_id in checkpoint.active_worker_session_ids


def test_captain_takeover_fails_closed_on_mission_or_team_mismatch(tmp_path: Path):
    _, _, service = _runtime(tmp_path)
    checkpoint = service.create_captain_handoff(
        mission_id="M-1", team_id="TEAM-1", old_captain_session_id="CAPTAIN-A",
        current_node_refs=["N4_TEST_DESIGN"], latest_delivery_refs=[], latest_gate_refs=[],
        next_workitem_ids=["WI-1"],
    )

    with pytest.raises(Exception, match="CAPTAIN_HANDOFF_IDENTITY_MISMATCH"):
        service.takeover_captain(
            checkpoint_id=checkpoint.checkpoint_id,
            new_captain_session_id="CAPTAIN-B",
            expected_mission_id="M-OTHER",
            expected_team_id="TEAM-1",
        )


def test_worker_checkpoint_and_captain_handoff_survive_r1_replay(tmp_path: Path):
    truth, _, service = _runtime(tmp_path)
    assignment = service.assign_fresh_worker(
        mission_id="M-1", team_id="TEAM-1", role="test-executor",
        etu_id="ETU-1", workitem_id="WI-1", canonical_refs=_refs("ETU-1"),
    )
    close = service.checkpoint_and_close(assignment.session_id, reason="SAFE_BOUNDARY")
    handoff = service.create_captain_handoff(
        mission_id="M-1", team_id="TEAM-1", old_captain_session_id="CAPTAIN-A",
        current_node_refs=["N7_EXECUTION"], latest_delivery_refs=[], latest_gate_refs=[],
        next_workitem_ids=["WI-2"],
    )

    replayed = TruthRuntime(tmp_path / "r1.jsonl")
    assert replayed.query("rc72_worker_checkpoint", checkpoint_id=close.checkpoint_id)[0]["reason"] == "SAFE_BOUNDARY"
    assert replayed.query("rc72_worker_session", session_id=assignment.session_id)[0]["state"] == "CLOSED"
    assert replayed.query("rc72_captain_handoff", checkpoint_id=handoff.checkpoint_id)[0]["mission_id"] == "M-1"
