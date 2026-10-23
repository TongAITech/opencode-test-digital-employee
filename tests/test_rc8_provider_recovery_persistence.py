from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from rc8_center.infrastructure.postgres import Base, PostgresStore
from rc8_center.infrastructure.postgres_provider_recovery import PostgresProviderRecoveryCheckpointRepository
from rc8_center.provider_recovery_service import ProviderRecoveryService
from rc8_runtime.provider_recovery import RecoveryAction, RecoveryCheckpoint, SideEffectState


def _store():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, PostgresStore(engine)


def _checkpoint(checkpoint_id="cp-1", cursor="step:3", side_effect_state=SideEffectState.NONE):
    return RecoveryCheckpoint(
        checkpoint_id=checkpoint_id,
        mission_id="mission-1",
        test_run_id="run-1",
        stage_instance_id="stage-code-analysis",
        work_item_id="work-1",
        attempt_id="attempt-1",
        input_snapshot_ref="snapshot-abc",
        cursor=cursor,
        side_effect_state=side_effect_state,
        completed_effect_refs=("effect-1",),
    )


def test_restart_and_model_failover_preserve_durable_identity_and_cursor():
    engine, store = _store()
    ProviderRecoveryService(PostgresProviderRecoveryCheckpointRepository(store)).checkpoint_before_request(
        _checkpoint(), provider_ref="bankgpt-provider", model_ref="bankgpt", now=100
    )
    plans = ProviderRecoveryService(
        PostgresProviderRecoveryCheckpointRepository(PostgresStore(engine))
    ).startup_reconcile(target_provider_ref="dsv4-provider", target_model_ref="dsv4")
    assert len(plans) == 1
    plan = plans[0]
    assert plan.action == RecoveryAction.CONTINUE
    assert plan.checkpoint.mission_id == "mission-1"
    assert plan.checkpoint.stage_instance_id == "stage-code-analysis"
    assert plan.checkpoint.work_item_id == "work-1"
    assert plan.checkpoint.attempt_id == "attempt-1"
    assert plan.checkpoint.cursor == "step:3"
    assert plan.source_model_ref == "bankgpt"
    assert plan.target_model_ref == "dsv4"
    assert plan.resume_key == _checkpoint().resume_key


def test_unknown_side_effect_never_blindly_replays_after_restart():
    engine, store = _store()
    ProviderRecoveryService(PostgresProviderRecoveryCheckpointRepository(store)).checkpoint_before_request(
        _checkpoint(side_effect_state=SideEffectState.UNKNOWN), provider_ref="bankgpt-provider", model_ref="bankgpt", now=100
    )
    plans = ProviderRecoveryService(
        PostgresProviderRecoveryCheckpointRepository(PostgresStore(engine))
    ).startup_reconcile(target_provider_ref="dsv4-provider", target_model_ref="dsv4")
    assert plans[0].action == RecoveryAction.RECONCILE_SIDE_EFFECT
    assert plans[0].r1_event_type == "PROVIDER_SIDE_EFFECT_RECONCILIATION_REQUIRED"


def test_newer_checkpoint_supersedes_older_cursor_and_completion_removes_resume_candidate():
    engine, store = _store()
    repo = PostgresProviderRecoveryCheckpointRepository(store)
    service = ProviderRecoveryService(repo)
    service.checkpoint_before_request(_checkpoint("cp-1", "step:3"), provider_ref="bankgpt-provider", model_ref="bankgpt", now=100)
    service.checkpoint_before_request(_checkpoint("cp-2", "step:4"), provider_ref="bankgpt-provider", model_ref="bankgpt", now=101)
    assert repo.get("cp-1").close_reason == "SUPERSEDED_BY_NEWER_CHECKPOINT"
    assert repo.latest_open_for_work_item("work-1").checkpoint.cursor == "step:4"
    service.complete_checkpoint("cp-2", now=102)
    assert repo.latest_open_for_work_item("work-1") is None
