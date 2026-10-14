from copy import deepcopy

import pytest

from rc6_runtime.executable_spec import ExecutableSpecBuilder, ExecutableSpecError


def frozen_case():
    return {
        "tc_id": "TC-L3-001",
        "case_version": 3,
        "release_id": "BLOAN-PF1.2.0",
        "requirement_id": "STBB19-320",
        "sst_id": "STB915-7489",
        "condition_id": "COND-1",
        "objective": "verify service response",
        "layer": "L3",
        "preconditions": ["4A session ready", {"id": "route", "state": "READY"}],
        "test_data": {"customer_ref": "data://customer/1"},
        "steps": [
            "invoke governed API client",
            {"order": 2, "action": "assert response"},
        ],
        "expected": "business response is accepted",
        "oracle": {"type": "field_equals", "field": "code", "value": "0000"},
        "evidence_requirements": ["request", "response", "assertion"],
        "status": "FROZEN",
    }


def build(case=None):
    return ExecutableSpecBuilder().build(
        case=case or frozen_case(),
        target_requirements=("TARGET-QUALIFIED", "api-runtime:READY"),
        test_data_refs=("data://customer/1",),
        oracle_refs=("oracle://TC-L3-001@3",),
        cleanup_policy={"mode": "rollback"},
        runner_type="pytest",
        automation_mapping={"reuse_refs": ["api-client://cfg-data"], "script_ref": None},
    )


def test_frozen_case_compiles_to_immutable_executable_spec():
    spec = build()
    assert spec.spec_id.startswith("XSPEC-")
    assert spec.tc_id == "TC-L3-001"
    assert spec.case_version == 3
    assert spec.layer == "L3"
    assert spec.runner_type == "PYTEST"
    assert spec.case_fingerprint
    assert spec.oracle_fingerprint
    assert [x["order"] for x in spec.ordered_actions] == [1, 2]
    artifact = spec.to_artifact()
    assert artifact["case_fingerprint"] == spec.case_fingerprint
    assert artifact["oracle_fingerprint"] == spec.oracle_fingerprint


def test_case_or_oracle_drift_fails_closed():
    builder = ExecutableSpecBuilder()
    case = frozen_case()
    spec = build(case)
    builder.verify_case_binding(spec, case)

    changed_case = deepcopy(case)
    changed_case["steps"][0] = "silently changed action"
    with pytest.raises(ExecutableSpecError, match="CASE_FINGERPRINT_DRIFT"):
        builder.verify_case_binding(spec, changed_case)

    changed_oracle = deepcopy(case)
    changed_oracle["oracle"]["value"] = "9999"
    with pytest.raises(ExecutableSpecError, match="CASE_FINGERPRINT_DRIFT"):
        builder.verify_case_binding(spec, changed_oracle)


def test_script_repair_cannot_change_oracle_binding():
    spec = build()
    ExecutableSpecBuilder.verify_script_or_repair_binding(
        spec,
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
    )
    with pytest.raises(ExecutableSpecError, match="SCRIPT_OR_REPAIR_ORACLE_CHANGED"):
        ExecutableSpecBuilder.verify_script_or_repair_binding(
            spec,
            case_fingerprint=spec.case_fingerprint,
            oracle_fingerprint="tampered",
        )


def test_natural_language_unfrozen_case_cannot_execute_spec_build():
    case = frozen_case()
    case["status"] = "TEST_READY"
    with pytest.raises(ExecutableSpecError, match="CASE_MUST_BE_FROZEN"):
        build(case)
