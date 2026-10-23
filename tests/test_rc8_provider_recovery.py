from rc8_runtime.provider_recovery import (
    ProviderFaultKind,
    ProviderHealth,
    RecoveryAction,
    RecoveryCheckpoint,
    RecoverySupervisor,
    RequestGovernor,
    RetryPolicy,
    SideEffectState,
    classify_provider_fault,
)


def _checkpoint(side_effect_state=SideEffectState.NONE):
    return RecoveryCheckpoint(
        checkpoint_id="cp-17",
        mission_id="mission-1",
        test_run_id="run-1",
        stage_instance_id="code-analysis-1",
        work_item_id="wi-9",
        attempt_id="attempt-4",
        input_snapshot_ref="code-snapshot:abc",
        cursor="file=Foo.java;method=submit;offset=42",
        side_effect_state=side_effect_state,
    )


def test_shared_request_governor_applies_safety_margin_before_provider_429():
    governor = RequestGovernor(max_requests=100, window_seconds=600, safety_ratio=0.90)
    for index in range(90):
        decision = governor.reserve(1000 + index)
        assert decision.allowed is True
    blocked = governor.reserve(1090)
    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.next_allowed_at == 1601
    recovered = governor.reserve(1601)
    assert recovered.allowed is True


def test_429_waits_for_capacity_without_losing_or_recreating_task():
    fault = classify_provider_fault(status_code=429, message="rate limit", retry_after_seconds=30)
    assert fault.kind == ProviderFaultKind.RATE_LIMIT
    supervisor = RecoverySupervisor()
    decision = supervisor.decide(_checkpoint(), fault, now=1000, next_capacity_at=1100)
    assert decision.action == RecoveryAction.WAITING_PROVIDER_CAPACITY
    assert decision.resume_at == 1100
    assert decision.mission_id == "mission-1"
    assert decision.work_item_id == "wi-9"
    assert decision.attempt_id == "attempt-4"
    assert decision.resume_key == "mission-1:code-analysis-1:wi-9:cp-17"
    assert decision.r1_event_type == "PROVIDER_CAPACITY_WAITING"


def test_502_and_sse_disconnect_backoff_then_wait_for_provider_recovery():
    supervisor = RecoverySupervisor(RetryPolicy(base_delay_seconds=2, max_delay_seconds=30, unavailable_after=3))
    cp = _checkpoint()
    first = supervisor.decide(cp, classify_provider_fault(status_code=502, message="bad gateway"), now=100)
    assert first.action == RecoveryAction.RETRY_BACKOFF
    assert first.resume_at == 102
    second = supervisor.decide(cp, classify_provider_fault(message="SSE ended without [DONE]"), now=102)
    assert second.action == RecoveryAction.RETRY_BACKOFF
    assert second.resume_at == 106
    third = supervisor.decide(cp, classify_provider_fault(status_code=503, message="provider unavailable"), now=106)
    assert third.action == RecoveryAction.WAITING_PROVIDER_RECOVERY
    assert third.provider_health == ProviderHealth.UNAVAILABLE
    assert third.resume_at == 114


def test_read_timeout_is_provider_fault_not_product_test_failure():
    supervisor = RecoverySupervisor()
    fault = classify_provider_fault(message="read timeout while waiting for model")
    assert fault.kind == ProviderFaultKind.READ_TIMEOUT
    decision = supervisor.decide(_checkpoint(), fault, now=200)
    assert decision.action == RecoveryAction.RETRY_BACKOFF
    assert decision.r1_event_type == "PROVIDER_RETRY_SCHEDULED"


def test_unknown_side_effect_must_reconcile_before_replay():
    supervisor = RecoverySupervisor()
    fault = classify_provider_fault(status_code=502, message="response lost")
    decision = supervisor.decide(_checkpoint(SideEffectState.UNKNOWN), fault, now=300)
    assert decision.action == RecoveryAction.RECONCILE_SIDE_EFFECT
    assert decision.resume_at is None
    assert decision.r1_event_type == "PROVIDER_SIDE_EFFECT_RECONCILIATION_REQUIRED"


def test_auth_or_invalid_request_blocks_provider_configuration_not_mission_truth():
    supervisor = RecoverySupervisor()
    decision = supervisor.decide(
        _checkpoint(),
        classify_provider_fault(status_code=401, message="token expired"),
        now=400,
    )
    assert decision.action == RecoveryAction.BLOCKED_PROVIDER_CONFIGURATION
    assert decision.provider_health == ProviderHealth.UNAVAILABLE


def test_successful_probe_recovers_provider_health():
    supervisor = RecoverySupervisor(RetryPolicy(unavailable_after=1))
    supervisor.decide(_checkpoint(), classify_provider_fault(status_code=502, message="down"), now=10)
    assert supervisor.health.state == ProviderHealth.UNAVAILABLE
    supervisor.recovered()
    assert supervisor.health.state == ProviderHealth.HEALTHY
    assert supervisor.health.consecutive_transient_failures == 0
