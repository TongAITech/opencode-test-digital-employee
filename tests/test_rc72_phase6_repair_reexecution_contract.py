from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Evidence, Task
from rc7_runtime.rc72_diagnosis_orchestration import DiagnosisOrchestrator
from rc7_runtime.rc72_domain import (
    AutonomousMissionNode,
    ExecutionTaskUnit,
    MissionNodeRecord,
    MissionNodeState,
    NodeDelivery,
    ReleaseBatch,
    TestObligation,
)
from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.rc72_state_machine import FailureClass, RC72StateMachine
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
from rc7_runtime.truth_overlay import append_entity


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

    # Persist a representative downstream N6 delivery that depends on the code ref.
    # Phase 2 already proves that any STALE mandatory upstream/ETU blocks N7 dispatch;
    # this slice focuses only on proving that repair creates the correct stale truth.
    n6 = runtime.node_by_type("M-1", AutonomousMissionNode.N6_EXECUTABLE_READINESS)
    repo.persist(
        MissionNodeRecord(
            mission_node_id=n6["mission_node_id"],
            mission_id="M-1",
            node_type=AutonomousMissionNode.N6_EXECUTABLE_READINESS,
            scope_ref=n6["scope_ref"],
            state=MissionNodeState.PASS,
            active_delivery_version=1,
            delivery_refs=["ND-N6-OLD"],
            gate_refs=["GATE-N6-OLD"],
            revision=int(n6.get("revision") or 1) + 1,
        ),
        artifact_version=int(n6.get("artifact_version") or 1) + 1,
    )
    repo.persist(
        NodeDelivery(
            delivery_id="ND-N6-OLD",
            mission_id="M-1",
            mission_node_id=n6["mission_node_id"],
            node_type=AutonomousMissionNode.N6_EXECUTABLE_READINESS,
            version=1,
            producer_ref="worker://executable-builder",
            input_refs=["Service#create"],
            artifact_refs=["EXEC-1"],
            evidence_refs=["EVD-FAIL-1"],
            created_by_workitems=["WI-N6"],
        )
    )

    workers = WorkerLifecycleService(truth, release_id="RC7.2")
    orchestrator = DiagnosisOrchestrator(
        truth,
        release_id="RC7.2",
        state_machine=runtime,
        worker_lifecycle=workers,
    )
    return truth, runtime, repo, orchestrator


def _persist_diagnosis_case(truth, orchestrator):
    # This slice focuses on repair/re-execution semantics. Persist the already accepted
    # diagnosis truth directly rather than repeating Phase-6 slice-1 state-machine setup.
    diagnosis_id = "DIAG-1"
    orchestrator._append(
        "RC72_DIAGNOSIS_CASE_UPSERTED",
        {
            "diagnosis_id": diagnosis_id,
            "mission_id": "M-1",
            "team_id": "TEAM-1",
            "source_binding_id": "BIND-1",
            "source_attempt_id": "ATT-1",
            "source_workitem_id": "WI-1",
            "source_etu_id": "ETU-1",
            "diagnosis_worker_id": "DIAG-WORKER-1",
            "diagnosis_session_id": "DIAG-SESSION-1",
            "transition_id": "NT-DIAG-1",
            "failure_evidence_refs": ["EVD-FAIL-1"],
            "executable_contract_refs": ["EXEC-1"],
            "state": "CLASSIFIED",
            "reason": "analysis gap identified",
            "created_at": 1,
        },
    )
    orchestrator._append(
        "RC72_DIAGNOSIS_OUTCOME_UPSERTED",
        {
            "diagnosis_id": diagnosis_id,
            "mission_id": "M-1",
            "source_attempt_id": "ATT-1",
            "failure_class": FailureClass.ANALYSIS_GAP.value,
            "responsible_node": AutonomousMissionNode.N3_CODE_ANALYSIS.value,
            "action": "SEMANTIC_BACK_EDGE",
            "gap_id": "GAP-ANALYSIS-1",
            "back_edge_id": "BE-ANALYSIS-1",
            "transition_id": "NT-ANALYSIS-1",
            "evidence_refs": ["EVD-FAIL-1"],
            "affected_refs": ["Service#create", "TO-1", "ETU-1"],
            "rationale": "analysis missed a required constraint",
            "replacement_attempt_required": True,
            "created_at": 1,
        },
    )
    return diagnosis_id


def test_upstream_repair_persists_impact_and_marks_old_execution_assets_stale(tmp_path: Path):
    truth, runtime, repo, orchestrator = _setup(tmp_path)
    diagnosis_id = _persist_diagnosis_case(truth, orchestrator)

    n3 = runtime.node_by_type("M-1", AutonomousMissionNode.N3_CODE_ANALYSIS)
    repair_delivery = NodeDelivery(
        delivery_id="ND-N3-REPAIR-2",
        mission_id="M-1",
        mission_node_id=n3["mission_node_id"],
        node_type=AutonomousMissionNode.N3_CODE_ANALYSIS,
        version=2,
        producer_ref="worker://fresh-code-analyst",
        input_refs=["REQ-1", "SST-1"],
        artifact_refs=["analysis://v2"],
        evidence_refs=["EVD-FAIL-1"],
        created_by_workitems=["WI-N3-REPAIR"],
    )
    repo.persist(repair_delivery)

    repair = orchestrator.record_upstream_repair(
        diagnosis_id=diagnosis_id,
        repair_delivery_id=repair_delivery.delivery_id,
        changed_refs=["Service#create"],
        reason="N3 repair changed executable assumptions",
    )

    assert repair.original_attempt_id == "ATT-1"
    assert repair.replacement_attempt_required is True
    impact = truth.query("rc72_impact_set", impact_set_id=repair.impact_set_id)[0]
    assert "TO-1" in impact["stale_obligation_ids"]
    assert "ETU-1" in impact["stale_etu_ids"]
    assert "ND-N6-OLD" in impact["affected_refs"]
    assert truth.query("rc72_test_obligation", obligation_id="TO-1")[0]["status"] == "STALE"
    assert truth.query("rc72_etu", etu_id="ETU-1")[0]["state"] == "STALE"


def test_replacement_attempt_is_rejected_until_repair_impact_is_recorded(tmp_path: Path):
    _, _, repo, orchestrator = _setup(tmp_path)
    diagnosis_id = _persist_diagnosis_case(orchestrator.truth, orchestrator)
    repo.persist(
        WorkItemAttemptBinding(
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
    )

    with pytest.raises(Exception, match="REPLACEMENT_ATTEMPT_REQUIRES_REPAIR_IMPACT"):
        orchestrator.record_replacement_attempt(
            diagnosis_id=diagnosis_id,
            replacement_binding_id="BIND-2",
        )


def test_repair_then_new_attempt_records_immutable_attempt_lineage_and_replays(tmp_path: Path):
    truth, runtime, repo, orchestrator = _setup(tmp_path)
    diagnosis_id = _persist_diagnosis_case(truth, orchestrator)
    n3 = runtime.node_by_type("M-1", AutonomousMissionNode.N3_CODE_ANALYSIS)
    repair_delivery = NodeDelivery(
        delivery_id="ND-N3-REPAIR-2",
        mission_id="M-1",
        mission_node_id=n3["mission_node_id"],
        node_type=AutonomousMissionNode.N3_CODE_ANALYSIS,
        version=2,
        producer_ref="worker://fresh-code-analyst",
        artifact_refs=["analysis://v2"],
        evidence_refs=["EVD-FAIL-1"],
        created_by_workitems=["WI-N3-REPAIR"],
    )
    repo.persist(repair_delivery)
    repair = orchestrator.record_upstream_repair(
        diagnosis_id=diagnosis_id,
        repair_delivery_id=repair_delivery.delivery_id,
        changed_refs=["Service#create"],
        reason="analysis corrected",
    )
    repo.persist(
        WorkItemAttemptBinding(
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
    )

    recovery = orchestrator.record_replacement_attempt(
        diagnosis_id=diagnosis_id,
        replacement_binding_id="BIND-2",
    )

    assert recovery.original_attempt_id == "ATT-1"
    assert recovery.replacement_attempt_id == "ATT-2"
    original = truth.query("rc72_workitem_attempt_binding", binding_id="BIND-1")[0]
    assert original["attempt_id"] == "ATT-1"
    assert repair.impact_set_id

    replayed = TruthRuntime(tmp_path / "r1.jsonl")
    repair_truth = replayed.query("rc72_diagnosis_repair", diagnosis_id=diagnosis_id)[0]
    recovery_truth = replayed.query("rc72_diagnosis_recovery", diagnosis_id=diagnosis_id)[0]
    assert repair_truth["impact_set_id"] == repair.impact_set_id
    assert repair_truth["original_attempt_id"] == "ATT-1"
    assert recovery_truth["original_attempt_id"] == "ATT-1"
    assert recovery_truth["replacement_attempt_id"] == "ATT-2"
