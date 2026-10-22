"""PostgreSQL persistence for first-class requirement/scope revisions."""
from __future__ import annotations

import hashlib
import time
from typing import List, Optional

from sqlalchemy import BigInteger, JSON, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from rc8_center.revisions import DeliveryRevisionBinding, RequirementRevision, ScopeRevision

from .postgres import Base, PostgresStore
from .postgres_delivery import RequirementDeliveryRow, RequirementRow


class RequirementRevisionRow(Base):
    __tablename__ = "rc8_requirement_revision"
    __table_args__ = (
        UniqueConstraint("requirement_id", "revision_label", name="uq_rc8_requirement_revision_label"),
    )

    requirement_revision_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    requirement_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    revision_label: Mapped[str] = mapped_column(String(80), nullable=False)
    parent_requirement_revision_id: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ScopeRevisionRow(Base):
    __tablename__ = "rc8_scope_revision"
    __table_args__ = (
        UniqueConstraint("requirement_revision_id", "revision_label", name="uq_rc8_scope_revision_label"),
    )

    scope_revision_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    requirement_revision_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    revision_label: Mapped[str] = mapped_column(String(80), nullable=False)
    parent_scope_revision_id: Mapped[Optional[str]] = mapped_column(String(240), nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class DeliveryRevisionBindingRow(Base):
    __tablename__ = "rc8_delivery_revision_binding"

    delivery_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    requirement_revision_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    scope_revision_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PostgresRequirementRevisionRepository:
    """Append-only revision identities and immutable Delivery bindings."""

    def __init__(self, store: PostgresStore) -> None:
        self.store = store

    @staticmethod
    def _now(now: Optional[int] = None) -> int:
        return int(now if now is not None else time.time())

    @staticmethod
    def _auto_id(prefix: str, *parts: str) -> str:
        digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
        return "%s-%s" % (prefix, digest)

    def create_requirement_revision(self, value: RequirementRevision) -> RequirementRevision:
        with self.store.session() as session:
            self._create_requirement_revision_in_session(session, value)
        return value

    def create_scope_revision(self, value: ScopeRevision) -> ScopeRevision:
        with self.store.session() as session:
            self._create_scope_revision_in_session(session, value)
        return value

    def bind_delivery(
        self,
        delivery_id: str,
        requirement_revision_id: str,
        scope_revision_id: str,
        *,
        now: Optional[int] = None,
    ) -> DeliveryRevisionBinding:
        with self.store.session() as session:
            delivery = session.get(RequirementDeliveryRow, delivery_id)
            if delivery is None:
                raise ValueError("REQUIREMENT_DELIVERY_NOT_FOUND")
            return self._bind_delivery_in_session(
                session,
                delivery,
                requirement_revision_id,
                scope_revision_id,
                now=now,
            )

    def ensure_delivery_binding(
        self,
        delivery_id: str,
        *,
        requirement_revision_id: Optional[str] = None,
        scope_revision_id: Optional[str] = None,
        now: Optional[int] = None,
    ) -> DeliveryRevisionBinding:
        with self.store.session() as session:
            delivery = session.get(RequirementDeliveryRow, delivery_id)
            if delivery is None:
                raise ValueError("REQUIREMENT_DELIVERY_NOT_FOUND")
            return self.ensure_delivery_binding_in_session(
                session,
                delivery,
                requirement_revision_id=requirement_revision_id,
                scope_revision_id=scope_revision_id,
                now=now,
            )

    def ensure_delivery_binding_in_session(
        self,
        session: Session,
        delivery: RequirementDeliveryRow,
        *,
        requirement_revision_id: Optional[str] = None,
        scope_revision_id: Optional[str] = None,
        now: Optional[int] = None,
    ) -> DeliveryRevisionBinding:
        """Ensure revision lineage in the caller's transaction.

        Delivery insertion and revision binding can therefore commit or roll
        back together. No product write is allowed to leave a versionless
        Delivery merely because a later validation failed.
        """
        existing = session.get(DeliveryRevisionBindingRow, delivery.delivery_id)
        if existing is not None:
            current = self._binding(existing)
            if requirement_revision_id and current.requirement_revision_id != requirement_revision_id:
                raise ValueError("DELIVERY_REVISION_BINDING_IMMUTABLE")
            if scope_revision_id and current.scope_revision_id != scope_revision_id:
                raise ValueError("DELIVERY_REVISION_BINDING_IMMUTABLE")
            return current

        timestamp = self._now(now)
        parent_binding: Optional[DeliveryRevisionBinding] = None
        if delivery.continuation_of_delivery_id:
            parent_delivery = session.get(RequirementDeliveryRow, delivery.continuation_of_delivery_id)
            if parent_delivery is None:
                raise ValueError("CONTINUATION_DELIVERY_NOT_FOUND")
            parent_binding = self.ensure_delivery_binding_in_session(
                session,
                parent_delivery,
                now=int(parent_delivery.created_at),
            )

        req_revision_id = requirement_revision_id
        if req_revision_id is None:
            req_revision_id = self._auto_id("req-rev", delivery.requirement_id, delivery.delivery_id)
            revision = session.get(RequirementRevisionRow, req_revision_id)
            if revision is None:
                value = RequirementRevision(
                    requirement_revision_id=req_revision_id,
                    requirement_id=delivery.requirement_id,
                    revision_label="AUTO-%s" % req_revision_id[-12:],
                    parent_requirement_revision_id=(
                        parent_binding.requirement_revision_id if parent_binding else None
                    ),
                    created_at=timestamp,
                    payload={
                        "source": "LEGACY_COMPAT_AUTO_MATERIALIZED",
                        "delivery_id": delivery.delivery_id,
                    },
                )
                self._create_requirement_revision_in_session(session, value)
        else:
            revision = session.get(RequirementRevisionRow, req_revision_id)
            if revision is None:
                raise ValueError("REQUIREMENT_REVISION_NOT_FOUND")
            if revision.requirement_id != delivery.requirement_id:
                raise ValueError("DELIVERY_REQUIREMENT_REVISION_MISMATCH")
            if parent_binding and revision.parent_requirement_revision_id not in {
                None,
                parent_binding.requirement_revision_id,
            }:
                raise ValueError("DELIVERY_REQUIREMENT_REVISION_LINEAGE_MISMATCH")

        scoped_revision_id = scope_revision_id
        if scoped_revision_id is None:
            scoped_revision_id = self._auto_id("scope-rev", req_revision_id, delivery.delivery_id)
            scoped_revision = session.get(ScopeRevisionRow, scoped_revision_id)
            if scoped_revision is None:
                value = ScopeRevision(
                    scope_revision_id=scoped_revision_id,
                    requirement_revision_id=req_revision_id,
                    revision_label="AUTO-%s" % scoped_revision_id[-12:],
                    parent_scope_revision_id=(parent_binding.scope_revision_id if parent_binding else None),
                    created_at=timestamp,
                    payload={
                        "source": "LEGACY_COMPAT_AUTO_MATERIALIZED",
                        "delivery_id": delivery.delivery_id,
                    },
                )
                self._create_scope_revision_in_session(session, value)
        else:
            scoped_revision = session.get(ScopeRevisionRow, scoped_revision_id)
            if scoped_revision is None:
                raise ValueError("SCOPE_REVISION_NOT_FOUND")
            if scoped_revision.requirement_revision_id != req_revision_id:
                raise ValueError("DELIVERY_SCOPE_REVISION_MISMATCH")
            if parent_binding and scoped_revision.parent_scope_revision_id not in {
                None,
                parent_binding.scope_revision_id,
            }:
                raise ValueError("DELIVERY_SCOPE_REVISION_LINEAGE_MISMATCH")

        return self._bind_delivery_in_session(
            session,
            delivery,
            req_revision_id,
            scoped_revision_id,
            now=timestamp,
        )

    def get_requirement_revision(self, requirement_revision_id: str) -> Optional[RequirementRevision]:
        with self.store.session() as session:
            row = session.get(RequirementRevisionRow, requirement_revision_id)
            return self._requirement_revision(row) if row is not None else None

    def list_requirement_revisions(self, requirement_id: str) -> List[RequirementRevision]:
        with self.store.session() as session:
            rows = session.scalars(
                select(RequirementRevisionRow)
                .where(RequirementRevisionRow.requirement_id == requirement_id)
                .order_by(RequirementRevisionRow.created_at, RequirementRevisionRow.requirement_revision_id)
            )
            return [self._requirement_revision(row) for row in rows]

    def get_scope_revision(self, scope_revision_id: str) -> Optional[ScopeRevision]:
        with self.store.session() as session:
            row = session.get(ScopeRevisionRow, scope_revision_id)
            return self._scope_revision(row) if row is not None else None

    def list_scope_revisions(self, requirement_revision_id: str) -> List[ScopeRevision]:
        with self.store.session() as session:
            rows = session.scalars(
                select(ScopeRevisionRow)
                .where(ScopeRevisionRow.requirement_revision_id == requirement_revision_id)
                .order_by(ScopeRevisionRow.created_at, ScopeRevisionRow.scope_revision_id)
            )
            return [self._scope_revision(row) for row in rows]

    def get_delivery_binding(self, delivery_id: str) -> Optional[DeliveryRevisionBinding]:
        with self.store.session() as session:
            row = session.get(DeliveryRevisionBindingRow, delivery_id)
            return self._binding(row) if row is not None else None

    def _create_requirement_revision_in_session(
        self,
        session: Session,
        value: RequirementRevision,
    ) -> None:
        if session.get(RequirementRow, value.requirement_id) is None:
            raise ValueError("REQUIREMENT_NOT_FOUND")
        if session.get(RequirementRevisionRow, value.requirement_revision_id) is not None:
            raise ValueError("REQUIREMENT_REVISION_ALREADY_EXISTS")
        duplicate = session.scalar(
            select(RequirementRevisionRow).where(
                RequirementRevisionRow.requirement_id == value.requirement_id,
                RequirementRevisionRow.revision_label == value.revision_label,
            )
        )
        if duplicate is not None:
            raise ValueError("REQUIREMENT_REVISION_LABEL_ALREADY_EXISTS")
        if value.parent_requirement_revision_id:
            parent = session.get(RequirementRevisionRow, value.parent_requirement_revision_id)
            if parent is None:
                raise ValueError("PARENT_REQUIREMENT_REVISION_NOT_FOUND")
            if parent.requirement_id != value.requirement_id:
                raise ValueError("PARENT_REQUIREMENT_REVISION_MISMATCH")
        session.add(self._requirement_revision_row(value))

    def _create_scope_revision_in_session(self, session: Session, value: ScopeRevision) -> None:
        requirement_revision = session.get(RequirementRevisionRow, value.requirement_revision_id)
        if requirement_revision is None:
            raise ValueError("REQUIREMENT_REVISION_NOT_FOUND")
        if session.get(ScopeRevisionRow, value.scope_revision_id) is not None:
            raise ValueError("SCOPE_REVISION_ALREADY_EXISTS")
        duplicate = session.scalar(
            select(ScopeRevisionRow).where(
                ScopeRevisionRow.requirement_revision_id == value.requirement_revision_id,
                ScopeRevisionRow.revision_label == value.revision_label,
            )
        )
        if duplicate is not None:
            raise ValueError("SCOPE_REVISION_LABEL_ALREADY_EXISTS")
        if value.parent_scope_revision_id:
            parent = session.get(ScopeRevisionRow, value.parent_scope_revision_id)
            if parent is None:
                raise ValueError("PARENT_SCOPE_REVISION_NOT_FOUND")
            if parent.requirement_revision_id != value.requirement_revision_id:
                parent_requirement_revision = session.get(
                    RequirementRevisionRow, parent.requirement_revision_id
                )
                if (
                    requirement_revision.parent_requirement_revision_id is None
                    or parent_requirement_revision is None
                    or requirement_revision.parent_requirement_revision_id
                    != parent_requirement_revision.requirement_revision_id
                ):
                    raise ValueError("PARENT_SCOPE_REVISION_REQUIREMENT_LINEAGE_MISMATCH")
        session.add(self._scope_revision_row(value))

    def _bind_delivery_in_session(
        self,
        session: Session,
        delivery: RequirementDeliveryRow,
        requirement_revision_id: str,
        scope_revision_id: str,
        *,
        now: Optional[int] = None,
    ) -> DeliveryRevisionBinding:
        requirement_revision = session.get(RequirementRevisionRow, requirement_revision_id)
        if requirement_revision is None:
            raise ValueError("REQUIREMENT_REVISION_NOT_FOUND")
        if requirement_revision.requirement_id != delivery.requirement_id:
            raise ValueError("DELIVERY_REQUIREMENT_REVISION_MISMATCH")
        scope_revision = session.get(ScopeRevisionRow, scope_revision_id)
        if scope_revision is None:
            raise ValueError("SCOPE_REVISION_NOT_FOUND")
        if scope_revision.requirement_revision_id != requirement_revision_id:
            raise ValueError("DELIVERY_SCOPE_REVISION_MISMATCH")
        existing = session.get(DeliveryRevisionBindingRow, delivery.delivery_id)
        incoming = DeliveryRevisionBinding(
            delivery_id=delivery.delivery_id,
            requirement_revision_id=requirement_revision_id,
            scope_revision_id=scope_revision_id,
            created_at=self._now(now),
        )
        if existing is not None:
            current = self._binding(existing)
            if (
                current.requirement_revision_id != incoming.requirement_revision_id
                or current.scope_revision_id != incoming.scope_revision_id
            ):
                raise ValueError("DELIVERY_REVISION_BINDING_IMMUTABLE")
            return current
        session.add(self._binding_row(incoming))
        return incoming

    @staticmethod
    def _requirement_revision_row(value: RequirementRevision) -> RequirementRevisionRow:
        return RequirementRevisionRow(
            requirement_revision_id=value.requirement_revision_id,
            requirement_id=value.requirement_id,
            revision_label=value.revision_label,
            parent_requirement_revision_id=value.parent_requirement_revision_id,
            created_at=int(value.created_at),
            payload=dict(value.payload),
        )

    @staticmethod
    def _requirement_revision(row: RequirementRevisionRow) -> RequirementRevision:
        return RequirementRevision(
            requirement_revision_id=row.requirement_revision_id,
            requirement_id=row.requirement_id,
            revision_label=row.revision_label,
            parent_requirement_revision_id=row.parent_requirement_revision_id,
            created_at=int(row.created_at),
            payload=dict(row.payload or {}),
        )

    @staticmethod
    def _scope_revision_row(value: ScopeRevision) -> ScopeRevisionRow:
        return ScopeRevisionRow(
            scope_revision_id=value.scope_revision_id,
            requirement_revision_id=value.requirement_revision_id,
            revision_label=value.revision_label,
            parent_scope_revision_id=value.parent_scope_revision_id,
            created_at=int(value.created_at),
            payload=dict(value.payload),
        )

    @staticmethod
    def _scope_revision(row: ScopeRevisionRow) -> ScopeRevision:
        return ScopeRevision(
            scope_revision_id=row.scope_revision_id,
            requirement_revision_id=row.requirement_revision_id,
            revision_label=row.revision_label,
            parent_scope_revision_id=row.parent_scope_revision_id,
            created_at=int(row.created_at),
            payload=dict(row.payload or {}),
        )

    @staticmethod
    def _binding_row(value: DeliveryRevisionBinding) -> DeliveryRevisionBindingRow:
        return DeliveryRevisionBindingRow(
            delivery_id=value.delivery_id,
            requirement_revision_id=value.requirement_revision_id,
            scope_revision_id=value.scope_revision_id,
            created_at=int(value.created_at),
        )

    @staticmethod
    def _binding(row: DeliveryRevisionBindingRow) -> DeliveryRevisionBinding:
        return DeliveryRevisionBinding(
            delivery_id=row.delivery_id,
            requirement_revision_id=row.requirement_revision_id,
            scope_revision_id=row.scope_revision_id,
            created_at=int(row.created_at),
        )
