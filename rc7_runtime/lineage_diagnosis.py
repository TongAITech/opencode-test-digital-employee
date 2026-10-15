"""Lineage-aware default diagnosis coordinator for autonomous execution loops."""

from __future__ import annotations

from typing import Optional

from rc6_runtime.diagnosis import AttemptHistory

from .attempt_lineage import LineageAwareAttemptHistory
from .execution_diagnosis import (
    DiagnosisClosure,
    ExecutionDiagnosisCoordinator,
    ExecutionTrustFacts,
)
from .runtime_execution import VerifiedScriptExecutionBundle
from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.preparation import PreparedAttempt


class LineageAwareExecutionDiagnosisCoordinator(ExecutionDiagnosisCoordinator):
    def __init__(self, *args, history: Optional[AttemptHistory] = None, **kwargs) -> None:
        super().__init__(
            *args,
            history=history or LineageAwareAttemptHistory(),
            **kwargs,
        )

    def diagnose(
        self,
        *,
        record: ExecutionRecord,
        bundle: VerifiedScriptExecutionBundle,
        prepared: PreparedAttempt,
        trust: Optional[ExecutionTrustFacts] = None,
    ) -> DiagnosisClosure:
        closure = super().diagnose(
            record=record,
            bundle=bundle,
            prepared=prepared,
            trust=trust,
        )
        if (
            closure.complete
            and closure.recovery is not None
            and closure.recovery.retry_allowed
            and closure.recovery.next_attempt_id
            and isinstance(self.history, LineageAwareAttemptHistory)
        ):
            self.history.reserve_successor(closure.recovery)
        return closure
