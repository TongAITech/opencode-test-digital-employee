"""PostgreSQL durable persistence for RC8 N8 diagnosis and recovery truth."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Boolean, JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column

from rc8_center.failure_diagnosis import (
    DiagnosticEvidence,
    FailureClassification,
    FailureDiagnosisError,
    FailureObservation,
    GapRouteDecision,
    RepairReceipt,
    RepairResult,
    RepairWorkOrder,
    RouteFailureScope,
    SuccessorAttempt,
)
from rc8_runtime.mission_nodes import MissionNodeType

from .postgres import Base, PostgresStore


class FailureObservationRow(Base):
    __tablename__ = "rc8_failure_observation"
    observation_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    source_mission_node_id: Mapped[str] = mapped_column(String(300), nullable=False)
    source_attempt_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_case_id: Mapped[str] = mapped_column(String(200), nullable=False)
    source_assertion_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    observed_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class DiagnosticEvidenceRow(Base):
    __tablename__ = "rc8_diagnostic_evidence"
    diagnostic_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    classification: Mapped[str] = mapped_column(String(64), nullable=False)
    classifier_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(240), nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    diagnosed_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    route_scope: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class GapRouteDecisionRow(Base):
    __tablename__ = "rc8_gap_route_decision"
    decision_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    observation_id: Mapped[str] = mapped_column(String(240), nullable=False)
    diagnostic_id: Mapped[str] = mapped_column(String(240), nullable=False)
    gap_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    classification: Mapped[str] = mapped_column(String(64), nullable=False)
    target_mission_node: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_code: Mapped[str] = mapped_column(String(240), nullable=False)
    repairable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    decided_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    authority: Mapped[str] = mapped_column(String(32), nullable=False)


class RepairWorkOrderRow(Base):
    __tablename__ = "rc8_repair_work_order"
    work_order_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    route_decision_id: Mapped[str] = mapped_column(String(240), nullable=False)
    gap_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    predecessor_attempt_id: Mapped[str] = mapped_column(String(200), nullable=False)
    target_mission_node: Mapped[str] = mapped_column(String(100), nullable=False)
    repair_strategy: Mapped[str] = mapped_column(String(240), nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RepairReceiptRow(Base):
    __tablename__ = "rc8_repair_receipt"
    receipt_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    work_order_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    recorded_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class SuccessorAttemptRow(Base):
    __tablename__ = "rc8_successor_attempt"
    successor_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    work_order_id: Mapped[str] = mapped_column(String(240), nullable=False, unique=True, index=True)
    repair_receipt_id: Mapped[str] = mapped_column(String(240), nullable=False)
    predecessor_attempt_id: Mapped[str] = mapped_column(String(200), nullable=False)
    successor_attempt_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    authorized_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PostgresFailureDiagnosisRepository:
    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    @staticmethod
    def _same_or_conflict(existing, value, converter, message: str) -> bool:
        if existing is None:
            return False
        if converter(existing) != value:
            raise FailureDiagnosisError(message)
        return True

    def save_observation(self, value: FailureObservation) -> None:
        with self.store.session() as session:
            existing = session.get(FailureObservationRow, value.observation_id)
            if self._same_or_conflict(existing, value, self._observation, "FAILURE_OBSERVATION_ID_CONFLICT"): return
            session.add(FailureObservationRow(observation_id=value.observation_id, test_run_id=value.test_run_id, source_mission_node_id=value.source_mission_node_id, source_attempt_id=value.source_attempt_id, source_case_id=value.source_case_id, source_assertion_id=value.source_assertion_id, summary=value.summary, evidence_refs=list(value.evidence_refs), observed_at=value.observed_at))

    def get_observation(self, observation_id: str) -> Optional[FailureObservation]:
        with self.store.session() as session:
            row = session.get(FailureObservationRow, observation_id)
            return self._observation(row) if row is not None else None

    def save_diagnostic(self, value: DiagnosticEvidence) -> None:
        with self.store.session() as session:
            existing = session.get(DiagnosticEvidenceRow, value.diagnostic_id)
            if self._same_or_conflict(existing, value, self._diagnostic, "DIAGNOSTIC_ID_CONFLICT"): return
            session.add(DiagnosticEvidenceRow(diagnostic_id=value.diagnostic_id, observation_id=value.observation_id, classification=value.classification.value, classifier_ref=value.classifier_ref, reason_code=value.reason_code, evidence_refs=list(value.evidence_refs), diagnosed_at=value.diagnosed_at, route_scope=value.route_scope.value if value.route_scope else None))

    def get_diagnostic(self, diagnostic_id: str) -> Optional[DiagnosticEvidence]:
        with self.store.session() as session:
            row = session.get(DiagnosticEvidenceRow, diagnostic_id)
            return self._diagnostic(row) if row is not None else None

    def save_route(self, value: GapRouteDecision) -> None:
        with self.store.session() as session:
            existing = session.get(GapRouteDecisionRow, value.decision_id)
            if self._same_or_conflict(existing, value, self._route, "GAP_ROUTE_ID_CONFLICT"): return
            session.add(GapRouteDecisionRow(decision_id=value.decision_id, test_run_id=value.test_run_id, observation_id=value.observation_id, diagnostic_id=value.diagnostic_id, gap_id=value.gap_id, classification=value.classification.value, target_mission_node=value.target_mission_node.value, policy_code=value.policy_code, repairable=value.repairable, evidence_refs=list(value.evidence_refs), decided_at=value.decided_at, authority=value.authority))

    def get_route(self, decision_id: str) -> Optional[GapRouteDecision]:
        with self.store.session() as session:
            row = session.get(GapRouteDecisionRow, decision_id)
            return self._route(row) if row is not None else None

    def save_work_order(self, value: RepairWorkOrder) -> None:
        with self.store.session() as session:
            existing = session.get(RepairWorkOrderRow, value.work_order_id)
            if self._same_or_conflict(existing, value, self._work_order, "REPAIR_WORK_ORDER_ID_CONFLICT"): return
            session.add(RepairWorkOrderRow(work_order_id=value.work_order_id, test_run_id=value.test_run_id, route_decision_id=value.route_decision_id, gap_id=value.gap_id, predecessor_attempt_id=value.predecessor_attempt_id, target_mission_node=value.target_mission_node.value, repair_strategy=value.repair_strategy, evidence_refs=list(value.evidence_refs), created_at=value.created_at))

    def get_work_order(self, work_order_id: str) -> Optional[RepairWorkOrder]:
        with self.store.session() as session:
            row = session.get(RepairWorkOrderRow, work_order_id)
            return self._work_order(row) if row is not None else None

    def save_repair_receipt(self, value: RepairReceipt) -> None:
        with self.store.session() as session:
            existing = session.get(RepairReceiptRow, value.receipt_id)
            if self._same_or_conflict(existing, value, self._repair_receipt, "REPAIR_RECEIPT_ID_CONFLICT"): return
            session.add(RepairReceiptRow(receipt_id=value.receipt_id, work_order_id=value.work_order_id, result=value.result.value, evidence_refs=list(value.evidence_refs), recorded_at=value.recorded_at))

    def get_repair_receipt(self, receipt_id: str) -> Optional[RepairReceipt]:
        with self.store.session() as session:
            row = session.get(RepairReceiptRow, receipt_id)
            return self._repair_receipt(row) if row is not None else None

    def save_successor(self, value: SuccessorAttempt) -> None:
        with self.store.session() as session:
            existing = session.get(SuccessorAttemptRow, value.successor_id)
            if self._same_or_conflict(existing, value, self._successor, "SUCCESSOR_ID_CONFLICT"): return
            duplicate = session.scalar(select(SuccessorAttemptRow).where(SuccessorAttemptRow.work_order_id == value.work_order_id).limit(1))
            if duplicate is not None:
                raise FailureDiagnosisError("REPAIR_WORK_ORDER_ALREADY_HAS_SUCCESSOR")
            session.add(SuccessorAttemptRow(successor_id=value.successor_id, test_run_id=value.test_run_id, work_order_id=value.work_order_id, repair_receipt_id=value.repair_receipt_id, predecessor_attempt_id=value.predecessor_attempt_id, successor_attempt_id=value.successor_attempt_id, authorized_at=value.authorized_at))

    @staticmethod
    def _observation(row: FailureObservationRow) -> FailureObservation:
        return FailureObservation(observation_id=row.observation_id, test_run_id=row.test_run_id, source_mission_node_id=row.source_mission_node_id, source_attempt_id=row.source_attempt_id, source_case_id=row.source_case_id, source_assertion_id=row.source_assertion_id, summary=row.summary, evidence_refs=tuple(row.evidence_refs or ()), observed_at=int(row.observed_at))

    @staticmethod
    def _diagnostic(row: DiagnosticEvidenceRow) -> DiagnosticEvidence:
        return DiagnosticEvidence(diagnostic_id=row.diagnostic_id, observation_id=row.observation_id, classification=FailureClassification(row.classification), classifier_ref=row.classifier_ref, reason_code=row.reason_code, evidence_refs=tuple(row.evidence_refs or ()), diagnosed_at=int(row.diagnosed_at), route_scope=RouteFailureScope(row.route_scope) if row.route_scope else None)

    @staticmethod
    def _route(row: GapRouteDecisionRow) -> GapRouteDecision:
        return GapRouteDecision(decision_id=row.decision_id, test_run_id=row.test_run_id, observation_id=row.observation_id, diagnostic_id=row.diagnostic_id, gap_id=row.gap_id, classification=FailureClassification(row.classification), target_mission_node=MissionNodeType(row.target_mission_node), policy_code=row.policy_code, repairable=bool(row.repairable), evidence_refs=tuple(row.evidence_refs or ()), decided_at=int(row.decided_at), authority=row.authority)

    @staticmethod
    def _work_order(row: RepairWorkOrderRow) -> RepairWorkOrder:
        return RepairWorkOrder(work_order_id=row.work_order_id, test_run_id=row.test_run_id, route_decision_id=row.route_decision_id, gap_id=row.gap_id, predecessor_attempt_id=row.predecessor_attempt_id, target_mission_node=MissionNodeType(row.target_mission_node), repair_strategy=row.repair_strategy, evidence_refs=tuple(row.evidence_refs or ()), created_at=int(row.created_at))

    @staticmethod
    def _repair_receipt(row: RepairReceiptRow) -> RepairReceipt:
        return RepairReceipt(receipt_id=row.receipt_id, work_order_id=row.work_order_id, result=RepairResult(row.result), evidence_refs=tuple(row.evidence_refs or ()), recorded_at=int(row.recorded_at))

    @staticmethod
    def _successor(row: SuccessorAttemptRow) -> SuccessorAttempt:
        return SuccessorAttempt(successor_id=row.successor_id, test_run_id=row.test_run_id, work_order_id=row.work_order_id, repair_receipt_id=row.repair_receipt_id, predecessor_attempt_id=row.predecessor_attempt_id, successor_attempt_id=row.successor_attempt_id, authorized_at=int(row.authorized_at))
