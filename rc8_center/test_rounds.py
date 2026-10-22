"""Formal test-round model for one production-date testing cycle.

Business invariants (do not collapse these concepts):
- ProductionBatch is the production date/window.
- RequirementDelivery is a requirement's participation in that production date.
- TestRound is one testing round inside the same production date.
- Multiple TestRounds never imply another ProductionBatch or another requirement delivery.
- A requirement can finish in one production date after many TestRounds, or continue
  into a later production date through another RequirementDelivery.
- Historical rounds are append-only facts; a later round does not overwrite an earlier one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class TestRoundState(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


TERMINAL_TEST_ROUND_STATES = {
    TestRoundState.COMPLETED,
    TestRoundState.CANCELLED,
}


_ALLOWED_TEST_ROUND_TRANSITIONS = {
    TestRoundState.PLANNED: {TestRoundState.ACTIVE, TestRoundState.CANCELLED},
    TestRoundState.ACTIVE: {TestRoundState.COMPLETED, TestRoundState.CANCELLED},
    TestRoundState.COMPLETED: set(),
    TestRoundState.CANCELLED: set(),
}


@dataclass(frozen=True)
class TestRound:
    test_round_id: str
    production_batch_id: str
    round_no: int
    name: str = ""
    state: TestRoundState = TestRoundState.PLANNED
    created_at: int = 0
    started_at: Optional[int] = None
    completed_at: Optional[int] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.test_round_id or "").strip():
            raise ValueError("TEST_ROUND_ID_REQUIRED")
        if not str(self.production_batch_id or "").strip():
            raise ValueError("PRODUCTION_BATCH_ID_REQUIRED")
        if int(self.round_no) <= 0:
            raise ValueError("TEST_ROUND_NO_MUST_BE_POSITIVE")

    def transition_to(self, target: TestRoundState, *, now: Optional[int] = None) -> "TestRound":
        target = TestRoundState(target)
        if target == self.state:
            return self
        if target not in _ALLOWED_TEST_ROUND_TRANSITIONS[self.state]:
            raise ValueError(
                "TEST_ROUND_TERMINAL_STATE_IMMUTABLE"
                if self.state in TERMINAL_TEST_ROUND_STATES
                else "TEST_ROUND_STATE_TRANSITION_INVALID"
            )
        timestamp = int(now if now is not None else self.created_at)
        started_at = self.started_at
        completed_at = self.completed_at
        if target == TestRoundState.ACTIVE and started_at is None:
            started_at = timestamp
        if target in TERMINAL_TEST_ROUND_STATES:
            completed_at = timestamp
        return TestRound(
            test_round_id=self.test_round_id,
            production_batch_id=self.production_batch_id,
            round_no=self.round_no,
            name=self.name,
            state=target,
            created_at=self.created_at,
            started_at=started_at,
            completed_at=completed_at,
            payload=dict(self.payload),
        )


@dataclass(frozen=True)
class TestRoundDelivery:
    """A requirement delivery selected into a testing round.

    The same delivery may appear in many TestRounds of the same production date.
    Cross-production-date attachment is forbidden by the repository boundary.
    """

    round_delivery_id: str
    test_round_id: str
    delivery_id: str
    included_at: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.round_delivery_id or "").strip():
            raise ValueError("TEST_ROUND_DELIVERY_ID_REQUIRED")
        if not str(self.test_round_id or "").strip():
            raise ValueError("TEST_ROUND_ID_REQUIRED")
        if not str(self.delivery_id or "").strip():
            raise ValueError("REQUIREMENT_DELIVERY_ID_REQUIRED")
