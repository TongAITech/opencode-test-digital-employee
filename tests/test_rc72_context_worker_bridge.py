from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from rc7_runtime.dsh_worker_bridge import DshTaskWorkerBridge, DshWorkerBridgeError
from rc7_runtime.models import Task
from rc7_runtime.rc72_context_economy import (
    ContextAffinity,
    ExecutionMode,
    SemanticWorkDescriptor,
    build_retry_delta,
)
from rc7_runtime.rc72_context_worker_bridge import Rc72ContextAwareDshTaskWorkerBridge
from rc7_runtime.rc72_model_economy import MissionCriticality, SemanticCostClass


class _Truth:
    def query(self, artifact_type, **filters):
        return []


class _Control:
    def __init__(self):
        self.truth = _Truth()


class _Launcher:
    pass


class _RetryAudit:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def observe(self, *, task, attempt_id, assignment_id, descriptor):
        self.calls.append(
            {
                "task": task,
                "attempt_id": attempt_id,
                "assignment_id": assignment_id,
                "descriptor": descriptor,
            }
        )
        return self.row


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


def _assignment(*, attempt_id="ATT-2", assignment_id="ASN-2"):
    return SimpleNamespace(
        scope="task:WI-1",
        allowed_tools=("mcp__filesystem__read_text", "codegraph"),
        attempt_id=attempt_id,
        assignment_id=assignment_id,
    )


def _descriptor(task, *, retry_delta=None, mode=ExecutionMode.SEMANTIC):
    return SemanticWorkDescriptor.from_task(
        task,
        stage="DESIGN",
        execution_mode=mode,
        mission_criticality=MissionCriticality.BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        affinity=ContextAffinity(
            requirement_id="REQ-1",
            sst_id="SST-1",
            service="cfg-scd",
            environment="FAT1",
            data_domain="loan",
            oracle_family="api-db",
            tool_family="codegraph",
        ),
        retry_delta=retry_delta,
    )


def _contract(prompt):
    marker = "TASK_CONTRACT="
    start = prompt.index(marker) + len(marker)
    end = prompt.index("\nRETURN_SCHEMA=", start)
    return json.loads(prompt[start:end])


def test_no_descriptor_delegates_exactly_to_legacy_prompt():
    control = _Control()
    launcher = _Launcher()
    task = _task()
    assignment = _assignment()
    legacy = DshTaskWorkerBridge(control, launcher)
    rc72 = Rc72ContextAwareDshTaskWorkerBridge(control, launcher)
    assert rc72.compile_prompt(task, assignment) == legacy.compile_prompt(task, assignment)


def test_normal_context_keeps_canonical_lineage_and_adds_bounded_envelope():
    control = _Control()
    task = _task()
    before_inputs = list(task.input_artifact_refs)
    before_gaps = list(task.gap_refs)
    bridge = Rc72ContextAwareDshTaskWorkerBridge(
        control,
        _Launcher(),
        context_descriptor_resolver=lambda current: _descriptor(current),
    )
    contract = _contract(bridge.compile_prompt(task, _assignment()))

    assert contract["input_artifact_refs"] == before_inputs
    assert contract["gap_refs"] == before_gaps
    assert contract["context_mode"] == "NORMAL"
    assert contract["effective_context_refs"] == [
        "ART-REQ-1",
        "ART-CODE-1",
        "file:///full/requirement.md",
        "GAP-1",
    ]
    assert contract["context_envelope"]["workitem_ids"] == ["WI-1"]
    assert contract["model_economy"]["mission_criticality"] == "BLOCKING"
    assert contract["model_economy"]["semantic_cost_class"] == "HIGH"
    assert contract["model_economy"]["retry_context"]["observation_status"] == "NOT_APPLICABLE"
    assert task.input_artifact_refs == before_inputs
    assert task.gap_refs == before_gaps


def test_retry_delta_hydrates_only_delta_but_preserves_parent_lineage_and_audits_assignment():
    task = _task()
    retry = build_retry_delta(
        previous_attempt_summary_ref="ATT-SUMMARY-1",
        explicit_gap_refs=("GAP-1",),
        delta_evidence_refs=("file:///delta/db-assertion.json",),
        changed_dependency_refs=("ART-DATA-V2",),
    )
    audit = _RetryAudit(
        {
            "observation_status": "OBSERVED",
            "retry_context_id": "RETRYCTX-1",
            "parent_attempt_id": "ATT-1",
        }
    )
    bridge = Rc72ContextAwareDshTaskWorkerBridge(
        _Control(),
        _Launcher(),
        context_descriptor_resolver=lambda current: _descriptor(current, retry_delta=retry),
        retry_context_audit=audit,
    )
    prompt = bridge.compile_prompt(task, _assignment())
    contract = _contract(prompt)

    assert contract["input_artifact_refs"] == [
        "ART-REQ-1",
        "ART-CODE-1",
        "file:///full/requirement.md",
    ]
    assert contract["context_mode"] == "RETRY_DELTA"
    assert contract["effective_context_refs"] == [
        "ATT-SUMMARY-1",
        "GAP-1",
        "file:///delta/db-assertion.json",
        "ART-DATA-V2",
    ]
    projected_ids = [item["artifact_id"] for item in contract["canonical_input_artifacts"]]
    assert projected_ids == ["ART-DATA-V2"]
    assert '"path": "/delta/db-assertion.json"' in prompt
    assert 'MANDATORY_FIRST_ACTION={"arguments": {"path": "/full/requirement.md"}' not in prompt
    assert contract["model_economy"]["retry_context"] == {
        "observation_status": "OBSERVED",
        "retry_context_id": "RETRYCTX-1",
        "parent_attempt_id": "ATT-1",
    }
    assert len(audit.calls) == 1
    assert audit.calls[0]["attempt_id"] == "ATT-2"
    assert audit.calls[0]["assignment_id"] == "ASN-2"
    assert audit.calls[0]["task"] is task


def test_retry_child_with_unresolved_delta_records_unknown_but_keeps_mission_executable():
    task = _task()
    audit = _RetryAudit(
        {
            "observation_status": "UNKNOWN",
            "retry_context_id": "RETRYCTX-UNKNOWN",
            "parent_attempt_id": "ATT-1",
        }
    )
    bridge = Rc72ContextAwareDshTaskWorkerBridge(
        _Control(),
        _Launcher(),
        context_descriptor_resolver=lambda current: _descriptor(current),
        retry_context_audit=audit,
    )
    contract = _contract(bridge.compile_prompt(task, _assignment()))

    assert contract["context_mode"] == "RETRY_DELTA_UNKNOWN"
    assert contract["effective_context_refs"] == [
        "ART-REQ-1",
        "ART-CODE-1",
        "file:///full/requirement.md",
        "GAP-1",
    ]
    assert contract["model_economy"]["retry_context"]["observation_status"] == "UNKNOWN"
    assert len(audit.calls) == 1


def test_initial_attempt_without_parent_remains_normal_when_audit_returns_not_applicable():
    task = _task()
    audit = _RetryAudit(None)
    bridge = Rc72ContextAwareDshTaskWorkerBridge(
        _Control(),
        _Launcher(),
        context_descriptor_resolver=lambda current: _descriptor(current),
        retry_context_audit=audit,
    )
    contract = _contract(
        bridge.compile_prompt(task, _assignment(attempt_id="ATT-INITIAL", assignment_id="ASN-INITIAL"))
    )
    assert contract["context_mode"] == "NORMAL"
    assert contract["model_economy"]["retry_context"]["observation_status"] == "NOT_APPLICABLE"
    assert len(audit.calls) == 1


def test_full_context_retry_requires_explicit_reason_and_rehydrates_canonical_inputs():
    task = _task()
    retry = build_retry_delta(
        previous_attempt_summary_ref="ATT-SUMMARY-1",
        explicit_gap_refs=("GAP-1",),
        delta_evidence_refs=("EVD-DELTA-1",),
        full_context_reason="UPSTREAM_REQUIREMENT_REVISION_INVALIDATED_PRIOR_PROJECTION",
    )
    bridge = Rc72ContextAwareDshTaskWorkerBridge(
        _Control(),
        _Launcher(),
        context_descriptor_resolver=lambda current: _descriptor(current, retry_delta=retry),
    )
    prompt = bridge.compile_prompt(task, _assignment())
    contract = _contract(prompt)

    assert contract["context_mode"] == "FULL_CONTEXT_RETRY"
    assert contract["context_envelope"]["full_context_reason"] == (
        "UPSTREAM_REQUIREMENT_REVISION_INVALIDATED_PRIOR_PROJECTION"
    )
    assert contract["effective_context_refs"] == [
        "ART-REQ-1",
        "ART-CODE-1",
        "file:///full/requirement.md",
        "GAP-1",
    ]
    assert '"path": "/full/requirement.md"' in prompt


def test_descriptor_cannot_change_canonical_task_lineage():
    task = _task()
    descriptor = SemanticWorkDescriptor(
        workitem_id=task.task_id,
        mission_id=task.mission_id,
        node=task.node,
        stage="DESIGN",
        execution_mode=ExecutionMode.SEMANTIC,
        mission_criticality=MissionCriticality.BLOCKING,
        semantic_cost_class=SemanticCostClass.HIGH,
        affinity=ContextAffinity(requirement_id="REQ-1", sst_id="SST-1"),
        input_refs=("ART-INVENTED",),
        gap_refs=tuple(task.gap_refs),
    )
    bridge = Rc72ContextAwareDshTaskWorkerBridge(
        _Control(),
        _Launcher(),
        context_descriptor_resolver=lambda current: descriptor,
    )
    with pytest.raises(DshWorkerBridgeError, match="CANONICAL_INPUT_LINEAGE_MISMATCH"):
        bridge.compile_prompt(task, _assignment())


def test_deterministic_descriptor_cannot_compile_semantic_dsh_prompt_or_emit_retry_audit():
    task = _task()
    audit = _RetryAudit(
        {
            "observation_status": "UNKNOWN",
            "retry_context_id": "SHOULD-NOT-EXIST",
            "parent_attempt_id": "ATT-1",
        }
    )
    bridge = Rc72ContextAwareDshTaskWorkerBridge(
        _Control(),
        _Launcher(),
        context_descriptor_resolver=lambda current: _descriptor(
            current,
            mode=ExecutionMode.DETERMINISTIC,
        ),
        retry_context_audit=audit,
    )
    with pytest.raises(DshWorkerBridgeError, match="DETERMINISTIC_WORK_MUST_NOT_COMPILE_LLM_PROMPT"):
        bridge.compile_prompt(task, _assignment())
    assert audit.calls == []
