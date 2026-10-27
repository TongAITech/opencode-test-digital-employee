"""PostgreSQL durable persistence for RC8 N9 defect closure."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column

from rc8_center.defect_closure import (
    DefectCase,
    DefectClosureError,
    DefectSeverity,
    DefectState,
)

from .postgres import Base, PostgresStore


class DefectCaseRow(Base):
    __tablename__ = "rc8_defect_case"

    defect_case_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    route_decision_id: Mapped[str] = mapped_column(String(240), nullable=False, unique=True, index=True)
    source_observation_id: Mapped[str] = mapped_column(String(240), nullable=False)
    source_case_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_attempt_id: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    candidate_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reproduction_attempt_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    reproducer_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    reproduction_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    qualification_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    rca_summary: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    rca_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    duplicate_of: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    dedup_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    impact_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    impact_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    severity: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    review_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    external_defect_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    filing_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    fix_revision_ref: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    fix_detected_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    fix_verification_work_item_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    fix_verification_attempt_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    fix_verification_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    impact_regression_work_item_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    impact_regression_case_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    impact_regression_attempt_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    impact_regression_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    closure_evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class PostgresDefectClosureRepository:
    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def get_defect_case(self, defect_case_id: str) -> Optional[DefectCase]:
        with self.store.session() as session:
            row = session.get(DefectCaseRow, defect_case_id)
            return self._value(row) if row is not None else None

    def by_route_decision(self, route_decision_id: str) -> Optional[DefectCase]:
        with self.store.session() as session:
            rows = list(
                session.scalars(
                    select(DefectCaseRow).where(
                        DefectCaseRow.route_decision_id == route_decision_id
                    )
                )
            )
            if len(rows) > 1:
                raise DefectClosureError("MULTIPLE_DEFECT_CASES_FOR_ROUTE")
            return self._value(rows[0]) if rows else None

    def save_defect_case(self, value: DefectCase) -> None:
        if not isinstance(value, DefectCase):
            raise DefectClosureError("DEFECT_CASE_REQUIRED")
        with self.store.session() as session:
            duplicate = session.scalar(
                select(DefectCaseRow)
                .where(
                    DefectCaseRow.route_decision_id == value.route_decision_id,
                    DefectCaseRow.defect_case_id != value.defect_case_id,
                )
                .limit(1)
            )
            if duplicate is not None:
                raise DefectClosureError("DEFECT_ROUTE_ALREADY_LINKED")
            row = session.get(DefectCaseRow, value.defect_case_id)
            if row is None:
                row = DefectCaseRow(defect_case_id=value.defect_case_id)
                session.add(row)
            self._assign(row, value)

    @staticmethod
    def _assign(row: DefectCaseRow, value: DefectCase) -> None:
        row.test_run_id = value.test_run_id
        row.route_decision_id = value.route_decision_id
        row.source_observation_id = value.source_observation_id
        row.source_case_id = value.source_case_id
        row.source_attempt_id = value.source_attempt_id
        row.state = value.state.value
        row.candidate_evidence_refs = list(value.candidate_evidence_refs)
        row.created_at = value.created_at
        row.updated_at = value.updated_at
        row.reproduction_attempt_id = value.reproduction_attempt_id
        row.reproducer_ref = value.reproducer_ref
        row.reproduction_evidence_refs = list(value.reproduction_evidence_refs)
        row.qualification_evidence_refs = list(value.qualification_evidence_refs)
        row.rca_summary = value.rca_summary
        row.rca_evidence_refs = list(value.rca_evidence_refs)
        row.duplicate_of = value.duplicate_of
        row.dedup_evidence_refs = list(value.dedup_evidence_refs)
        row.impact_refs = list(value.impact_refs)
        row.impact_evidence_refs = list(value.impact_evidence_refs)
        row.severity = value.severity.value if value.severity else None
        row.review_evidence_refs = list(value.review_evidence_refs)
        row.external_defect_ref = value.external_defect_ref
        row.filing_evidence_refs = list(value.filing_evidence_refs)
        row.fix_revision_ref = value.fix_revision_ref
        row.fix_detected_evidence_refs = list(value.fix_detected_evidence_refs)
        row.fix_verification_work_item_id = value.fix_verification_work_item_id
        row.fix_verification_attempt_id = value.fix_verification_attempt_id
        row.fix_verification_evidence_refs = list(value.fix_verification_evidence_refs)
        row.impact_regression_work_item_id = value.impact_regression_work_item_id
        row.impact_regression_case_id = value.impact_regression_case_id
        row.impact_regression_attempt_id = value.impact_regression_attempt_id
        row.impact_regression_evidence_refs = list(value.impact_regression_evidence_refs)
        row.closure_evidence_refs = list(value.closure_evidence_refs)

    @staticmethod
    def _value(row: DefectCaseRow) -> DefectCase:
        return DefectCase(
            defect_case_id=row.defect_case_id,
            test_run_id=row.test_run_id,
            route_decision_id=row.route_decision_id,
            source_observation_id=row.source_observation_id,
            source_case_id=row.source_case_id,
            source_attempt_id=row.source_attempt_id,
            state=DefectState(row.state),
            candidate_evidence_refs=tuple(row.candidate_evidence_refs or ()),
            created_at=int(row.created_at),
            updated_at=int(row.updated_at),
            reproduction_attempt_id=row.reproduction_attempt_id,
            reproducer_ref=row.reproducer_ref,
            reproduction_evidence_refs=tuple(row.reproduction_evidence_refs or ()),
            qualification_evidence_refs=tuple(row.qualification_evidence_refs or ()),
            rca_summary=row.rca_summary,
            rca_evidence_refs=tuple(row.rca_evidence_refs or ()),
            duplicate_of=row.duplicate_of,
            dedup_evidence_refs=tuple(row.dedup_evidence_refs or ()),
            impact_refs=tuple(row.impact_refs or ()),
            impact_evidence_refs=tuple(row.impact_evidence_refs or ()),
            severity=DefectSeverity(row.severity) if row.severity else None,
            review_evidence_refs=tuple(row.review_evidence_refs or ()),
            external_defect_ref=row.external_defect_ref,
            filing_evidence_refs=tuple(row.filing_evidence_refs or ()),
            fix_revision_ref=row.fix_revision_ref,
            fix_detected_evidence_refs=tuple(row.fix_detected_evidence_refs or ()),
            fix_verification_work_item_id=row.fix_verification_work_item_id,
            fix_verification_attempt_id=row.fix_verification_attempt_id,
            fix_verification_evidence_refs=tuple(row.fix_verification_evidence_refs or ()),
            impact_regression_work_item_id=row.impact_regression_work_item_id,
            impact_regression_case_id=row.impact_regression_case_id,
            impact_regression_attempt_id=row.impact_regression_attempt_id,
            impact_regression_evidence_refs=tuple(row.impact_regression_evidence_refs or ()),
            closure_evidence_refs=tuple(row.closure_evidence_refs or ()),
        )
