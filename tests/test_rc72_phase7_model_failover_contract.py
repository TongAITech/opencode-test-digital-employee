from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Task
from rc7_runtime.rc72_domain import ExecutionTaskUnit, ReleaseBatch, TestObligation
from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from rc7_runtime.rc72_model_failover import (
    ModelFailoverManager,
    ProviderFailureClass,
    ProviderReadinessState,
)
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.rc72_worker_lifecycle import WorkerLifecycleService
from rc7_runtime.rc72_state_machine import RC72StateMachine
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
            business_scenario="provider failover execution",
            business_rule="provider failures must not become SUT failures",
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
            input_artifact_refs=["ETU-1"],
            acceptance_criteria=["evidence persisted"],
        ),
        release_id="RC7.2",
    )

    workers = WorkerLifecycleService(truth, release_id="RC7.2")
    original = workers.assign_fresh_worker(
        mission_id="M-1",
        team_id="TEAM-1",
        role="test-executor",
        etu_id="ETU-1",
        workitem_id="WI-1",
        canonical_refs={"etu_refs": ["ETU-1"]},
    )

    # A BLOCKED WorkItemAttemptBinding is accepted only when its inherited
    # execution_attempt truth exists. Keep that lineage real instead of
    # weakening CanonicalRC72Repository for a provider-control test.
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
            "status": "NOT_RUN",
            "tool_call_refs": [],
            "evidence_refs": [],
            "worker_id": original.worker_id,
            "lease_id": "LEASE-1",
            "artifact_version": 1,
        },
    )
    repo.persist(
        WorkItemAttemptBinding(
            binding_id="BIND-1",
            mission_id="M-1",
            etu_id="ETU-1",
            workitem_id="WI-1",
            case_id="TC-1",
            attempt_id="ATT-1",
            worker_id=original.worker_id,
            session_id=original.session_id,
            task_lease_ref="LEASE-1",
            state=WorkItemAttemptState.RUNNING,
        )
    )

    manager = ModelFailoverManager(
        truth,
        release_id="RC7.2",
        worker_lifecycle=workers,
    )
    manager.set_provider_readiness(
        provider="aicoder-plus",
        model="aicoder-plus",
        state=ProviderReadinessState.MODEL_READY,
        evidence_ref="probe://aicoder-plus/ready",
    )
    manager.set_provider_readiness(
        provider="dsv4",
        model="deepseek-v4-flash",
        state=ProviderReadinessState.MODEL_READY,
        evidence_ref="probe://dsv4/ready",
    )
    manager.set_provider_readiness(
        provider="wizard-bankgpt",
        model="bankgpt",
        state=ProviderReadinessState.MODEL_PROVIDER_UNAVAILABLE,
        evidence_ref="probe://bankgpt/unavailable",
    )
    manager.assign_model(
        assignment_id="MA-1",
        mission_id="M-1",
        workitem_id="WI-1",
        attempt_id="ATT-1",
        worker_id=original.worker_id,
        session_id=original.session_id,
        provider="aicoder-plus",
        model="aicoder-plus",
        capability_profile="general-test-execution",
        fallback_chain=["wizard-bankgpt:bankgpt", "dsv4:deepseek-v4-flash"],
    )
    return truth, repo, workers, manager, original


def test_model_assignment_is_attempt_worker_session_scoped_not_mission_scoped(tmp_path: Path):
    truth, _, _, _, original = _setup(tmp_path)
    row = truth.query("rc72_model_assignment", assignment_id="MA-1")[0]
    assert row["attempt_id"] == "ATT-1"
    assert row["worker_id"] == original.worker_id
    assert row["session_id"] == original.session_id
    assert row["provider"] == "aicoder-plus"
    assert row["state"] == "ACTIVE"


def test_quota_failure_blocks_old_attempt_and_checkpoints_old_worker(tmp_path: Path):
    truth, _, _, manager, original = _setup(tmp_path)
    manager.record_provider_failure(
        failure_id="PF-1",
        assignment_id="MA-1",
        failure_class=ProviderFailureClass.PROVIDER_QUOTA,
        reason="HTTP 451 daily quota exhausted",
        evidence_refs=["provider-evidence://451"],
    )

    failure = truth.query("rc72_provider_failure", failure_id="PF-1")[0]
    assert failure["failure_class"] == "PROVIDER_QUOTA"
    assert failure["state"] == "BLOCKED_PROVIDER"
    binding = truth.query("rc72_workitem_attempt_binding", binding_id="BIND-1")[0]
    assert binding["state"] == "BLOCKED"
    session = truth.query("rc72_worker_session", session_id=original.session_id)[0]
    assert session["state"] == "CLOSED"
    assert session["checkpoint_id"]
    assert not truth.query("rc7_defect")


def test_failover_skips_unready_provider_and_creates_fresh_worker_new_attempt(tmp_path: Path):
    truth, _, _, manager, original = _setup(tmp_path)
    manager.record_provider_failure(
        failure_id="PF-1",
        assignment_id="MA-1",
        failure_class=ProviderFailureClass.PROVIDER_QUOTA,
        reason="quota exhausted",
        evidence_refs=["provider-evidence://451"],
    )
    result = manager.failover(failure_id="PF-1", reason="continue same WorkItem on approved fallback")

    assert result.provider == "dsv4"
    assert result.model == "deepseek-v4-flash"
    assert result.attempt_id != "ATT-1"
    assert result.worker_id != original.worker_id
    assert result.session_id != original.session_id

    new_binding = truth.query("rc72_workitem_attempt_binding", attempt_id=result.attempt_id)[0]
    assert new_binding["workitem_id"] == "WI-1"
    assert new_binding["etu_id"] == "ETU-1"
    assert new_binding["parent_attempt_id"] == "ATT-1"
    assert new_binding["state"] == "PREPARED"

    old_assignment = truth.query("rc72_model_assignment", assignment_id="MA-1")[0]
    assert old_assignment["provider"] == "aicoder-plus"
    assert old_assignment["model"] == "aicoder-plus"
    assert old_assignment["state"] == "BLOCKED_PROVIDER"
    new_assignment = truth.query("rc72_model_assignment", assignment_id=result.assignment_id)[0]
    assert new_assignment["attempt_id"] == result.attempt_id
    assert new_assignment["worker_id"] == result.worker_id
    assert new_assignment["session_id"] == result.session_id
    assert new_assignment["state"] == "ACTIVE"


def test_failover_never_hot_swaps_existing_session_or_attempt(tmp_path: Path):
    truth, _, _, manager, original = _setup(tmp_path)
    manager.record_provider_failure(
        failure_id="PF-1",
        assignment_id="MA-1",
        failure_class=ProviderFailureClass.PROVIDER_TIMEOUT,
        reason="provider timed out",
        evidence_refs=["provider-evidence://timeout"],
    )
    result = manager.failover(failure_id="PF-1", reason="fresh takeover")

    assert result.attempt_id != "ATT-1"
    assert result.session_id != original.session_id
    assert truth.query("rc72_worker_session", session_id=original.session_id)[0]["state"] == "CLOSED"
    assert len(truth.query("rc72_model_assignment")) == 2


@pytest.mark.parametrize(
    "failure_class",
    [
        ProviderFailureClass.PROVIDER_AUTH,
        ProviderFailureClass.PROVIDER_QUOTA,
        ProviderFailureClass.PROVIDER_TIMEOUT,
        ProviderFailureClass.PROVIDER_UNAVAILABLE,
    ],
)
def test_supported_provider_failures_stay_in_provider_namespace(tmp_path: Path, failure_class):
    truth, _, _, manager, _ = _setup(tmp_path)
    manager.record_provider_failure(
        failure_id="PF-1",
        assignment_id="MA-1",
        failure_class=failure_class,
        reason="provider failure",
        evidence_refs=["provider-evidence://failure"],
    )
    row = truth.query("rc72_provider_failure", failure_id="PF-1")[0]
    assert row["failure_class"] == failure_class.value
    assert row["namespace"] == "PROVIDER_FAILURE"
    assert not truth.query("rc7_defect")


def test_no_ready_fallback_fails_closed_without_reusing_old_attempt(tmp_path: Path):
    truth, _, _, manager, _ = _setup(tmp_path)
    manager.set_provider_readiness(
        provider="dsv4",
        model="deepseek-v4-flash",
        state=ProviderReadinessState.MODEL_PROVIDER_UNAVAILABLE,
        evidence_ref="probe://dsv4/unavailable",
    )
    manager.record_provider_failure(
        failure_id="PF-1",
        assignment_id="MA-1",
        failure_class=ProviderFailureClass.PROVIDER_UNAVAILABLE,
        reason="provider unavailable",
        evidence_refs=["provider-evidence://unavailable"],
    )
    with pytest.raises(Exception, match="NO_READY_FALLBACK_MODEL"):
        manager.failover(failure_id="PF-1", reason="no ready fallback")

    assert len(truth.query("rc72_model_assignment")) == 1
    assert not truth.query("rc72_model_failover")


def test_config_invalid_is_recorded_but_not_auto_failed_over(tmp_path: Path):
    truth, _, _, manager, _ = _setup(tmp_path)
    manager.record_provider_failure(
        failure_id="PF-1",
        assignment_id="MA-1",
        failure_class=ProviderFailureClass.PROVIDER_CONFIG_INVALID,
        reason="model/provider configuration invalid",
        evidence_refs=["provider-evidence://config"],
    )
    with pytest.raises(Exception, match="PROVIDER_CONFIG_INVALID_REQUIRES_OPERATOR_REPAIR"):
        manager.failover(failure_id="PF-1", reason="unsafe automatic failover")
    assert not truth.query("rc72_model_failover")


def test_provider_failover_truth_survives_r1_replay(tmp_path: Path):
    truth, _, _, manager, _ = _setup(tmp_path)
    manager.record_provider_failure(
        failure_id="PF-1",
        assignment_id="MA-1",
        failure_class=ProviderFailureClass.PROVIDER_QUOTA,
        reason="quota exhausted",
        evidence_refs=["provider-evidence://451"],
    )
    result = manager.failover(failure_id="PF-1", reason="fresh fallback")

    replay = TruthRuntime(tmp_path / "r1.jsonl")
    manager.install_overlay()
    failover = replay.query("rc72_model_failover", failover_id=result.failover_id)[0]
    assert failover["source_attempt_id"] == "ATT-1"
    assert failover["replacement_attempt_id"] == result.attempt_id
    assert failover["replacement_worker_id"] == result.worker_id
    assert replay.query("rc72_model_assignment", assignment_id=result.assignment_id)[0]["state"] == "ACTIVE"
