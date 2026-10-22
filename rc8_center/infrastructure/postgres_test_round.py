"""PostgreSQL persistence for TestRounds inside one production date."""
from __future__ import annotations

import time
from typing import List, Optional

from sqlalchemy import BigInteger, JSON, String, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column

from rc8_center.test_rounds import TestRound, TestRoundDelivery, TestRoundState

from .postgres import Base, PostgresStore
from .postgres_delivery import ProductionBatchRow, RequirementDeliveryRow


class TestRoundRow(Base):
    __tablename__ = "rc8_test_round"
    __table_args__ = (
        UniqueConstraint("production_batch_id", "round_no", name="uq_rc8_test_round_batch_no"),
    )

    test_round_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    production_batch_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    round_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    completed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class TestRoundDeliveryRow(Base):
    __tablename__ = "rc8_test_round_delivery"
    __table_args__ = (
        UniqueConstraint("test_round_id", "delivery_id", name="uq_rc8_test_round_delivery_pair"),
    )

    round_delivery_id: Mapped[str] = mapped_column(String(220), primary_key=True)
    test_round_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    delivery_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    included_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class PostgresTestRoundRepository:
    """Durable append-only test-round history scoped by production date."""

    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    @staticmethod
    def _now(now: Optional[int] = None) -> int:
        return int(now if now is not None else time.time())

    def next_round_no(self, production_batch_id: str) -> int:
        with self.store.session() as session:
            if session.get(ProductionBatchRow, production_batch_id) is None:
                raise ValueError("PRODUCTION_BATCH_NOT_FOUND")
            current = session.scalar(
                select(func.max(TestRoundRow.round_no)).where(
                    TestRoundRow.production_batch_id == production_batch_id
                )
            )
            return int(current or 0) + 1

    def create_round(self, value: TestRound) -> TestRound:
        with self.store.session() as session:
            if session.get(ProductionBatchRow, value.production_batch_id) is None:
                raise ValueError("PRODUCTION_BATCH_NOT_FOUND")
            if session.get(TestRoundRow, value.test_round_id) is not None:
                raise ValueError("TEST_ROUND_ALREADY_EXISTS")
            duplicate = session.scalar(
                select(TestRoundRow).where(
                    TestRoundRow.production_batch_id == value.production_batch_id,
                    TestRoundRow.round_no == value.round_no,
                )
            )
            if duplicate is not None:
                raise ValueError("TEST_ROUND_NO_ALREADY_EXISTS_IN_PRODUCTION_DATE")
            session.add(self._round_row(value))
        return value

    def get_round(self, test_round_id: str) -> Optional[TestRound]:
        with self.store.session() as session:
            row = session.get(TestRoundRow, test_round_id)
            return self._round(row) if row is not None else None

    def list_rounds(self, production_batch_id: str) -> List[TestRound]:
        with self.store.session() as session:
            rows = session.scalars(
                select(TestRoundRow)
                .where(TestRoundRow.production_batch_id == production_batch_id)
                .order_by(TestRoundRow.round_no)
            )
            return [self._round(row) for row in rows]

    def include_delivery(self, value: TestRoundDelivery) -> TestRoundDelivery:
        with self.store.session() as session:
            round_row = session.get(TestRoundRow, value.test_round_id)
            if round_row is None:
                raise ValueError("TEST_ROUND_NOT_FOUND")
            delivery_row = session.get(RequirementDeliveryRow, value.delivery_id)
            if delivery_row is None:
                raise ValueError("REQUIREMENT_DELIVERY_NOT_FOUND")
            if delivery_row.production_batch_id != round_row.production_batch_id:
                raise ValueError("TEST_ROUND_DELIVERY_PRODUCTION_DATE_MISMATCH")
            if session.get(TestRoundDeliveryRow, value.round_delivery_id) is not None:
                raise ValueError("TEST_ROUND_DELIVERY_ALREADY_EXISTS")
            duplicate = session.scalar(
                select(TestRoundDeliveryRow).where(
                    TestRoundDeliveryRow.test_round_id == value.test_round_id,
                    TestRoundDeliveryRow.delivery_id == value.delivery_id,
                )
            )
            if duplicate is not None:
                raise ValueError("REQUIREMENT_DELIVERY_ALREADY_IN_TEST_ROUND")
            session.add(self._round_delivery_row(value))
        return value

    def list_round_deliveries(self, test_round_id: str) -> List[TestRoundDelivery]:
        with self.store.session() as session:
            rows = session.scalars(
                select(TestRoundDeliveryRow)
                .where(TestRoundDeliveryRow.test_round_id == test_round_id)
                .order_by(TestRoundDeliveryRow.included_at, TestRoundDeliveryRow.round_delivery_id)
            )
            return [self._round_delivery(row) for row in rows]

    def transition_round(self, test_round_id: str, target: TestRoundState, *, now: Optional[int] = None) -> TestRound:
        timestamp = self._now(now)
        with self.store.session() as session:
            row = session.get(TestRoundRow, test_round_id)
            if row is None:
                raise ValueError("TEST_ROUND_NOT_FOUND")
            next_value = self._round(row).transition_to(TestRoundState(target), now=timestamp)
            row.state = next_value.state.value
            row.started_at = next_value.started_at
            row.completed_at = next_value.completed_at
            return self._round(row)

    @staticmethod
    def _round_row(value: TestRound) -> TestRoundRow:
        return TestRoundRow(
            test_round_id=value.test_round_id,
            production_batch_id=value.production_batch_id,
            round_no=int(value.round_no),
            name=value.name,
            state=value.state.value,
            created_at=int(value.created_at),
            started_at=value.started_at,
            completed_at=value.completed_at,
            payload=dict(value.payload),
        )

    @staticmethod
    def _round(row: TestRoundRow) -> TestRound:
        return TestRound(
            test_round_id=row.test_round_id,
            production_batch_id=row.production_batch_id,
            round_no=int(row.round_no),
            name=row.name,
            state=TestRoundState(row.state),
            created_at=int(row.created_at),
            started_at=row.started_at,
            completed_at=row.completed_at,
            payload=dict(row.payload or {}),
        )

    @staticmethod
    def _round_delivery_row(value: TestRoundDelivery) -> TestRoundDeliveryRow:
        return TestRoundDeliveryRow(
            round_delivery_id=value.round_delivery_id,
            test_round_id=value.test_round_id,
            delivery_id=value.delivery_id,
            included_at=int(value.included_at),
            payload=dict(value.payload),
        )

    @staticmethod
    def _round_delivery(row: TestRoundDeliveryRow) -> TestRoundDelivery:
        return TestRoundDelivery(
            round_delivery_id=row.round_delivery_id,
            test_round_id=row.test_round_id,
            delivery_id=row.delivery_id,
            included_at=int(row.included_at),
            payload=dict(row.payload or {}),
        )
