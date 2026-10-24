from __future__ import annotations

import hashlib
import json

import pytest

from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.autonomous_preparation_node import WaveCNodeAdoptionControl
from rc7_runtime.autonomous_script_node import AutonomousScriptNodeError, AutonomousScriptNodeService
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence, Mission, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity


RELEASE = "RC7.1-WAVE-C-N6"
MISSION = "MISSION-RC7-1-N6"
RUN = "RUN-RC7-1-N6"
TASK_ID = "TASK-SCRIPT-N6-001"
ARTIFACT_ID = "ART-SCRIPT-CANDIDATE-N6"


def _spec():
    case = {
        "status": "FROZEN",
        "tc_id": "TC-N6-001",
        "case_version": 1,
        "release_id": RELEASE,
        "requirement_id": "REQ-001",
        "sst_id": "SST-001",
        "layer": "L3",
        "preconditions": [{"id": "PRE-AUTH", "description": "fresh auth"}],
        "steps": [
            {"order": 1, "action": "create request"},
            {"order": 2, "action": "submit request"},
        ],
        "expected": "business result saved",
        "oracle": {"type": "API_AND_STATE", "checks": ["code", "state"]},
        "evidence_requirements": ["REQUEST_RESPONSE", "CAT_CORRELATION"],
    }
    return ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-001",),
        test_data_refs=("DATA-LOAN",),
        oracle_refs=("ORACLE-API", "ORACLE-STATE"),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )


def _matrix(spec, *, omit_step=False):
    steps = [
        {"order": 1, "implementation_ref": "fn:test_case/step_1"},
        {"order": 2, "implementation_ref": "fn:test_case/step_2"},
    ]
    if omit_step:
        steps = steps[:1]
    return {
        "steps": steps,
        "oracles": [
            {"oracle_ref": ref, "assertion_ref": "assert:%s" % ref}
            for ref in spec.oracle_refs
        ],
        "runtime_bindings": [
            {"binding_ref": "PRE-AUTH", "injection_ref": "fixture:auth"},
            {"binding_ref": "DATA-LOAN", "injection_ref": "fixture:loan"},
        ],
        "evidence_collectors": [
            {"requirement": ref, "collector_ref": "collector:%s" % ref}
            for ref in spec.evidence_requirements
        ],
    }


def _setup(tmp_path, *, omit_step=False, business_assertion_executed=False):
    spec = _spec()
    truth = TruthRuntime(tmp_path / "runtime-state" / "r1" / "event-stream.jsonl")
    append_entity(truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="N6 autonomous script closure"), release_id=RELEASE)

    candidate_evidence = Evidence(
        evidence_id="EVD-N6-CANDIDATE",
        mission_id=MISSION,
        kind="WORKER_CANDIDATE_RECORD",
        source_ref="dsh://worker/script-worker",
        content_ref="runtime://candidate/script",
        subject_refs=[TASK_ID, ARTIFACT_ID],
    )
    append_entity(truth, candidate_evidence, release_id=RELEASE)

    semantic_payload = {
        "binding": {
            "spec_id": spec.spec_id,
            "tc_id": spec.tc_id,
            "case_version": spec.case_version,
            "runner_type": spec.runner_type,
            "case_fingerprint": spec.case_fingerprint,
            "oracle_fingerprint": spec.oracle_fingerprint,
            "design_content_hash": "sha256:design",
        },
        "source_text": "def test_case(auth, loan):\n    response = submit(loan)\n    assert response is not None\n",
        "test_symbol": "test_case",
        "implementation_matrix": _matrix(spec, omit_step=omit_step),
    }
    envelope = {
        "task_id": TASK_ID,
        "artifact": {"artifact_id": ARTIFACT_ID, "artifact_type": "SCRIPT_CANDIDATE"},
        "semantic_payload": semantic_payload,
    }
    path = tmp_path / "script-candidate.json"
    raw = (json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path.write_bytes(raw)
    content_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    append_entity(
        truth,
        Artifact(
            artifact_id=ARTIFACT_ID,
            mission_id=MISSION,
            artifact_type="SCRIPT_CANDIDATE",
            producer_task_id=TASK_ID,
            content_ref="file://" + str(path),
            evidence_refs=[candidate_evidence.evidence_id],
            content_hash=content_hash,
        ),
        release_id=RELEASE,
    )

    evaluation = Evaluation(
        evaluation_id="EVAL-N6-READY",
        mission_id=MISSION,
        node="SCRIPT_READINESS",
        artifact_refs=[ARTIFACT_ID],
        result=EvaluationResult.PASS,
        evaluator_ref="rc7-runtime-script-readiness-gate",
        dimensions={
            "gate_status": "SCRIPT_READY",
            "business_assertion_executed": business_assertion_executed,
            "case_fingerprint": spec.case_fingerprint,
            "oracle_fingerprint": spec.oracle_fingerprint,
        },
        gap_refs=[],
        evidence_refs=[candidate_evidence.evidence_id],
    )
    append_entity(truth, evaluation, release_id=RELEASE)
    append_entity(
        truth,
        Task(
            task_id=TASK_ID,
            mission_id=MISSION,
            node="SCRIPT_READINESS",
            task_type="AGENT",
            objective="generate script candidate",
            state=TaskStatus.PASS,
            lease_owner="script-worker",
            output_artifact_refs=[ARTIFACT_ID],
            evaluation_id=evaluation.evaluation_id,
        ),
        release_id=RELEASE,
    )
    return truth, ClosedLoopControlPlane(truth, RELEASE, MISSION), spec


def test_n6_requires_semantic_matrix_then_director_gate(tmp_path) -> None:
    truth, control, spec = _setup(tmp_path)
    service = AutonomousScriptNodeService(evidence_root=str(tmp_path / "evidence"))
    delivery = service.publish_ready(
        control,
        run_id=RUN,
        task_id=TASK_ID,
        artifact_id=ARTIFACT_ID,
        spec=spec,
        team_id="TEAM-SCRIPT",
        assignment_ids=["ASSIGN-SCRIPT-1"],
        member_ids=["script-worker", "script-critic"],
    )
    assert delivery.node_id == "N6"
    assert not [
        row for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_TERMINAL" and row.get("data", {}).get("node_id") == "N6"
    ]
    matrix_evidence = [
        row for row in truth.query("rc7_evidence", mission_id=MISSION)
        if row.get("kind") == "SCRIPT_IMPLEMENTATION_MATRIX_VERIFIED"
    ]
    assert len(matrix_evidence) == 1

    decision = WaveCNodeAdoptionControl(
        truth,
        release_id=RELEASE,
        evidence_root=str(tmp_path / "evidence"),
    ).director_accept(
        mission_id=MISSION,
        run_id=RUN,
        node_id="N6",
        director_ref="director-runtime-authority",
    )
    assert decision.accepted is True


def test_n6_incomplete_matrix_creates_durable_gap_and_no_delivery(tmp_path) -> None:
    truth, control, spec = _setup(tmp_path, omit_step=True)
    service = AutonomousScriptNodeService(evidence_root=str(tmp_path / "evidence"))
    with pytest.raises(AutonomousScriptNodeError, match="N6_SEMANTIC_IMPLEMENTATION_INCOMPLETE"):
        service.publish_ready(
            control,
            run_id=RUN,
            task_id=TASK_ID,
            artifact_id=ARTIFACT_ID,
            spec=spec,
        )
    gaps = [
        row for row in truth.query("rc7_gap", mission_id=MISSION)
        if row.get("category") == "SCRIPT_IMPLEMENTATION_COVERAGE_GAP"
    ]
    assert len(gaps) == 1
    assert "SCRIPT_MATRIX_MISSING:steps:2" in gaps[0]["description"]
    assert not [
        row for row in truth.query("rc7_control_event", mission_id=MISSION)
        if row.get("event_type_name") == "NODE_READY_FOR_DIRECTOR_REVIEW"
        and row.get("data", {}).get("node_id") == "N6"
    ]


def test_n6_never_accepts_business_assertion_execution_in_readiness_gate(tmp_path) -> None:
    _truth, control, spec = _setup(tmp_path, business_assertion_executed=True)
    with pytest.raises(AutonomousScriptNodeError, match="N6_BUSINESS_ASSERTION_MUST_NOT_EXECUTE"):
        AutonomousScriptNodeService(evidence_root=str(tmp_path / "evidence")).publish_ready(
            control,
            run_id=RUN,
            task_id=TASK_ID,
            artifact_id=ARTIFACT_ID,
            spec=spec,
        )
