from __future__ import annotations

import pytest

from rc8_runtime.contracts import RC8ContractError
from rc8_runtime.provider_recovery import RecoveryCheckpoint, SideEffectState
from rc8_runtime.recovery_store import PostgreSQLRecoveryCheckpointStore
from rc8_runtime.startup_recovery import StartupRecoveryCoordinator


def checkpoint(checkpoint_id, state):
    return RecoveryCheckpoint(
        checkpoint_id=checkpoint_id,
        mission_id="mission-1",
        test_run_id="run-1",
        stage_instance_id="stage-1",
        work_item_id="work-1",
        attempt_id="attempt-1",
        input_snapshot_ref="snapshot:abc",
        cursor="cursor:7",
        side_effect_state=state,
        completed_effect_refs=("evidence:1",),
    )


class FakeStore:
    def __init__(self, items):
        self.items = list(items)

    def load_open(self):
        return list(self.items)

    @staticmethod
    def startup_reconciliation(items):
        return PostgreSQLRecoveryCheckpointStore.startup_reconciliation(items)


def test_startup_resumes_exact_original_identity_and_emits_r1_event():
    item = checkpoint("ckpt-resume", SideEffectState.CONFIRMED_NOT_APPLIED)
    resumed = []
    reconciled = []
    events = []
    coordinator = StartupRecoveryCoordinator(
        FakeStore([item]),
        resume_same_work_item=resumed.append,
        reconcile_side_effect=reconciled.append,
        emit_r1_event=events.append,
    )

    dispatches = coordinator.recover_on_startup()

    assert resumed == [item]
    assert reconciled == []
    assert len(dispatches) == 1
    dispatch = dispatches[0]
    assert dispatch.mission_id == item.mission_id
    assert dispatch.test_run_id == item.test_run_id
    assert dispatch.stage_instance_id == item.stage_instance_id
    assert dispatch.work_item_id == item.work_item_id
    assert dispatch.attempt_id == item.attempt_id
    assert dispatch.input_snapshot_ref == item.input_snapshot_ref
    assert dispatch.resume_key == item.resume_key
    assert dispatch.r1_event_type == "PROVIDER_STARTUP_RESUME_SCHEDULED"
    assert events == dispatches


def test_unknown_side_effect_is_reconciled_and_never_replayed():
    item = checkpoint("ckpt-unknown", SideEffectState.UNKNOWN)
    resumed = []
    reconciled = []
    coordinator = StartupRecoveryCoordinator(
        FakeStore([item]),
        resume_same_work_item=resumed.append,
        reconcile_side_effect=reconciled.append,
    )

    dispatch = coordinator.recover_on_startup()[0]

    assert resumed == []
    assert reconciled == [item]
    assert dispatch.r1_event_type == "PROVIDER_SIDE_EFFECT_RECONCILIATION_REQUIRED"


def test_duplicate_resume_identity_fails_closed_before_second_dispatch():
    item = checkpoint("ckpt-1", SideEffectState.CONFIRMED_NOT_APPLIED)
    resumed = []
    coordinator = StartupRecoveryCoordinator(
        FakeStore([item, item]),
        resume_same_work_item=resumed.append,
        reconcile_side_effect=lambda value: None,
    )

    with pytest.raises(RC8ContractError, match="DUPLICATE_STARTUP_RECOVERY_IDENTITY"):
        coordinator.recover_on_startup()

    assert resumed == [item]
