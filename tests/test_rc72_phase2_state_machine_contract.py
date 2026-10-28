from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_domain import (
    AutonomousMissionNode,
    ExecutionTaskUnit,
    MissionNodeState,
    NodeDelivery,
    NodeGate,
    NodeGateDecision,
    ObligationStatus,
    ReleaseBatch,
    TestObligation,
)
from rc7_runtime.rc72_state_machine import (
    FailureClass,
    RC72StateMachine,
    ReleaseConvergenceFacts,
    ReleaseConvergenceResult,
    StateMachineContractError,
)


def _runtime(tmp_path: Path):
    event_path = tmp_path / "r1.jsonl"
    truth = TruthRuntime(event_path)
    runtime = RC72StateMachine(truth, release_id="RC7.2")
    batch = ReleaseBatch(
        release_batch_id="RB-1",
        mission_id="M-1",
        name="batch 1",
        application_ids=["cfg-center"],
        requirement_ids=["REQ-1"],
    )
    runtime.bootstrap_release_batch(batch)
    return truth, runtime, event_path


def _node(runtime: RC72StateMachine, node_type: AutonomousMissionNode):
    return runtime.node_by_type("M-1", node_type)


def _pass_node(runtime: RC72StateMachine, node_type: AutonomousMissionNode, version: int = 1):
    node = _node(runtime, node_type)
    if node["state"] == "NOT_STARTED":
        runtime.transition_state(node["mission_node_id"], MissionNodeState.READY, reason="dependencies satisfied")
    if runtime.node(node["mission_node_id"])["state"] == "READY":
        runtime.transition_state(node["mission_node_id"], MissionNodeState.RUNNING, reason="work started")
    delivery = NodeDelivery(
        delivery_id="ND-%s-V%d" % (node_type.value, version),
        mission_id="M-1",
        mission_node_id=node["mission_node_id"],
        node_type=node_type,
        version=version,
        producer_ref="worker://%s/%d" % (node_type.value, version),
        input_refs=[],
        artifact_refs=["artifact://%s/%d" % (node_type.value, version)],
        evidence_refs=["evidence://%s/%d" % (node_type.value, version)],
        created_by_workitems=["WI-%s-%d" % (node_type.value, version)],
    )
    runtime.submit_delivery(delivery)
    gate = NodeGate(
        gate_id="GATE-%s-V%d" % (node_type.value, version),
        mission_id="M-1",
        mission_node_id=node["mission_node_id"],
        node_type=node_type,
        delivery_id=delivery.delivery_id,
        decision=NodeGateDecision.PASS,
        reviewer_worker_id="fresh-reviewer-%s-%d" % (node_type.value, version),
        reviewer_session_id="fresh-review-session-%s-%d" % (node_type.value, version),
        criteria=["contract criteria satisfied"],
        passed=["contract criteria satisfied"],
        evidence_refs=["evidence://review/%s/%d" % (node_type.value, version)],
    )
    runtime.apply_gate(gate)
    return delivery, gate


def _advance_pass_chain(runtime: RC72StateMachine, through: AutonomousMissionNode):
    ordered = list(AutonomousMissionNode.ordered())
    stop = ordered.index(through)
    previous = None
    previous_gate = None
    for node_type in ordered[: stop + 1]:
        if node_type in {
            AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY,
            AutonomousMissionNode.N9_DEFECT,
            AutonomousMissionNode.N10_RELEASE_CONVERGENCE,
        }:
            break
        if previous is not None:
            runtime.forward(previous, node_type, source_gate_id=previous_gate.gate_id)
        _, gate = _pass_node(runtime, node_type)
        previous = node_type
        previous_gate = gate


def test_bootstrap_creates_real_n1_n10_nodes_and_only_n1_is_ready(tmp_path: Path):
    truth, runtime, _ = _runtime(tmp_path)
    rows = truth.query("rc72_mission_node", mission_id="M-1")
    assert len(rows) == 10
    states = {row["node_type"]: row["state"] for row in rows}
    assert states["N1_REALITY"] == "READY"
    assert all(states[node.value] == "NOT_STARTED" for node in AutonomousMissionNode.ordered()[1:])


def test_node_cannot_become_pass_without_persisted_gate(tmp_path: Path):
    _, runtime, _ = _runtime(tmp_path)
    n1 = _node(runtime, AutonomousMissionNode.N1_REALITY)
    runtime.transition_state(n1["mission_node_id"], MissionNodeState.RUNNING, reason="start reality")
    with pytest.raises(StateMachineContractError, match="PASS_REQUIRES_NODE_GATE"):
        runtime.transition_state(n1["mission_node_id"], MissionNodeState.PASS, reason="agent said completed")
    _pass_node(runtime, AutonomousMissionNode.N1_REALITY)
    assert runtime.node(n1["mission_node_id"])["state"] == "PASS"


def test_forward_requires_pass_and_non_stale_mandatory_upstream(tmp_path: Path):
    _, runtime, _ = _runtime(tmp_path)
    n1 = _node(runtime, AutonomousMissionNode.N1_REALITY)
    with pytest.raises(StateMachineContractError, match="FORWARD_SOURCE_NOT_PASS"):
        runtime.forward(AutonomousMissionNode.N1_REALITY, AutonomousMissionNode.N2_REQUIREMENT, source_gate_id="missing")

    _, gate1 = _pass_node(runtime, AutonomousMissionNode.N1_REALITY)
    runtime.forward(AutonomousMissionNode.N1_REALITY, AutonomousMissionNode.N2_REQUIREMENT, source_gate_id=gate1.gate_id)
    assert _node(runtime, AutonomousMissionNode.N2_REQUIREMENT)["state"] == "READY"

    runtime.mark_stale(
        n1["mission_node_id"],
        reason="environment changed",
    )
    with pytest.raises(StateMachineContractError, match="MANDATORY_UPSTREAM_NOT_PASS"):
        runtime.transition_state(
            _node(runtime, AutonomousMissionNode.N2_REQUIREMENT)["mission_node_id"],
            MissionNodeState.RUNNING,
            reason="must not run with stale N1",
        )


def test_duplicate_conflicting_active_delivery_is_rejected(tmp_path: Path):
    _, runtime, _ = _runtime(tmp_path)
    n1 = _node(runtime, AutonomousMissionNode.N1_REALITY)
    runtime.transition_state(n1["mission_node_id"], MissionNodeState.RUNNING, reason="start")
    first = NodeDelivery(
        delivery_id="ND-N1-A",
        mission_id="M-1",
        mission_node_id=n1["mission_node_id"],
        node_type=AutonomousMissionNode.N1_REALITY,
        version=1,
        producer_ref="worker://a",
        evidence_refs=["evidence://a"],
    )
    runtime.submit_delivery(first)
    conflict = NodeDelivery(
        delivery_id="ND-N1-B",
        mission_id="M-1",
        mission_node_id=n1["mission_node_id"],
        node_type=AutonomousMissionNode.N1_REALITY,
        version=1,
        producer_ref="worker://b",
        evidence_refs=["evidence://b"],
    )
    with pytest.raises(StateMachineContractError, match="CONFLICTING_ACTIVE_DELIVERY"):
        runtime.submit_delivery(conflict)


def test_n7_failure_moves_to_n8_instead_of_executor_redesigning_inline(tmp_path: Path):
    truth, runtime, _ = _runtime(tmp_path)
    _advance_pass_chain(runtime, AutonomousMissionNode.N6_EXECUTABLE_READINESS)
    n6_gate = truth.query("rc72_node_gate", mission_id="M-1")[-1]
    runtime.forward(
        AutonomousMissionNode.N6_EXECUTABLE_READINESS,
        AutonomousMissionNode.N7_EXECUTION,
        source_gate_id=n6_gate["gate_id"],
    )
    n7 = _node(runtime, AutonomousMissionNode.N7_EXECUTION)
    runtime.transition_state(n7["mission_node_id"], MissionNodeState.RUNNING, reason="execute contract")
    transition = runtime.route_execution_failure(
        failure_evidence_refs=["evidence://attempt/failure-1"],
        reason="actual result cannot honor executable contract",
    )
    assert runtime.node(n7["mission_node_id"])["state"] == "NEEDS_REVISION"
    assert _node(runtime, AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)["state"] == "READY"
    persisted = truth.query("rc72_node_transition", transition_id=transition.transition_id)[0]
    assert persisted["kind"] == "DIAGNOSIS"
    assert persisted["to_node_type"] == "N8_DIAGNOSIS_RECOVERY"


@pytest.mark.parametrize(
    "failure_class,target",
    [
        (FailureClass.ENVIRONMENT_GAP, AutonomousMissionNode.N1_REALITY),
        (FailureClass.REQUIREMENT_GAP, AutonomousMissionNode.N2_REQUIREMENT),
        (FailureClass.ANALYSIS_GAP, AutonomousMissionNode.N3_CODE_ANALYSIS),
        (FailureClass.TEST_DESIGN_GAP, AutonomousMissionNode.N4_TEST_DESIGN),
        (FailureClass.TEST_DATA_GAP, AutonomousMissionNode.N5_TEST_DATA),
        (FailureClass.EXECUTABLE_GAP, AutonomousMissionNode.N6_EXECUTABLE_READINESS),
        (FailureClass.PRODUCT_DEFECT, AutonomousMissionNode.N9_DEFECT),
    ],
)
def test_n8_classification_creates_persisted_semantic_route(tmp_path: Path, failure_class, target):
    truth, runtime, _ = _runtime(tmp_path)
    n8 = _node(runtime, AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
    runtime.transition_state(n8["mission_node_id"], MissionNodeState.READY, reason="failure arrived")
    runtime.transition_state(n8["mission_node_id"], MissionNodeState.RUNNING, reason="diagnose")
    delivery = NodeDelivery(
        delivery_id="ND-N8-%s" % failure_class.value,
        mission_id="M-1",
        mission_node_id=n8["mission_node_id"],
        node_type=AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY,
        version=1,
        producer_ref="worker://fresh-diagnosis/%s" % failure_class.value,
        evidence_refs=["evidence://diagnosis/%s" % failure_class.value],
    )
    runtime.submit_delivery(delivery)
    gate = NodeGate(
        gate_id="GATE-N8-%s" % failure_class.value,
        mission_id="M-1",
        mission_node_id=n8["mission_node_id"],
        node_type=AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY,
        delivery_id=delivery.delivery_id,
        decision=NodeGateDecision.PASS,
        reviewer_worker_id="fresh-reviewer-%s" % failure_class.value,
        reviewer_session_id="fresh-session-%s" % failure_class.value,
        criteria=["classification supported by evidence"],
        passed=["classification supported by evidence"],
        evidence_refs=["evidence://review/%s" % failure_class.value],
    )
    runtime.apply_gate(gate)
    route = runtime.route_diagnosis(
        failure_class,
        source_delivery_id=delivery.delivery_id,
        evidence_refs=["evidence://diagnosis/%s" % failure_class.value],
        affected_refs=["asset://affected/1"],
        rationale="classification is evidence-backed",
    )
    assert route.responsible_node == target
    assert truth.query("rc7_gap", gap_id=route.gap_id)
    assert truth.query("rc72_back_edge", back_edge_id=route.back_edge_id)
    transition = truth.query("rc72_node_transition", transition_id=route.transition_id)[0]
    assert transition["to_node_type"] == target.value
    assert _node(runtime, target)["state"] == "NEEDS_REVISION"


def test_explicit_impact_marks_downstream_assets_stale_and_blocks_n7_dispatch(tmp_path: Path):
    truth, runtime, _ = _runtime(tmp_path)
    _advance_pass_chain(runtime, AutonomousMissionNode.N3_CODE_ANALYSIS)
    n3 = _node(runtime, AutonomousMissionNode.N3_CODE_ANALYSIS)
    n3_delivery = truth.query("rc72_node_delivery", mission_node_id=n3["mission_node_id"])[0]

    n4 = _node(runtime, AutonomousMissionNode.N4_TEST_DESIGN)
    runtime.transition_state(n4["mission_node_id"], MissionNodeState.READY, reason="prepare dependent design")
    runtime.transition_state(n4["mission_node_id"], MissionNodeState.RUNNING, reason="design")
    n4_delivery = NodeDelivery(
        delivery_id="ND-N4-DEPENDENT",
        mission_id="M-1",
        mission_node_id=n4["mission_node_id"],
        node_type=AutonomousMissionNode.N4_TEST_DESIGN,
        version=1,
        producer_ref="worker://designer/1",
        input_refs=["dto://GuarantorRequest#status"],
        evidence_refs=["evidence://design/1"],
    )
    runtime.submit_delivery(n4_delivery)
    runtime.apply_gate(NodeGate(
        gate_id="GATE-N4-DEPENDENT",
        mission_id="M-1",
        mission_node_id=n4["mission_node_id"],
        node_type=AutonomousMissionNode.N4_TEST_DESIGN,
        delivery_id=n4_delivery.delivery_id,
        decision=NodeGateDecision.PASS,
        reviewer_worker_id="fresh-reviewer-n4",
        reviewer_session_id="fresh-review-session-n4",
        criteria=["design sufficient"],
        passed=["design sufficient"],
    ))
    obligation = TestObligation(
        obligation_id="TO-STALE",
        mission_id="M-1",
        release_batch_id="RB-1",
        requirement_id="REQ-1",
        sst_id="SST-1",
        application_id="cfg-center",
        business_scenario="guarantor",
        business_rule="status required",
        risk_level="HIGH",
        test_level="L3",
        code_slice_refs=["dto://GuarantorRequest#status"],
        oracle_refs=["HTTP"],
    )
    runtime.repository.persist(obligation)
    etu = ExecutionTaskUnit(
        etu_id="ETU-STALE",
        mission_id="M-1",
        release_batch_id="RB-1",
        obligation_id="TO-STALE",
        case_ids=["TC-STALE"],
        primary_goal="verify status",
        primary_code_slice="dto://GuarantorRequest#status",
        test_level="L3",
        primary_oracle="HTTP",
        data_domain="guarantor",
        primary_tool_family="api",
        planning_snapshot_ref="snapshot://stale",
        cohesion_score=1.0,
        cohesion_explanation="single target",
    )
    runtime.repository.persist(etu)

    impact = runtime.propagate_stale(
        source_delivery_id=n3_delivery["delivery_id"],
        changed_refs=["dto://GuarantorRequest#status"],
        reason="N3 DTO constraint changed",
    )
    assert "MN-M-1-N4_TEST_DESIGN" in impact.stale_mission_node_ids
    assert "TO-STALE" in impact.stale_obligation_ids
    assert "ETU-STALE" in impact.stale_etu_ids
    assert _node(runtime, AutonomousMissionNode.N4_TEST_DESIGN)["state"] == "STALE"
    assert truth.query("rc72_test_obligation", obligation_id="TO-STALE")[0]["status"] == ObligationStatus.STALE.value
    assert truth.query("rc72_etu", etu_id="ETU-STALE")[0]["state"] == "STALE"
    with pytest.raises(StateMachineContractError, match="N7_DISPATCH_BLOCKED_BY_UPSTREAM"):
        runtime.assert_n7_dispatchable(etu_id="ETU-STALE")


def test_coverage_only_can_never_converge_release_batch(tmp_path: Path):
    _, runtime, _ = _runtime(tmp_path)
    result = runtime.evaluate_convergence(
        ReleaseConvergenceFacts(
            requirement_completion=False,
            sst_completion=False,
            obligation_completion=False,
            required_l1_l7_completion=False,
            high_risk_completion=False,
            incremental_coverage_met=True,
            critical_defects_closed=False,
            no_blocked_workitems=False,
            no_unresolved_gaps=False,
            evidence_complete=False,
            runtime_integrity=False,
        )
    )
    assert result == ReleaseConvergenceResult.NOT_CONVERGED


def test_state_machine_recovers_current_truth_from_r1_without_session_history(tmp_path: Path):
    truth, runtime, event_path = _runtime(tmp_path)
    _pass_node(runtime, AutonomousMissionNode.N1_REALITY)
    assert _node(runtime, AutonomousMissionNode.N1_REALITY)["state"] == "PASS"

    replayed_truth = TruthRuntime(event_path)
    recovered = RC72StateMachine(replayed_truth, release_id="RC7.2")
    assert recovered.node_by_type("M-1", AutonomousMissionNode.N1_REALITY)["state"] == "PASS"
    assert recovered.node_by_type("M-1", AutonomousMissionNode.N1_REALITY)["active_delivery_version"] == 1
