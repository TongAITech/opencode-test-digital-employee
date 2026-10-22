"""Formal PostgreSQL repository for Node/Capability/WorkItem durable state."""
from __future__ import annotations

import time
from typing import List, Optional

from sqlalchemy import BigInteger, JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column

from rc8_center.control_plane import NodeRecord, NodeStatus, WorkItemRecord, WorkItemState
from rc8_runtime import CapabilityQualification, CapabilityState, NodeIdentity, WorkItemIdentity

from .postgres import Base, MissionStageRow, PostgresStore


class NodeRow(Base):
    __tablename__ = "rc8_node"
    node_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    operator_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    os_family: Mapped[str] = mapped_column(String(32), nullable=False)
    architecture: Mapped[str] = mapped_column(String(64), nullable=False)
    shell: Mapped[str] = mapped_column(String(64), nullable=False)
    registered_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    first_registered_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_heartbeat_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class CapabilityRow(Base):
    __tablename__ = "rc8_node_capability"
    node_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    capability_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    probe_ref: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    verified_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class WorkItemRow(Base):
    __tablename__ = "rc8_work_item"
    work_item_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    required_capabilities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    lease_owner_node_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    lease_expires_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class StageWorkItemLinkRow(Base):
    """Exact lineage from a schedulable WorkItem to one StageInstance.

    ``WorkItemIdentity.stage`` remains the human/routing stage type. This table
    carries the instance identity needed for retries and parallel scope chains.
    One StageInstance may intentionally own more than one WorkItem later, while
    each WorkItem belongs to exactly one StageInstance.
    """

    __tablename__ = "rc8_stage_work_item_link"

    work_item_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    stage_instance_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PostgresCenterRepository:
    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def get_node(self, node_id: str) -> Optional[NodeRecord]:
        with self.store.session() as session:
            row = session.get(NodeRow, node_id)
            return self._node(row) if row is not None else None

    def upsert_node(self, node: NodeRecord) -> None:
        with self.store.session() as session:
            row = session.get(NodeRow, node.identity.node_id)
            if row is None:
                session.add(self._node_row(node))
                return
            current = self._node(row)
            if current.identity != node.identity:
                raise ValueError("NODE_IDENTITY_CONFLICT")
            row.status = node.status.value
            row.last_heartbeat_at = node.last_heartbeat_at

    def list_nodes(self) -> List[NodeRecord]:
        with self.store.session() as session:
            return [self._node(row) for row in session.scalars(select(NodeRow).order_by(NodeRow.node_id))]

    def get_capability(self, node_id: str, capability_id: str) -> Optional[CapabilityQualification]:
        with self.store.session() as session:
            row = session.get(CapabilityRow, {"node_id": node_id, "capability_id": capability_id})
            return self._capability(row) if row is not None else None

    def upsert_capability(self, value: CapabilityQualification) -> None:
        with self.store.session() as session:
            row = session.get(CapabilityRow, {"node_id": value.node_id, "capability_id": value.capability_id})
            if row is None:
                session.add(self._capability_row(value))
                return
            row.state = value.state.value
            row.probe_ref = value.probe_ref
            row.evidence_refs = list(value.evidence_refs)
            row.verified_at = value.verified_at

    def list_capabilities(self, node_id: str) -> List[CapabilityQualification]:
        with self.store.session() as session:
            rows = session.scalars(select(CapabilityRow).where(CapabilityRow.node_id == node_id).order_by(CapabilityRow.capability_id))
            return [self._capability(row) for row in rows]

    def get_work_item(self, work_item_id: str) -> Optional[WorkItemRecord]:
        with self.store.session() as session:
            row = session.get(WorkItemRow, work_item_id)
            return self._work(row) if row is not None else None

    def upsert_work_item(self, value: WorkItemRecord) -> None:
        with self.store.session() as session:
            row = session.get(WorkItemRow, value.identity.work_item_id)
            if row is None:
                session.add(self._work_row(value))
                return
            current = self._work(row)
            if current.identity != value.identity:
                raise ValueError("WORK_ITEM_IDENTITY_CONFLICT")
            if current.state in {WorkItemState.COMPLETED, WorkItemState.FAILED} and value.state != current.state:
                raise ValueError("WORK_ITEM_TERMINAL_STATE_IMMUTABLE")
            row.state = value.state.value
            row.lease_id = value.lease_id
            row.lease_owner_node_id = value.lease_owner_node_id
            row.lease_expires_at = value.lease_expires_at

    def list_work_items(self) -> List[WorkItemRecord]:
        with self.store.session() as session:
            return [self._work(row) for row in session.scalars(select(WorkItemRow).order_by(WorkItemRow.work_item_id))]

    def link_work_item_to_stage(
        self,
        *,
        work_item_id: str,
        stage_instance_id: str,
        test_run_id: str,
        created_at: Optional[int] = None,
    ) -> StageWorkItemLinkRow:
        timestamp = int(created_at if created_at is not None else time.time())
        with self.store.session() as session:
            work = session.get(WorkItemRow, work_item_id)
            if work is None:
                raise ValueError("WORK_ITEM_NOT_FOUND")
            stage = session.get(MissionStageRow, stage_instance_id)
            if stage is None:
                raise ValueError("MISSION_STAGE_NOT_FOUND")
            if work.test_run_id != test_run_id or stage.test_run_id != test_run_id:
                raise ValueError("STAGE_WORK_ITEM_TEST_RUN_MISMATCH")
            existing = session.get(StageWorkItemLinkRow, work_item_id)
            if existing is not None:
                if existing.stage_instance_id != stage_instance_id or existing.test_run_id != test_run_id:
                    raise ValueError("STAGE_WORK_ITEM_LINK_CONFLICT")
                return existing
            row = StageWorkItemLinkRow(
                work_item_id=work_item_id,
                stage_instance_id=stage_instance_id,
                test_run_id=test_run_id,
                created_at=timestamp,
            )
            session.add(row)
            return row

    def get_stage_link_for_work_item(self, work_item_id: str) -> Optional[StageWorkItemLinkRow]:
        with self.store.session() as session:
            return session.get(StageWorkItemLinkRow, work_item_id)

    def list_work_item_links_for_stage(self, stage_instance_id: str) -> List[StageWorkItemLinkRow]:
        with self.store.session() as session:
            return list(
                session.scalars(
                    select(StageWorkItemLinkRow)
                    .where(StageWorkItemLinkRow.stage_instance_id == stage_instance_id)
                    .order_by(StageWorkItemLinkRow.work_item_id)
                )
            )

    @staticmethod
    def _node_row(v: NodeRecord) -> NodeRow:
        return NodeRow(node_id=v.identity.node_id, operator_ref=v.identity.operator_ref, os_family=v.identity.os_family,
                       architecture=v.identity.architecture, shell=v.identity.shell, registered_at=v.identity.registered_at,
                       status=v.status.value, first_registered_at=v.first_registered_at, last_heartbeat_at=v.last_heartbeat_at)

    @staticmethod
    def _node(row: NodeRow) -> NodeRecord:
        identity = NodeIdentity(node_id=row.node_id, operator_ref=row.operator_ref, os_family=row.os_family,
                                architecture=row.architecture, shell=row.shell, registered_at=int(row.registered_at))
        return NodeRecord(identity=identity, status=NodeStatus(row.status), first_registered_at=int(row.first_registered_at), last_heartbeat_at=int(row.last_heartbeat_at))

    @staticmethod
    def _capability_row(v: CapabilityQualification) -> CapabilityRow:
        return CapabilityRow(node_id=v.node_id, capability_id=v.capability_id, state=v.state.value,
                             probe_ref=v.probe_ref, evidence_refs=list(v.evidence_refs), verified_at=v.verified_at)

    @staticmethod
    def _capability(row: CapabilityRow) -> CapabilityQualification:
        return CapabilityQualification(node_id=row.node_id, capability_id=row.capability_id, state=CapabilityState(row.state),
                                       probe_ref=row.probe_ref, evidence_refs=list(row.evidence_refs or []), verified_at=row.verified_at)

    @staticmethod
    def _work_row(v: WorkItemRecord) -> WorkItemRow:
        return WorkItemRow(work_item_id=v.identity.work_item_id, test_run_id=v.identity.test_run_id, stage=v.identity.stage,
                           scope_refs=list(v.identity.scope_refs), required_capabilities=list(v.identity.required_capabilities),
                           state=v.state.value, lease_id=v.lease_id, lease_owner_node_id=v.lease_owner_node_id,
                           lease_expires_at=v.lease_expires_at)

    @staticmethod
    def _work(row: WorkItemRow) -> WorkItemRecord:
        identity = WorkItemIdentity(work_item_id=row.work_item_id, test_run_id=row.test_run_id, stage=row.stage,
                                    scope_refs=list(row.scope_refs or []), required_capabilities=list(row.required_capabilities or []))
        return WorkItemRecord(identity=identity, state=WorkItemState(row.state), lease_id=row.lease_id,
                              lease_owner_node_id=row.lease_owner_node_id, lease_expires_at=row.lease_expires_at)