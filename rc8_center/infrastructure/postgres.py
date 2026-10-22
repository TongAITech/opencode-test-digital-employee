"""Formal PostgreSQL persistence models for RC8 Center.

The schema mirrors RC8 governance semantics rather than flattening them into a
single opaque status/payload.  R1 remains runtime truth; these tables are
durable control-domain state and replayable product projections.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from sqlalchemy import BigInteger, Boolean, Float, JSON, String, Text, create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class TestRunRow(Base):
    __tablename__ = "rc8_test_run"

    test_run_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    production_batch_id: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    test_round_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, unique=True, index=True)
    status_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="MISSION")
    current_state: Mapped[str] = mapped_column(String(64), nullable=False, default="PLANNED")
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class MissionStageRow(Base):
    __tablename__ = "rc8_mission_stage"

    stage_instance_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    stage_type: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_version: Mapped[str] = mapped_column(String(300), nullable=False)
    attempt_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    input_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    output_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    gap_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    invalidation_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    predecessor_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    successor_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    assigned_worker: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    evaluator_id: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    policy_version: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    started_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    finished_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AttemptRow(Base):
    __tablename__ = "rc8_attempt"

    attempt_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    stage_instance_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    work_item_id: Mapped[str] = mapped_column(String(200), nullable=False)
    producer_node_id: Mapped[str] = mapped_column(String(200), nullable=False)
    producer_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    input_snapshot_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    case_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    action_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    assertion_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    coverage_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    gap_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    defect_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    failure_ownership: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    started_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    finished_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class GapRow(Base):
    __tablename__ = "rc8_gap"

    gap_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    source_stage_instance_id: Mapped[str] = mapped_column(String(200), nullable=False)
    gap_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner_stage: Mapped[str] = mapped_column(String(100), nullable=False)
    repair_strategy: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    source_attempt_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    source_case_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    source_assertion_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    invalidates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    closure_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    opened_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    closed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class CoverageObservationRow(Base):
    __tablename__ = "rc8_coverage_observation"

    observation_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    stage_instance_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    attempt_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    case_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    subject_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    source_snapshot_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    source_tool: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metric_id: Mapped[str] = mapped_column(String(200), nullable=False)
    dimension: Mapped[str] = mapped_column(String(100), nullable=False)
    covered: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    artifact_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    observed_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class InvalidationRow(Base):
    __tablename__ = "rc8_invalidation"

    invalidation_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    source_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    target_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class SufficiencyEvaluationRow(Base):
    __tablename__ = "rc8_sufficiency_evaluation"

    evaluation_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    evaluator_id: Mapped[str] = mapped_column(String(240), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(240), nullable=False)
    result: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    satisfied_requirement_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    unsatisfied_requirement_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    unresolved_gap_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    accepted_waiver_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ReleaseDecisionRow(Base):
    __tablename__ = "rc8_release_decision"

    release_decision_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    mission_evaluation_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    blocking_defect_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ProjectionReceiptRow(Base):
    __tablename__ = "rc8_projection_receipt"

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    domain_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


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
    """Formal persistence boundary used by Center application services."""

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
        test_round_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        now: Optional[int] = None,
    ) -> TestRunRow:
        timestamp = int(now if now is not None else time.time())
        row = TestRunRow(
            test_run_id=test_run_id,
            production_batch_id=production_batch_id,
            test_round_id=test_round_id,
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

    def get_test_run_for_round(self, test_round_id: str) -> Optional[TestRunRow]:
        with self._sessions() as session:
            return session.scalar(select(TestRunRow).where(TestRunRow.test_round_id == test_round_id))

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
