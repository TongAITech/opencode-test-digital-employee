from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc6_runtime.truth import TruthRuntime
from rc7_runtime import Artifact, ClosedLoopControlPlane, Evidence, Mission, Task, TaskStatus
from rc7_runtime.control_plane import WorkerOutput
from rc7_runtime.dsh_script_evaluator import DshScriptReadinessEvaluator
from rc7_runtime.models import EvaluationResult
from rc7_runtime.script_contract import CompiledScriptContract
from rc7_runtime.truth_overlay import append_entity


MISSION = "MISSION-DSH-SCRIPT"
DESIGN_ARTIFACT = "ART-DESIGN-PARENT-SCRIPT"
SCRIPT_TASK = "TASK-DSH-SCRIPT"
SCRIPT_ARTIFACT = "ART-DSH-SCRIPT"
WORKER = "worker-script-builder"


def _contract():
    frozen_case = {
        "tc_id": "TC-SCRIPT-1",
        "case_version": 1,
        "release_id": "RC7",
        "requirement_id": "REQ-SCRIPT-1",
        "sst_id": "SST-SCRIPT-1",
        "layer": "L3",
        "status": "FROZEN",
        "preconditions": ["loan exists"],
        "steps": ["query loan"],
        "expected": "loan returned",
        "oracle": {"checks": [{"type": "BUSINESS_RULE", "expected": "FOUND"}]},
        "evidence_requirements": ["api-response"],
    }
    spec = ExecutableSpecBuilder().build(
        case=frozen_case,
        target_requirements=("REQ-SCRIPT-1",),
        test_data_refs=("data://loan/1",),
        oracle_refs=("oracle://loan/found",),
        cleanup_policy={"required": False},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    return CompiledScriptContract(
        design_artifact_id=DESIGN_ARTIFACT,
        design_content_hash="sha256:accepted-design-parent",
        tc_id=spec.tc_id,
        frozen_case=frozen_case,
        spec=spec,
    )


def _runtime(tmp_path, *, source_text, binding_override=None, worker_validation_claim=None):
    truth = TruthRuntime(Path(tmp_path) / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=MISSION, release_id="RC7", goal="real Script readiness gate"),
    )
    parent_evidence = Evidence(
        evidence_id="EVD-DESIGN-PARENT-SCRIPT",
        mission_id=MISSION,
        kind="ACCEPTED_TEST_DESIGN",
        source_ref="source://design-parent",
        content_ref="evidence://design-parent",
        subject_refs=[DESIGN_ARTIFACT],
    )
    append_entity(truth, parent_evidence, release_id="RC7", artifact_version=1)
    append_entity(
        truth,
        Artifact(
            artifact_id=DESIGN_ARTIFACT,
            mission_id=MISSION,
            artifact_type="TEST_DESIGN_MODEL",
            producer_task_id="TASK-DESIGN-PARENT",
            content_ref="file://" + str((Path(tmp_path) / "unused-parent.json").resolve()),
            evidence_refs=[parent_evidence.evidence_id],
            content_hash="sha256:accepted-design-parent",
        ),
        release_id="RC7",
        artifact_version=1,
    )
    task = Task(
        task_id=SCRIPT_TASK,
        mission_id=MISSION,
        node="SCRIPT_READINESS",
        task_type="PRODUCE",
        objective="implement frozen executable spec",
        required_capabilities=["test_automation"],
        input_artifact_refs=[DESIGN_ARTIFACT],
    )
    control.register_task(task)
    leased = control.lease_next(worker_ref=WORKER, capabilities=["test_automation"])
    assert leased is not None
    control.start(SCRIPT_TASK, worker_ref=WORKER)

    contract = _contract()
    binding = {
        "spec_id": contract.spec.spec_id,
        "tc_id": contract.spec.tc_id,
        "case_version": contract.spec.case_version,
        "runner_type": contract.spec.runner_type,
        "case_fingerprint": contract.spec.case_fingerprint,
        "oracle_fingerprint": contract.spec.oracle_fingerprint,
        "design_content_hash": contract.design_content_hash,
    }
    if binding_override:
        binding.update(binding_override)
    semantic = {
        "binding": binding,
        "source_text": source_text,
        "test_symbol": "test_generated_script_case",
    }
    if worker_validation_claim is not None:
        semantic["validation"] = worker_validation_claim
        semantic["script_ready"] = True
    evidence = Evidence(
        evidence_id="EVD-SCRIPT-WORKER-CANDIDATE",
        mission_id=MISSION,
        kind="DSH_SCRIPT_BUILD_PROOF",
        source_ref="dsh://worker/%s" % WORKER,
        content_ref="evidence://script-worker-candidate",
        subject_refs=[SCRIPT_TASK],
    )
    envelope = {
        "task_id": SCRIPT_TASK,
        "artifact": {
            "artifact_id": SCRIPT_ARTIFACT,
            "artifact_type": "EXECUTABLE_SCRIPT",
            "content_ref": "worker://script-candidate",
            "parent_refs": [DESIGN_ARTIFACT],
            "evidence_refs": [evidence.evidence_id],
        },
        "semantic_payload": semantic,
        "evidence": [],
    }
    raw = (json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path = Path(tmp_path) / "script-candidate.json"
    path.write_bytes(raw)
    candidate = Artifact(
        artifact_id=SCRIPT_ARTIFACT,
        mission_id=MISSION,
        artifact_type="EXECUTABLE_SCRIPT",
        producer_task_id=SCRIPT_TASK,
        content_ref="file://" + str(path.resolve()),
        parent_refs=[DESIGN_ARTIFACT],
        evidence_refs=[evidence.evidence_id],
        content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
    )
    control.submit_worker_output(
        WorkerOutput(task_id=SCRIPT_TASK, worker_ref=WORKER, artifacts=(candidate,), evidence=(evidence,))
    )
    return truth, control, contract


def test_real_runtime_validation_is_sole_script_ready_authority(tmp_path):
    truth, control, contract = _runtime(
        tmp_path,
        source_text="def test_generated_script_case():\n    actual = 1\n    assert actual == 1\n",
    )

    evaluated = DshScriptReadinessEvaluator(
        evidence_root=str(Path(tmp_path) / "runtime-evidence"),
        validation_timeout_seconds=30,
    ).evaluate_and_apply(
        control,
        SCRIPT_TASK,
        SCRIPT_ARTIFACT,
        contract=contract,
        cwd=str(tmp_path),
    )

    assert evaluated.loop_result.evaluation.result == EvaluationResult.PASS
    assert evaluated.loop_result.script_ready is True
    assert evaluated.validation is not None and evaluated.validation.ready
    assert [step.name for step in evaluated.validation.steps] == [
        "python_compile",
        "pytest_collect",
        "fixture_dependency_resolution",
    ]
    assert control.scheduler.task(SCRIPT_TASK).state == TaskStatus.PASS
    assert evaluated.source_ref and evaluated.source_ref.startswith("file://")
    for evidence_id in evaluated.validation.evidence_refs:
        rows = truth.query("rc7_evidence", evidence_id=evidence_id)
        assert len(rows) == 1
        assert rows[0]["kind"] == "SCRIPT_READINESS_VALIDATION_PROOF"


def test_worker_fake_script_ready_claim_cannot_hide_real_compile_failure(tmp_path):
    _truth, control, contract = _runtime(
        tmp_path,
        source_text="def test_generated_script_case(:\n    pass\n",
        worker_validation_claim={"status": "SCRIPT_READY", "passed": True},
    )

    evaluated = DshScriptReadinessEvaluator(
        evidence_root=str(Path(tmp_path) / "runtime-evidence"),
        validation_timeout_seconds=30,
    ).evaluate_and_apply(
        control,
        SCRIPT_TASK,
        SCRIPT_ARTIFACT,
        contract=contract,
        cwd=str(tmp_path),
    )

    assert evaluated.loop_result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert evaluated.validation is not None and not evaluated.validation.ready
    assert any(gap.category == "SCRIPT_VALIDATION_FAILED" for gap in evaluated.loop_result.gaps)
    assert control.scheduler.task(SCRIPT_TASK).state == TaskStatus.REPAIR_REQUIRED


def test_worker_cannot_change_frozen_oracle_binding(tmp_path):
    _truth, control, contract = _runtime(
        tmp_path,
        source_text="def test_generated_script_case():\n    assert 1 == 1\n",
        binding_override={"oracle_fingerprint": "worker-changed-oracle"},
    )

    evaluated = DshScriptReadinessEvaluator(
        evidence_root=str(Path(tmp_path) / "runtime-evidence"),
    ).evaluate_and_apply(
        control,
        SCRIPT_TASK,
        SCRIPT_ARTIFACT,
        contract=contract,
        cwd=str(tmp_path),
    )

    assert evaluated.script is None
    assert evaluated.loop_result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert any(gap.category == "SCRIPT_BINDING_VIOLATION" for gap in evaluated.loop_result.gaps)
    assert control.scheduler.task(SCRIPT_TASK).state == TaskStatus.REPAIR_REQUIRED


def test_collectable_assert_true_placeholder_is_still_rejected(tmp_path):
    _truth, control, contract = _runtime(
        tmp_path,
        source_text="def test_generated_script_case():\n    assert True\n",
    )

    evaluated = DshScriptReadinessEvaluator(
        evidence_root=str(Path(tmp_path) / "runtime-evidence"),
        validation_timeout_seconds=30,
    ).evaluate_and_apply(
        control,
        SCRIPT_TASK,
        SCRIPT_ARTIFACT,
        contract=contract,
        cwd=str(tmp_path),
    )

    assert evaluated.validation is not None and evaluated.validation.ready
    assert evaluated.loop_result.evaluation.result == EvaluationResult.REPAIR_REQUIRED
    assert any(gap.category == "ASSERTION_IMPLEMENTATION_DEFECT" for gap in evaluated.loop_result.gaps)
    assert control.scheduler.task(SCRIPT_TASK).state == TaskStatus.REPAIR_REQUIRED
