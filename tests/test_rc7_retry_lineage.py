from __future__ import annotations

from types import SimpleNamespace

from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.execution import ExecutionRecord
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.lineage_diagnosis import LineageAwareExecutionDiagnosisCoordinator
from rc7_runtime.execution_diagnosis import ExecutionTrustFacts


TARGET = "TARGET-RETRY-LINEAGE"


def _bundle():
    return SimpleNamespace(validation=SimpleNamespace(ready=True))


def _prepared(attempt_id):
    return SimpleNamespace(
        status="PREPARED",
        attempt_id=attempt_id,
        tc_id="TC-RETRY-LINEAGE",
        case_version=1,
        target_id=TARGET,
        oracle_snapshot={
            "checks": [
                {
                    "id": "CHK-1",
                    "type": "BUSINESS_RULE",
                    "actual_path": "code",
                    "operator": "EQ",
                    "expected": "OK",
                }
            ]
        },
    )


def _record(attempt_id):
    return ExecutionRecord(
        attempt_id=attempt_id,
        tc_id="TC-RETRY-LINEAGE",
        case_version=1,
        target_id=TARGET,
        layer="L2",
        worker_id="runtime-worker",
        lease_id="runtime-lease",
        status="FAIL",
        integrity_passed=False,
        actual_result=None,
        tool_call_refs=(),
        evidence_refs=("EVD-%s" % attempt_id,),
        assertion_ref=None,
        assertion_passed=None,
        reason="TIMEOUT",
    )


def test_transient_retry_lineage_exhausts_budget_without_fake_planned_attempts(tmp_path):
    coordinator = LineageAwareExecutionDiagnosisCoordinator(
        authority=RC7AuthorityRuntime(b"0123456789abcdef0123456789abcdef"),
        tool_broker=ToolCapabilityBroker(),
        evidence_root=str(tmp_path / "diag"),
        max_transient_retries=2,
    )

    first = coordinator.diagnose(
        record=_record("ATT-ROOT"),
        bundle=_bundle(),
        prepared=_prepared("ATT-ROOT"),
        trust=ExecutionTrustFacts(exception_type="TimeoutError"),
    )
    assert first.complete is True
    assert first.recovery is not None
    assert first.recovery.action == "RETRY_SAME_STEP"
    assert first.recovery.retry_allowed is True
    second_id = first.recovery.next_attempt_id
    assert second_id
    assert coordinator.history.get(second_id) is None

    second = coordinator.diagnose(
        record=_record(second_id),
        bundle=_bundle(),
        prepared=_prepared(second_id),
        trust=ExecutionTrustFacts(exception_type="TimeoutError"),
    )
    assert second.complete is True
    assert coordinator.history.get(second_id).parent_attempt_id == "ATT-ROOT"
    assert coordinator.history.retry_count(second_id) == 1
    assert second.recovery is not None
    assert second.recovery.action == "RETRY_SAME_STEP"
    third_id = second.recovery.next_attempt_id
    assert third_id
    assert coordinator.history.get(third_id) is None

    third = coordinator.diagnose(
        record=_record(third_id),
        bundle=_bundle(),
        prepared=_prepared(third_id),
        trust=ExecutionTrustFacts(exception_type="TimeoutError"),
    )
    assert third.complete is True
    assert coordinator.history.get(third_id).parent_attempt_id == second_id
    assert coordinator.history.retry_count(third_id) == 2
    assert third.recovery is not None
    assert third.recovery.action == "RETRY_BUDGET_EXHAUSTED"
    assert third.recovery.retry_allowed is False
    assert third.recovery.terminal is True
    assert third.recovery.next_attempt_id is None
    assert third.work_plan is not None
    assert third.work_plan.mode == "TERMINAL"
    assert third.work_plan.target_node == "RUNTIME"
