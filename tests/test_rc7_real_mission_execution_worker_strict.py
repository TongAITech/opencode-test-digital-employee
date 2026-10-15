from __future__ import annotations

import importlib.util
from pathlib import Path

from rc6_runtime.truth import TruthRuntime
from rc7_release.real_mission_qualification_strict import evaluate_real_mission_strict
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity


_HELPER_PATH = Path(__file__).with_name("test_rc7_real_mission_qualification.py")
_SPEC = importlib.util.spec_from_file_location("rc7_real_mission_execution_fixture", str(_HELPER_PATH))
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)

EXEC_TASK = "TASK-EXEC-REAL"
EXEC_ARTIFACT = "ART-EXEC-REAL"
EXEC_EVAL = "EVAL-EXEC-REAL"
EXEC_WORKER = "worker-execution"
EXEC_DSH_EVIDENCE = "EVD-DSH-EXECUTION"


def _append_execution_pass(r1_path, *, include_tool_receipt: bool):
    truth = TruthRuntime(r1_path)
    append_entity(
        truth,
        Artifact(
            artifact_id=EXEC_ARTIFACT,
            mission_id=_FIXTURE.MISSION,
            artifact_type="EXECUTION_CONCLUSION",
            producer_task_id=EXEC_TASK,
            content_ref="artifact://execution/real",
        ),
        release_id=_FIXTURE.RELEASE,
    )
    append_entity(
        truth,
        Evaluation(
            evaluation_id=EXEC_EVAL,
            mission_id=_FIXTURE.MISSION,
            node="EXECUTION",
            artifact_refs=[EXEC_ARTIFACT],
            result=EvaluationResult.PASS,
            evaluator_ref="independent-execution-evaluator",
            evidence_refs=[_FIXTURE.FORMAL_EVIDENCE],
            dimensions={"test_result": "PASS", "failure_class": "NONE"},
        ),
        release_id=_FIXTURE.RELEASE,
    )
    append_entity(
        truth,
        Task(
            task_id=EXEC_TASK,
            mission_id=_FIXTURE.MISSION,
            node="EXECUTION",
            task_type="EXECUTE",
            objective="execute a real bank test case",
            state=TaskStatus.PASS,
            lease_owner=EXEC_WORKER,
            output_artifact_refs=[EXEC_ARTIFACT],
            evaluation_id=EXEC_EVAL,
        ),
        release_id=_FIXTURE.RELEASE,
        artifact_version=6,
    )
    _FIXTURE._dsh_evidence(
        truth,
        evidence_id=EXEC_DSH_EVIDENCE,
        worker=EXEC_WORKER,
        task_id=EXEC_TASK,
    )
    if include_tool_receipt:
        _FIXTURE._append_tool_call(
            truth,
            worker=EXEC_WORKER,
            task_id=EXEC_TASK,
            number=30,
        )


def test_strict_gate_holds_when_execution_task_has_no_own_real_tool_receipt(tmp_path):
    r1_path = _FIXTURE._build_r1(tmp_path)
    _append_execution_pass(r1_path, include_tool_receipt=False)

    result = evaluate_real_mission_strict(
        r1_path=str(r1_path),
        mission_id=_FIXTURE.MISSION,
        source_commit=_FIXTURE.COMMIT,
    )

    assert result["status"] == "HOLD"
    assert "DOMAIN_TASK_REAL_TOOL_CALL_MISSING:%s" % EXEC_TASK in result["blocking_reasons"]
    proof = result["task_scoped_worker_proof"][EXEC_TASK]
    assert proof["lease_owner"] == EXEC_WORKER
    assert proof["owner_dsh_runtime_proven"] is True
    assert proof["tool_receipts"] == []
    assert proof["proven"] is False


def test_strict_gate_passes_when_execution_task_has_owner_dsh_and_task_scoped_receipt(tmp_path):
    r1_path = _FIXTURE._build_r1(tmp_path)
    _append_execution_pass(r1_path, include_tool_receipt=True)

    result = evaluate_real_mission_strict(
        r1_path=str(r1_path),
        mission_id=_FIXTURE.MISSION,
        source_commit=_FIXTURE.COMMIT,
    )

    assert result["status"] == "PASS"
    proof = result["task_scoped_worker_proof"][EXEC_TASK]
    assert proof["lease_owner"] == EXEC_WORKER
    assert proof["dsh_runtime_workers"] == [EXEC_WORKER]
    assert proof["owner_dsh_runtime_proven"] is True
    assert proof["tool_receipts"] == ["tool://real/%s/30" % EXEC_WORKER]
    assert proof["proven"] is True
