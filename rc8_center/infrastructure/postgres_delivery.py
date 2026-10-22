"""PostgreSQL persistence for production-batch-first requirement delivery."""
from __future__ import annotations

import time
from typing import Dict, List, Optional

from sqlalchemy import BigInteger, JSON, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from rc8_center.delivery import (
    ProductionBatch,
    ProductionBatchState,
    Requirement,
    RequirementDelivery,
    RequirementDeliveryHistory,
    RequirementDeliveryScope,
    RequirementDeliveryState,
)

from .postgres import Base, PostgresStore


class ProductionBatchRow(Base):
    __tablename__ = "rc8_production_batch"

    production_batch_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    production_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class RequirementRow(Base):
    __tablename__ = "rc8_requirement"

    requirement_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class RequirementDeliveryRow(Base):
    __tablename__ = "rc8_requirement_delivery"
    __table_args__ = (
        UniqueConstraint("production_batch_id", "requirement_id", name="uq_rc8_requirement_delivery_batch_requirement"),
    )

    delivery_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    production_batch_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    requirement_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    continuation_of_delivery_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class RequirementDeliveryScopeRow(Base):
    __tablename__ = "rc8_requirement_delivery_scope"
    __table_args__ = (
        UniqueConstraint("scope_identity", name="uq_rc8_requirement_delivery_scope_identity"),
    )

    scope_id: Mapped[str] = mapped_column(String(220), primary_key=True)
    delivery_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    scope_identity: Mapped[str] = mapped_column(String(900), nullable=False)
    system_id: Mapped[str] = mapped_column(String(240), nullable=False)
    system_version: Mapped[str] = mapped_column(String(240), nullable=False)
    application_id: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    sst_id: Mapped[str] = mapped_column(String(240), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class PostgresRequirementDeliveryRepository:
    """Durable task-scope model; historical batch participation is append-only."""

    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    @staticmethod
    def _now(now: Optional[int] = None) -> int:
        return int(now if now is not None else time.time())

    @staticmethod
    def _required(value: str, error: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(error)
        return normalized

    def create_batch(self, value: ProductionBatch) -> ProductionBatch:
        self._required(value.production_batch_id, "PRODUCTION_BATCH_ID_REQUIRED")
        self._required(value.production_date, "PRODUCTION_DATE_REQUIRED")
        self._required(value.name, "PRODUCTION_BATCH_NAME_REQUIRED")
        with self.store.session() as session:
            if session.get(ProductionBatchRow, value.production_batch_id) is not None:
                raise ValueError("PRODUCTION_BATCH_ALREADY_EXISTS")
            session.add(self._batch_row(value))
        return value

    def get_batch(self, production_batch_id: str) -> Optional[ProductionBatch]:
        with self.store.session() as session:
            row = session.get(ProductionBatchRow, production_batch_id)
            return self._batch(row) if row is not None else None

    def list_batches(self) -> List[ProductionBatch]:
        with self.store.session() as session:
            rows = session.scalars(
                select(ProductionBatchRow).order_by(ProductionBatchRow.production_date, ProductionBatchRow.created_at)
            )
            return [self._batch(row) for row in rows]

    def create_requirement(self, value: Requirement) -> Requirement:
        self._required(value.requirement_id, "REQUIREMENT_ID_REQUIRED")
        self._required(value.title, "REQUIREMENT_TITLE_REQUIRED")
        with self.store.session() as session:
            if session.get(RequirementRow, value.requirement_id) is not None:
                raise ValueError("REQUIREMENT_ALREADY_EXISTS")
            session.add(self._requirement_row(value))
        return value

    def get_requirement(self, requirement_id: str) -> Optional[Requirement]:
        with self.store.session() as session:
            row = session.get(RequirementRow, requirement_id)
            return self._requirement(row) if row is not None else None

    def create_delivery(self, value: RequirementDelivery) -> RequirementDelivery:
        self._required(value.delivery_id, "REQUIREMENT_DELIVERY_ID_REQUIRED")
        with self.store.session() as session:
            if session.get(RequirementDeliveryRow, value.delivery_id) is not None:
                raise ValueError("REQUIREMENT_DELIVERY_ALREADY_EXISTS")
            if session.get(ProductionBatchRow, value.production_batch_id) is None:
                raise ValueError("PRODUCTION_BATCH_NOT_FOUND")
            if session.get(RequirementRow, value.requirement_id) is None:
                raise ValueError("REQUIREMENT_NOT_FOUND")
            duplicate = session.scalar(
                select(RequirementDeliveryRow).where(
                    RequirementDeliveryRow.production_batch_id == value.production_batch_id,
                    RequirementDeliveryRow.requirement_id == value.requirement_id,
                )
            )
            if duplicate is not None:
                raise ValueError("REQUIREMENT_ALREADY_PARTICIPATES_IN_BATCH")
            if value.continuation_of_delivery_id:
                previous = session.get(RequirementDeliveryRow, value.continuation_of_delivery_id)
                if previous is None:
                    raise ValueError("CONTINUATION_DELIVERY_NOT_FOUND")
                if previous.requirement_id != value.requirement_id:
                    raise ValueError("CONTINUATION_REQUIREMENT_MISMATCH")
                if previous.production_batch_id == value.production_batch_id:
                    raise ValueError("CONTINUATION_MUST_USE_DIFFERENT_BATCH")
            session.add(self._delivery_row(value))
        return value

    def get_delivery(self, delivery_id: str) -> Optional[RequirementDelivery]:
        with self.store.session() as session:
            row = session.get(RequirementDeliveryRow, delivery_id)
            return self._delivery(row) if row is not None else None

    def transition_delivery(self, delivery_id: str, target: RequirementDeliveryState, *, now: Optional[int] = None) -> RequirementDelivery:
        target = RequirementDeliveryState(target)
        with self.store.session() as session:
            row = session.get(RequirementDeliveryRow, delivery_id)
            if row is None:
                raise ValueError("REQUIREMENT_DELIVERY_NOT_FOUND")
            current = self._delivery(row)
            next_value = current.transition_to(target)
            row.state = next_value.state.value
            row.updated_at = self._now(now)
            return RequirementDelivery(
                delivery_id=next_value.delivery_id,
                production_batch_id=next_value.production_batch_id,
                requirement_id=next_value.requirement_id,
                state=next_value.state,
                continuation_of_delivery_id=next_value.continuation_of_delivery_id,
                created_at=next_value.created_at,
                updated_at=int(row.updated_at),
                payload=dict(next_value.payload),
            )

    def create_scope(self, value: RequirementDeliveryScope) -> RequirementDeliveryScope:
        for raw, error in (
            (value.scope_id, "DELIVERY_SCOPE_ID_REQUIRED"),
            (value.delivery_id, "REQUIREMENT_DELIVERY_ID_REQUIRED"),
            (value.system_id, "DELIVERY_SCOPE_SYSTEM_REQUIRED"),
            (value.system_version, "DELIVERY_SCOPE_SYSTEM_VERSION_REQUIRED"),
            (value.sst_id, "DELIVERY_SCOPE_SST_REQUIRED"),
        ):
            self._required(raw, error)
        with self.store.session() as session:
            if session.get(RequirementDeliveryScopeRow, value.scope_id) is not None:
                raise ValueError("DELIVERY_SCOPE_ALREADY_EXISTS")
            if session.get(RequirementDeliveryRow, value.delivery_id) is None:
                raise ValueError("REQUIREMENT_DELIVERY_NOT_FOUND")
            duplicate = session.scalar(
                select(RequirementDeliveryScopeRow).where(
                    RequirementDeliveryScopeRow.scope_identity == value.scope_identity
                )
            )
            if duplicate is not None:
                raise ValueError("DELIVERY_SCOPE_DUPLICATE")
            session.add(self._scope_row(value))
        return value

    def list_scopes(self, delivery_id: str) -> List[RequirementDeliveryScope]:
        with self.store.session() as session:
            rows = session.scalars(
                select(RequirementDeliveryScopeRow)
                .where(RequirementDeliveryScopeRow.delivery_id == delivery_id)
                .order_by(
                    RequirementDeliveryScopeRow.system_id,
                    RequirementDeliveryScopeRow.system_version,
                    RequirementDeliveryScopeRow.sst_id,
                )
            )
            return [self._scope(row) for row in rows]

    def requirement_history(self, requirement_id: str) -> RequirementDeliveryHistory:
        requirement = self.get_requirement(requirement_id)
        if requirement is None:
            raise ValueError("REQUIREMENT_NOT_FOUND")
        with self.store.session() as session:
            rows = session.execute(
                select(RequirementDeliveryRow, ProductionBatchRow)
                .join(ProductionBatchRow, ProductionBatchRow.production_batch_id == RequirementDeliveryRow.production_batch_id)
                .where(RequirementDeliveryRow.requirement_id == requirement_id)
                .order_by(ProductionBatchRow.production_date, RequirementDeliveryRow.created_at)
            ).all()
        deliveries = [self._delivery(row) for row, _batch in rows]
        scopes: Dict[str, List[RequirementDeliveryScope]] = {
            delivery.delivery_id: self.list_scopes(delivery.delivery_id) for delivery in deliveries
        }
        return RequirementDeliveryHistory(requirement=requirement, deliveries=deliveries, scopes_by_delivery=scopes)

    def batch_plan(self, production_batch_id: str) -> Dict[str, object]:
        batch = self.get_batch(production_batch_id)
        if batch is None:
            raise ValueError("PRODUCTION_BATCH_NOT_FOUND")
        with self.store.session() as session:
            rows = session.scalars(
                select(RequirementDeliveryRow)
                .where(RequirementDeliveryRow.production_batch_id == production_batch_id)
                .order_by(RequirementDeliveryRow.created_at, RequirementDeliveryRow.requirement_id)
            )
            deliveries = [self._delivery(row) for row in rows]
        items = []
        for delivery in deliveries:
            requirement = self.get_requirement(delivery.requirement_id)
            items.append(
                {
                    "delivery": delivery,
                    "requirement": requirement,
                    "scopes": self.list_scopes(delivery.delivery_id),
                }
            )
        return {"batch": batch, "requirements": items}

    @staticmethod
    def _batch_row(value: ProductionBatch) -> ProductionBatchRow:
        return ProductionBatchRow(
            production_batch_id=value.production_batch_id,
            production_date=value.production_date,
            name=value.name,
            state=value.state.value,
            created_at=int(value.created_at),
            payload=dict(value.payload),
        )

    @staticmethod
    def _batch(row: ProductionBatchRow) -> ProductionBatch:
        return ProductionBatch(
            production_batch_id=row.production_batch_id,
            production_date=row.production_date,
            name=row.name,
            state=ProductionBatchState(row.state),
            created_at=int(row.created_at),
            payload=dict(row.payload or {}),
        )

    @staticmethod
    def _requirement_row(value: Requirement) -> RequirementRow:
        return RequirementRow(
            requirement_id=value.requirement_id,
            title=value.title,
            created_at=int(value.created_at),
            payload=dict(value.payload),
        )

    @staticmethod
    def _requirement(row: RequirementRow) -> Requirement:
        return Requirement(
            requirement_id=row.requirement_id,
            title=row.title,
            created_at=int(row.created_at),
            payload=dict(row.payload or {}),
        )

    @staticmethod
    def _delivery_row(value: RequirementDelivery) -> RequirementDeliveryRow:
        return RequirementDeliveryRow(
            delivery_id=value.delivery_id,
            production_batch_id=value.production_batch_id,
            requirement_id=value.requirement_id,
            state=value.state.value,
            continuation_of_delivery_id=value.continuation_of_delivery_id,
            created_at=int(value.created_at),
            updated_at=int(value.updated_at),
            payload=dict(value.payload),
        )

    @staticmethod
    def _delivery(row: RequirementDeliveryRow) -> RequirementDelivery:
        return RequirementDelivery(
            delivery_id=row.delivery_id,
            production_batch_id=row.production_batch_id,
            requirement_id=row.requirement_id,
            state=RequirementDeliveryState(row.state),
            continuation_of_delivery_id=row.continuation_of_delivery_id,
            created_at=int(row.created_at),
            updated_at=int(row.updated_at),
            payload=dict(row.payload or {}),
        )

    @staticmethod
    def _scope_row(value: RequirementDeliveryScope) -> RequirementDeliveryScopeRow:
        return RequirementDeliveryScopeRow(
            scope_id=value.scope_id,
            delivery_id=value.delivery_id,
            scope_identity=value.scope_identity,
            system_id=value.system_id,
            system_version=value.system_version,
            application_id=value.application_id,
            sst_id=value.sst_id,
            created_at=int(value.created_at),
            payload=dict(value.payload),
        )

    @staticmethod
    def _scope(row: RequirementDeliveryScopeRow) -> RequirementDeliveryScope:
        return RequirementDeliveryScope(
            scope_id=row.scope_id,
            delivery_id=row.delivery_id,
            system_id=row.system_id,
            system_version=row.system_version,
            application_id=row.application_id,
            sst_id=row.sst_id,
            created_at=int(row.created_at),
            payload=dict(row.payload or {}),
        )
