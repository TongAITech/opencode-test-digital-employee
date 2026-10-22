"""Scope-aware autonomous Mission Graph planning for one TestRound/TestRun.

The planner is deliberately pure: it creates deterministic domain StageInstance
objects and validates them through ``MissionGraphRuntime`` before persistence.
It does not call workers, infer PASS, or write runtime truth.

A production TestRound can contain multiple RequirementDeliveryScope values.
Each scope receives an independent analysis/design/execution chain.  The chains
converge only at MISSION_SUFFICIENCY, so one SST/application scope cannot hide
another scope's unresolved work.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Dict, List, Sequence, Tuple

from rc8_runtime.governance import StageInstance, StageState
from rc8_runtime.mission_graph import MissionGraphRuntime, MissionStageType


PLAN_POLICY_VERSION = "rc8.autonomous-mission-plan.v1"

# DELTA_REPAIR and TARGETED_REEXECUTION are intentionally not created here.
# They are dynamic repair work produced only when FAILURE_COVERAGE_EVALUATION
# identifies a real gap. Pre-creating them would turn a green run into fake work.
_SCOPE_STAGE_CHAIN: Tuple[MissionStageType, ...] = (
    MissionStageType.SCOPE_INTAKE,
    MissionStageType.REQUIREMENT_ANALYSIS,
    MissionStageType.REQUIREMENT_SUFFICIENCY,
    MissionStageType.CODE_ANALYSIS,
    MissionStageType.CODE_SUFFICIENCY,
    MissionStageType.RISK_TEST_MODEL,
    MissionStageType.TEST_DESIGN,
    MissionStageType.DESIGN_SUFFICIENCY,
    MissionStageType.EXECUTABLE_SPEC,
    MissionStageType.PRECONDITION_DATA_PREP,
    MissionStageType.APPLICABLE_LAYER_EXECUTION,
    MissionStageType.FAILURE_COVERAGE_EVALUATION,
)


@dataclass(frozen=True)
class PlannedMissionGraph:
    test_run_id: str
    test_round_id: str
    scope_refs: Tuple[str, ...]
    stages: Tuple[StageInstance, ...]
    initial_ready_stage_ids: Tuple[str, ...]
    mission_sufficiency_stage_id: str
    report_release_stage_id: str
    policy_version: str = PLAN_POLICY_VERSION

    @property
    def stage_count(self) -> int:
        return len(self.stages)


def _required(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("%s_REQUIRED" % name.upper())
    return normalized


def _normalized_scopes(scope_refs: Sequence[str]) -> Tuple[str, ...]:
    values: List[str] = []
    seen = set()
    for raw in scope_refs:
        value = _required(raw, "scope_ref")
        if value in seen:
            raise ValueError("MISSION_PLAN_DUPLICATE_SCOPE_REF")
        seen.add(value)
        values.append(value)
    if not values:
        raise ValueError("MISSION_PLAN_SCOPE_REQUIRED")
    return tuple(values)


def _stable_id(kind: str, test_run_id: str, scope_ref: str, stage_type: str) -> str:
    raw = "\x1f".join((kind, test_run_id, scope_ref, stage_type, "attempt:1"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    readable = stage_type.lower().replace("_", "-")
    return "%s-%s-%s" % (kind, readable[:48], digest)


def _scope_version(scope_ref: str) -> str:
    # RequirementDeliveryScope IDs are immutable. Prefixing makes the semantic
    # boundary explicit without inventing a second version counter.
    return "delivery-scope:%s" % scope_ref


def plan_test_round_mission(
    *,
    test_run_id: str,
    test_round_id: str,
    scope_refs: Sequence[str],
    policy_version: str = PLAN_POLICY_VERSION,
) -> PlannedMissionGraph:
    """Create and validate the initial autonomous graph for one testing round.

    Initial planning is scope-parallel. Only SCOPE_INTAKE roots become READY.
    Downstream stages remain PENDING and are unlocked by actual completion and
    sufficiency evidence through CenterMissionService.
    """
    run_id = _required(test_run_id, "test_run_id")
    round_id = _required(test_round_id, "test_round_id")
    policy = _required(policy_version, "policy_version")
    scopes = _normalized_scopes(scope_refs)

    raw_stages: List[StageInstance] = []
    failure_eval_ids: List[str] = []

    for scope_ref in scopes:
        version = _scope_version(scope_ref)
        predecessor_ids: Tuple[str, ...] = tuple()
        for stage_type in _SCOPE_STAGE_CHAIN:
            stage_id = _stable_id("stage", run_id, version, stage_type.value)
            stage = StageInstance(
                stage_instance_id=stage_id,
                test_run_id=run_id,
                stage_type=stage_type.value,
                scope_version=version,
                attempt_no=1,
                state=StageState.PENDING,
                input_refs=("test-round:%s" % round_id, version),
                predecessor_ids=predecessor_ids,
                policy_version=policy,
            )
            raw_stages.append(stage)
            predecessor_ids = (stage_id,)
        failure_eval_ids.append(predecessor_ids[0])

    mission_scope = "test-round:%s" % round_id
    mission_sufficiency_id = _stable_id(
        "stage",
        run_id,
        mission_scope,
        MissionStageType.MISSION_SUFFICIENCY.value,
    )
    raw_stages.append(
        StageInstance(
            stage_instance_id=mission_sufficiency_id,
            test_run_id=run_id,
            stage_type=MissionStageType.MISSION_SUFFICIENCY.value,
            scope_version=mission_scope,
            attempt_no=1,
            state=StageState.PENDING,
            input_refs=tuple(_scope_version(value) for value in scopes),
            predecessor_ids=tuple(failure_eval_ids),
            policy_version=policy,
        )
    )

    report_release_id = _stable_id(
        "stage",
        run_id,
        mission_scope,
        MissionStageType.REPORT_RELEASE.value,
    )
    raw_stages.append(
        StageInstance(
            stage_instance_id=report_release_id,
            test_run_id=run_id,
            stage_type=MissionStageType.REPORT_RELEASE.value,
            scope_version=mission_scope,
            attempt_no=1,
            state=StageState.PENDING,
            input_refs=(mission_scope,),
            predecessor_ids=(mission_sufficiency_id,),
            policy_version=policy,
        )
    )

    # Materialize successor refs for product/debug visibility, while dependency
    # truth remains predecessor-based and is revalidated by MissionGraphRuntime.
    successors: Dict[str, List[str]] = {stage.stage_instance_id: [] for stage in raw_stages}
    for stage in raw_stages:
        for predecessor_id in stage.predecessor_ids:
            successors[predecessor_id].append(stage.stage_instance_id)
    stages = [
        replace(stage, successor_ids=tuple(sorted(successors[stage.stage_instance_id])))
        for stage in raw_stages
    ]

    graph = MissionGraphRuntime(run_id)
    for stage in stages:
        graph.add_stage(stage)

    ready_ids: List[str] = []
    final_stages: List[StageInstance] = []
    for stage in stages:
        if graph.can_mark_ready(stage.stage_instance_id):
            updated = graph.mark_ready(stage.stage_instance_id)
            ready_ids.append(updated.stage_instance_id)
            final_stages.append(updated)
        else:
            final_stages.append(stage)

    # Exactly one intake root per scope must be initially schedulable; nothing
    # downstream may be READY merely because the plan was generated.
    if len(ready_ids) != len(scopes):
        raise ValueError("MISSION_PLAN_INITIAL_READY_SCOPE_COUNT_MISMATCH")
    if any(
        stage.state == StageState.READY and stage.stage_type != MissionStageType.SCOPE_INTAKE.value
        for stage in final_stages
    ):
        raise ValueError("MISSION_PLAN_DOWNSTREAM_STAGE_PREMATURELY_READY")

    return PlannedMissionGraph(
        test_run_id=run_id,
        test_round_id=round_id,
        scope_refs=scopes,
        stages=tuple(final_stages),
        initial_ready_stage_ids=tuple(sorted(ready_ids)),
        mission_sufficiency_stage_id=mission_sufficiency_id,
        report_release_stage_id=report_release_id,
        policy_version=policy,
    )
