from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError, Gap, GapSeverity, Task
from rc7_runtime.rc72_domain import (
    AutonomousMissionNode,
    BackEdge,
    BackEdgeState,
    ExecutionTaskUnit,
    MissionNodeRecord,
    MissionNodeState,
    NodeDelivery,
    NodeGate,
    NodeGateDecision,
    RC72_CANONICAL_NODE_ORDER,
    ReleaseBatch,
    TestObligation,
)
from rc7_runtime.rc72_linkage import (
    NodeTransition,
    NodeTransitionKind,
    WorkItemAttemptBinding,
    WorkItemAttemptState,
)
from rc7_runtime.rc72_repository import CanonicalRC72Repository, RC72LineageError
from rc7_runtime.truth_overlay import append_entity


def _batch() -> ReleaseBatch:
    return ReleaseBatch(
        release_batch_id="RB-2026-10-28",
        mission_id="M-RC72-1",
        name="2026-10-28 production batch",
        version_ids=["BLOAN-PF1.2.1"],
        application_ids=["cfg-center", "cfg-scd", "cfg-data"],
        requirement_ids=["STBB19-322"],
    )


def _node(node_type: AutonomousMissionNode) -> MissionNodeRecord:
    return MissionNodeRecord(
        mission_node_id="MN-M-RC72-1-%s" % node_type.value,
        mission_id="M-RC72-1",
        node_type=node_type,
        scope_ref="release-batch://RB-2026-10-28",
    )


def _obligation() -> TestObligation:
    return TestObligation(
        obligation_id="TO-STBB19-322-STB913-14130-GUARANTOR-L3",
        mission_id="M-RC72-1",
        release_batch_id="RB-2026-10-28",
        requirement_id="STBB19-322",
        sst_id="STB913-14130",
        application_id="cfg-center",
        business_scenario="government guarantor creation",
        business_rule="type=2 guarantor obeys required business and persistence constraints",
        risk_level="HIGH",
        test_level="L3",
        code_slice_refs=["GuarantorServiceImpl#create"],
        oracle_refs=["HTTP", "DB", "CAT"],
        coverage_targets=[],
    )


def _etu(case_ids=None, *, oversize_justification=None) -> ExecutionTaskUnit:
    return ExecutionTaskUnit(
        etu_id="ETU-GUARANTOR-L3-01",
        mission_id="M-RC72-1",
        release_batch_id="RB-2026-10-28",
        obligation_id="TO-STBB19-322-STB913-14130-GUARANTOR-L3",
        case_ids=case_ids or ["TC-001", "TC-002", "TC-003"],
        primary_goal="verify type=2 guarantor creation contract",
        primary_code_slice="GuarantorServiceImpl#create",
        test_level="L3",
        primary_oracle="HTTP+DB+CAT",
        data_domain="guarantor",
        primary_tool_family="api-runtime",
        planning_snapshot_ref="r1://decomposition-snapshot/M-RC72-1/1",
        cohesion_score=0.94,
        cohesion_explanation="same requirement/SST/obligation/code slice/L3/data/oracle/tool",
        required_capabilities=["test_execution", "db_read", "cat_query"],
        estimated_duration_minutes=10,
        oversize_justification=oversize_justification,
    )


def _delivery(node: MissionNodeRecord, version=1) -> NodeDelivery:
    return NodeDelivery(
        delivery_id="ND-%s-V%d" % (node.node_type.value, version),
        mission_id=node.mission_id,
        mission_node_id=node.mission_node_id,
        node_type=node.node_type,
        version=version,
        producer_ref="worker://%s/attempt-%d" % (node.node_type.value, version),
        artifact_refs=["artifact://%s/v%d" % (node.node_type.value, version)],
        evidence_refs=["evidence://%s/v%d" % (node.node_type.value, version)],
        created_by_workitems=["WI-%s-%d" % (node.node_type.value, version)],
        sufficiency_score=0.93,
    )


def test_n1_n10_and_mission_node_states_match_frozen_contract() -> None:
    assert RC72_CANONICAL_NODE_ORDER == (
        "N1_REALITY", "N2_REQUIREMENT", "N3_CODE_ANALYSIS", "N4_TEST_DESIGN",
        "N5_TEST_DATA", "N6_EXECUTABLE_READINESS", "N7_EXECUTION",
        "N8_DIAGNOSIS_RECOVERY", "N9_DEFECT", "N10_RELEASE_CONVERGENCE",
    )
    assert tuple(state.value for state in MissionNodeState) == (
        "NOT_STARTED", "READY", "RUNNING", "REVIEW_PENDING", "PASS",
        "NEEDS_REVISION", "BLOCKED", "HUMAN_GATE", "STALE",
    )


def test_phase1_runtime_objects_contain_frozen_minimum_fields() -> None:
    assert {"scope_ref", "active_delivery_version", "entered_at", "exited_at", "blocked_reason"} <= {
        item.name for item in fields(MissionNodeRecord)
    }
    assert {"mission_node_id", "known_gaps", "created_by_workitems"} <= {
        item.name for item in fields(NodeDelivery)
    }
    assert {"reviewer_worker_id", "reviewer_session_id", "return_node"} <= {
        item.name for item in fields(NodeGate)
    }
    assert {"from_delivery_id", "resolved_by_delivery_id", "state"} <= {
        item.name for item in fields(BackEdge)
    }
    assert {"planning_snapshot_ref", "cohesion_score", "cohesion_explanation", "primary_tool_family"} <= {
        item.name for item in fields(ExecutionTaskUnit)
    }
    assert {"source_gate_id", "back_edge_id", "kind"} <= {item.name for item in fields(NodeTransition)}
    assert {"workitem_id", "attempt_id", "worker_id", "session_id", "task_lease_ref", "capability_lease_refs", "resource_lease_refs"} <= {
        item.name for item in fields(WorkItemAttemptBinding)
    }


def test_test_obligation_cannot_be_persisted_without_release_batch_root(tmp_path: Path) -> None:
    repository = CanonicalRC72Repository(TruthRuntime(tmp_path / "r1.jsonl"), release_id="RC7.2")
    with pytest.raises(RC72LineageError, match="RC72_PARENT_NOT_UNIQUE:rc72_release_batch"):
        repository.persist(_obligation())


def test_test_obligation_must_stay_inside_release_batch_scope(tmp_path: Path) -> None:
    repository = CanonicalRC72Repository(TruthRuntime(tmp_path / "r1.jsonl"), release_id="RC7.2")
    repository.persist(_batch())
    outside = _obligation()
    outside.requirement_id = "REQ-OUTSIDE"
    with pytest.raises(RC72LineageError, match="TEST_OBLIGATION_REQUIREMENT_OUTSIDE_RELEASE_BATCH"):
        repository.persist(outside)


def test_node_delivery_and_gate_attach_to_exact_mission_node(tmp_path: Path) -> None:
    repository = CanonicalRC72Repository(TruthRuntime(tmp_path / "r1.jsonl"), release_id="RC7.2")
    repository.persist(_batch())
    n4 = _node(AutonomousMissionNode.N4_TEST_DESIGN)
    repository.persist(n4)
    wrong = NodeDelivery(
        delivery_id="ND-WRONG",
        mission_id=n4.mission_id,
        mission_node_id=n4.mission_node_id,
        node_type=AutonomousMissionNode.N3_CODE_ANALYSIS,
        version=1,
        producer_ref="worker://wrong",
    )
    with pytest.raises(RC72LineageError, match="MISSION_NODE_TYPE_MISMATCH"):
        repository.persist(wrong)


def test_node_gate_requires_explicit_fresh_reviewer_identity() -> None:
    with pytest.raises(ContractError, match="REVIEWER_SESSION_ID_REQUIRED"):
        NodeGate(
            gate_id="NG-1",
            mission_id="M-RC72-1",
            mission_node_id="MN-M-RC72-1-N4_TEST_DESIGN",
            node_type=AutonomousMissionNode.N4_TEST_DESIGN,
            delivery_id="ND-1",
            decision=NodeGateDecision.PASS,
            reviewer_worker_id="reviewer-worker-1",
            reviewer_session_id="",
            criteria=["design ready"],
            passed=["design ready"],
        )


def test_etu_default_3_to_8_is_explainable_default_not_blind_hard_limit() -> None:
    with pytest.raises(ContractError, match="ETU_OVERSIZE_REQUIRES_JUSTIFICATION"):
        _etu(["TC-%02d" % i for i in range(1, 10)])
    large = _etu(
        ["TC-%02d" % i for i in range(1, 10)],
        oversize_justification="same expensive L5-style setup and shared browser/data lease makes split costlier",
    )
    assert len(large.case_ids) == 9
    assert large.oversize_justification
    small = _etu(["TC-001"])
    assert small.case_ids == ["TC-001"]


def test_forward_transition_requires_pass_gate_and_persists(tmp_path: Path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    repo.persist(_batch())
    n4 = _node(AutonomousMissionNode.N4_TEST_DESIGN)
    n5 = _node(AutonomousMissionNode.N5_TEST_DATA)
    repo.persist(n4)
    repo.persist(n5)
    delivery = _delivery(n4)
    repo.persist(delivery)
    gate = NodeGate(
        gate_id="NG-N4-PASS",
        mission_id=n4.mission_id,
        mission_node_id=n4.mission_node_id,
        node_type=n4.node_type,
        delivery_id=delivery.delivery_id,
        decision=NodeGateDecision.PASS,
        reviewer_worker_id="fresh-reviewer-1",
        reviewer_session_id="fresh-review-session-1",
        criteria=["N4 sufficient"],
        passed=["N4 sufficient"],
    )
    repo.persist(gate)
    transition = NodeTransition(
        transition_id="NT-N4-N5-1",
        mission_id=n4.mission_id,
        from_mission_node_id=n4.mission_node_id,
        from_node_type=n4.node_type,
        to_mission_node_id=n5.mission_node_id,
        to_node_type=n5.node_type,
        kind=NodeTransitionKind.FORWARD,
        reason="N4 PASS",
        source_gate_id=gate.gate_id,
    )
    repo.persist(transition)
    assert truth.query("rc72_node_transition", transition_id=transition.transition_id)[0]["kind"] == "FORWARD"


def test_etu_to_existing_task_and_execution_attempt_linkage_survives_replay(tmp_path: Path) -> None:
    event_path = tmp_path / "r1.jsonl"
    truth = TruthRuntime(event_path)
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    repo.persist(_batch())
    obligation = _obligation()
    repo.persist(obligation)
    etu = _etu(["TC-001"])
    repo.persist(etu)

    task = Task(
        task_id="WI-ETU-GUARANTOR-01",
        mission_id="M-RC72-1",
        node="EXECUTION",
        task_type="ETU_EXECUTION",
        objective="execute one canonical ETU",
        required_capabilities=["test_execution"],
        input_artifact_refs=[etu.etu_id],
        acceptance_criteria=["real execution attempt persisted"],
    )
    append_entity(truth, task, release_id="RC7.2")
    truth.append_atomic(
        "EXECUTION_ATTEMPT_UPSERTED",
        {
            "attempt_id": "ATT-ETU-001",
            "release_id": "RC7.2",
            "artifact_version": 1,
            "requirement_id": "STBB19-322",
            "tc_id": "TC-001",
            "case_version": 1,
            "target_id": "FAT1",
            "layer": "L3",
            "status": "PASS",
            "actual_result": {"http_status": 200},
            "tool_call_refs": ["tool://api/1"],
            "evidence_refs": ["evidence://api/1"],
            "worker_id": "wrk-real-1",
            "lease_id": "lease-real-1",
        },
    )
    binding = WorkItemAttemptBinding(
        binding_id="WAB-ETU-001",
        mission_id="M-RC72-1",
        etu_id=etu.etu_id,
        workitem_id=task.task_id,
        case_id="TC-001",
        attempt_id="ATT-ETU-001",
        state=WorkItemAttemptState.COMPLETED,
        worker_id="wrk-real-1",
        session_id="dsh-session-real-1",
        task_lease_ref="lease-real-1",
        capability_lease_refs=["caplease://api-runtime/1"],
        resource_lease_refs=["resource://fat1/slot-1"],
    )
    receipt = repo.persist(binding)
    assert receipt.status == "PERSISTENCE_VERIFIED"

    replayed = TruthRuntime(event_path)
    row = replayed.query("rc72_workitem_attempt_binding", binding_id=binding.binding_id)[0]
    assert row["etu_id"] == etu.etu_id
    assert row["workitem_id"] == task.task_id
    assert row["attempt_id"] == "ATT-ETU-001"
    assert row["worker_id"] == "wrk-real-1"
    assert row["task_lease_ref"] == "lease-real-1"
    assert row["capability_lease_refs"] == ["caplease://api-runtime/1"]


def test_back_edge_reuses_canonical_gap_and_transition_is_explicit(tmp_path: Path) -> None:
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    repo.persist(_batch())
    n3 = _node(AutonomousMissionNode.N3_CODE_ANALYSIS)
    n8 = _node(AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
    repo.persist(n3)
    repo.persist(n8)
    n8_delivery = _delivery(n8)
    repo.persist(n8_delivery)
    gap = Gap(
        gap_id="GAP-ANALYSIS-1",
        mission_id="M-RC72-1",
        source_node="N8_DIAGNOSIS_RECOVERY",
        category="ANALYSIS_GAP",
        severity=GapSeverity.HIGH,
        target_node="N3_CODE_ANALYSIS",
        description="runtime exposed a missing code constraint",
    )
    append_entity(truth, gap, release_id="RC7.2")
    edge = BackEdge(
        back_edge_id="BE-ANALYSIS-1",
        mission_id="M-RC72-1",
        gap_id=gap.gap_id,
        from_node=n8.node_type,
        from_delivery_id=n8_delivery.delivery_id,
        return_node=n3.node_type,
        reason="ANALYSIS_GAP",
        state=BackEdgeState.OPEN,
    )
    repo.persist(edge)
    transition = NodeTransition(
        transition_id="NT-N8-N3-1",
        mission_id="M-RC72-1",
        from_mission_node_id=n8.mission_node_id,
        from_node_type=n8.node_type,
        to_mission_node_id=n3.mission_node_id,
        to_node_type=n3.node_type,
        kind=NodeTransitionKind.BACK_EDGE,
        reason="ANALYSIS_GAP",
        back_edge_id=edge.back_edge_id,
    )
    repo.persist(transition)
    assert truth.query("rc72_node_transition", transition_id=transition.transition_id)[0]["to_node_type"] == "N3_CODE_ANALYSIS"
