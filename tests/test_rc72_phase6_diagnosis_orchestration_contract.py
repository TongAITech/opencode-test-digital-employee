from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Evidence, Task
from rc7_runtime.rc72_diagnosis_orchestration import DiagnosisOrchestrator
from rc7_runtime.rc72_domain import (
    AutonomousMissionNode,
    ExecutionTaskUnit,
    MissionNodeState,
    NodeDelivery,
    NodeGate,
    NodeGateDecision,
    ReleaseBatch,
    TestObligation,
)
from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.rc72_state_machine import FailureClass, RC72StateMachine
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
from rc7_runtime.truth_overlay import append_entity


def _pass_node(runtime: RC72StateMachine, node_type: AutonomousMissionNode, version=1):
    node = runtime.node_by_type("M-1", node_type)
    if node["state"] == "NOT_STARTED":
        runtime.transition_state(node["mission_node_id"], MissionNodeState.READY, reason="phase6 upstream ready")
    if runtime.node(node["mission_node_id"])["state"] == "READY":
        runtime.transition_state(node["mission_node_id"], MissionNodeState.RUNNING, reason="phase6 upstream work")
    delivery = NodeDelivery(
        delivery_id="ND-%s-V%d" % (node_type.value, version),
        mission_id="M-1",
        mission_node_id=node["mission_node_id"],
        node_type=node_type,
        version=version,
        producer_ref="worker://%s" % node_type.value,
        artifact_refs=["artifact://%s" % node_type.value],
        evidence_refs=["evidence://%s" % node_type.value],
        created_by_workitems=["WI-%s" % node_type.value],
    )
    runtime.submit_delivery(delivery)
    gate = NodeGate(
        gate_id="GATE-%s-V%d" % (node_type.value, version),
        mission_id="M-1",
        mission_node_id=node["mission_node_id"],
        node_type=node_type,
        delivery_id=delivery.delivery_id,
        decision=NodeGateDecision.PASS,
        reviewer_worker_id="reviewer-%s" % node_type.value,
        reviewer_session_id="review-session-%s" % node_type.value,
        criteria=["evidence backed"],
        passed=["evidence backed"],
        evidence_refs=["evidence://review/%s" % node_type.value],
    )
    runtime.apply_gate(gate)
    return delivery, gate


def _advance_to_n7_running(runtime: RC72StateMachine):
    ordered = [
        AutonomousMissionNode.N1_REALITY,
        AutonomousMissionNode.N2_REQUIREMENT,
        AutonomousMissionNode.N3_CODE_ANALYSIS,
        AutonomousMissionNode.N4_TEST_DESIGN,
        AutonomousMissionNode.N5_TEST_DATA,
        AutonomousMissionNode.N6_EXECUTABLE_READINESS,
    ]
    previous = None
    previous_gate = None
    for node_type in ordered:
        if previous is not None:
            runtime.forward(previous, node_type, source_gate_id=previous_gate.gate_id)
        _, previous_gate = _pass_node(runtime, node_type)
        previous = node_type
    runtime.forward(
        AutonomousMissionNode.N6_EXECUTABLE_READINESS,
        AutonomousMissionNode.N7_EXECUTION,
        source_gate_id=previous_gate.gate_id,
    )
    n7 = runtime.node_by_type("M-1", AutonomousMissionNode.N7_EXECUTION)
    runtime.transition_state(n7["mission_node_id"], MissionNodeState.RUNNING, reason="execute immutable contract")


def _setup(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    runtime = RC72StateMachine(truth, release_id="RC7.2")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    runtime.bootstrap_release_batch(
        ReleaseBatch(
            release_batch_id="RB-1",
            mission_id="M-1",
            name="batch",
            application_ids=["cfg-center"],
            requirement_ids=["REQ-1"],
        )
    )
    repo.persist(
        TestObligation(
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
    )
    repo.persist(
        ExecutionTaskUnit(
            etu_id="ETU-1",
            mission_id="M-1",
            release_batch_id="RB-1",
            obligation_id="TO-1",
            case_ids=["TC-1"],
            primary_goal="execute TC-1",
            primary_code_slice="Service#create",
            test_level="L3",
            primary_oracle="HTTP+DB",
            data_domain="guarantor",
            primary_tool_family="api",
            planning_snapshot_ref="PLAN-1",
            cohesion_score=1.0,
            cohesion_explanation="single high-risk case",
            required_capabilities=["tool:api"],
            estimated_duration_minutes=5,
            estimated_cost=1.0,
        )
    )
    append_entity(
        truth,
        Task(
            task_id="WI-1",
            mission_id="M-1",
            node="N7_EXECUTION",
            task_type="ETU_EXECUTION",
            objective="execute ETU-1",
            required_capabilities=["api"],
            input_artifact_refs=["ETU-1", "EXEC-1"],
            acceptance_criteria=["evidence persisted"],
        ),
        release_id="RC7.2",
    )
    repo.persist(
        WorkItemAttemptBinding(
            binding_id="BIND-1",
            mission_id="M-1",
            etu_id="ETU-1",
            workitem_id="WI-1",
            case_id="TC-1",
            attempt_id="ATT-1",
            worker_id="EXEC-WORKER-1",
            session_id="DSH-EXEC-SESSION-1",
            task_lease_ref="LEASE-EXEC-1",
            state=WorkItemAttemptState.RUNNING,
        )
    )
    append_entity(
        truth,
        Evidence(
            evidence_id="EVD-FAIL-1",
            mission_id="M-1",
            kind="EXECUTION_FAILURE",
            source_ref="attempt://ATT-1",
            content_ref="evidence://failure/ATT-1",
            subject_refs=["ATT-1", "WI-1", "ETU-1", "TC-1"],
        ),
        release_id="RC7.2",
    )
    _advance_to_n7_running(runtime)
    workers = WorkerLifecycleService(truth, release_id="RC7.2")
    orchestrator = DiagnosisOrchestrator(
        truth,
        release_id="RC7.2",
        state_machine=runtime,
        worker_lifecycle=workers,
    )
    return truth, runtime, repo, orchestrator


def _begin(orchestrator):
    return orchestrator.begin_failure_diagnosis(
        mission_id="M-1",
        team_id="TEAM-1",
        source_binding_id="BIND-1",
        failure_evidence_refs=["EVD-FAIL-1"],
        executable_contract_refs=["EXEC-1"],
        reason="actual result differs from executable contract",
    )


def _accept_n8(runtime: RC72StateMachine, assignment, failure_class: FailureClass):
    n8 = runtime.node_by_type("M-1", AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
    runtime.transition_state(n8["mission_node_id"], MissionNodeState.RUNNING, reason="fresh diagnosis running")
    delivery = NodeDelivery(
        delivery_id="ND-N8-%s" % failure_class.value,
        mission_id="M-1",
        mission_node_id=n8["mission_node_id"],
        node_type=AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY,
        version=1,
        producer_ref="worker://%s" % assignment.worker_id,
        artifact_refs=["diagnosis://%s" % assignment.diagnosis_id],
        evidence_refs=["EVD-FAIL-1"],
        created_by_workitems=["DIAG-%s" % assignment.diagnosis_id],
    )
    runtime.submit_delivery(delivery)
    gate = NodeGate(
        gate_id="GATE-N8-%s" % failure_class.value,
        mission_id="M-1",
        mission_node_id=n8["mission_node_id"],
        node_type=AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY,
        delivery_id=delivery.delivery_id,
        decision=NodeGateDecision.PASS,
        reviewer_worker_id="fresh-diagnosis-reviewer-%s" % failure_class.value,
        reviewer_session_id="fresh-diagnosis-review-session-%s" % failure_class.value,
        criteria=["classification supported by evidence"],
        passed=["classification supported by evidence"],
        evidence_refs=["EVD-FAIL-1"],
    )
    runtime.apply_gate(gate)
    return delivery


def test_n7_failure_dispatches_fresh_diagnosis_worker_without_executor_chat(tmp_path: Path):
    truth, runtime, _, orchestrator = _setup(tmp_path)
    before = truth.query("rc72_workitem_attempt_binding", binding_id="BIND-1")[0]

    assignment = _begin(orchestrator)

    n8 = runtime.node_by_type("M-1", AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
    assert n8["state"] == "READY"
    assert assignment.source_attempt_id == "ATT-1"
    assert assignment.session_id != "DSH-EXEC-SESSION-1"
    session = truth.query("rc72_worker_session", session_id=assignment.session_id)[0]
    assert session["purpose"] == "DIAGNOSIS"
    assert session["worker_id"] == assignment.worker_id
    assert session["context_bundle"]["source_attempt_id"] == "ATT-1"
    assert session["context_bundle"]["failure_evidence_refs"] == ["EVD-FAIL-1"]
    assert session["context_bundle"]["executable_contract_refs"] == ["EXEC-1"]
    assert "chat_history" not in session["context_bundle"]
    assert "previous_session_transcript" not in session["context_bundle"]
    after = truth.query("rc72_workitem_attempt_binding", binding_id="BIND-1")[0]
    assert after["attempt_id"] == before["attempt_id"]
    assert after["state"] == before["state"] == "RUNNING"


@pytest.mark.parametrize(
    "failure_class,target",
    [
        (FailureClass.ANALYSIS_GAP, AutonomousMissionNode.N3_CODE_ANALYSIS),
        (FailureClass.TEST_DESIGN_GAP, AutonomousMissionNode.N4_TEST_DESIGN),
        (FailureClass.TEST_DATA_GAP, AutonomousMissionNode.N5_TEST_DATA),
        (FailureClass.EXECUTABLE_GAP, AutonomousMissionNode.N6_EXECUTABLE_READINESS),
        (FailureClass.PRODUCT_DEFECT, AutonomousMissionNode.N9_DEFECT),
    ],
)
def test_accepted_diagnosis_routes_semantically_without_mutating_original_attempt(tmp_path: Path, failure_class, target):
    truth, runtime, _, orchestrator = _setup(tmp_path)
    assignment = _begin(orchestrator)
    delivery = _accept_n8(runtime, assignment, failure_class)

    outcome = orchestrator.accept_classification(
        diagnosis_id=assignment.diagnosis_id,
        failure_class=failure_class,
        source_delivery_id=delivery.delivery_id,
        evidence_refs=["EVD-FAIL-1"],
        affected_refs=["Service#create", "TO-1", "ETU-1"],
        rationale="evidence-backed diagnosis",
    )

    assert outcome.responsible_node == target
    assert truth.query("rc7_gap", gap_id=outcome.gap_id)
    assert truth.query("rc72_back_edge", back_edge_id=outcome.back_edge_id)
    original = truth.query("rc72_workitem_attempt_binding", binding_id="BIND-1")[0]
    assert original["attempt_id"] == "ATT-1"
    assert original["state"] == "RUNNING"
    persisted = truth.query("rc72_diagnosis_outcome", diagnosis_id=assignment.diagnosis_id)[0]
    assert persisted["failure_class"] == failure_class.value
    assert persisted["source_attempt_id"] == "ATT-1"


@pytest.mark.parametrize(
    "failure_class,action",
    [
        (FailureClass.PROVIDER_QUOTA, "RUNTIME_RECOVERY"),
        (FailureClass.CAPABILITY_GAP, "CAPABILITY_BROKER"),
        (FailureClass.RESOURCE_CONFLICT, "RESOURCE_MANAGER"),
    ],
)
def test_runtime_failures_do_not_become_sut_defects(tmp_path: Path, failure_class, action):
    truth, runtime, _, orchestrator = _setup(tmp_path)
    assignment = _begin(orchestrator)
    delivery = _accept_n8(runtime, assignment, failure_class)

    outcome = orchestrator.accept_classification(
        diagnosis_id=assignment.diagnosis_id,
        failure_class=failure_class,
        source_delivery_id=delivery.delivery_id,
        evidence_refs=["EVD-FAIL-1"],
        affected_refs=["ETU-1"],
        rationale="runtime failure",
    )

    assert outcome.action == action
    assert outcome.gap_id is None
    assert outcome.back_edge_id is None
    assert not truth.query("rc7_defect", mission_id="M-1")


def test_unknown_diagnosis_stays_blocked_and_never_auto_passes(tmp_path: Path):
    truth, runtime, _, orchestrator = _setup(tmp_path)
    assignment = _begin(orchestrator)
    delivery = _accept_n8(runtime, assignment, FailureClass.UNKNOWN)

    outcome = orchestrator.accept_classification(
        diagnosis_id=assignment.diagnosis_id,
        failure_class=FailureClass.UNKNOWN,
        source_delivery_id=delivery.delivery_id,
        evidence_refs=["EVD-FAIL-1"],
        affected_refs=["ETU-1"],
        rationale="evidence is insufficient to classify",
    )

    n8 = runtime.node_by_type("M-1", AutonomousMissionNode.N8_DIAGNOSIS_RECOVERY)
    assert outcome.action == "DIAGNOSIS_BLOCKED"
    assert n8["state"] == "BLOCKED"
    assert truth.query("rc72_diagnosis_outcome", diagnosis_id=assignment.diagnosis_id)[0]["failure_class"] == "UNKNOWN"


def test_replacement_attempt_requires_parent_lineage_and_survives_r1_replay(tmp_path: Path):
    truth, _, repo, orchestrator = _setup(tmp_path)
    assignment = _begin(orchestrator)
    replacement = WorkItemAttemptBinding(
        binding_id="BIND-2",
        mission_id="M-1",
        etu_id="ETU-1",
        workitem_id="WI-1",
        case_id="TC-1",
        attempt_id="ATT-2",
        worker_id="EXEC-WORKER-2",
        session_id="DSH-EXEC-SESSION-2",
        task_lease_ref="LEASE-EXEC-2",
        parent_attempt_id="ATT-1",
        state=WorkItemAttemptState.RUNNING,
    )
    repo.persist(replacement)

    recovery = orchestrator.record_replacement_attempt(
        diagnosis_id=assignment.diagnosis_id,
        replacement_binding_id="BIND-2",
    )
    assert recovery.original_attempt_id == "ATT-1"
    assert recovery.replacement_attempt_id == "ATT-2"

    replayed = TruthRuntime(tmp_path / "r1.jsonl")
    row = replayed.query("rc72_diagnosis_recovery", diagnosis_id=assignment.diagnosis_id)[0]
    assert row["original_attempt_id"] == "ATT-1"
    assert row["replacement_attempt_id"] == "ATT-2"
    assert replayed.query("rc72_workitem_attempt_binding", binding_id="BIND-1")[0]["attempt_id"] == "ATT-1"
