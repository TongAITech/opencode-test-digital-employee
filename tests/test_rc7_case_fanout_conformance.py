from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rc6_runtime.automation import ProcessStepResult, ScriptArtifact, ScriptValidation
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.bank_mission import start_or_resume
from rc7_runtime.case_fanout_conformance import (
    AcceptedCaseInventoryReader,
    CaseFanoutConformanceError,
    check_script_barrier,
    persist_contract,
    record_script_ready,
)
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence, TaskStatus
from rc7_runtime.script_contract import AcceptedTestDesignScriptContractCompiler
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-CASE-FANOUT"
RELEASE = "REL-CASE-FANOUT"
DESIGN_ARTIFACT = "ART-TD-CASE-FANOUT"


def _case(tc_id: str) -> dict:
    return {
        "tc_id": tc_id,
        "case_version": 1,
        "requirement_id": "REQ-FANOUT",
        "sst_id": "SST-FANOUT",
        "layer": "L3",
        "preconditions": [],
        "test_data": {
            "strategy": "REUSE_EXISTING",
            "required_capabilities": [],
            "cleanup_policy": {"mode": "NONE", "required": False},
        },
        "cleanup_policy": {"mode": "NONE", "required": False},
        "steps": [{"action": "GET", "target": "/loan"}],
        "expected": "loan returned",
        "oracle": {"checks": [{"type": "STATUS", "expected": 200}]},
        "evidence_requirements": ["api-response"],
        "target_requirements": ["REQ-FANOUT"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://loan/status-200"],
        "runner_type": "PYTEST",
        "coverage_links": [],
    }


def _candidate_bytes(task_id: str, cases: list[dict]) -> bytes:
    envelope = {
        "task_id": task_id,
        "artifact": {
            "artifact_id": DESIGN_ARTIFACT,
            "artifact_type": "TEST_DESIGN_MODEL",
            "content_ref": "runtime://accepted-test-design",
            "parent_refs": [],
            "evidence_refs": ["EVD-TD-FANOUT-SOURCE"],
        },
        "semantic_payload": {"cases": cases, "obligations": [{"obligation_id": "OB-1"}]},
        "evidence": [],
    }
    return (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _setup(tmp_path: Path, monkeypatch, cases: list[dict]):
    monkeypatch.setenv("PFC_RC7_SOURCE_COMMIT", "c" * 40)
    r1 = tmp_path / "r1" / "event-stream.jsonl"
    start_or_resume(
        r1_path=str(r1),
        mission_id=MISSION,
        release_id=RELEASE,
        goal="prove every accepted case reaches script readiness",
        graph_version="v2",
    )
    truth = TruthRuntime(r1)
    control = ClosedLoopControlPlane(truth, RELEASE, MISSION)
    design_row = next(
        row for row in truth.query("rc7_task", mission_id=MISSION)
        if row.get("node") == "TEST_DESIGN" and row.get("task_type") == "PRODUCE"
    )
    design_task_id = str(design_row["task_id"])
    source = Evidence(
        evidence_id="EVD-TD-FANOUT-SOURCE",
        mission_id=MISSION,
        kind="TEST_DESIGN_SOURCE",
        source_ref="dsh://test-design-worker",
        content_ref="evidence://test-design-source",
        subject_refs=[design_task_id],
    )
    append_entity(truth, source, release_id=RELEASE, artifact_version=1)
    raw = _candidate_bytes(design_task_id, cases)
    path = tmp_path / "accepted-test-design.json"
    path.write_bytes(raw)
    artifact = Artifact(
        artifact_id=DESIGN_ARTIFACT,
        mission_id=MISSION,
        artifact_type="TEST_DESIGN_MODEL",
        producer_task_id=design_task_id,
        content_ref="file://" + str(path.resolve()),
        evidence_refs=[source.evidence_id],
        content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
    )
    append_entity(truth, artifact, release_id=RELEASE, artifact_version=1)
    evaluation = Evaluation(
        evaluation_id="EVAL-TD-FANOUT-PASS",
        mission_id=MISSION,
        node="TEST_DESIGN",
        artifact_refs=[DESIGN_ARTIFACT],
        result=EvaluationResult.PASS,
        evaluator_ref="independent-test-design-reviewer",
        dimensions={"semantic_coverage": "PASS"},
        evidence_refs=[source.evidence_id],
    )
    append_entity(truth, evaluation, release_id=RELEASE, artifact_version=1)
    task = control.scheduler.task(design_task_id)
    task.state = TaskStatus.PASS
    task.output_artifact_refs = [DESIGN_ARTIFACT]
    task.evaluation_id = evaluation.evaluation_id
    append_entity(
        truth,
        task,
        release_id=RELEASE,
        artifact_version=int(design_row["artifact_version"]) + 1,
    )
    script_task = next(row for row in truth.query("rc7_task", mission_id=MISSION) if row.get("node") == "SCRIPT_READINESS")
    execution_task = next(row for row in truth.query("rc7_task", mission_id=MISSION) if row.get("node") == "EXECUTION")
    persist_contract(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        script_task_id=str(script_task["task_id"]),
        execution_task_id=str(execution_task["task_id"]),
    )
    return truth


def _record(tmp_path: Path, truth: TruthRuntime, tc_id: str) -> str:
    contract = AcceptedTestDesignScriptContractCompiler().compile(
        truth,
        mission_id=MISSION,
        design_artifact_id=DESIGN_ARTIFACT,
        tc_id=tc_id,
    )
    validation_evidence = Evidence(
        evidence_id="EVD-VALIDATION-" + tc_id,
        mission_id=MISSION,
        kind="SCRIPT_READINESS_VALIDATION_PROOF",
        source_ref="runtime://script-validator",
        content_ref="validation://" + tc_id,
        subject_refs=[tc_id],
    )
    append_entity(truth, validation_evidence, release_id=RELEASE, artifact_version=1)
    step = ProcessStepResult(
        name="pytest_collect",
        command=("pytest", "--collect-only"),
        exit_code=0,
        stdout_ref="stdout://" + tc_id,
        stderr_ref="stderr://" + tc_id,
        duration_ms=1,
        passed=True,
    )
    script = ScriptArtifact(
        script_id="SCRIPT-" + tc_id,
        spec_id=contract.spec.spec_id,
        tc_id=tc_id,
        case_version=1,
        layer=contract.spec.layer,
        runner_type=contract.spec.runner_type,
        source_ref="file://" + str((tmp_path / (tc_id + ".py")).resolve()),
        test_symbol="test_" + tc_id.lower().replace("-", "_"),
        case_fingerprint=contract.spec.case_fingerprint,
        oracle_fingerprint=contract.spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=(validation_evidence.evidence_id,),
        revision=1,
    )
    validation = ScriptValidation(
        validation_id="VALIDATION-" + tc_id,
        script_id=script.script_id,
        runner_type=script.runner_type,
        test_symbol=script.test_symbol,
        steps=(step,),
        evidence_refs=(validation_evidence.evidence_id,),
        status="SCRIPT_READY",
    )
    return record_script_ready(
        truth,
        mission_id=MISSION,
        release_id=RELEASE,
        task_id="TASK-SCRIPT-UNIT-" + tc_id,
        artifact_id="ART-SCRIPT-UNIT-" + tc_id,
        contract=contract,
        script=script,
        validation=validation,
        evidence_root=str(tmp_path / "runtime-evidence"),
    )


def test_script_barrier_requires_every_accepted_case(tmp_path: Path, monkeypatch) -> None:
    truth = _setup(tmp_path, monkeypatch, [_case("TC-1"), _case("TC-2")])
    inventory = AcceptedCaseInventoryReader().load(truth, MISSION)
    assert inventory.tc_ids == ("TC-1", "TC-2")

    first = _record(tmp_path, truth, "TC-1")
    incomplete = check_script_barrier(truth, MISSION)
    assert incomplete.status == "INCOMPLETE"
    assert incomplete.ready_tc_ids == ("TC-1",)
    assert incomplete.missing_tc_ids == ("TC-2",)
    assert first in incomplete.receipt_ids

    second = _record(tmp_path, truth, "TC-2")
    complete = check_script_barrier(truth, MISSION)
    assert complete.status == "PASS"
    assert complete.required_tc_ids == ("TC-1", "TC-2")
    assert complete.ready_tc_ids == ("TC-1", "TC-2")
    assert complete.missing_tc_ids == ()
    assert set(complete.receipt_ids) == {first, second}


def test_script_receipt_cannot_claim_case_outside_accepted_design(tmp_path: Path, monkeypatch) -> None:
    truth = _setup(tmp_path, monkeypatch, [_case("TC-1"), _case("TC-2")])
    try:
        _record(tmp_path, truth, "TC-NOT-ACCEPTED")
    except Exception as exc:
        assert "SCRIPT_TARGET_TEST_CASE_NOT_UNIQUE" in str(exc) or "CASE_SCRIPT_TC_NOT_ACCEPTED" in str(exc)
    else:
        raise AssertionError("unaccepted case must not receive Script Ready credit")


def test_duplicate_case_identity_is_rejected_from_denominator(tmp_path: Path, monkeypatch) -> None:
    truth = _setup(tmp_path, monkeypatch, [_case("TC-1"), _case("TC-1")])
    try:
        AcceptedCaseInventoryReader().load(truth, MISSION)
    except CaseFanoutConformanceError as exc:
        assert str(exc) == "ACCEPTED_CASE_TC_ID_DUPLICATE:TC-1"
    else:
        raise AssertionError("duplicate tc_id must fail closed")
