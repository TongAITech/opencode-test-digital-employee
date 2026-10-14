from pathlib import Path

import pytest

from rc6_runtime.automation import (
    AIScriptBuilder,
    AutomationContractError,
    AutomationReuseResolver,
    JUnitRunnerAdapter,
    PytestRunnerAdapter,
    ScriptValidator,
)
from rc6_runtime.executable_spec import ExecutableSpecBuilder


def spec(tmp_path):
    case = {
        "tc_id": "TC-L3-RUNNER",
        "case_version": 1,
        "release_id": "BLOAN-PF1.2.0",
        "requirement_id": "STBB19-320",
        "sst_id": "STB915-7489",
        "condition_id": "COND-RUNNER",
        "objective": "runner qualification",
        "layer": "L3",
        "preconditions": [],
        "test_data": {},
        "steps": ["run target"],
        "expected": "code 0000",
        "oracle": {"field": "code", "value": "0000"},
        "evidence_requirements": ["runner stdout", "runner stderr"],
        "status": "FROZEN",
    }
    return ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("TARGET-QUALIFIED",),
        test_data_refs=(),
        oracle_refs=("oracle://TC-L3-RUNNER@1",),
        cleanup_policy={"mode": "none"},
        runner_type="PYTEST",
        automation_mapping={"reuse_refs": []},
    )


def test_reuse_resolution_searches_existing_helpers_before_build(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_stbb19_320_api.py").write_text("def test_existing(): pass\n", encoding="utf-8")
    (tmp_path / "helpers").mkdir()
    (tmp_path / "helpers" / "foura_auth.py").write_text("def login(): pass\n", encoding="utf-8")
    resolution = AutomationReuseResolver().resolve(spec=spec(tmp_path), search_roots=(str(tmp_path),))
    categories = {asset.category for asset in resolution.assets}
    assert "test" in categories
    assert "auth_skill" in categories
    assert resolution.evidence_refs


def test_generated_script_must_preserve_case_and_oracle_fingerprints(tmp_path):
    target = tmp_path / "test_real_runner.py"
    target.write_text("def test_real_api_contract():\n    assert {'code': '0000'}['code'] == '0000'\n", encoding="utf-8")
    xs = spec(tmp_path)
    resolution = AutomationReuseResolver().resolve(spec=xs, search_roots=(str(tmp_path),))

    def generator(spec_value, mapping):
        return {
            "source_ref": "file://" + str(target),
            "test_symbol": "test_real_api_contract",
            "case_fingerprint": spec_value.case_fingerprint,
            "oracle_fingerprint": spec_value.oracle_fingerprint,
            "evidence_refs": ["builder://real-runner"],
        }

    script = AIScriptBuilder().build(spec=xs, resolution=resolution, generator=generator)
    assert script.status == "SCRIPT_GENERATED"

    def tampering_generator(spec_value, mapping):
        raw = generator(spec_value, mapping)
        raw["oracle_fingerprint"] = "tampered"
        return raw

    with pytest.raises(AutomationContractError, match="SCRIPT_OR_REPAIR_ORACLE_CHANGED"):
        AIScriptBuilder().build(spec=xs, resolution=resolution, generator=tampering_generator)


def test_pytest_script_validation_and_production_runner_use_real_process(tmp_path):
    target = tmp_path / "test_real_runner.py"
    target.write_text(
        "def test_real_api_contract():\n"
        "    actual = {'code': '0000', 'source': 'real-process'}\n"
        "    assert actual['code'] == '0000'\n",
        encoding="utf-8",
    )
    xs = spec(tmp_path)
    resolution = AutomationReuseResolver().resolve(spec=xs, search_roots=(str(tmp_path),))
    script = AIScriptBuilder().build(
        spec=xs,
        resolution=resolution,
        generator=lambda spec_value, mapping: {
            "source_ref": "file://" + str(target),
            "test_symbol": "test_real_api_contract",
            "evidence_refs": ["builder://pytest"],
        },
    )

    validation = ScriptValidator(timeout_seconds=60).validate(
        spec=xs,
        script=script,
        cwd=str(tmp_path),
        execute_target=True,
    )
    assert validation.status == "SCRIPT_READY"
    assert [step.name for step in validation.steps] == [
        "python_compile",
        "pytest_collect",
        "fixture_dependency_resolution",
        "targeted_execution",
    ]
    assert all(step.exit_code == 0 for step in validation.steps)

    result = PytestRunnerAdapter(timeout_seconds=60).execute(
        spec=xs,
        script=script,
        validation=validation,
        cwd=str(tmp_path),
    )
    assert result.status == "EXECUTED"
    assert result.exit_code == 0
    assert result.actual_result["runner_passed"] is True
    assert result.tool_call_refs
    assert result.evidence_refs


def test_script_generated_is_not_runner_ready_without_validation(tmp_path):
    target = tmp_path / "test_not_ready.py"
    target.write_text("def test_x(): assert True\n", encoding="utf-8")
    xs = spec(tmp_path)
    resolution = AutomationReuseResolver().resolve(spec=xs, search_roots=(str(tmp_path),))
    script = AIScriptBuilder().build(
        spec=xs,
        resolution=resolution,
        generator=lambda spec_value, mapping: {
            "source_ref": "file://" + str(target),
            "test_symbol": "test_x",
            "evidence_refs": ["builder://not-ready"],
        },
    )
    from rc6_runtime.automation import ScriptValidation
    fake = ScriptValidation("VAL-fake", script.script_id, "PYTEST", script.test_symbol, (), (), "SCRIPT_GENERATED")
    with pytest.raises(AutomationContractError, match="SCRIPT_READY_RUNTIME_GATE_REQUIRED"):
        PytestRunnerAdapter().execute(spec=xs, script=script, validation=fake, cwd=str(tmp_path))


def test_junit_adapter_is_capability_version_agnostic():
    adapter = JUnitRunnerAdapter()
    class S:
        test_symbol = "com.bank.CfgDataTest#shouldAccept"
    command = adapter.command(S())
    assert command[0] == "mvn"
    assert not any(part.startswith("3.") for part in command)
    assert "-Dtest=com.bank.CfgDataTest#shouldAccept" in command
