from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import ContractError, Gap, GapSeverity
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


def test_n1_n10_and_mission_node_states_match_frozen_contract() -> None:
    assert RC72_CANONICAL_NODE_ORDER == (
        "N1_REALITY",
        "N2_REQUIREMENT",
        "N3_CODE_ANALYSIS",
        "N4_TEST_DESIGN",
        "N5_TEST_DATA",
        "N6_EXECUTABLE_READINESS",
        "N7_EXECUTION",
        "N8_DIAGNOSIS_RECOVERY",
        "N9_DEFECT",
        "N10_RELEASE_CONVERGENCE",
    )
    assert len(AutonomousMissionNode.ordered()) == 10
    assert tuple(state.value for state in MissionNodeState) == (
        "NOT_STARTED",
        "READY",
        "RUNNING",
        "REVIEW_PENDING",
        "PASS",
        "NEEDS_REVISION",
        "BLOCKED",
        "HUMAN_GATE",
        "STALE",
    )


def test_phase1_runtime_objects_contain_frozen_minimum_fields() -> None:
    mission_node_fields = {item.name for item in fields(MissionNodeRecord)}
    assert {
        "mission_node_id", "mission_id", "node_type", "scope_ref", "state",
        "active_delivery_version", "entered_at", "exited_at", "blocked_reason",
    } <= mission_node_fields

    delivery_fields = {item.name for item in fields(NodeDelivery)}
    assert {
        "delivery_id", "mission_node_id", "version", "input_refs", "artifact_refs",
        "evidence_refs", "known_gaps", "created_by_workitems", "created_at",
    } <= delivery_fields

    gate_fields = {item.name for item in fields(NodeGate)}
    assert {
        "gate_id", "mission_node_id", "delivery_id", "criteria", "passed", "failed",
        "evidence_refs", "decision", "return_node", "reviewer_worker_id", "reviewer_session_id",
    } <= gate_fields

    back_edge_fields = {item.name for item in fields(BackEdge)}
    assert {
        "back_edge_id", "from_node", "from_delivery_id", "gap_id", "return_node",
        "reason", "created_at", "resolved_by_delivery_id", "state",
    } <= back_edge_fields


def test_test_obligation_cannot_be_persisted_without_release_batch_root(tmp_path: Path) -> None:
    truth = TruthRuntime(tmp_path / "r1-events.jsonl")
    repository = CanonicalRC72Repository(truth, release_id="RC7.2")

    with pytest.raises(RC72LineageError, match="RC72_PARENT_NOT_UNIQUE:rc72_release_batch"):
        repository.persist(_obligation())


def test_test_obligation_must_stay_inside_release_batch_requirement_and_application_scope(tmp_path: Path) -> None:
    truth = TruthRuntime(tmp_path / "r1-events.jsonl")
    repository = CanonicalRC72Repository(truth, release_id="RC7.2")
    repository.persist(_batch())

    outside_requirement = _obligation()
    outside_requirement.requirement_id = "REQ-OUTSIDE"
    with pytest.raises(RC72LineageError, match="TEST_OBLIGATION_REQUIREMENT_OUTSIDE_RELEASE_BATCH"):
        repository.persist(outside_requirement)

    outside_application = _obligation()
    outside_application.application_id = "other-app"
    with pytest.raises(RC72LineageError, match="TEST_OBLIGATION_APPLICATION_OUTSIDE_RELEASE_BATCH"):
        repository.persist(outside_application)


def test_node_delivery_and_gate_must_attach_to_same_canonical_mission_node(tmp_path: Path) -> None:
    truth = TruthRuntime(tmp_path / "r1-events.jsonl")
    repository = CanonicalRC72Repository(truth, release_id="RC7.2")
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
    with pytest.raises(RC72LineageError, match="NODE_DELIVERY_MISSION_NODE_TYPE_MISMATCH"):
        repository.persist(wrong)


def test_node_gate_requires_explicit_reviewer_worker_and_session_identity() -> None:
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


def test_phase1_entities_share_canonical_r1_and_replay_without_session_state(tmp_path: Path) -> None:
    event_path = tmp_path / "r1-events.jsonl"
    truth = TruthRuntime(event_path)
    repository = CanonicalRC72Repository(truth, release_id="RC7.2")

    batch = _batch()
    n4 = _node(AutonomousMissionNode.N4_TEST_DESIGN)
    n8 = _node(AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
    n4_delivery = NodeDelivery(
        delivery_id="ND-M-RC72-1-N4-V1",
        mission_id=batch.mission_id,
        mission_node_id=n4.mission_node_id,
        node_type=AutonomousMissionNode.N4_TEST_DESIGN,
        version=1,
        producer_ref="worker://test-designer/attempt-1",
        artifact_refs=["artifact://test-design/v1"],
        evidence_refs=["evidence://review/input"],
        known_gaps=[],
        created_by_workitems=["WI-N4-001"],
        sufficiency_score=0.93,
    )
    gate = NodeGate(
        gate_id="NG-M-RC72-1-N4-V1",
        mission_id=batch.mission_id,
        mission_node_id=n4.mission_node_id,
        node_type=AutonomousMissionNode.N4_TEST_DESIGN,
        delivery_id=n4_delivery.delivery_id,
        decision=NodeGateDecision.PASS,
        reviewer_worker_id="quality-reviewer-N4-001",
        reviewer_session_id="session-review-N4-001",
        criteria=["all mandatory obligations are represented", "all cases have executable oracles"],
        passed=["all mandatory obligations are represented", "all cases have executable oracles"],
        evidence_refs=["evidence://review/N4/1"],
    )
    obligation = _obligation()
    etu = ExecutionTaskUnit(
        etu_id="ETU-GUARANTOR-L3-01",
        mission_id=batch.mission_id,
        release_batch_id=batch.release_batch_id,
        obligation_id=obligation.obligation_id,
        case_ids=["TC-001", "TC-002", "TC-003"],
        primary_goal="verify type=2 guarantor creation contract",
        primary_code_slice="GuarantorServiceImpl#create",
        test_level="L3",
        primary_oracle="HTTP+DB+CAT",
        data_domain="guarantor",
        required_capabilities=["test_execution", "db_read", "cat_query"],
        estimated_duration_minutes=10,
    )
    n8_delivery = NodeDelivery(
        delivery_id="ND-M-RC72-1-N8-V1",
        mission_id=batch.mission_id,
        mission_node_id=n8.mission_node_id,
        node_type=AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY,
        version=1,
        producer_ref="worker://diagnosis/attempt-1",
        input_refs=["attempt://N7/failed-1"],
        artifact_refs=["artifact://diagnosis/v1"],
        evidence_refs=["evidence://failure/1"],
        known_gaps=["GAP-M-RC72-1-N7-ANALYSIS"],
        created_by_workitems=["WI-N8-001"],
    )

    for entity in (batch, n4, n8, n4_delivery, gate, obligation, etu, n8_delivery):
        receipt = repository.persist(entity)
        assert receipt.status == "PERSISTENCE_VERIFIED"
        assert receipt.persisted_count == 1
        assert receipt.queryable_count == 1

    # BackEdge reuses the existing canonical RC7 Gap rather than inventing a
    # second RC7.2 gap store.
    gap = Gap(
        gap_id="GAP-M-RC72-1-N7-ANALYSIS",
        mission_id=batch.mission_id,
        source_node="N8_DIAGNOSIS_RECOVERY",
        category="RUNTIME_DISCOVERED_CODE_PATH",
        severity=GapSeverity.HIGH,
        target_node="N3_CODE_ANALYSIS",
        description="execution revealed a code constraint missing from accepted analysis",
    )
    append_entity(truth, gap, release_id="RC7.2")
    back_edge = BackEdge(
        back_edge_id="BE-M-RC72-1-001",
        mission_id=batch.mission_id,
        gap_id=gap.gap_id,
        from_node=AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY,
        from_delivery_id=n8_delivery.delivery_id,
        return_node=AutonomousMissionNode.N3_CODE_ANALYSIS,
        reason="ANALYSIS_GAP",
        invalidated_refs=[n4_delivery.delivery_id],
        state=BackEdgeState.OPEN,
    )
    receipt = repository.persist(back_edge)
    assert receipt.status == "PERSISTENCE_VERIFIED"

    assert truth.query("rc72_release_batch", release_batch_id=batch.release_batch_id)[0]["mission_id"] == batch.mission_id
    assert truth.query("rc72_mission_node", mission_id=batch.mission_id)[0]["node_type"] == "N4_TEST_DESIGN"
    assert truth.query("rc72_test_obligation", obligation_id=obligation.obligation_id)[0]["sst_id"] == "STB913-14130"
    assert truth.query("rc72_etu", etu_id=etu.etu_id)[0]["case_ids"] == ["TC-001", "TC-002", "TC-003"]
    assert truth.query("rc72_back_edge", back_edge_id=back_edge.back_edge_id)[0]["return_node"] == "N3_CODE_ANALYSIS"

    # Session/process-independent truth: rebuild entirely from the R1 JSONL.
    replayed = TruthRuntime(event_path)
    assert replayed.query("rc72_release_batch", release_batch_id=batch.release_batch_id)[0]["name"] == batch.name
    replayed_gate = replayed.query("rc72_node_gate", gate_id=gate.gate_id)[0]
    assert replayed_gate["decision"] == "PASS"
    assert replayed_gate["reviewer_worker_id"] == "quality-reviewer-N4-001"
    assert replayed_gate["reviewer_session_id"] == "session-review-N4-001"
    assert replayed.query("rc72_test_obligation", obligation_id=obligation.obligation_id)[0]["requirement_id"] == "STBB19-322"
    assert replayed.query("rc72_etu", etu_id=etu.etu_id)[0]["obligation_id"] == obligation.obligation_id
    replayed_edge = replayed.query("rc72_back_edge", back_edge_id=back_edge.back_edge_id)[0]
    assert replayed_edge["from_delivery_id"] == n8_delivery.delivery_id
    assert replayed_edge["state"] == "OPEN"


def test_etu_default_guard_prevents_large_round_batch_from_becoming_one_unit() -> None:
    with pytest.raises(ContractError, match="ETU_CASE_COUNT_EXCEEDS_DEFAULT_MAX"):
        ExecutionTaskUnit(
            etu_id="ETU-TOO-LARGE",
            mission_id="M-RC72-1",
            release_batch_id="RB-2026-10-28",
            obligation_id="TO-1",
            case_ids=["TC-%02d" % i for i in range(1, 10)],
            primary_goal="too many heterogeneous cases",
            primary_code_slice="slice",
            test_level="L3",
            primary_oracle="HTTP",
            data_domain="mixed",
        )
