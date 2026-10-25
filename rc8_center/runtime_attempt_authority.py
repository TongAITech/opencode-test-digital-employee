from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class RuntimeAttemptAuthorityError(RuntimeError):
    """Raised when evidence is not owned by the current runtime attempt."""


@dataclass(frozen=True)
class RuntimeAttemptAuthoritySnapshot:
    work_item_id: str
    attempt_id: str
    producer_node_id: str
    attempt_started_at: int
    lease_owner_node_id: str
    lease_expires_at: int
    superseded: bool = False

    def __post_init__(self) -> None:
        for name in ("work_item_id", "attempt_id", "producer_node_id", "lease_owner_node_id"):
            if not str(getattr(self, name) or "").strip():
                raise RuntimeAttemptAuthorityError("%s_REQUIRED" % name.upper())
        if int(self.attempt_started_at) < 0:
            raise RuntimeAttemptAuthorityError("ATTEMPT_STARTED_AT_INVALID")
        if int(self.lease_expires_at) < int(self.attempt_started_at):
            raise RuntimeAttemptAuthorityError("LEASE_WINDOW_INVALID")


@dataclass(frozen=True)
class RuntimeEvidenceAuthorityContext:
    work_item_id: str
    attempt_id: str
    producer_node_id: str
    observed_at: int


class RuntimeAttemptAuthority:
    """Center-side N3 authority for accepting runtime evidence.

    The caller must build ``current`` from Center runtime truth (current WorkItem,
    current Attempt and current lease), never from worker supplied payload.  This
    object deliberately has no 'best effort' path: stale/superseded attempts,
    failover nodes, future-dated observations, and observations outside the
    active attempt/lease window are rejected deterministically.
    """

    @staticmethod
    def authorize(
        *,
        current: RuntimeAttemptAuthoritySnapshot,
        evidence: RuntimeEvidenceAuthorityContext,
        now: Optional[int] = None,
    ) -> None:
        if current.superseded:
            raise RuntimeAttemptAuthorityError("ATTEMPT_SUPERSEDED")
        if evidence.work_item_id != current.work_item_id:
            raise RuntimeAttemptAuthorityError("WORK_ITEM_AUTHORITY_MISMATCH")
        if evidence.attempt_id != current.attempt_id:
            raise RuntimeAttemptAuthorityError("STALE_ATTEMPT_EVIDENCE_REJECTED")
        if evidence.producer_node_id != current.producer_node_id:
            raise RuntimeAttemptAuthorityError("ATTEMPT_PRODUCER_MISMATCH")
        if evidence.producer_node_id != current.lease_owner_node_id:
            raise RuntimeAttemptAuthorityError("LEASE_OWNER_MISMATCH")
        observed_at = int(evidence.observed_at)
        if observed_at < int(current.attempt_started_at):
            raise RuntimeAttemptAuthorityError("EVIDENCE_PREDATES_ATTEMPT")
        if observed_at > int(current.lease_expires_at):
            raise RuntimeAttemptAuthorityError("EVIDENCE_AFTER_LEASE_EXPIRY")
        effective_now = int(observed_at if now is None else now)
        if now is not None and observed_at > effective_now:
            # Runtime observations are worker supplied. They may not move the
            # Center clock forward to manufacture an apparently valid lease
            # window or bypass freshness checks.
            raise RuntimeAttemptAuthorityError("EVIDENCE_FROM_FUTURE")
        if effective_now < int(current.attempt_started_at):
            raise RuntimeAttemptAuthorityError("ATTEMPT_NOT_STARTED")
        if effective_now > int(current.lease_expires_at):
            raise RuntimeAttemptAuthorityError("LEASE_EXPIRED")
