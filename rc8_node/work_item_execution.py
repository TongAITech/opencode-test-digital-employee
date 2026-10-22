"""Single-node W1/W-B orchestration for a real Maven/JUnit WorkItem.

Center remains authoritative for capability/lease decisions. The node leases and
starts the WorkItem before invoking the real execution adapter, publishes
AVAILABLE evidence and R1 Actual, and only then completes the WorkItem. Optional
L1 changed-code coverage scope/context travels through the same transaction so
JaCoCo cannot become a side-channel truth source.

The W-B changed-scope path also emits a canonical ATTEMPT lifecycle. Tool-only
Maven Reality remains backward compatible and is not silently promoted into an
L1 Attempt.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Dict, List, Optional

from rc8_runtime import ArtifactAvailability, RuntimeEventEnvelope, RuntimeProducerKind
from rc8_runtime.artifacts import ArtifactManifest

from .agent import NodeAgent, NodeAgentError
from .execution import MavenExecutionResult, MavenJUnitExecutionAdapter
from .execution_publish import CoveragePublishContext, publish_maven_junit_execution
from .jacoco import ChangedCoverageScope


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _available(response: Dict[str, object], artifact_id: str) -> None:
    artifact = response.get("artifact") if isinstance(response, dict) else None
    if artifact is None:
        artifact = response
    if not isinstance(artifact, dict):
        raise NodeAgentError("ATTEMPT_EVIDENCE_RESPONSE_INVALID:%s" % artifact_id)
    availability = str(artifact.get("availability") or artifact.get("status") or "")
    if availability.upper() != ArtifactAvailability.AVAILABLE.value:
        raise NodeAgentError("ATTEMPT_EVIDENCE_NOT_AVAILABLE:%s" % artifact_id)


def _upload_failure_classification(
    agent: NodeAgent,
    *,
    test_run_id: str,
    work_item_id: str,
    execution: MavenExecutionResult,
) -> List[str]:
    failure = execution.failure_classification
    if failure is None:
        return []
    path = Path(failure.result_path)
    if not path.is_file():
        raise NodeAgentError("FAILURE_CLASSIFICATION_FILE_MISSING")
    digest = _sha256(path)
    if digest != failure.sha256:
        raise NodeAgentError("FAILURE_CLASSIFICATION_HASH_MISMATCH")
    seed = (work_item_id + "|failure-classification|" + digest).encode("utf-8")
    artifact_id = "exec-failure-classification-%s" % hashlib.sha256(seed).hexdigest()[:20]
    manifest = ArtifactManifest(
        artifact_id=artifact_id,
        test_run_id=test_run_id,
        work_item_id=work_item_id,
        node_id=agent.identity.node_id,
        kind="junit-failure-classification",
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="rc8:junit-failure-classifier",
        file_name=path.name,
        sha256=digest,
        size_bytes=path.stat().st_size,
        availability=ArtifactAvailability.PENDING_UPLOAD,
        refs=[],
        metadata={
            "media_type": "application/json",
            "truth_role": "failure-classification",
            "primary_ownership": failure.primary_ownership.value,
            "semantic_review_required": failure.semantic_review_required,
        },
    )
    response = agent.upload_artifact_file(manifest, str(path))
    _available(response, artifact_id)
    return [artifact_id]


def _terminal_attempt_type(execution: MavenExecutionResult) -> str:
    if execution.actual.failures > 0 or execution.actual.errors > 0:
        # The execution itself completed and produced test Actual. A failed test
        # is not a runtime-crashed Attempt.
        return "ATTEMPT_COMPLETED"
    if execution.classification == "MAVEN_FAILED_BEFORE_FRESH_JUNIT":
        return "ATTEMPT_FAILED_RUNTIME"
    if execution.returncode not in (None, 0):
        return "ATTEMPT_FAILED_RUNTIME"
    if execution.coverage_required and execution.coverage is None:
        return "ATTEMPT_BLOCKED"
    return "ATTEMPT_COMPLETED"


def _last_publish_sequence(base_sequence: int, published: Dict[str, object]) -> int:
    return (
        base_sequence
        + len(published.get("coverage_events") or [])
        + len(published.get("gap_events") or [])
        + len(published.get("gap_closure_events") or [])
    )


def execute_maven_junit_work_item(
    agent: NodeAgent,
    adapter: MavenJUnitExecutionAdapter,
    *,
    test_run_id: str,
    work_item_id: str,
    project_dir: str,
    event_id: str,
    sequence: int,
    goals: Optional[List[str]] = None,
    lease_ttl_seconds: int = 900,
    coverage_scope: Optional[ChangedCoverageScope] = None,
    coverage_context: Optional[CoveragePublishContext] = None,
) -> Dict[str, object]:
    """Run one evidence-bound RC8 execution transaction.

    W-B coverage is optional for backward-compatible Tool Reality, but scope and
    governance context are atomic: supplying only one would create unprojectable
    coverage truth and is therefore rejected before leasing the WorkItem.
    """
    if (coverage_scope is None) != (coverage_context is None):
        raise ValueError("COVERAGE_SCOPE_AND_CONTEXT_MUST_BE_SUPPLIED_TOGETHER")

    lease = agent.lease(work_item_id, ttl_seconds=lease_ttl_seconds)
    started = agent.start(work_item_id)

    attempt_started = None
    publish_sequence = sequence
    if coverage_scope is not None and coverage_context is not None:
        attempt_started_event = RuntimeEventEnvelope(
            event_id="%s-attempt-started" % event_id,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            node_id=agent.identity.node_id,
            producer_kind=RuntimeProducerKind.TOOL,
            producer_ref="rc8:maven-junit-attempt",
            event_type="ATTEMPT_STARTED",
            sequence=sequence,
            attempt_id=coverage_context.attempt_id,
            refs=[],
            data={
                "stage_instance_id": coverage_context.stage_instance_id,
                "input_snapshot_ref": coverage_scope.source_snapshot_ref,
                "started_at": int(time.time()),
                "action_refs": [],
                "assertion_refs": [],
                "evidence_refs": [],
                "coverage_refs": [],
                "gap_refs": [],
                "defect_refs": [],
            },
        )
        attempt_started = agent.append_runtime_event(attempt_started_event)
        publish_sequence = sequence + 1

    if coverage_scope is None:
        execution = adapter.execute(project_dir, goals=goals)
    else:
        execution = adapter.execute(project_dir, goals=goals, coverage_scope=coverage_scope)

    published = publish_maven_junit_execution(
        agent,
        test_run_id=test_run_id,
        work_item_id=work_item_id,
        result=execution,
        event_id=event_id,
        sequence=publish_sequence,
        coverage_context=coverage_context,
    )

    attempt_terminal = None
    failure_artifact_ids: List[str] = []
    if coverage_scope is not None and coverage_context is not None:
        failure_artifact_ids = _upload_failure_classification(
            agent,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            execution=execution,
        )
        evidence_refs = list(dict.fromkeys(
            list(published.get("artifact_ids") or []) + failure_artifact_ids
        ))
        coverage_refs = [
            "coverage:%s" % item["observation_id"]
            for item in published.get("coverage_events") or []
        ]
        gap_ids: List[str] = []
        gap_ids.extend(str(item["gap_id"]) for item in published.get("gap_events") or [])
        gap_ids.extend(str(item["gap_id"]) for item in published.get("gap_closure_events") or [])
        gap_ids.extend(str(item) for item in published.get("retained_gap_ids") or [])
        gap_refs = ["gap:%s" % gap_id for gap_id in dict.fromkeys(gap_ids)]
        terminal_type = _terminal_attempt_type(execution)
        terminal_data: Dict[str, object] = {
            "stage_instance_id": coverage_context.stage_instance_id,
            "input_snapshot_ref": coverage_scope.source_snapshot_ref,
            "finished_at": execution.finished_at,
            "action_refs": [],
            "assertion_refs": [],
            "evidence_refs": evidence_refs,
            "coverage_refs": coverage_refs,
            "gap_refs": gap_refs,
            "defect_refs": [],
        }
        if execution.failure_classification is not None:
            terminal_data["failure_ownership"] = execution.failure_classification.primary_ownership.value
        terminal_sequence = _last_publish_sequence(publish_sequence, published) + 1
        terminal_event = RuntimeEventEnvelope(
            event_id="%s-attempt-terminal" % event_id,
            test_run_id=test_run_id,
            work_item_id=work_item_id,
            node_id=agent.identity.node_id,
            producer_kind=RuntimeProducerKind.TOOL,
            producer_ref="rc8:maven-junit-attempt",
            event_type=terminal_type,
            sequence=terminal_sequence,
            attempt_id=coverage_context.attempt_id,
            refs=evidence_refs,
            data=terminal_data,
        )
        attempt_terminal = agent.append_runtime_event(terminal_event)

    completed = agent.complete(work_item_id)
    return {
        "work_item_id": work_item_id,
        "test_run_id": test_run_id,
        "lease": lease,
        "started": started,
        "attempt_started": attempt_started,
        "execution": execution,
        "published": published,
        "failure_artifact_ids": failure_artifact_ids,
        "attempt_terminal": attempt_terminal,
        "completed": completed,
        "actual_passed": execution.execution_passed,
        "coverage_collected": execution.coverage is not None,
    }
