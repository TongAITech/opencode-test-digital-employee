from __future__ import annotations

from dataclasses import replace

import pytest

from rc6_runtime.diagnosis import DiagnosisResult, FailureContext, FailureSignature, RecoveryDecision
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.recovery_adapters import (
    AuthRecoveryAdapter,
    ExecutableSpecRepairAdapter,
    RecoveryAdapterError,
    RecoveryAdapterRegistry,
    RouteRecoveryAdapter,
)


def context():
    return FailureContext(
        attempt_id="ATT-1", tc_id="TC-1", case_version=1, target_id="TARGET-1", layer="L3",
        execution_status="FAIL", preparation_verified=True, real_action_executed=True,
        assertion_failed=True, execution_evidence_refs=("evidence://fail",),
    )


def diagnosis(failure_class):
    ctx = context()
    return DiagnosisResult(
        diagnosis_id="DIAG-1", attempt_id=ctx.attempt_id, failure_class=failure_class,
        evidence_refs=("evidence://diag",), cat_required=False, cat_queried=False,
        rationale="qualified", classifier_ref="classifier://v1",
        failure_signature=FailureSignature.from_context(ctx),
    )


def decision(action):
    return RecoveryDecision("DIAG-1", "ATT-1", action, True, False, False, "ATT-2", action)


def test_route_adapter_executes_side_effect_and_verifies(tmp_path):
    binding = tmp_path / "route.txt"
    binding.write_text("/wrong", encoding="utf-8")

    def reconcile(ctx, diag):
        binding.write_text("/ok", encoding="utf-8")
        return {"binding_ref": "cfg-data/ok", "evidence_ref": "route-evidence://reconciled"}

    adapter = RouteRecoveryAdapter(
        reconcile=reconcile,
        verify=lambda result: binding.read_text(encoding="utf-8").strip() == "/ok",
    )
    result = adapter(context(), diagnosis("ROUTE"), decision("RECONCILE_ROUTE_BINDING"))
    assert result["verified"] is True
    assert result["output_refs"] == ["route-binding://cfg-data/ok"]
    assert binding.read_text(encoding="utf-8").strip() == "/ok"


def test_auth_adapter_rejects_secret_material_and_only_returns_refs():
    bad = AuthRecoveryAdapter(
        authenticate=lambda ctx, diag: {"session_ref": "session-1", "evidence_ref": "auth-evidence://1", "token": "should-never-persist"},
        verify=lambda result: True,
    )
    with pytest.raises(RecoveryAdapterError, match="AUTH_SECRET_MUST_NOT_ENTER_RECOVERY_ARTIFACT"):
        bad(context(), diagnosis("AUTH"), decision("REAUTH"))

    good = AuthRecoveryAdapter(
        authenticate=lambda ctx, diag: {"session_ref": "4a-session-ref-1", "evidence_ref": "evidence://4a/verified"},
        verify=lambda result: result["session_ref"].startswith("4a-session-ref"),
    )
    result = good(context(), diagnosis("AUTH"), decision("REAUTH"))
    assert result["verified"] is True
    assert result["output_refs"] == ["auth-evidence://4a-session-ref-1"]


def test_spec_repair_cannot_silently_change_oracle():
    case = {
        "tc_id": "TC-1", "case_version": 1, "release_id": "R1", "requirement_id": "REQ-1",
        "sst_id": None, "layer": "L3", "preconditions": [], "test_data": {},
        "steps": ["call"], "expected": "code=0000", "oracle": {"field": "code", "value": "0000"},
        "evidence_requirements": ["response"], "status": "FROZEN",
    }
    spec = ExecutableSpecBuilder().build(
        case=case, target_requirements=("TARGET",), test_data_refs=(), oracle_refs=("oracle://1",),
        cleanup_policy={"mode": "NONE"}, runner_type="PYTEST", automation_mapping={},
    )
    tampered = replace(spec, spec_id="XSPEC-2", oracle_fingerprint="tampered")
    adapter = ExecutableSpecRepairAdapter(
        current_spec=spec, rebuilder=lambda old, diag: tampered,
        verifier=lambda candidate: (True, "evidence://spec/review"),
    )
    with pytest.raises(RecoveryAdapterError, match="SPEC_REPAIR_CANNOT_CHANGE_ORACLE"):
        adapter(context(), diagnosis("SPEC"), decision("REOPEN_EXECUTABLE_SPEC"))


def test_registry_fails_closed_when_action_adapter_is_not_configured():
    registry = RecoveryAdapterRegistry()
    with pytest.raises(RecoveryAdapterError, match="RECOVERY_ADAPTER_NOT_CONFIGURED"):
        registry.require("REAUTH")
