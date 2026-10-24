"""PostgreSQL durable persistence for RC8 N6 Executable Readiness."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column

from rc8_center.executable_readiness import ExecutableReadinessError, ExecutableReadinessState, ExecutableSpec

from .postgres import Base, PostgresStore


class ExecutableSpecRow(Base):
    __tablename__ = "rc8_executable_spec"

    executable_spec_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    mission_node_id: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    prepared_attempt_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    frozen_case_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    driver_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    script_artifact_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    fixture_binding_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    assertion_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_collector_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    build_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    semantic_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    invalidation_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    invalidation_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class PostgresExecutableSpecRepository:
    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def get_executable_spec(self, executable_spec_id: str) -> Optional[ExecutableSpec]:
        with self.store.session() as session:
            row = session.get(ExecutableSpecRow, executable_spec_id)
            return self._value(row) if row is not None else None

    def current_for_attempt(self, test_run_id: str, case_id: str, attempt_id: str) -> Optional[ExecutableSpec]:
        with self.store.session() as session:
            rows = list(session.scalars(select(ExecutableSpecRow).where(ExecutableSpecRow.test_run_id == test_run_id, ExecutableSpecRow.case_id == case_id, ExecutableSpecRow.attempt_id == attempt_id, ExecutableSpecRow.state != ExecutableReadinessState.INVALIDATED.value)))
            if len(rows) > 1:
                raise ExecutableReadinessError("MULTIPLE_CURRENT_EXECUTABLE_SPECS")
            return self._value(rows[0]) if rows else None

    def save_executable_spec(self, value: ExecutableSpec) -> None:
        if not isinstance(value, ExecutableSpec):
            raise ExecutableReadinessError("EXECUTABLE_SPEC_REQUIRED")
        with self.store.session() as session:
            current = list(session.scalars(select(ExecutableSpecRow).where(ExecutableSpecRow.test_run_id == value.test_run_id, ExecutableSpecRow.case_id == value.case_id, ExecutableSpecRow.attempt_id == value.attempt_id, ExecutableSpecRow.state != ExecutableReadinessState.INVALIDATED.value)))
            if any(row.executable_spec_id != value.executable_spec_id for row in current) and value.state != ExecutableReadinessState.INVALIDATED:
                raise ExecutableReadinessError("CURRENT_EXECUTABLE_SPEC_ALREADY_EXISTS")
            row = session.get(ExecutableSpecRow, value.executable_spec_id)
            if row is None:
                row = ExecutableSpecRow(executable_spec_id=value.executable_spec_id)
                session.add(row)
            self._assign(row, value)

    @staticmethod
    def _assign(row: ExecutableSpecRow, value: ExecutableSpec) -> None:
        row.test_run_id = value.test_run_id
        row.mission_node_id = value.mission_node_id
        row.case_id = value.case_id
        row.attempt_id = value.attempt_id
        row.prepared_attempt_id = value.prepared_attempt_id
        row.frozen_case_ref = value.frozen_case_ref
        row.driver_ref = value.driver_ref
        row.script_artifact_ref = value.script_artifact_ref
        row.fixture_binding_refs = list(value.fixture_binding_refs)
        row.assertion_refs = list(value.assertion_refs)
        row.evidence_collector_refs = list(value.evidence_collector_refs)
        row.build_evidence_refs = list(value.build_evidence_refs)
        row.semantic_evidence_refs = list(value.semantic_evidence_refs)
        row.state = value.state.value
        row.created_at = value.created_at
        row.updated_at = value.updated_at
        row.invalidation_reason = value.invalidation_reason
        row.invalidation_evidence_refs = list(value.invalidation_evidence_refs)

    @staticmethod
    def _value(row: ExecutableSpecRow) -> ExecutableSpec:
        return ExecutableSpec(executable_spec_id=row.executable_spec_id, test_run_id=row.test_run_id, mission_node_id=row.mission_node_id, case_id=row.case_id, attempt_id=row.attempt_id, prepared_attempt_id=row.prepared_attempt_id, frozen_case_ref=row.frozen_case_ref, driver_ref=row.driver_ref, script_artifact_ref=row.script_artifact_ref, fixture_binding_refs=tuple(row.fixture_binding_refs or ()), assertion_refs=tuple(row.assertion_refs or ()), evidence_collector_refs=tuple(row.evidence_collector_refs or ()), build_evidence_refs=tuple(row.build_evidence_refs or ()), semantic_evidence_refs=tuple(row.semantic_evidence_refs or ()), state=ExecutableReadinessState(row.state), created_at=int(row.created_at), updated_at=int(row.updated_at), invalidation_reason=row.invalidation_reason, invalidation_evidence_refs=tuple(row.invalidation_evidence_refs or ()))
