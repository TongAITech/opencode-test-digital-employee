from __future__ import annotations

import subprocess
import sys

import pytest

from rc6_runtime.automation import ScriptArtifact
from rc6_runtime.executable_spec import ExecutableSpecError
from rc7_runtime import Task, TaskStatus, transition_task
from rc7_runtime.script_readiness_loop import ScriptReadinessClosedLoop


def _frozen_case():
    return {
        "tc_id": "TC-RATE-1",
        "case_version": 1,
        "release_id": "RC7",
        "requirement_id": "REQ-1",
        "sst_id": "SST-1",
        "layer": "L3",
        "status": "FROZEN",
        "preconditions": ["loan exists"],
        "steps": ["submit rate adjustment"],
        "expected": "rate adjustment is rejected",
        "oracle": {
            "checks": [
                {"type": "API_RESPONSE", "expected": "REJECTED"},
                {"type": "BUSINESS_RULE", "expected": "NO_CHANGE"},
            ]
        },
        "evidence_requirements": ["api-response", "db-before-after"],
    }


def _spec(loop: ScriptReadinessClosedLoop):
    return loop.compile_execution_contract(
        case=_frozen_case(),
        target_requirements=("REQ-1",),
        test_data_refs=("data://loan-1",),
        oracle_refs=("oracle://rate-rejected",),
        cleanup_policy={"required": False},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )


def _script(spec, source_ref: str, *, oracle_fingerprint=None):
    return ScriptArtifact(
        script_id="SCRIPT-RATE-1",
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref=source_ref,
        test_symbol="test_generated_case",
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=oracle_fingerprint or spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("EVD-SCRIPT-BUILD",),
        revision=1,
    )


def _candidate_task() -> Task:
    task = Task(
        task_id="TASK-SCRIPT-1",
        mission_id="MISSION-1",
        node="SCRIPT_READINESS",
        task_type="PRODUCE",
        objective="Build a trustworthy executable script",
    )
    transition_task(task, TaskStatus.READY)
    transition_task(task, TaskStatus.LEASED, lease_owner="script-worker")
    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.OUTPUT_PRODUCED)
    return task


def test_script_can_be_ready_even_when_business_assertion_would_fail(tmp_path) -> None:
    loop = ScriptReadinessClosedLoop(validation_timeout_seconds=60)
    spec = _spec(loop)
    path = tmp_path / "test_generated_case.py"
    path.write_text(
        "def test_generated_case():\n"
        "    assert False, 'simulated product behavior mismatch'\n",
        encoding="utf-8",
    )
    script = _script(spec, "file://" + str(path))

    validation = loop.validate_script(spec=spec, script=script, cwd=str(tmp_path))
    assert validation.ready is True
    assert [step.name for step in validation.steps] == [
        "python_compile",
        "pytest_collect",
        "fixture_dependency_resolution",
    ]
    assert "targeted_execution" not in [step.name for step in validation.steps]

    result = loop.evaluate(
        mission_id="MISSION-1",
        artifact_ref="ART-SCRIPT-1",
        spec=spec,
        script=script,
        validation=validation,
    )
    assert result.script_ready is True
    assert result.evaluation.result.value == "PASS"
    assert result.evaluation.dimensions["business_assertion_executed"] is False

    task = _candidate_task()
    loop.accept_candidate(task, result)
    assert task.state == TaskStatus.PASS

    # Formal product execution is a different phase and does fail. This is the
    # invariant RC7 needs: SCRIPT_READY must not be rewritten as TEST_PASS.
    formal = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(path) + "::test_generated_case"],
        cwd=str(tmp_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert formal.returncode != 0


def test_script_readiness_rejects_compile_failure(tmp_path) -> None:
    loop = ScriptReadinessClosedLoop(validation_timeout_seconds=60)
    spec = _spec(loop)
    path = tmp_path / "test_generated_case.py"
    path.write_text("def test_generated_case(:\n    pass\n", encoding="utf-8")
    script = _script(spec, "file://" + str(path))

    validation = loop.validate_script(spec=spec, script=script, cwd=str(tmp_path))
    assert validation.ready is False
    result = loop.evaluate(
        mission_id="MISSION-1",
        artifact_ref="ART-SCRIPT-BAD",
        spec=spec,
        script=script,
        validation=validation,
    )
    assert result.script_ready is False
    assert any(gap.category == "SCRIPT_VALIDATION_FAILED" for gap in result.gaps)


def test_script_or_repair_cannot_silently_change_oracle(tmp_path) -> None:
    loop = ScriptReadinessClosedLoop(validation_timeout_seconds=60)
    spec = _spec(loop)
    path = tmp_path / "test_generated_case.py"
    path.write_text("def test_generated_case():\n    pass\n", encoding="utf-8")
    drifted = _script(
        spec,
        "file://" + str(path),
        oracle_fingerprint="different-business-oracle",
    )

    with pytest.raises(ExecutableSpecError, match="SCRIPT_OR_REPAIR_ORACLE_CHANGED"):
        loop.validate_script(spec=spec, script=drifted, cwd=str(tmp_path))
