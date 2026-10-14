from __future__ import annotations

import subprocess
from pathlib import Path

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator


def _case(layer="L3"):
    return {
        "tc_id": "TC-READY-1",
        "case_version": 1,
        "release_id": "RC7",
        "requirement_id": "REQ-READY-1",
        "sst_id": "SST-READY-1",
        "layer": layer,
        "status": "FROZEN",
        "preconditions": ["loan exists"],
        "steps": ["query loan"],
        "expected": "loan is returned",
        "oracle": {"checks": [{"type": "BUSINESS_RULE", "expected": "FOUND"}]},
        "evidence_requirements": ["api-response"],
    }


def _spec(runner):
    return ExecutableSpecBuilder().build(
        case=_case(),
        target_requirements=("REQ-READY-1",),
        test_data_refs=(),
        oracle_refs=("oracle://ready",),
        cleanup_policy={"required": False},
        runner_type=runner,
        automation_mapping={"reuse": {}},
    )


def _script(spec, source, symbol):
    return ScriptArtifact(
        script_id="SCRIPT-READY-1",
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(source),
        test_symbol=symbol,
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("EVD-BUILD-1",),
        revision=1,
    )


def test_pytest_readiness_collects_and_resolves_fixtures_without_target_execution(tmp_path):
    spec = _spec("PYTEST")
    source = tmp_path / "test_ready.py"
    source.write_text("def test_ready_case():\n    assert 1 == 1\n", encoding="utf-8")
    script = _script(spec, source, "test_ready_case")

    validation = EvidenceBackedScriptReadinessValidator(
        evidence_root=str(tmp_path / "evidence"),
        timeout_seconds=30,
    ).validate(spec=spec, script=script, cwd=str(tmp_path))

    assert validation.ready
    assert [step.name for step in validation.steps] == [
        "python_compile",
        "pytest_collect",
        "fixture_dependency_resolution",
    ]
    assert "targeted_execution" not in [step.name for step in validation.steps]
    for ref in validation.evidence_refs:
        assert ref.startswith("file://")
        assert Path(ref[len("file://"):]).is_file()


def test_pytest_compile_failure_keeps_real_stderr_log(tmp_path):
    spec = _spec("PYTEST")
    source = tmp_path / "test_broken.py"
    source.write_text("def test_broken(:\n    pass\n", encoding="utf-8")
    script = _script(spec, source, "test_broken")

    validation = EvidenceBackedScriptReadinessValidator(
        evidence_root=str(tmp_path / "evidence"),
        timeout_seconds=30,
    ).validate(spec=spec, script=script, cwd=str(tmp_path))

    assert not validation.ready
    assert [step.name for step in validation.steps] == ["python_compile"]
    stderr_path = Path(validation.steps[0].stderr_ref[len("file://"):])
    assert stderr_path.is_file()
    assert stderr_path.read_text(encoding="utf-8").strip()


def test_junit_readiness_never_invokes_maven_test_business_execution(tmp_path):
    spec = _spec("JUNIT")
    source = tmp_path / "RateReadyTest.java"
    source.write_text(
        "public class RateReadyTest { public void shouldReturnLoan() {} }\n",
        encoding="utf-8",
    )
    (tmp_path / "pom.xml").write_text("<project></project>\n", encoding="utf-8")
    script = _script(spec, source, "RateReadyTest#shouldReturnLoan")
    commands = []

    def fake_runner(command, **kwargs):
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    validation = EvidenceBackedScriptReadinessValidator(
        evidence_root=str(tmp_path / "evidence"),
        timeout_seconds=30,
        command_runner=fake_runner,
    ).validate(spec=spec, script=script, cwd=str(tmp_path))

    assert validation.ready
    assert [step.name for step in validation.steps] == [
        "dependency_resolution",
        "test_compile",
        "test_symbol_discovery",
    ]
    maven_commands = [command for command in commands if command and command[0] == "mvn"]
    assert maven_commands
    assert all(command[-1] != "test" for command in maven_commands)
