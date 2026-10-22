"""Single-node W1/W-B orchestration for a real Maven/JUnit WorkItem.

Center remains authoritative for capability/lease decisions. The node leases and
starts the WorkItem before invoking the real execution adapter, publishes
AVAILABLE evidence and R1 Actual, and only then completes the WorkItem. Optional
L1 changed-code coverage scope/context travels through the same transaction so
JaCoCo cannot become a side-channel truth source.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .agent import NodeAgent
from .execution import MavenJUnitExecutionAdapter
from .execution_publish import CoveragePublishContext, publish_maven_junit_execution
from .jacoco import ChangedCoverageScope


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
        sequence=sequence,
        coverage_context=coverage_context,
    )
    completed = agent.complete(work_item_id)
    return {
        "work_item_id": work_item_id,
        "test_run_id": test_run_id,
        "lease": lease,
        "started": started,
        "execution": execution,
        "published": published,
        "completed": completed,
        "actual_passed": execution.execution_passed,
        "coverage_collected": execution.coverage is not None,
    }
