from __future__ import annotations

from rc7_runtime.models import Task
from rc7_runtime.rc72_context_economy import (
    ContextAffinity,
    ContextEnvelopeBuilder,
    ExecutionBatchPlanner,
    ExecutionMode,
    SemanticWorkDescriptor,
    build_retry_delta,
)
from rc7_runtime.rc72_model_economy import MissionCriticality, SemanticCostClass


def _descriptor(
    workitem_id: str,
    *,
    requirement: str = "REQ-1",
    sst: str = "SST-1",
    service: str = "cfg-scd",
    node: str = "TEST_DESIGN",
    stage: str = "DESIGN",
    mode: ExecutionMode = ExecutionMode.SEMANTIC,
    refs=(),
    gaps=(),
    retry_delta=None,
    batch_eligible: bool = True,
):
    return SemanticWorkDescriptor(
        workitem_id=workitem_id,
        mission_id="MISSION-1",
        node=node,
        stage=stage,
        execution_mode=mode,
        mission_criticality=MissionCriticality.NON_BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        affinity=ContextAffinity(
            requirement_id=requirement,
            sst_id=sst,
            service=service,
            environment="FAT1",
            data_domain="loan",
            oracle_family="api-db",
            tool_family="codegraph",
        ),
        input_refs=tuple(refs),
        gap_refs=tuple(gaps),
        retry_delta=retry_delta,
        batch_eligible=batch_eligible,
    )


def test_compatible_same_sst_workitems_share_one_batch_but_keep_member_ids():
    planner = ExecutionBatchPlanner(max_batch_size=8)
    items = [
        _descriptor("WI-1", refs=("ART-REQ", "ART-CODE", "ART-CASE-1")),
        _descriptor("WI-2", refs=("ART-REQ", "ART-CODE", "ART-CASE-2")),
        _descriptor("WI-3", refs=("ART-REQ", "ART-CODE", "ART-CASE-3")),
    ]
    plan = planner.plan(items)
    assert len(plan.batches) == 1
    batch = plan.batches[0]
    assert batch.workitem_ids == ("WI-1", "WI-2", "WI-3")
    assert batch.context_envelope.shared_refs == ("ART-CODE", "ART-REQ")
    assert batch.context_envelope.workitem_refs["WI-1"] == ("ART-CASE-1",)
    assert batch.context_envelope.workitem_refs["WI-2"] == ("ART-CASE-2",)
    assert batch.context_envelope.workitem_refs["WI-3"] == ("ART-CASE-3",)


def test_different_sst_never_batches_even_if_technical_context_matches():
    planner = ExecutionBatchPlanner(max_batch_size=8)
    plan = planner.plan([
        _descriptor("WI-1", sst="SST-A", refs=("ART-SHARED",)),
        _descriptor("WI-2", sst="SST-B", refs=("ART-SHARED",)),
    ])
    assert len(plan.batches) == 2
    assert all(batch.member_count == 1 for batch in plan.batches)
    assert set(plan.unbatched_semantic_workitem_ids) == {"WI-1", "WI-2"}


def test_missing_business_affinity_fails_closed_to_singleton_not_cross_task_batch():
    planner = ExecutionBatchPlanner(max_batch_size=8)
    items = [
        SemanticWorkDescriptor(
            workitem_id="WI-1",
            mission_id="MISSION-1",
            node="TEST_DESIGN",
            stage="DESIGN",
            execution_mode=ExecutionMode.SEMANTIC,
            mission_criticality=MissionCriticality.NON_BLOCKING,
            semantic_cost_class=SemanticCostClass.HIGH,
            affinity=ContextAffinity(),
            input_refs=("ART-A",),
        ),
        SemanticWorkDescriptor(
            workitem_id="WI-2",
            mission_id="MISSION-1",
            node="TEST_DESIGN",
            stage="DESIGN",
            execution_mode=ExecutionMode.SEMANTIC,
            mission_criticality=MissionCriticality.NON_BLOCKING,
            semantic_cost_class=SemanticCostClass.HIGH,
            affinity=ContextAffinity(),
            input_refs=("ART-A",),
        ),
    ]
    plan = planner.plan(items)
    assert len(plan.batches) == 2
    assert set(plan.unbatched_semantic_workitem_ids) == {"WI-1", "WI-2"}


def test_deterministic_items_are_excluded_from_semantic_batches():
    planner = ExecutionBatchPlanner(max_batch_size=8)
    plan = planner.plan([
        _descriptor("WI-DB", mode=ExecutionMode.DETERMINISTIC, refs=("DB-REF",)),
        _descriptor("WI-SEM", refs=("ART-REQ",)),
    ])
    assert plan.deterministic_workitem_ids == ("WI-DB",)
    assert len(plan.batches) == 1
    assert plan.batches[0].workitem_ids == ("WI-SEM",)


def test_batch_size_is_bounded_without_coarsening_workitem_truth():
    planner = ExecutionBatchPlanner(max_batch_size=2)
    plan = planner.plan([
        _descriptor("WI-%s" % index, refs=("ART-SHARED", "ART-%s" % index))
        for index in range(5)
    ])
    assert [batch.member_count for batch in plan.batches] == [2, 2, 1]
    members = [item for batch in plan.batches for item in batch.workitem_ids]
    assert members == ["WI-0", "WI-1", "WI-2", "WI-3", "WI-4"]


def test_retry_delta_excludes_unchanged_full_context_by_default():
    retry = build_retry_delta(
        previous_attempt_summary_ref="ATT-SUMMARY-1",
        explicit_gap_refs=("GAP-MISSING-DB-ASSERTION",),
        delta_evidence_refs=("EVD-NEW-DB",),
        changed_dependency_refs=("ART-DATA-V2",),
    )
    item = _descriptor(
        "WI-RETRY",
        refs=("ART-REQ-FULL", "ART-CODE-FULL", "ART-CASE-FULL"),
        retry_delta=retry,
    )
    envelope = ContextEnvelopeBuilder.build([item])
    retry_refs = envelope.retry_delta_refs["WI-RETRY"]
    assert retry_refs == (
        "ATT-SUMMARY-1",
        "GAP-MISSING-DB-ASSERTION",
        "EVD-NEW-DB",
        "ART-DATA-V2",
    )
    assert "ART-REQ-FULL" not in retry_refs
    assert "ART-CODE-FULL" not in retry_refs
    assert "ART-CASE-FULL" not in retry_refs
    projection = envelope.as_prompt_projection()
    assert projection["full_context_workitem_ids"] == []


def test_full_retry_context_requires_explicit_reason_and_is_auditable():
    retry = build_retry_delta(
        previous_attempt_summary_ref="ATT-SUMMARY-1",
        explicit_gap_refs=("GAP-UPSTREAM-REVISION",),
        delta_evidence_refs=("EVD-CHANGE",),
        full_context_reason="UPSTREAM_REQUIREMENT_REVISION_INVALIDATED_PRIOR_PROJECTION",
    )
    item = _descriptor(
        "WI-RETRY",
        refs=("ART-REQ-V2", "ART-CODE", "ART-CASE"),
        retry_delta=retry,
    )
    envelope = ContextEnvelopeBuilder.build([item])
    assert envelope.full_context_workitem_ids == ("WI-RETRY",)
    assert envelope.shared_refs == ("ART-CASE", "ART-CODE", "ART-REQ-V2")
    assert envelope.workitem_refs["WI-RETRY"] == ()
    assert envelope.retry_delta_refs["WI-RETRY"] == (
        "ATT-SUMMARY-1",
        "GAP-UPSTREAM-REVISION",
        "EVD-CHANGE",
    )


def test_from_task_is_projection_only_and_does_not_mutate_canonical_task():
    task = Task(
        task_id="WI-1",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="design boundary obligations",
        input_artifact_refs=["ART-REQ", "ART-CODE"],
        gap_refs=["GAP-1"],
    )
    before_inputs = list(task.input_artifact_refs)
    before_gaps = list(task.gap_refs)
    projected = SemanticWorkDescriptor.from_task(
        task,
        stage="DESIGN",
        affinity=ContextAffinity(requirement_id="REQ-1", sst_id="SST-1"),
    )
    assert projected.workitem_id == task.task_id
    assert projected.input_refs == ("ART-REQ", "ART-CODE")
    assert task.input_artifact_refs == before_inputs
    assert task.gap_refs == before_gaps


def test_same_batch_aggregates_blocking_criticality_without_losing_members():
    blocking = _descriptor("WI-BLOCK", refs=("ART-SHARED", "ART-A"))
    blocking = SemanticWorkDescriptor(
        **{
            **blocking.__dict__,
            "mission_criticality": MissionCriticality.BLOCKING,
        }
    )
    nonblocking = _descriptor("WI-NONBLOCK", refs=("ART-SHARED", "ART-B"))
    batch = ExecutionBatchPlanner(max_batch_size=8).plan([blocking, nonblocking]).batches[0]
    assert batch.mission_criticality == MissionCriticality.BLOCKING
    assert batch.workitem_ids == ("WI-BLOCK", "WI-NONBLOCK")
