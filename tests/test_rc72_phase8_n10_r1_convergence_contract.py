from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.defect_loop import DefectRecord, DefectStatus
from rc7_runtime.models import Evaluation, EvaluationResult, Evidence, Task, TaskStatus
from rc7_runtime.rc72_coverage_convergence import CoverageFeedbackService
from rc7_runtime.rc72_domain import (
    AutonomousMissionNode,
    ETUState,
    ExecutionTaskUnit,
    MissionNodeState,
    NodeDelivery,
    NodeGate,
    NodeGateDecision,
    ObligationStatus,
    ReleaseBatch,
    TestObligation,
)
from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from rc7_runtime.rc72_release_convergence import ReleaseConvergenceAggregator
from rc7_runtime.rc72_release_scope import ReleaseScopeManifest, ReleaseScopeService
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.rc72_state_machine import RC72StateMachine, ReleaseConvergenceResult
from rc7_runtime.truth_overlay import append_entity


def _bootstrap(tmp_path: Path):
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
    return truth, runtime, repo


def _manifest(truth):
    scope = ReleaseScopeService(truth, release_id="RC7.2")
    scope.persist_manifest(
        ReleaseScopeManifest(
            manifest_id="SCOPE-1",
            mission_id="M-1",
            release_batch_id="RB-1",
            requirement_ssts={"REQ-1": ["SST-1"]},
            required_levels_by_sst={"SST-1": ["L3"]},
            source_refs=["starlink://release-batch/RB-1"],
        )
    )
    return scope


def _obligation(status=ObligationStatus.VERIFIED):
    return TestObligation(
        obligation_id="TO-1",
        mission_id="M-1",
        release_batch_id="RB-1",
        requirement_id="REQ-1",
        sst_id="SST-1",
        application_id="cfg-center",
        business_scenario="create guarantor",
        business_rule="government guarantor creation",
        risk_level="HIGH",
        test_level="L3",
        code_slice_refs=["GuarantorServiceImpl#create:type2"],
        oracle_refs=["HTTP", "DB"],
        coverage_targets=["GuarantorServiceImpl#create:type2"],
        status=status,
    )


def _pass_n1_n9(runtime: RC72StateMachine):
    ordered = list(AutonomousMissionNode.ordered())
    for index, node_type in enumerate(ordered[:-1]):
        node = runtime.node_by_type("M-1", node_type)
        assert node["state"] == MissionNodeState.READY.value
        runtime.transition_state(node["mission_node_id"], MissionNodeState.RUNNING, reason="test delivery")
        delivery = NodeDelivery(
            delivery_id=f"ND-{node_type.value}",
            mission_id="M-1",
            mission_node_id=node["mission_node_id"],
            node_type=node_type,
            version=1,
            producer_ref=f"worker://{node_type.value}",
            artifact_refs=[f"artifact://{node_type.value}"],
            evidence_refs=[f"node-evidence://{node_type.value}"],
            sufficiency_score=1.0,
        )
        runtime.submit_delivery(delivery)
        gate = NodeGate(
            gate_id=f"NG-{node_type.value}",
            mission_id="M-1",
            mission_node_id=node["mission_node_id"],
            node_type=node_type,
            delivery_id=delivery.delivery_id,
            decision=NodeGateDecision.PASS,
            reviewer_worker_id=f"reviewer-{node_type.value}",
            reviewer_session_id=f"review-session-{node_type.value}",
            criteria=["canonical delivery reviewed"],
            passed=["canonical delivery reviewed"],
            evidence_refs=[f"review-evidence://{node_type.value}"],
        )
        runtime.apply_gate(gate)
        runtime.forward(node_type, ordered[index + 1], source_gate_id=gate.gate_id)


def _coverage(truth, covered=920, total=1000, target=0.92):
    coverage = CoverageFeedbackService(truth, release_id="RC7.2")
    coverage.record_observation(
        observation_id="COV-1",
        mission_id="M-1",
        release_batch_id="RB-1",
        application_id="cfg-center",
        source="LIBRA",
        covered_units=covered,
        total_units=total,
        target_ratio=target,
        evidence_ref="libra://snapshot/1",
    )
    return coverage


def _execution_proof(truth, repo):
    repo.persist(
        ExecutionTaskUnit(
            etu_id="ETU-1",
            mission_id="M-1",
            release_batch_id="RB-1",
            obligation_id="TO-1",
            case_ids=["TC-1"],
            primary_goal="execute TC-1",
            primary_code_slice="GuarantorServiceImpl#create:type2",
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
            state=ETUState.PASS,
        )
    )
    append_entity(
        truth,
        Evidence(
            evidence_id="EV-ATT-1",
            mission_id="M-1",
            kind="EXECUTION",
            source_ref="attempt://ATT-1",
            content_ref="evidence://ATT-1",
            subject_refs=["ATT-1", "TC-1", "TO-1"],
        ),
        release_id="RC7.2",
    )
    truth.append_atomic(
        "EXECUTION_ATTEMPT_UPSERTED",
        {
            "attempt_id": "ATT-1",
            "release_id": "RC7.2",
            "requirement_id": "REQ-1",
            "tc_id": "TC-1",
            "case_version": 1,
            "target_id": "cfg-center",
            "layer": "L3",
            "status": "PASS",
            "actual_result": {"http": 200, "db": "asserted"},
            "tool_call_refs": ["tool://api/ATT-1"],
            "evidence_refs": ["EV-ATT-1"],
            "worker_id": "worker-1",
            "lease_id": "LEASE-1",
            "artifact_version": 1,
        },
    )
    append_entity(
        truth,
        Evaluation(
            evaluation_id="EVAL-WI-1",
            mission_id="M-1",
            node="N7_EXECUTION",
            artifact_refs=["ETU-1"],
            result=EvaluationResult.PASS,
            evaluator_ref="fresh-reviewer-1",
            dimensions={"attempt_pass": True, "evidence_complete": True},
            evidence_refs=["EV-ATT-1"],
        ),
        release_id="RC7.2",
    )
    append_entity(
        truth,
        Task(
            task_id="WI-1",
            mission_id="M-1",
            node="N7_EXECUTION",
            task_type="ETU_EXECUTION",
            objective="execute ETU-1",
            state=TaskStatus.PASS,
            required_capabilities=["api"],
            input_artifact_refs=["ETU-1"],
            acceptance_criteria=["attempt PASS with canonical evidence"],
            lease_owner="worker-1",
            output_artifact_refs=["ETU-1"],
            evaluation_id="EVAL-WI-1",
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
            worker_id="worker-1",
            session_id="session-1",
            task_lease_ref="LEASE-1",
            state=WorkItemAttemptState.COMPLETED,
        )
    )


def _full_truth(tmp_path: Path):
    truth, runtime, repo = _bootstrap(tmp_path)
    _manifest(truth)
    repo.persist(_obligation())
    _execution_proof(truth, repo)
    _coverage(truth)
    _pass_n1_n9(runtime)
    return truth, runtime, repo


def test_missing_scope_manifest_fails_closed(tmp_path: Path):
    truth, runtime, _ = _bootstrap(tmp_path)
    aggregator = ReleaseConvergenceAggregator(truth, release_id="RC7.2", runtime=runtime)
    with pytest.raises(Exception, match="RELEASE_CONVERGENCE_SCOPE_MANIFEST_REQUIRED"):
        aggregator.aggregate(mission_id="M-1")


def test_92_percent_coverage_and_naked_verified_status_cannot_converge(tmp_path: Path):
    truth, runtime, repo = _bootstrap(tmp_path)
    _manifest(truth)
    repo.persist(_obligation(status=ObligationStatus.VERIFIED))
    _coverage(truth, covered=920, total=1000, target=0.92)
    _pass_n1_n9(runtime)

    snapshot = ReleaseConvergenceAggregator(truth, release_id="RC7.2", runtime=runtime).aggregate(mission_id="M-1")
    assert snapshot.facts.incremental_coverage_met is True
    assert snapshot.facts.obligation_completion is False
    assert snapshot.facts.required_l1_l7_completion is False
    assert snapshot.facts.high_risk_completion is False
    assert snapshot.facts.evidence_complete is False
    assert snapshot.result == ReleaseConvergenceResult.NOT_CONVERGED
    assert "TO-1" in snapshot.unproven_obligation_ids


def test_full_canonical_truth_converges_without_manual_pass_booleans(tmp_path: Path):
    truth, runtime, _ = _full_truth(tmp_path)
    snapshot = ReleaseConvergenceAggregator(truth, release_id="RC7.2", runtime=runtime).aggregate(mission_id="M-1")

    assert snapshot.facts.requirement_completion is True
    assert snapshot.facts.sst_completion is True
    assert snapshot.facts.obligation_completion is True
    assert snapshot.facts.required_l1_l7_completion is True
    assert snapshot.facts.high_risk_completion is True
    assert snapshot.facts.incremental_coverage_met is True
    assert snapshot.facts.critical_defects_closed is True
    assert snapshot.facts.no_blocked_workitems is True
    assert snapshot.facts.no_unresolved_gaps is True
    assert snapshot.facts.evidence_complete is True
    assert snapshot.facts.runtime_integrity is True
    assert snapshot.result == ReleaseConvergenceResult.CONVERGED


def test_open_coverage_gap_blocks_release_even_when_ratio_is_92_percent(tmp_path: Path):
    truth, runtime, _ = _full_truth(tmp_path)
    coverage = CoverageFeedbackService(truth, release_id="RC7.2")
    coverage.map_gap(
        gap_id="CG-1",
        observation_id="COV-1",
        code_slice="GuarantorServiceImpl#create:type2",
        uncovered_units=80,
    )

    snapshot = ReleaseConvergenceAggregator(truth, release_id="RC7.2", runtime=runtime).aggregate(mission_id="M-1")
    assert snapshot.facts.incremental_coverage_met is True
    assert snapshot.facts.no_unresolved_gaps is False
    assert snapshot.result == ReleaseConvergenceResult.NOT_CONVERGED
    assert "coverage-gap:CG-1" in snapshot.blockers


def test_high_or_critical_defect_must_be_closed_not_merely_deferred(tmp_path: Path):
    truth, runtime, _ = _full_truth(tmp_path)
    append_entity(
        truth,
        DefectRecord(
            defect_id="DEF-1",
            mission_id="M-1",
            source_gap_id="GAP-PRODUCT-1",
            requirement_refs=["REQ-1"],
            test_case_ids=["TC-1"],
            execution_attempt_ids=["ATT-1"],
            expected={"http": 200},
            actual={"http": 500},
            evidence_refs=["EV-ATT-1"],
            severity="HIGH",
            state=DefectStatus.DEFERRED,
        ),
        release_id="RC7.2",
    )

    snapshot = ReleaseConvergenceAggregator(truth, release_id="RC7.2", runtime=runtime).aggregate(mission_id="M-1")
    assert snapshot.facts.critical_defects_closed is False
    assert snapshot.result == ReleaseConvergenceResult.NOT_CONVERGED
    assert "defect:DEF-1:DEFERRED" in snapshot.blockers


def test_non_pass_workitem_blocks_release_convergence(tmp_path: Path):
    truth, runtime, _ = _full_truth(tmp_path)
    append_entity(
        truth,
        Task(
            task_id="WI-BLOCKED",
            mission_id="M-1",
            node="N7_EXECUTION",
            task_type="ETU_EXECUTION",
            objective="unfinished follow-up",
            state=TaskStatus.BLOCKED,
            acceptance_criteria=["must recover before release"],
        ),
        release_id="RC7.2",
    )

    snapshot = ReleaseConvergenceAggregator(truth, release_id="RC7.2", runtime=runtime).aggregate(mission_id="M-1")
    assert snapshot.facts.no_blocked_workitems is False
    assert snapshot.result == ReleaseConvergenceResult.NOT_CONVERGED
    assert "workitem:WI-BLOCKED:BLOCKED" in snapshot.blockers


def test_n1_n9_must_be_gate_passed_for_runtime_integrity(tmp_path: Path):
    truth, runtime, repo = _bootstrap(tmp_path)
    _manifest(truth)
    repo.persist(_obligation())
    _execution_proof(truth, repo)
    _coverage(truth)
    # N1 remains READY; do not manufacture PASS node state.

    snapshot = ReleaseConvergenceAggregator(truth, release_id="RC7.2", runtime=runtime).aggregate(mission_id="M-1")
    assert snapshot.facts.runtime_integrity is False
    assert snapshot.result == ReleaseConvergenceResult.NOT_CONVERGED
    assert "node:N1_REALITY:READY" in snapshot.blockers


def test_convergence_snapshot_survives_r1_replay(tmp_path: Path):
    truth, runtime, _ = _full_truth(tmp_path)
    snapshot = ReleaseConvergenceAggregator(truth, release_id="RC7.2", runtime=runtime).aggregate(mission_id="M-1")
    assert snapshot.result == ReleaseConvergenceResult.CONVERGED

    replay = TruthRuntime(tmp_path / "r1.jsonl")
    aggregator = ReleaseConvergenceAggregator(replay, release_id="RC7.2", runtime=RC72StateMachine(replay, release_id="RC7.2"))
    aggregator.install_overlay()
    row = replay.query("rc72_release_convergence_snapshot", snapshot_id=snapshot.snapshot_id)[0]
    assert row["result"] == "CONVERGED"
    assert row["facts"]["incremental_coverage_met"] is True
    assert row["facts"]["runtime_integrity"] is True
    assert row["unproven_obligation_ids"] == []
