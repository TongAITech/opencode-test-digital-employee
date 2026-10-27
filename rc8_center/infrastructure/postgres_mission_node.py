"""PostgreSQL durable current-state repository for Center MissionNodes."""
from __future__ import annotations

import time
from typing import Callable, Optional, Tuple

from sqlalchemy import BigInteger, JSON, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from rc8_center.mission_node_repository import MissionNodeRepositoryError
from rc8_runtime.mission_nodes import (
    MISSION_NODE_SEQUENCE,
    MissionNodeInstance,
    MissionNodeState,
    MissionNodeType,
)

from .postgres import Base, PostgresStore


class MissionNodeRow(Base):
    __tablename__ = "rc8_mission_node"
    __table_args__ = (
        UniqueConstraint("test_run_id", "node_type", name="uq_rc8_mission_node_test_run_type"),
    )

    mission_node_id: Mapped[str] = mapped_column(String(300), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    node_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    scope_version: Mapped[str] = mapped_column(String(300), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    stage_instance_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    predecessor_node_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    output_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PostgresMissionNodeRepository:
    def __init__(self, store: PostgresStore, now_fn: Callable[[], int] = None) -> None:
        self.store = store
        self._now_fn = now_fn or (lambda: int(time.time()))

    def save(self, node: MissionNodeInstance) -> None:
        if not isinstance(node, MissionNodeInstance):
            raise MissionNodeRepositoryError("MISSION_NODE_INSTANCE_REQUIRED")
        with self.store.session() as session:
            row = session.get(MissionNodeRow, node.mission_node_id)
            if row is None:
                duplicate = session.scalar(
                    select(MissionNodeRow)
                    .where(
                        MissionNodeRow.test_run_id == node.test_run_id,
                        MissionNodeRow.node_type == node.node_type.value,
                    )
                    .limit(1)
                )
                if duplicate is not None:
                    raise MissionNodeRepositoryError("MISSION_NODE_TYPE_ALREADY_EXISTS_FOR_TEST_RUN")
                session.add(
                    MissionNodeRow(
                        mission_node_id=node.mission_node_id,
                        test_run_id=node.test_run_id,
                        node_type=node.node_type.value,
                        scope_version=node.scope_version,
                        state=node.state.value,
                        stage_instance_ids=list(node.stage_instance_ids),
                        predecessor_node_ids=list(node.predecessor_node_ids),
                        output_refs=list(node.output_refs),
                        updated_at=int(self._now_fn()),
                    )
                )
                return

            current = self._node(row)
            self._require_same_identity(current, node)
            row.state = node.state.value
            row.stage_instance_ids = list(node.stage_instance_ids)
            row.output_refs = list(node.output_refs)
            row.updated_at = int(self._now_fn())

    def get(self, mission_node_id: str) -> Optional[MissionNodeInstance]:
        with self.store.session() as session:
            row = session.get(MissionNodeRow, mission_node_id)
            return self._node(row) if row is not None else None

    def list_for_test_run(self, test_run_id: str) -> Tuple[MissionNodeInstance, ...]:
        with self.store.session() as session:
            rows = list(
                session.scalars(
                    select(MissionNodeRow).where(MissionNodeRow.test_run_id == test_run_id)
                )
            )
        order = {node_type: index for index, node_type in enumerate(MISSION_NODE_SEQUENCE)}
        nodes = [self._node(row) for row in rows]
        nodes.sort(key=lambda node: order[node.node_type])
        return tuple(nodes)

    @staticmethod
    def _node(row: MissionNodeRow) -> MissionNodeInstance:
        return MissionNodeInstance(
            mission_node_id=row.mission_node_id,
            test_run_id=row.test_run_id,
            node_type=MissionNodeType(row.node_type),
            scope_version=row.scope_version,
            state=MissionNodeState(row.state),
            stage_instance_ids=tuple(row.stage_instance_ids or ()),
            predecessor_node_ids=tuple(row.predecessor_node_ids or ()),
            output_refs=tuple(row.output_refs or ()),
        )

    @staticmethod
    def _require_same_identity(existing: MissionNodeInstance, candidate: MissionNodeInstance) -> None:
        if existing.test_run_id != candidate.test_run_id:
            raise MissionNodeRepositoryError("MISSION_NODE_TEST_RUN_IMMUTABLE")
        if existing.node_type != candidate.node_type:
            raise MissionNodeRepositoryError("MISSION_NODE_TYPE_IMMUTABLE")
        if existing.scope_version != candidate.scope_version:
            raise MissionNodeRepositoryError("MISSION_NODE_SCOPE_VERSION_IMMUTABLE")
        if existing.predecessor_node_ids != candidate.predecessor_node_ids:
            raise MissionNodeRepositoryError("MISSION_NODE_PREDECESSORS_IMMUTABLE")
