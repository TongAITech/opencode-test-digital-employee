from __future__ import annotations

from types import SimpleNamespace

from rc6_runtime.capability import ToolCapabilityBroker
from rc6_runtime.diagnosis import CorrelationScope
from rc6_runtime.execution import ExecutionRecord
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.execution_diagnosis import ExecutionDiagnosisCoordinator, ExecutionTrustFacts


TARGET = "TARGET-RC7-DIAGNOSIS"


def _bundle():
    return SimpleNamespace(validation=SimpleNamespace(ready=True))


def _prepared():
    return SimpleNamespace(
        status="PREPARED",
        oracle_snapshot={
            "checks": [
                {
                    "id": "CHK-1",
                    "type": "BUSINESS_RULE",
                    "actual_path": "business_code",
                    "operator": "EQ",
                    "expected": "OK",
                }
            ]
        },
    )


def _record(
    *,
    layer="L2",
    status="FAIL",
    integrity=False,
    assertion_passed=None,
    actual_result=None,
    tool_call_refs=(),
    reason="RUNTIME_FAILURE",
):
    return ExecutionRecord(
        attempt_id="ATT-RC7-DIAGNOSIS-1",
        tc_id="TC-RC7-DIAGNOSIS-1",
        case_version=1,
        target_id=TARGET,
        layer=layer,
        worker_id="runtime-worker",
        lease_id="runtime-lease",
        status=status,
        integrity_passed=integrity,
        actual_result=actual_result,
        tool_call_refs=tuple(tool_call_refs),
        evidence_refs=("EVD-EXEC-CANONICAL-1",),
        assertion_ref="oracle-assertion://1" if assertion_passed is not None else None,
        assertion_passed=assertion_passed,
        reason=reason,
    )


def _runtime(tmp_path, *, broker=None, cat_query=None):
    return ExecutionDiagnosisCoordinator(
        authority=RC7AuthorityRuntime(b"0123456789abcdef0123456789abcdef"),
        tool_broker=broker or ToolCapabilityBroker(),
        evidence_root=str(tmp_path / "diagnosis-evidence"),
        cat_query=cat_query,
    )


def test_script_load_failure_is_classified_and_repaired_without_external_injection(tmp_path):
    coordinator = _runtime(tmp_path)
    closure = coordinator.diagnose(
        record=_record(layer="L2", reason="IMPORT_ERROR"),
        bundle=_bundle(),
        prepared=_prepared(),
        trust=ExecutionTrustFacts(exception_type="ImportError"),
    )

    assert closure.complete is True
    assert closure.diagnosis is not None
    assert closure.diagnosis.failure_class == "SCRIPT"
    assert closure.recovery is not None
    assert closure.recovery.action == "REPAIR_SCRIPT"
    assert closure.recovery.retry_allowed is True
    assert closure.evidence_ref is not None
    assert closure.evidence_sha256 is not None


def test_l3_failure_without_required_cat_correlation_fails_closed(tmp_path):
    coordinator = _runtime(tmp_path)
    closure = coordinator.diagnose(
        record=_record(
            layer="L3",
            integrity=True,
            assertion_passed=False,
            actual_result={
                "business_code": "BAD",
                "_http": {
                    "status_code": 200,
                    "target_url": "https://example.invalid/cfg-data/apply",
                    "receipt_id": "APIREC-1",
                },
            },
            tool_call_refs=("api-runtime://APIREC-1",),
            reason="ORACLE_ASSERTION_FAILED",
        ),
        bundle=_bundle(),
        prepared=_prepared(),
        trust=ExecutionTrustFacts(
            auth_verified=True,
            route_verified=True,
            tool_verified=True,
            environment_verified=True,
            dependency_verified=True,
        ),
    )

    assert closure.complete is False
    assert closure.diagnosis is None
    assert closure.recovery is None
    assert closure.unavailable_reason == "CAT_CORRELATION_SCOPE_REQUIRED"


def test_product_defect_requires_complete_runtime_trust_and_cat_proof(tmp_path):
    broker = ToolCapabilityBroker()
    broker.discover("cat", "qualification://cat")
    broker.mark_executable("cat", "executable://cat")
    broker.register("cat", "registration://cat")
    broker.record_probe(
        "cat",
        success=True,
        tool_call_ref="toolcall://cat/probe",
        evidence_ref="evidence://cat/probe",
    )
    broker.mark_target_ready("cat", TARGET, "evidence://cat/target-ready")

    def cat_query(scope, context):
        return {
            "tool_call_ref": "toolcall://cat/%s" % context.attempt_id,
            "evidence_ref": "evidence://cat/%s" % context.attempt_id,
            "signals": {"trace_id": scope.trace_id, "product_error": True},
        }

    coordinator = _runtime(tmp_path, broker=broker, cat_query=cat_query)
    closure = coordinator.diagnose(
        record=_record(
            layer="L3",
            integrity=True,
            assertion_passed=False,
            actual_result={
                "business_code": "BAD",
                "_http": {
                    "status_code": 200,
                    "target_url": "https://example.invalid/cfg-data/apply",
                    "receipt_id": "APIREC-2",
                },
            },
            tool_call_refs=("api-runtime://APIREC-2",),
            reason="ORACLE_ASSERTION_FAILED",
        ),
        bundle=_bundle(),
        prepared=_prepared(),
        trust=ExecutionTrustFacts(
            auth_verified=True,
            route_verified=True,
            tool_verified=True,
            environment_verified=True,
            dependency_verified=True,
            correlation=CorrelationScope(
                applications=("cfg-center", "cfg-data"),
                window_start=1000,
                window_end=1060,
                trace_id="trace-rc7-1",
            ),
        ),
    )

    assert closure.complete is True
    assert closure.diagnosis is not None
    assert closure.diagnosis.failure_class == "PRODUCT"
    assert closure.diagnosis.cat_required is True
    assert closure.diagnosis.cat_queried is True
    assert closure.recovery is not None
    assert closure.recovery.action == "PRODUCT_DEFECT"
    assert closure.recovery.terminal is True
    assert closure.recovery.retry_allowed is False
