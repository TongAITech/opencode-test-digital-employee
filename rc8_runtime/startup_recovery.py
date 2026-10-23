"""Non-LLM startup reconciliation for durable RC8 provider recovery.

This coordinator is intentionally deterministic.  On process start it loads the
PostgreSQL authority, preserves the original Mission/TestRun/Stage/WorkItem/
Attempt identity, and either reclaims that exact work item or routes an unknown
external side effect to reconciliation before any replay.

Python 3.8 compatible.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Protocol

from .contracts import RC8ContractError
from .provider_recovery import RecoveryCheckpoint
from .recovery_store import StartupRecoveryAction, StartupRecoveryRecord


class RecoveryStore(Protocol):
    def load_open(self) -> List[RecoveryCheckpoint]:
        ...

    @staticmethod
    def startup_reconciliation(
        checkpoints: Iterable[RecoveryCheckpoint],
    ) -> List[StartupRecoveryRecord]:
        ...


@dataclass(frozen=True)
class StartupRecoveryDispatch:
    checkpoint_id: str
    mission_id: str
    test_run_id: str
    stage_instance_id: str
    work_item_id: str
    attempt_id: str
    input_snapshot_ref: str
    resume_key: str
    action: StartupRecoveryAction
    r1_event_type: str


class StartupRecoveryCoordinator:
    """Rehydrate unfinished provider work without consulting an LLM.

    ``resume_same_work_item`` and ``reconcile_side_effect`` are runtime-owned
    callbacks.  They receive the original checkpoint; creating a replacement
    Mission/Stage/WorkItem/Attempt is outside this coordinator and forbidden by
    contract.  A checkpoint with UNKNOWN side effects is never sent to resume.
    """

    def __init__(
        self,
        store: RecoveryStore,
        *,
        resume_same_work_item: Callable[[RecoveryCheckpoint], None],
        reconcile_side_effect: Callable[[RecoveryCheckpoint], None],
        emit_r1_event: Optional[Callable[[StartupRecoveryDispatch], None]] = None,
    ) -> None:
        if store is None:
            raise RC8ContractError("STARTUP_RECOVERY_STORE_REQUIRED")
        if not callable(resume_same_work_item):
            raise RC8ContractError("STARTUP_RECOVERY_RESUME_CALLBACK_REQUIRED")
        if not callable(reconcile_side_effect):
            raise RC8ContractError("STARTUP_RECOVERY_RECONCILE_CALLBACK_REQUIRED")
        if emit_r1_event is not None and not callable(emit_r1_event):
            raise RC8ContractError("STARTUP_RECOVERY_EVENT_CALLBACK_INVALID")
        self.store = store
        self.resume_same_work_item = resume_same_work_item
        self.reconcile_side_effect = reconcile_side_effect
        self.emit_r1_event = emit_r1_event

    def recover_on_startup(self) -> List[StartupRecoveryDispatch]:
        checkpoints = self.store.load_open()
        records = self.store.startup_reconciliation(checkpoints)
        dispatches = []
        seen_resume_keys = set()

        for record in records:
            checkpoint = record.checkpoint
            if checkpoint.resume_key in seen_resume_keys:
                raise RC8ContractError("DUPLICATE_STARTUP_RECOVERY_IDENTITY")
            seen_resume_keys.add(checkpoint.resume_key)

            if record.action == StartupRecoveryAction.RECONCILE_SIDE_EFFECT:
                event_type = "PROVIDER_SIDE_EFFECT_RECONCILIATION_REQUIRED"
                self.reconcile_side_effect(checkpoint)
            elif record.action == StartupRecoveryAction.RESUME_SAME_WORK_ITEM:
                event_type = "PROVIDER_STARTUP_RESUME_SCHEDULED"
                self.resume_same_work_item(checkpoint)
            else:
                raise RC8ContractError("STARTUP_RECOVERY_ACTION_UNSUPPORTED")

            dispatch = StartupRecoveryDispatch(
                checkpoint_id=checkpoint.checkpoint_id,
                mission_id=checkpoint.mission_id,
                test_run_id=checkpoint.test_run_id,
                stage_instance_id=checkpoint.stage_instance_id,
                work_item_id=checkpoint.work_item_id,
                attempt_id=checkpoint.attempt_id,
                input_snapshot_ref=checkpoint.input_snapshot_ref,
                resume_key=checkpoint.resume_key,
                action=record.action,
                r1_event_type=event_type,
            )
            dispatches.append(dispatch)
            if self.emit_r1_event is not None:
                self.emit_r1_event(dispatch)

        return dispatches
