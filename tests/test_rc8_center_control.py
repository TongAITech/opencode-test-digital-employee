from __future__ import annotations

from pathlib import Path

import pytest

from rc8_center import CenterControlError, CenterControlPlane, MemoryCenterRepository, NodeStatus, WorkItemState
from rc8_runtime import (
    CapabilityQualification,
    CapabilityState,
    CentralR1RuntimeLedger,
    NodeIdentity,
    RuntimeProducerKind,
    WorkItemIdentity,
    runtime_event,
)


class Clock:
    def __init__(self, value: int = 100) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += seconds


def _center(tmp_path: Path, clock: Clock):
    repo = MemoryCenterRepository()
    ledger = CentralR1RuntimeLedger(str(tmp_path / "r1.jsonl"))
    return CenterControlPlane(repo, ledger, now_fn=clock), repo, ledger


def _node(node_id="NODE-1"):
    return NodeIdentity(
        node_id=node_id,
        operator_ref="tester",
        os_family="windows",
        architecture="x86_64",
        shell="git-bash",
        registered_at=1,
    )


def _work(required=None):
    return WorkItemIdentity(
        work_item_id="WI-1",
        test_run_id="RUN-1",
        stage="EXECUTION",
        scope_refs=["SCOPE-1"],
        required_capabilities=list(required or []),
    )


def test_node_registration_heartbeat_and_queryable_state(tmp_path: Path) -> None:
    clock = Clock()
    center, repo, _ = _center(tmp_path, clock)
    node = center.register_node(_node())
    assert node.status == NodeStatus.ONLINE
    assert node.last_heartbeat_at == 100

    clock.advance(5)
    heartbeat = center.heartbeat("NODE-1")
    assert heartbeat.status == NodeStatus.IDLE
    assert heartbeat.last_heartbeat_at == 105
    assert repo.get_node("NODE-1") == heartbeat


def test_node_id_cannot_silently_change_platform_identity(tmp_path: Path) -> None:
    clock = Clock()
    center, _, _ = _center(tmp_path, clock)
    center.register_node(_node())
    conflict = NodeIdentity(
        node_id="NODE-1",
        operator_ref="tester",
        os_family="linux",
        architecture="x86_64",
        shell="bash",
        registered_at=1,
    )
    with pytest.raises(CenterControlError, match="NODE_IDENTITY_CONFLICT"):
        center.register_node(conflict)


def test_unverified_capability_cannot_lease_required_work(tmp_path: Path) -> None:
    clock = Clock()
    center, _, _ = _center(tmp_path, clock)
    center.register_node(_node())
    center.register_work_item(_work(["CAN_CODEGRAPH"]))

    with pytest.raises(CenterControlError, match="NODE_REQUIRED_CAPABILITY_NOT_VERIFIED:CAN_CODEGRAPH"):
        center.lease_work_item("WI-1", "NODE-1")

    center.qualify_capability(
        CapabilityQualification(
            node_id="NODE-1",
            capability_id="CAN_CODEGRAPH",
            state=CapabilityState.VERIFIED,
            probe_ref="probe://codegraph/1",
            evidence_refs=["ART-CG-1"],
            verified_at=100,
        )
    )
    leased = center.lease_work_item("WI-1", "NODE-1", ttl_seconds=30)
    assert leased.state == WorkItemState.LEASED
    assert leased.lease_owner_node_id == "NODE-1"
    assert leased.lease_expires_at == 130


def test_work_item_lease_is_owned_by_node_not_session(tmp_path: Path) -> None:
    clock = Clock()
    center, _, _ = _center(tmp_path, clock)
    center.register_node(_node("NODE-1"))
    center.register_node(_node("NODE-2"))
    center.register_work_item(_work())
    leased = center.lease_work_item("WI-1", "NODE-1")
    assert leased.lease_owner_node_id == "NODE-1"
    assert not hasattr(leased, "session_id")
    with pytest.raises(CenterControlError, match="WORK_ITEM_LEASE_HELD"):
        center.lease_work_item("WI-1", "NODE-2")


def test_runtime_event_requires_active_node_lease_and_matching_test_run(tmp_path: Path) -> None:
    clock = Clock()
    center, _, ledger = _center(tmp_path, clock)
    center.register_node(_node())
    center.register_work_item(_work())
    center.lease_work_item("WI-1", "NODE-1", ttl_seconds=10)
    center.start_work_item("WI-1", "NODE-1")

    event = runtime_event(
        event_id="EV-1",
        test_run_id="RUN-1",
        work_item_id="WI-1",
        node_id="NODE-1",
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="codegraph",
        event_type="TOOL_EXECUTED",
        sequence=1,
    )
    receipt = center.append_runtime_event(event)
    assert receipt["status"] == "PERSISTENCE_VERIFIED"
    assert len(ledger.runtime_events(test_run_id="RUN-1")) == 1

    wrong_run = runtime_event(
        event_id="EV-2",
        test_run_id="RUN-OTHER",
        work_item_id="WI-1",
        node_id="NODE-1",
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="codegraph",
        event_type="TOOL_EXECUTED",
        sequence=2,
    )
    with pytest.raises(CenterControlError, match="RUNTIME_EVENT_TEST_RUN_MISMATCH"):
        center.append_runtime_event(wrong_run)

    clock.advance(11)
    expired = runtime_event(
        event_id="EV-3",
        test_run_id="RUN-1",
        work_item_id="WI-1",
        node_id="NODE-1",
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="codegraph",
        event_type="TOOL_EXECUTED",
        sequence=2,
    )
    with pytest.raises(CenterControlError, match="ACTIVE_WORK_ITEM_LEASE_REQUIRED"):
        center.append_runtime_event(expired)


def test_complete_work_item_returns_node_to_idle(tmp_path: Path) -> None:
    clock = Clock()
    center, repo, _ = _center(tmp_path, clock)
    center.register_node(_node())
    center.register_work_item(_work())
    center.lease_work_item("WI-1", "NODE-1", ttl_seconds=30)
    center.start_work_item("WI-1", "NODE-1")
    done = center.complete_work_item("WI-1", "NODE-1")
    assert done.state == WorkItemState.COMPLETED
    assert repo.get_node("NODE-1").status == NodeStatus.IDLE
