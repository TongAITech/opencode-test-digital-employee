"""Append-only attempt lineage for governed RC7 retries.

A successor id may be planned before it executes, but a planned retry is not an
execution attempt and must not be inserted into AttemptHistory as if it had
already run.  This adapter stores only the parent reservation; when the real
ExecutionRecord arrives its history entry is appended once with the reserved
parent.  Retry counting can then walk the real parent chain and exhaust budget.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, Optional

from rc6_runtime.diagnosis import (
    AttemptHistory,
    AttemptHistoryEntry,
    DiagnosisContractError,
    RecoveryDecision,
)


class LineageAwareAttemptHistory(AttemptHistory):
    def __init__(self) -> None:
        super().__init__()
        self._planned_parent: Dict[str, str] = {}

    def reserve_successor(self, decision: RecoveryDecision) -> None:
        successor = decision.next_attempt_id
        if not decision.retry_allowed:
            raise DiagnosisContractError("SUCCESSOR_RESERVATION_REQUIRES_RETRY_PERMISSION")
        if decision.terminal:
            raise DiagnosisContractError("TERMINAL_RECOVERY_CANNOT_RESERVE_SUCCESSOR")
        if not isinstance(successor, str) or not successor:
            raise DiagnosisContractError("RECOVERY_SUCCESSOR_ATTEMPT_REQUIRED")
        if successor == decision.attempt_id:
            raise DiagnosisContractError("RECOVERY_SUCCESSOR_MUST_BE_NEW_ATTEMPT")
        if self.get(decision.attempt_id) is None:
            raise DiagnosisContractError("PARENT_ATTEMPT_NOT_RECORDED")
        existing = self._planned_parent.get(successor)
        if existing is not None and existing != decision.attempt_id:
            raise DiagnosisContractError("SUCCESSOR_PARENT_IMMUTABLE")
        if self.get(successor) is not None:
            raise DiagnosisContractError("SUCCESSOR_ATTEMPT_ALREADY_EXECUTED")
        self._planned_parent[successor] = decision.attempt_id

    def planned_parent(self, attempt_id: str) -> Optional[str]:
        return self._planned_parent.get(attempt_id)

    def append_execution(self, entry: AttemptHistoryEntry) -> None:
        parent = self._planned_parent.get(entry.attempt_id)
        if parent is not None:
            if entry.parent_attempt_id not in {None, parent}:
                raise DiagnosisContractError("EXECUTION_PARENT_MISMATCH")
            entry = replace(entry, parent_attempt_id=parent)
        super().append(entry)
        self._planned_parent.pop(entry.attempt_id, None)
