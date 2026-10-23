from __future__ import annotations

import os

from sqlalchemy import inspect

from rc8_center.infrastructure.postgres import PostgresStore, build_engine
from rc8_center.infrastructure.postgres_provider_recovery import PostgresProviderRecoveryCheckpointRepository
from rc8_center.provider_recovery_service import ProviderRecoveryService
from rc8_runtime.provider_recovery import RecoveryAction, RecoveryCheckpoint, SideEffectState


def main() -> int:
    database_url = os.environ.get("RC8_DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("RC8_DATABASE_URL_REQUIRED")
    engine = build_engine(database_url)
    assert "rc8_provider_recovery_checkpoint" in set(inspect(engine).get_table_names())
    source_service = ProviderRecoveryService(PostgresProviderRecoveryCheckpointRepository(PostgresStore(engine)))
    checkpoint = RecoveryCheckpoint(
        checkpoint_id="pg-provider-cp-1",
        mission_id="pg-mission-1",
        test_run_id="pg-run-1",
        stage_instance_id="pg-stage-1",
        work_item_id="pg-work-1",
        attempt_id="pg-attempt-1",
        input_snapshot_ref="pg-snapshot-1",
        cursor="code-analysis:graph-query-complete",
        side_effect_state=SideEffectState.CONFIRMED_NOT_APPLIED,
        completed_effect_refs=("graph-evidence-1",),
    )
    source_service.checkpoint_before_request(checkpoint, provider_ref="bankgpt-provider", model_ref="bankgpt", now=1000)
    engine.dispose()

    restarted_engine = build_engine(database_url)
    restarted_repo = PostgresProviderRecoveryCheckpointRepository(PostgresStore(restarted_engine))
    restarted_service = ProviderRecoveryService(restarted_repo)
    plans = restarted_service.startup_reconcile(target_provider_ref="dsv4-provider", target_model_ref="dsv4", test_run_id="pg-run-1")
    assert len(plans) == 1
    plan = plans[0]
    assert plan.action == RecoveryAction.CONTINUE
    assert plan.checkpoint == checkpoint
    assert plan.source_model_ref == "bankgpt"
    assert plan.target_model_ref == "dsv4"
    assert plan.checkpoint.cursor == "code-analysis:graph-query-complete"
    restarted_service.complete_checkpoint("pg-provider-cp-1", now=1001)
    assert restarted_repo.list_open(test_run_id="pg-run-1") == []
    restarted_engine.dispose()

    print("RC8_PROVIDER_RECOVERY_REAL_POSTGRES_RESTART_PASS")
    print("BANK_REALITY_VERIFIED=NO")
    print("TEST_SUFFICIENT=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
