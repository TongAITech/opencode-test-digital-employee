from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Mapping, Tuple

from rc7_runtime import (
    Artifact,
    Evidence,
    Evaluation,
    EvaluationResult,
    Task,
    TaskStatus,
)
from rc7_runtime.dsh_script_execution_guard import DshExecutionReadyScriptEvaluator
from rc7_runtime.truth_overlay import append_entity

from . import script_qualification as legacy


_L3_CONTROLLED_API_GUIDANCE = (
    " L3 FORMAL EXECUTION CONTRACT: the generated script MUST send every business HTTP request through the loopback URL "
    "provided at execution time in RC7_API_RUNTIME_PROXY_URL. The script sends a JSON command to that URL with method, "
    "target-relative path, optional headers/body, and capture_as=actual_result for exactly the response that feeds the Oracle. "
    "Do not hard-code or directly call the business target host. Do not use rc6_runtime.runner_manifest.record_tool_call or "
    "record_actual_result to claim api-runtime evidence/results: formal L3 Execution discards child-authored API claims and accepts "
    "only parent-owned APIREC receipts from the controlled proxy. Readiness will reject L3 source that does not bind the proxy or "
    "that self-attests tool calls/results."
)


def _fixed_import_accepted_design(
    control,
    *,
    state_root: Path,
    upstream_result_path: Path,
    upstream_result: Mapping[str, object],
    envelope: Mapping[str, object],
    raw: bytes,
) -> Tuple[str, str]:
    """Import an upstream PASS as evidence, then re-evaluate it in this Mission."""
    mission_id = control.mission_id
    producer_task_id = legacy._stable_id(
        "TASK-IMPORT-DESIGN", mission_id, str(upstream_result_path)
    )
    artifact_id = legacy._stable_id(
        "ART-IMPORT-DESIGN", mission_id, str(upstream_result_path)
    )
    evidence_id = legacy._stable_id(
        "EVD-IMPORT-DESIGN", mission_id, str(upstream_result_path)
    )
    evaluation_id = legacy._stable_id(
        "EVAL-IMPORT-DESIGN",
        mission_id,
        str(upstream_result_path),
        str(upstream_result.get("mission_id") or ""),
        str(upstream_result.get("evaluation_id") or ""),
        hashlib.sha256(raw).hexdigest(),
    )

    folder = state_root / "qualification" / "imported-design"
    folder.mkdir(parents=True, exist_ok=True)
    relative = Path("qualification") / "imported-design" / (artifact_id + ".json")
    target = state_root / relative
    imported = {
        "task_id": producer_task_id,
        "artifact": {
            "artifact_id": artifact_id,
            "artifact_type": "TEST_DESIGN_MODEL",
            "content_ref": "upstream-result://%s" % upstream_result_path,
            "parent_refs": [],
            "evidence_refs": [evidence_id],
        },
        "semantic_payload": dict(envelope["semantic_payload"]),
        "evidence": [],
        "upstream_provenance": {
            "result_file": str(upstream_result_path),
            "upstream_mission_id": upstream_result.get("mission_id"),
            "upstream_task_id": upstream_result.get("task_id"),
            "upstream_evaluation_id": upstream_result.get("evaluation_id"),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
        },
    }
    encoded = (
        json.dumps(imported, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    target.write_bytes(encoded)

    append_entity(
        control.truth,
        Evidence(
            evidence_id=evidence_id,
            mission_id=mission_id,
            kind="UPSTREAM_TEST_DESIGN_PASS_PROOF",
            source_ref=str(upstream_result_path),
            content_ref="file://" + str(target),
            subject_refs=[producer_task_id, artifact_id],
            content_hash="sha256:" + hashlib.sha256(raw).hexdigest(),
        ),
        release_id=control.release_id,
        artifact_version=1,
    )
    append_entity(
        control.truth,
        Artifact(
            artifact_id=artifact_id,
            mission_id=mission_id,
            artifact_type="TEST_DESIGN_MODEL",
            producer_task_id=producer_task_id,
            content_ref="file://" + str(target),
            evidence_refs=[evidence_id],
            content_hash="sha256:" + hashlib.sha256(encoded).hexdigest(),
        ),
        release_id=control.release_id,
        artifact_version=1,
    )
    append_entity(
        control.truth,
        Evaluation(
            evaluation_id=evaluation_id,
            mission_id=mission_id,
            node="TEST_DESIGN",
            artifact_refs=[artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="runtime://upstream-test-design-import-verifier",
            dimensions={
                "imported_upstream_pass": True,
                "upstream_result_file": str(upstream_result_path),
                "upstream_mission_id": str(upstream_result.get("mission_id") or ""),
                "upstream_task_id": str(upstream_result.get("task_id") or ""),
                "upstream_evaluation_id": str(upstream_result.get("evaluation_id") or ""),
                "upstream_artifact_sha256": hashlib.sha256(raw).hexdigest(),
            },
            evidence_refs=[evidence_id],
        ),
        release_id=control.release_id,
        artifact_version=1,
    )
    append_entity(
        control.truth,
        Task(
            task_id=producer_task_id,
            mission_id=mission_id,
            node="TEST_DESIGN",
            task_type="IMPORTED_UPSTREAM_PASS",
            objective="import previously qualified Test Design truth for Script readiness",
            state=TaskStatus.PASS,
            output_artifact_refs=[artifact_id],
            evaluation_id=evaluation_id,
        ),
        release_id=control.release_id,
        artifact_version=1,
    )
    return artifact_id, relative.as_posix()


def _install_strict_overrides():
    original_import = legacy._import_accepted_design
    original_objective = legacy._worker_objective
    original_evaluator = legacy.DshScriptReadinessEvaluator

    def strict_objective(*, contract, imported_design_path, reuse_targets):
        text = original_objective(
            contract=contract,
            imported_design_path=imported_design_path,
            reuse_targets=reuse_targets,
        )
        if str(contract.spec.layer).upper() == "L3":
            text += _L3_CONTROLLED_API_GUIDANCE
        return text

    legacy._import_accepted_design = _fixed_import_accepted_design
    legacy._worker_objective = strict_objective
    legacy.DshScriptReadinessEvaluator = DshExecutionReadyScriptEvaluator
    return original_import, original_objective, original_evaluator


def _restore_strict_overrides(originals) -> None:
    original_import, original_objective, original_evaluator = originals
    legacy._import_accepted_design = original_import
    legacy._worker_objective = original_objective
    legacy.DshScriptReadinessEvaluator = original_evaluator


def run_strict_script_qualification(**kwargs):
    originals = _install_strict_overrides()
    try:
        return legacy.run_real_script_qualification(**kwargs)
    finally:
        _restore_strict_overrides(originals)


def main(argv=None) -> int:
    originals = _install_strict_overrides()
    try:
        return legacy.main(argv)
    finally:
        _restore_strict_overrides(originals)


if __name__ == "__main__":
    sys.exit(main())
