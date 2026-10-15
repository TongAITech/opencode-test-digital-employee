from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rc6_runtime.executable_spec import ExecutableSpecBuilder, ExecutableSpecError
from rc6_runtime.truth import TruthRuntime
from rc7_runtime import Artifact, ClosedLoopControlPlane, Evaluation, EvaluationResult, Evidence, Mission, Task
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.script_contract import AcceptedTestDesignScriptContractCompiler, ScriptContractError


MISSION = "MISSION-SCRIPT-CONTRACT"
TASK_ID = "TASK-DESIGN-FOR-SCRIPT"
ARTIFACT_ID = "ART-DESIGN-FOR-SCRIPT"
WORKER = "worker-design-for-script"


def _case(*, include_steps=True):
    cleanup = {"required": True, "mode": "rollback"}
    case = {
        "tc_id": "TC-RATE-SCRIPT-1",
        "case_version": 3,
        "status": "CANDIDATE",
        "release_id": "WORKER-CANNOT-OVERRIDE",
        "requirement_id": "REQ-RATE-1",
        "sst_id": "SST-RATE-1",
        "layer": "L3",
        "preconditions": [
            {
                "id": "PRE-1",
                "type": "BUSINESS_STATE",
                "requirement": "loan exists and is eligible for rate adjustment",
            }
        ],
        "test_data": {
            "initial_state": [
                {
                    "id": "DATA-LOAN",
                    "selectors": {"loan_status": "ACTIVE"},
                    "allowed_strategies": ["REUSE_EXISTING"],
                }
            ],
            "input_data": [
                {
                    "id": "DATA-RATE",
                    "selectors": {"rate_adjustment": "VALID"},
                    "allowed_strategies": ["REUSE_EXISTING"],
                }
            ],
            "cleanup_policy": dict(cleanup),
        },
        "expected": "rate adjustment accepted",
        "oracle": {"checks": [{"type": "BUSINESS_RULE", "expected": "RATE_UPDATED"}]},
        "evidence_requirements": ["api-response", "db-before-after"],
        "target_requirements": ["REQ-RATE-1"],
        "test_data_refs": ["data://loan/rate-case-1"],
        "oracle_refs": ["oracle://rate/accepted"],
        "cleanup_policy": dict(cleanup),
        "runner_type": "PYTEST",
    }
    if include_steps:
        case["steps"] = [
            {"order": 1, "action": "submit rate adjustment"},
            {"order": 2, "action": "query resulting loan rate"},
        ]
    return case


def _accepted_design(tmp_path, *, case):
    truth = TruthRuntime(Path(tmp_path) / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id="RC7-SCRIPT-QUAL", goal="compile immutable script contract"),
    )
    task = Task(
        task_id=TASK_ID,
        mission_id=MISSION,
        node="TEST_DESIGN",
        task_type="PRODUCE",
        objective="accepted Test Design parent",
        required_capabilities=["test_design"],
    )
    control.register_task(task)
    leased = control.lease_next(worker_ref=WORKER, capabilities=["test_design"])
    assert leased is not None
    control.start(TASK_ID, worker_ref=WORKER)
    evidence = Evidence(
        evidence_id="EVD-DESIGN-SCRIPT-CONTRACT",
        mission_id=MISSION,
        kind="TEST_DESIGN_PROOF",
        source_ref="source://design",
        content_ref="evidence://design/script-contract",
        subject_refs=[TASK_ID],
    )
    envelope = {
        "task_id": TASK_ID,
        "artifact": {
            "artifact_id": ARTIFACT_ID,
            "artifact_type": "TEST_DESIGN_MODEL",
            "content_ref": "source://design",
            "parent_refs": [],
            "evidence_refs": [evidence.evidence_id],
        },
        "semantic_payload": {"obligations": [], "cases": [case]},
        "evidence": [],
    }
    raw = (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path = Path(tmp_path) / "accepted-design.json"
    path.write_bytes(raw)
    artifact = Artifact(
        artifact_id=ARTIFACT_ID,
        mission_id=MISSION,
        artifact_type="TEST_DESIGN_MODEL",
        producer_task_id=TASK_ID,
        content_ref="file://" + str(path.resolve()),
        evidence_refs=[evidence.evidence_id],
        content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
    )
    control.submit_worker_output(
        WorkerOutput(task_id=TASK_ID, worker_ref=WORKER, artifacts=(artifact,), evidence=(evidence,))
    )
    control.accept_evaluation(
        TASK_ID,
        evaluation=Evaluation(
            evaluation_id="EVAL-DESIGN-SCRIPT-CONTRACT",
            mission_id=MISSION,
            node="TEST_DESIGN",
            artifact_refs=[ARTIFACT_ID],
            result=EvaluationResult.PASS,
            evaluator_ref="independent-design-gate",
            evidence_refs=[evidence.evidence_id],
        ),
    )
    return truth


def test_runtime_freezes_accepted_case_and_compiles_executable_spec(tmp_path):
    truth = _accepted_design(tmp_path, case=_case())

    contract = AcceptedTestDesignScriptContractCompiler().compile(
        truth,
        mission_id=MISSION,
        design_artifact_id=ARTIFACT_ID,
        tc_id="TC-RATE-SCRIPT-1",
    )

    assert contract.frozen_case["status"] == "FROZEN"
    assert contract.frozen_case["release_id"] == "RC7-SCRIPT-QUAL"
    assert contract.spec.tc_id == "TC-RATE-SCRIPT-1"
    assert contract.spec.case_version == 3
    assert contract.spec.runner_type == "PYTEST"
    assert contract.spec.target_requirements == ("REQ-RATE-1",)
    assert contract.spec.test_data_refs == ("data://loan/rate-case-1",)
    assert contract.spec.oracle_refs == ("oracle://rate/accepted",)
    assert len(contract.spec.ordered_actions) == 2
    assert contract.spec.cleanup_policy == {"required": True, "mode": "ROLLBACK"}


def test_script_contract_rejects_design_case_without_executable_steps(tmp_path):
    truth = _accepted_design(tmp_path, case=_case(include_steps=False))

    with pytest.raises(ScriptContractError, match="SCRIPT_CASE_STEPS_REQUIRED"):
        AcceptedTestDesignScriptContractCompiler().compile(
            truth,
            mission_id=MISSION,
            design_artifact_id=ARTIFACT_ID,
            tc_id="TC-RATE-SCRIPT-1",
        )


def test_frozen_case_drift_is_detected_after_contract_compile(tmp_path):
    truth = _accepted_design(tmp_path, case=_case())
    contract = AcceptedTestDesignScriptContractCompiler().compile(
        truth,
        mission_id=MISSION,
        design_artifact_id=ARTIFACT_ID,
        tc_id="TC-RATE-SCRIPT-1",
    )
    tampered = dict(contract.frozen_case)
    tampered["expected"] = "silently changed oracle semantics"

    with pytest.raises(ExecutableSpecError, match="CASE_FINGERPRINT_DRIFT"):
        ExecutableSpecBuilder.verify_case_binding(contract.spec, tampered)
