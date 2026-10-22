"""PostgreSQL durable Center foundation.

This is the first formal persistence adapter. It intentionally starts with
identity/projection primitives that can be exercised independently from the W1
JSON repositories. Domain semantics stay in rc8_runtime/rc8_center services.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from sqlalchemy import BigInteger, JSON, String, Text, create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class TestRunRow(Base):
    __tablename__ = "rc8_test_run"

    test_run_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    production_batch_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    status_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="MISSION")
    current_state: Mapped[str] = mapped_column(String(64), nullable=False, default="PLANNED")
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class MissionStageRow(Base):
    __tablename__ = "rc8_mission_stage"

    stage_instance_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    stage_type: Mapped[str] = mapped_column(String(80), nullable=False)
    scope_ref: Mapped[str] = mapped_column(String(240), nullable=False, default="GLOBAL")
    scope_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluator_ref: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AttemptRow(Base):
    __tablename__ = "rc8_attempt"

    attempt_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    stage_instance_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ended_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_snapshot_ref: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class GapRow(Base):
    __tablename__ = "rc8_gap"

    gap_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    source_stage_instance_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_attempt_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    gap_type: Mapped[str] = mapped_column(String(100), nullable=False)
    owner_stage: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    resolved_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class CoverageObservationRow(Base):
    __tablename__ = "rc8_coverage_observation"

    observation_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    stage_instance_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    dimension: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    covered: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_snapshot_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    source_tool: Mapped[str] = mapped_column(String(100), nullable=False)
    observed_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class ProjectionCheckpointRow(Base):
    __tablename__ = "rc8_projection_checkpoint"

    projector_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    last_event_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


def build_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True, future=True)


class PostgresStore:
    """Small formal persistence boundary used by the first full-stack slice."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._sessions() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def ping(self) -> bool:
        with self.engine.connect() as connection:
            value = connection.execute(text("SELECT 1")).scalar_one()
            return int(value) == 1

    def create_test_run(
        self,
        test_run_id: str,
        *,
        production_batch_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        now: Optional[int] = None,
    ) -> TestRunRow:
        timestamp = int(now if now is not None else time.time())
        row = TestRunRow(
            test_run_id=test_run_id,
            production_batch_id=production_batch_id,
            status_scope="MISSION",
            current_state="PLANNED",
            created_at=timestamp,
            updated_at=timestamp,
            payload=dict(payload or {}),
        )
        with self.session() as session:
            session.add(row)
        return row

    def get_test_run(self, test_run_id: str) -> Optional[TestRunRow]:
        with self._sessions() as session:
            return session.get(TestRunRow, test_run_id)

    def list_test_runs(self) -> list[TestRunRow]:
        with self._sessions() as session:
            return list(session.scalars(select(TestRunRow).order_by(TestRunRow.created_at.desc())))

    def get_checkpoint(self, projector_id: str) -> Optional[ProjectionCheckpointRow]:
        with self._sessions() as session:
            return session.get(ProjectionCheckpointRow, projector_id)

    def set_checkpoint(
        self,
        projector_id: str,
        *,
        last_event_id: Optional[str],
        last_sequence: int,
        detail: Optional[str] = None,
        now: Optional[int] = None,
    ) -> ProjectionCheckpointRow:
        timestamp = int(now if now is not None else time.time())
        with self.session() as session:
            row = session.get(ProjectionCheckpointRow, projector_id)
            if row is None:
                row = ProjectionCheckpointRow(
                    projector_id=projector_id,
                    last_event_id=last_event_id,
                    last_sequence=int(last_sequence),
                    updated_at=timestamp,
                    detail=detail,
                )
                session.add(row)
            else:
                if int(last_sequence) < int(row.last_sequence):
                    raise ValueError("PROJECTION_CHECKPOINT_CANNOT_REGRESS")
                row.last_event_id = last_event_id
                row.last_sequence = int(last_sequence)
                row.updated_at = timestamp
                row.detail = detail
            return row
