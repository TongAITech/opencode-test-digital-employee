"""PostgreSQL durable persistence for RC8 N10 convergence decisions."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Boolean, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from rc8_center.mission_convergence import (
    MissionConvergenceDecision,
    MissionConvergenceError,
    ProductQualityAssessment,
    ReleaseRecommendation,
    ReportReleaseAuthorization,
    TestSufficiencyDecision,
)

from .postgres import Base, PostgresStore


class MissionConvergenceDecisionRow(Base):
    __tablename__ = "rc8_mission_convergence_decision"

    decision_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    truth_snapshot_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    test_sufficiency: Mapped[str] = mapped_column(String(64), nullable=False)
    product_quality: Mapped[str] = mapped_column(String(64), nullable=False)
    release_recommendation: Mapped[str] = mapped_column(String(64), nullable=False)
    mission_converged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    decided_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    authority: Mapped[str] = mapped_column(String(32), nullable=False)


class ReportReleaseAuthorizationRow(Base):
    __tablename__ = "rc8_report_release_authorization"

    authorization_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    report_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    authorized_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PostgresMissionConvergenceRepository:
    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def get_decision(self, decision_id: str) -> Optional[MissionConvergenceDecision]:
        with self.store.session() as session:
            row = session.get(MissionConvergenceDecisionRow, decision_id)
            return self._decision(row) if row is not None else None

    def save_decision(self, value: MissionConvergenceDecision) -> None:
        if not isinstance(value, MissionConvergenceDecision):
            raise MissionConvergenceError("CONVERGENCE_DECISION_REQUIRED")
        with self.store.session() as session:
            existing = session.get(MissionConvergenceDecisionRow, value.decision_id)
            if existing is not None:
                if self._decision(existing) != value:
                    raise MissionConvergenceError("CONVERGENCE_DECISION_ID_CONFLICT")
                return
            session.add(MissionConvergenceDecisionRow(
                decision_id=value.decision_id,
                truth_snapshot_id=value.truth_snapshot_id,
                test_run_id=value.test_run_id,
                test_sufficiency=value.test_sufficiency.value,
                product_quality=value.product_quality.value,
                release_recommendation=value.release_recommendation.value,
                mission_converged=value.mission_converged,
                reason_codes=list(value.reason_codes),
                evidence_refs=list(value.evidence_refs),
                decided_at=value.decided_at,
                authority=value.authority,
            ))

    def save_report_authorization(self, value: ReportReleaseAuthorization) -> None:
        if not isinstance(value, ReportReleaseAuthorization):
            raise MissionConvergenceError("REPORT_AUTHORIZATION_REQUIRED")
        with self.store.session() as session:
            existing = session.get(ReportReleaseAuthorizationRow, value.authorization_id)
            if existing is not None:
                current = ReportReleaseAuthorization(
                    authorization_id=existing.authorization_id,
                    decision_id=existing.decision_id,
                    report_id=existing.report_id,
                    authorized_at=int(existing.authorized_at),
                )
                if current != value:
                    raise MissionConvergenceError("REPORT_AUTHORIZATION_ID_CONFLICT")
                return
            session.add(ReportReleaseAuthorizationRow(
                authorization_id=value.authorization_id,
                decision_id=value.decision_id,
                report_id=value.report_id,
                authorized_at=value.authorized_at,
            ))

    @staticmethod
    def _decision(row: MissionConvergenceDecisionRow) -> MissionConvergenceDecision:
        return MissionConvergenceDecision(
            decision_id=row.decision_id,
            truth_snapshot_id=row.truth_snapshot_id,
            test_run_id=row.test_run_id,
            test_sufficiency=TestSufficiencyDecision(row.test_sufficiency),
            product_quality=ProductQualityAssessment(row.product_quality),
            release_recommendation=ReleaseRecommendation(row.release_recommendation),
            mission_converged=bool(row.mission_converged),
            reason_codes=tuple(row.reason_codes or ()),
            evidence_refs=tuple(row.evidence_refs or ()),
            decided_at=int(row.decided_at),
            authority=row.authority,
        )
