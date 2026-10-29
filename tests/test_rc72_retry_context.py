from __future__ import annotations

from types import SimpleNamespace

import pytest

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.diagnosis import AttemptHistoryEntry, RecoveryDecision
from rc7_runtime.attempt_lineage import LineageAwareAttemptHistory
from rc7_runtime.models import ContractError, Task
from rc7_runtime.rc72_context_economy import (
    ContextAffinity,
    ExecutionMode,
    SemanticWorkDescriptor,
    build_retry_delta,
)
from rc7_runtime.rc72_model_economy import MissionCriticality, SemanticCostClass
from rc7_runtime.rc72_retry_context import RetryContextAuditService


class _MemoryTruth:
    def __init__(self):
        self.projection = SimpleNamespace(_versions={})
        self.events = []

    def query(self, artifact_type, **filters):
        bucket_name = _truth.BUCKETS.get(artifact_type)
        bucket = getattr(self.projection, bucket_name, {}) if bucket_name else {}
        return [
            dict(row)
            for row in bucket.values()
            if all(row.get(name) == value for name, value in filters.items())
        ]

    def append_atomic(self, event_type, payload):
        artifact_type, identity = _truth.EVENT_TYPES[event_type]
        validator = _contracts.VALIDATORS[artifact_type]
        row = validator(dict(payload))
        bucket_name = _truth.BUCKETS[artifact_type]
        if not hasattr(self.projection, bucket_name):
            setattr(self.projection, bucket_name, {})
        bucket = getattr(self.projection, bucket_name)
        current = bucket.get(row[identity])
        if current is not None:
            assert row["artifact_version"] == current["artifact_version"] + 1
        bucket[row[identity]] = dict(row)
        self.events.append((event_type, dict(row)))
        return row


def _task():
    return Task(
        task_id="WI-1",
        mission_id="MISSION-1",
        node="TEST_DESIGN",
        task_type="REPAIR",
        objective="repair missing boundary and oracle coverage",
        input_artifact_refs=["ART-REQ-1", "ART-CODE-1", "file:///full/requirement.md"],
        gap_refs=["GAP-1"],
        acceptance_criteria=["boundary covered", "oracle explicit"],
        required_capabilities=["filesystem"],
    )


def _descriptor(task, *, retry_delta=None):
    return SemanticWorkDescriptor.from_task(
        task,
        stage="DESIGN",
        execution_mode=ExecutionMode.SEMANTIC,
        mission_criticality=MissionCriticality.BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        affinity=ContextAffinity(requirement_id="REQ-1", sst_id="SST-1"),
        retry_delta=retry_delta,
    )


def _history():
    history = LineageAwareAttemptHistory()
    history.append(
        AttemptHistoryEntry(
            attempt_id="ATT-1",
            parent_attempt_id=None,
            tc_id="TC-1",
            case_version=1,
            target_id="FAT1",
            layer="L3",
            status="FAILED",
            evidence_refs=("EVD-FAIL-1",),
            recorded_at=1,
            failure_signature_id="FSIG-1",
        )
    )
    history.reserve_successor(
        RecoveryDecision(
            diagnosis_id="DIAG-1",
            attempt_id="ATT-1",
            action="RETRY_SAME_STEP",
            retry_allowed=True,
            reprepare_allowed=False,
            terminal=False,
            next_attempt_id="ATT-2",
            reason="repair explicit assertion gap",
        )
    )
    return history


def _service(history=None):
    truth = _MemoryTruth()
    service = RetryContextAuditService(
        truth,
        release_id="REL-1",
        attempt_history=history or _history(),
    )
    return truth, service


def _retry(*, summary="ATT-SUMMARY-1", evidence="file:///delta/db-assertion.json"):
    return build_retry_delta(
        previous_attempt_summary_ref=summary,
        explicit_gap_refs=("GAP-1",),
        delta_evidence_refs=(evidence,),
        changed_dependency_refs=("ART-DATA-V2",),
    )


def test_observed_retry_delta_binds_real_parent_attempt_and_persists_r1_audit():
    truth, service = _service()
    task = _task()
    row = service.observe(
        task=task,
        attempt_id="ATT-2",
        assignment_id="ASN-2",
        descriptor=_descriptor(task, retry_delta=_retry()),
    )

    assert row["observation_status"] == "OBSERVED"
    assert row["parent_attempt_id"] == "ATT-1"
    assert row["context_mode"] == "RETRY_DELTA"
    assert row["explicit_gap_refs"] == ["GAP-1"]
    assert row["delta_evidence_refs"] == ["file:///delta/db-assertion.json"]
    assert row["changed_dependency_refs"] == ["ART-DATA-V2"]
    assert row["canonical_lineage_refs_not_in_delta"] == [
        "ART-REQ-1",
        "ART-CODE-1",
        "file:///full/requirement.md",
    ]
    assert row["retry_delta_sha256"]
    assert [event for event, _ in truth.events] == ["RC72_RETRY_CONTEXT_COMPILED"]


def test_retry_without_resolved_delta_is_unknown_and_does_not_block_mission():
    truth, service = _service()
    task = _task()
    row = service.observe(
        task=task,
        attempt_id="ATT-2",
        assignment_id="ASN-2",
        descriptor=_descriptor(task),
    )

    assert row["observation_status"] == "UNKNOWN"
    assert row["context_mode"] == "RETRY_DELTA_UNKNOWN"
    assert row["retry_delta_sha256"] is None
    assert row["previous_attempt_summary_ref"] is None
    assert len(truth.events) == 1


def test_unknown_retry_context_can_upgrade_to_observed_without_rewriting_attempt_lineage():
    truth, service = _service()
    task = _task()
    first = service.observe(
        task=task,
        attempt_id="ATT-2",
        assignment_id="ASN-2",
        descriptor=_descriptor(task),
    )
    second = service.observe(
        task=task,
        attempt_id="ATT-2",
        assignment_id="ASN-2",
        descriptor=_descriptor(task, retry_delta=_retry()),
    )

    assert first["artifact_version"] == 1
    assert second["artifact_version"] == 2
    assert second["observation_status"] == "OBSERVED"
    assert second["parent_attempt_id"] == "ATT-1"
    assert len(truth.events) == 2


def test_same_observed_retry_delta_is_idempotent_but_conflicting_delta_is_immutable():
    truth, service = _service()
    task = _task()
    descriptor = _descriptor(task, retry_delta=_retry())
    first = service.observe(
        task=task,
        attempt_id="ATT-2",
        assignment_id="ASN-2",
        descriptor=descriptor,
    )
    replay = service.observe(
        task=task,
        attempt_id="ATT-2",
        assignment_id="ASN-2",
        descriptor=descriptor,
    )
    assert replay == first
    assert len(truth.events) == 1

    with pytest.raises(ContractError, match="RETRY_CONTEXT_IMMUTABLE"):
        service.observe(
            task=task,
            attempt_id="ATT-2",
            assignment_id="ASN-2",
            descriptor=_descriptor(task, retry_delta=_retry(summary="ATT-SUMMARY-CONFLICT")),
        )


def test_retry_delta_without_real_parent_attempt_is_structural_truth_failure():
    history = LineageAwareAttemptHistory()
    truth, service = _service(history=history)
    task = _task()
    with pytest.raises(ContractError, match="RETRY_DELTA_REQUIRES_REAL_PARENT_ATTEMPT"):
        service.observe(
            task=task,
            attempt_id="ATT-ORPHAN",
            assignment_id="ASN-ORPHAN",
            descriptor=_descriptor(task, retry_delta=_retry()),
        )
    assert truth.events == []


def test_retry_delta_gap_must_belong_to_canonical_task_gap_lineage():
    truth, service = _service()
    task = _task()
    bad_retry = build_retry_delta(
        previous_attempt_summary_ref="ATT-SUMMARY-1",
        explicit_gap_refs=("GAP-INVENTED",),
        delta_evidence_refs=("EVD-DELTA-1",),
    )
    with pytest.raises(ContractError, match="RETRY_DELTA_GAP_NOT_IN_CANONICAL_TASK_LINEAGE"):
        service.observe(
            task=task,
            attempt_id="ATT-2",
            assignment_id="ASN-2",
            descriptor=_descriptor(task, retry_delta=bad_retry),
        )
    assert truth.events == []
