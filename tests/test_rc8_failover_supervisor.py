import pytest

from rc8_runtime.contracts import RC8ContractError
from rc8_runtime.failover_supervisor import DeterministicFailoverSupervisor, ProviderRoute
from rc8_runtime.provider_recovery import RecoveryCheckpoint, SideEffectState


def checkpoint(side_effect_state=SideEffectState.NONE):
    return RecoveryCheckpoint(
        checkpoint_id="cp-1", mission_id="mission-1", test_run_id="run-1",
        stage_instance_id="stage-1", work_item_id="work-1", attempt_id="attempt-1",
        input_snapshot_ref="snapshot-1", cursor="cursor-1", side_effect_state=side_effect_state,
    )


def test_failover_changes_route_not_durable_identity():
    cp = checkpoint()
    supervisor = DeterministicFailoverSupervisor([
        ProviderRoute("bankgpt", "primary", 0),
        ProviderRoute("dsv4", "fallback", 1),
    ])
    dispatch = supervisor.select(cp, failed_provider_id="bankgpt", failed_model_id="primary")
    assert dispatch.provider_id == "dsv4"
    assert dispatch.model_id == "fallback"
    assert dispatch.checkpoint is cp
    assert dispatch.checkpoint.resume_key == cp.resume_key
    assert dispatch.checkpoint.mission_id == "mission-1"
    assert dispatch.checkpoint.stage_instance_id == "stage-1"
    assert dispatch.checkpoint.work_item_id == "work-1"
    assert dispatch.checkpoint.attempt_id == "attempt-1"


def test_unknown_side_effect_must_reconcile_before_failover():
    supervisor = DeterministicFailoverSupervisor([ProviderRoute("dsv4", "fallback", 0)])
    with pytest.raises(RC8ContractError, match="SIDE_EFFECT_RECONCILIATION_REQUIRED_BEFORE_FAILOVER"):
        supervisor.select(checkpoint(SideEffectState.UNKNOWN), failed_provider_id="bankgpt")


def test_no_healthy_route_fails_closed():
    supervisor = DeterministicFailoverSupervisor([ProviderRoute("bankgpt", "primary", 0)])
    with pytest.raises(RC8ContractError, match="NO_HEALTHY_PROVIDER_FAILOVER_ROUTE"):
        supervisor.select(checkpoint(), failed_provider_id="bankgpt", failed_model_id="primary")
