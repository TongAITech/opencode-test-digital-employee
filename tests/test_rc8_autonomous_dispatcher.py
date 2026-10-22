from __future__ import annotations

from dataclasses import dataclass

import pytest

from rc8_node.autonomous_claim_client import ClaimedWork
from rc8_node.autonomous_dispatcher import AutonomousDispatcherError, AutonomousWorkerDispatcher


class FakeClaimant:
    def __init__(self, claims):
        self.claims = list(claims)
        self.calls = []

    def claim_next(self, **kwargs):
        self.calls.append(kwargs)
        if self.claims:
            return self.claims.pop(0)
        return ClaimedWork(False, None, None, "NO_COMPATIBLE_READY_WORK_ITEM")


class Worker:
    def __init__(self, name):
        self.name = name
        self.claims = []

    def execute(self, claimed):
        self.claims.append(claimed)
        return {"status": "COMPLETED", "worker": self.name}


def _claim(stage="REQUIREMENT_ANALYSIS"):
    return ClaimedWork(
        claimed=True,
        work_item={
            "identity": {
                "work_item_id": "WORK-1",
                "test_run_id": "TR-1",
                "stage": stage,
                "scope_refs": [],
                "required_capabilities": [],
            },
            "lease_id": "LEASE-1",
        },
        stage_instance_id="STAGE-1",
        truth_note="CLAIMED",
    )


def test_dispatcher_claims_only_registered_stage_types() -> None:
    analysis = Worker("analysis")
    sufficiency = Worker("sufficiency")
    claimant = FakeClaimant([_claim()])
    dispatcher = AutonomousWorkerDispatcher(
        claimant=claimant,
        workers={
            "REQUIREMENT_ANALYSIS": analysis,
            "REQUIREMENT_SUFFICIENCY": sufficiency,
        },
    )
    outcome = dispatcher.run_once(test_run_id="TR-1")
    assert outcome.status == "EXECUTED"
    assert outcome.stage == "REQUIREMENT_ANALYSIS"
    assert outcome.result == {"status": "COMPLETED", "worker": "analysis"}
    assert claimant.calls == [{
        "ttl_seconds": 60,
        "test_run_id": "TR-1",
        "stage_types": ("REQUIREMENT_ANALYSIS", "REQUIREMENT_SUFFICIENCY"),
    }]
    assert len(analysis.claims) == 1
    assert sufficiency.claims == []


def test_dispatcher_idle_does_not_execute_worker() -> None:
    worker = Worker("analysis")
    claimant = FakeClaimant([])
    dispatcher = AutonomousWorkerDispatcher(
        claimant=claimant,
        workers={"REQUIREMENT_ANALYSIS": worker},
        idle_sleep_seconds=0,
    )
    outcome = dispatcher.run_once()
    assert outcome.status == "IDLE"
    assert worker.claims == []


def test_dispatcher_fails_closed_if_center_returns_unrequested_stage() -> None:
    claimant = FakeClaimant([_claim(stage="CODE_SUFFICIENCY")])
    dispatcher = AutonomousWorkerDispatcher(
        claimant=claimant,
        workers={"REQUIREMENT_ANALYSIS": Worker("analysis")},
    )
    with pytest.raises(AutonomousDispatcherError, match="CLAIMED_STAGE_NOT_IMPLEMENTED:CODE_SUFFICIENCY"):
        dispatcher.run_once()


def test_dispatcher_rejects_worker_without_execute() -> None:
    with pytest.raises(AutonomousDispatcherError, match="AUTONOMOUS_WORKER_EXECUTE_REQUIRED"):
        AutonomousWorkerDispatcher(
            claimant=FakeClaimant([]),
            workers={"REQUIREMENT_ANALYSIS": object()},
        )
