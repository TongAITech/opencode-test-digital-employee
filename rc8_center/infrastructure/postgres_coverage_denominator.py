"""PostgreSQL durable persistence for RC8 N7 Coverage Denominator."""
from __future__ import annotations

from typing import Optional, Tuple

from sqlalchemy import BigInteger, Boolean, JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column

from rc8_center.coverage_denominator import CoverageDenominatorError, CoverageDenominatorSnapshot, CoverageObligation, CoverageObligationState, CoverageReceipt, LayerReopen

from .postgres import Base, PostgresStore


class CoverageDenominatorSnapshotRow(Base):
    __tablename__ = "rc8_coverage_denominator_snapshot"
    snapshot_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    mission_node_id: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    layer: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_revision: Mapped[str] = mapped_column(String(300), nullable=False)
    obligations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supersedes_snapshot_id: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)


class CoverageReceiptRow(Base):
    __tablename__ = "rc8_coverage_receipt"
    receipt_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    obligation_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    observed_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    case_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)


class LayerReopenRow(Base):
    __tablename__ = "rc8_layer_reopen"
    reopen_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    test_run_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    layer: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    previous_snapshot_id: Mapped[str] = mapped_column(String(240), nullable=False)
    new_snapshot_id: Mapped[str] = mapped_column(String(240), nullable=False)
    invalidated_receipt_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    added_obligation_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PostgresCoverageDenominatorRepository:
    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    def get_snapshot(self, snapshot_id: str) -> Optional[CoverageDenominatorSnapshot]:
        with self.store.session() as session:
            row = session.get(CoverageDenominatorSnapshotRow, snapshot_id)
            return self._snapshot(row) if row is not None else None

    def current_snapshot(self, test_run_id: str, layer: str) -> Optional[CoverageDenominatorSnapshot]:
        with self.store.session() as session:
            row = session.scalar(select(CoverageDenominatorSnapshotRow).where(CoverageDenominatorSnapshotRow.test_run_id == test_run_id, CoverageDenominatorSnapshotRow.layer == layer).order_by(CoverageDenominatorSnapshotRow.version.desc()).limit(1))
            return self._snapshot(row) if row is not None else None

    def save_snapshot(self, value: CoverageDenominatorSnapshot) -> None:
        with self.store.session() as session:
            existing = session.get(CoverageDenominatorSnapshotRow, value.snapshot_id)
            if existing is not None:
                if self._snapshot(existing) != value:
                    raise CoverageDenominatorError("COVERAGE_SNAPSHOT_ID_CONFLICT")
                return
            latest = session.scalar(select(CoverageDenominatorSnapshotRow).where(CoverageDenominatorSnapshotRow.test_run_id == value.test_run_id, CoverageDenominatorSnapshotRow.layer == value.layer).order_by(CoverageDenominatorSnapshotRow.version.desc()).limit(1))
            expected = 1 if latest is None else int(latest.version) + 1
            if value.version != expected:
                raise CoverageDenominatorError("COVERAGE_SNAPSHOT_VERSION_NON_MONOTONIC")
            session.add(CoverageDenominatorSnapshotRow(snapshot_id=value.snapshot_id, test_run_id=value.test_run_id, mission_node_id=value.mission_node_id, layer=value.layer, version=value.version, source_revision=value.source_revision, obligations=[self._obligation_json(item) for item in value.obligations], created_at=value.created_at, supersedes_snapshot_id=value.supersedes_snapshot_id))

    def receipts(self, snapshot_id: str) -> Tuple[CoverageReceipt, ...]:
        with self.store.session() as session:
            rows = list(session.scalars(select(CoverageReceiptRow).where(CoverageReceiptRow.snapshot_id == snapshot_id).order_by(CoverageReceiptRow.receipt_id)))
            return tuple(self._receipt(row) for row in rows)

    def save_receipt(self, value: CoverageReceipt) -> None:
        with self.store.session() as session:
            existing = session.get(CoverageReceiptRow, value.receipt_id)
            if existing is not None:
                if self._receipt(existing) != value:
                    raise CoverageDenominatorError("COVERAGE_RECEIPT_ID_CONFLICT")
                return
            duplicate = session.scalar(select(CoverageReceiptRow).where(CoverageReceiptRow.snapshot_id == value.snapshot_id, CoverageReceiptRow.obligation_id == value.obligation_id).limit(1))
            if duplicate is not None:
                raise CoverageDenominatorError("COVERAGE_OBLIGATION_ALREADY_RECEIPTED")
            session.add(CoverageReceiptRow(receipt_id=value.receipt_id, snapshot_id=value.snapshot_id, obligation_id=value.obligation_id, state=value.state.value, evidence_refs=list(value.evidence_refs), observed_at=value.observed_at, attempt_id=value.attempt_id, case_id=value.case_id))

    def save_reopen(self, value: LayerReopen) -> None:
        with self.store.session() as session:
            existing = session.get(LayerReopenRow, value.reopen_id)
            if existing is not None:
                return
            session.add(LayerReopenRow(reopen_id=value.reopen_id, test_run_id=value.test_run_id, layer=value.layer, previous_snapshot_id=value.previous_snapshot_id, new_snapshot_id=value.new_snapshot_id, invalidated_receipt_ids=list(value.invalidated_receipt_ids), added_obligation_ids=list(value.added_obligation_ids), evidence_refs=list(value.evidence_refs), created_at=value.created_at))

    @staticmethod
    def _obligation_json(value: CoverageObligation) -> dict:
        return {"obligation_id": value.obligation_id, "layer": value.layer, "subject_ref": value.subject_ref, "source_refs": list(value.source_refs), "critical": value.critical}

    @staticmethod
    def _snapshot(row: CoverageDenominatorSnapshotRow) -> CoverageDenominatorSnapshot:
        return CoverageDenominatorSnapshot(snapshot_id=row.snapshot_id, test_run_id=row.test_run_id, mission_node_id=row.mission_node_id, layer=row.layer, version=int(row.version), source_revision=row.source_revision, obligations=tuple(CoverageObligation(obligation_id=item["obligation_id"], layer=item["layer"], subject_ref=item["subject_ref"], source_refs=tuple(item.get("source_refs") or ()), critical=bool(item.get("critical", False))) for item in (row.obligations or [])), created_at=int(row.created_at), supersedes_snapshot_id=row.supersedes_snapshot_id)

    @staticmethod
    def _receipt(row: CoverageReceiptRow) -> CoverageReceipt:
        return CoverageReceipt(receipt_id=row.receipt_id, snapshot_id=row.snapshot_id, obligation_id=row.obligation_id, state=CoverageObligationState(row.state), evidence_refs=tuple(row.evidence_refs or ()), observed_at=int(row.observed_at), attempt_id=row.attempt_id, case_id=row.case_id)
