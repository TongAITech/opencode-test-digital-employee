from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Task
from rc7_runtime.rc72_decomposer import DecompositionSnapshot, PlanningCase
from rc7_runtime.rc72_decomposition_truth import PersistentAdaptiveTaskDecomposer
from rc7_runtime.rc72_domain import (
    AutonomousMissionNode,
    ExecutionTaskUnit,
    MissionNodeRecord,
    ReleaseBatch,
    TestObligation,
)
from rc7_runtime.rc72_linkage import (
    MissionNodeLineageStatus,
    WorkItemAttemptBinding,
)
from rc7_runtime.rc72_repository import CanonicalRC72Repository, RC72LineageError
from rc7_runtime.truth_overlay import append_entity


def _obligation() -> TestObligation:
    return TestObligation(
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


def _truth_and_repo(tmp_path: Path):
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
    repo.persist(_obligation())
    return truth, repo


def _persist_task(truth: TruthRuntime, etu_id: str, *, node: str = "EXECUTION") -> None:
    append_entity(
        truth,
        Task(
            task_id="WI-1",
            mission_id="M-1",
            node=node,
            task_type="ETU_EXECUTION",
            objective="execute canonical ETU",
            required_capabilities=["api"],
            input_artifact_refs=[etu_id],
            acceptance_criteria=["evidence persisted"],
        ),
        release_id="RC7.2",
    )


def _persist_planned_etu(truth: TruthRuntime, repo: CanonicalRC72Repository, *, persist_n7: bool = True):
    if persist_n7:
        repo.persist(
            MissionNodeRecord(
                mission_node_id="MN-N7",
                mission_id="M-1",
                node_type=AutonomousMissionNode.N7_EXECUTION,
                scope_ref="release-batch://RB-1",
            )
        )
    planner = PersistentAdaptiveTaskDecomposer(truth, release_id="RC7.2")
    result = planner.plan_and_persist(
        DecompositionSnapshot(
            snapshot_id="PLAN-1",
            mission_id="M-1",
            release_batch_id="RB-1",
            current_node=AutonomousMissionNode.N7_EXECUTION.value,
            obligations=[_obligation()],
            cases=[
                PlanningCase(
                    case_id="TC-1",
                    release_batch_id="RB-1",
                    requirement_id="REQ-1",
                    sst_id="SST-1",
                    obligation_id="TO-1",
                    business_scenario="guarantor creation",
                    code_slice="Service#create",
                    test_level="L3",
                    data_domain="guarantor",
                    auth_role="tester",
                    oracle_family="HTTP+DB",
                    execution_tool="api",
                    browser_context="none",
                    environment="FAT1",
                )
            ],
        )
    )
    assert len(result.etus) == 1
    etu = result.etus[0]
    _persist_task(truth, etu.etu_id, node="EXECUTION")
    return etu


def test_binding_resolves_exact_mission_node_from_planning_snapshot_not_task_node(tmp_path: Path) -> None:
    truth, repo = _truth_and_repo(tmp_path)
    etu = _persist_planned_etu(truth, repo)

    binding = WorkItemAttemptBinding(
        binding_id="BIND-1",
        mission_id="M-1",
        etu_id=etu.etu_id,
        workitem_id="WI-1",
        case_id="TC-1",
        attempt_id="ATT-1",
    )
    repo.persist(binding)

    row = truth.query("rc72_workitem_attempt_binding", binding_id="BIND-1")[0]
    assert row["mission_node_lineage_status"] == "RESOLVED"
    assert row["mission_node_id"] == "MN-N7"
    assert row["mission_node_type"] == "N7_EXECUTION"
    assert row["mission_node_lineage_reason"] is None
    assert truth.query("rc7_task", task_id="WI-1")[0]["node"] == "EXECUTION"


def test_missing_snapshot_is_explicitly_unresolved_and_never_guessed_from_task_node(tmp_path: Path) -> None:
    truth, repo = _truth_and_repo(tmp_path)
    etu = ExecutionTaskUnit(
        etu_id="ETU-MANUAL",
        mission_id="M-1",
        release_batch_id="RB-1",
        obligation_id="TO-1",
        case_ids=["TC-1"],
        primary_goal="manual legacy fixture",
        primary_code_slice="Service#create",
        test_level="L3",
        primary_oracle="HTTP+DB",
        data_domain="guarantor",
        primary_tool_family="api",
        planning_snapshot_ref="PLAN-MISSING",
        cohesion_score=1.0,
        cohesion_explanation="legacy fixture",
    )
    repo.persist(etu)
    _persist_task(truth, etu.etu_id, node="N7_EXECUTION")

    repo.persist(
        WorkItemAttemptBinding(
            binding_id="BIND-UNRESOLVED",
            mission_id="M-1",
            etu_id=etu.etu_id,
            workitem_id="WI-1",
            case_id="TC-1",
            attempt_id="ATT-1",
        )
    )

    row = truth.query("rc72_workitem_attempt_binding", binding_id="BIND-UNRESOLVED")[0]
    assert row["mission_node_lineage_status"] == "UNRESOLVED"
    assert row["mission_node_id"] is None
    assert row["mission_node_type"] is None
    assert row["mission_node_lineage_reason"] == "PLANNING_SNAPSHOT_NOT_FOUND:PLAN-MISSING"


def test_existing_snapshot_without_canonical_mission_node_fails_closed(tmp_path: Path) -> None:
    truth, repo = _truth_and_repo(tmp_path)
    etu = _persist_planned_etu(truth, repo, persist_n7=False)

    with pytest.raises(RC72LineageError, match="WORKITEM_BINDING_MISSION_NODE_NOT_UNIQUE:N7_EXECUTION:0"):
        repo.persist(
            WorkItemAttemptBinding(
                binding_id="BIND-NO-NODE",
                mission_id="M-1",
                etu_id=etu.etu_id,
                workitem_id="WI-1",
                case_id="TC-1",
                attempt_id="ATT-1",
            )
        )


def test_claimed_node_conflicting_with_snapshot_fails_closed(tmp_path: Path) -> None:
    truth, repo = _truth_and_repo(tmp_path)
    etu = _persist_planned_etu(truth, repo)
    repo.persist(
        MissionNodeRecord(
            mission_node_id="MN-N4",
            mission_id="M-1",
            node_type=AutonomousMissionNode.N4_TEST_DESIGN,
            scope_ref="release-batch://RB-1",
        )
    )

    with pytest.raises(RC72LineageError, match="WORKITEM_BINDING_MISSION_NODE_ID_MISMATCH"):
        repo.persist(
            WorkItemAttemptBinding(
                binding_id="BIND-WRONG-NODE",
                mission_id="M-1",
                etu_id=etu.etu_id,
                workitem_id="WI-1",
                case_id="TC-1",
                attempt_id="ATT-1",
                mission_node_id="MN-N4",
                mission_node_type=AutonomousMissionNode.N4_TEST_DESIGN,
                mission_node_lineage_status=MissionNodeLineageStatus.RESOLVED,
                mission_node_lineage_reason=None,
            )
        )
