"""Single-node W1 orchestration for a real Maven/JUnit WorkItem.

Center remains authoritative for capability/lease decisions. The node leases and
starts the WorkItem before invoking the real execution adapter, publishes
AVAILABLE evidence and R1 Actual, and only then completes the WorkItem. Any
failure is fail-closed: completion is not attempted.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .agent import NodeAgent
from .execution import MavenJUnitExecutionAdapter
from .execution_publish import publish_maven_junit_execution


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
) -> Dict[str, object]:
    """Run the first complete RC8 single-node execution transaction.

    The lease call is deliberately first: Center rejects nodes whose required
    capabilities are not VERIFIED. Completion is deliberately last and is never
    reached when subprocess execution, evidence upload, or R1 append fails.
    """
    lease = agent.lease(work_item_id, ttl_seconds=lease_ttl_seconds)
    started = agent.start(work_item_id)
    execution = adapter.execute(project_dir, goals=goals)
    published = publish_maven_junit_execution(
        agent,
        test_run_id=test_run_id,
        work_item_id=work_item_id,
        result=execution,
        event_id=event_id,
        sequence=sequence,
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
        "actual_passed": execution.actual.passed,
    }
