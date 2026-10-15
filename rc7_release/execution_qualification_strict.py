"""RC7 strict formal Execution qualification.

Pipeline:
  strict SCRIPT_READY result
    -> import upstream proof into a new Execution Mission
    -> executable field EnvironmentAdapter admission
    -> runtime-owned precondition/data Preparation
    -> real runner / controlled L3 execution
    -> independent Oracle + Diagnosis + bounded Recovery
    -> durable result projection from R1.

Qualification PASS means the Execution control loop reached a trustworthy
conclusion. It does not mean the product test passed: a trusted PRODUCT FAIL is
reported as status=PASS, test_result=FAIL with a PRODUCT_DEFECT handoff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.autonomous_execution_service import AutonomousClosedLoopExecutionService
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.execution_environment import ExecutionEnvironmentAdmissionService
from rc7_runtime.models import Artifact, Evaluation, EvaluationResult, Evidence, Mission, Task, TaskStatus
from rc7_runtime.oracle_runtime import DeterministicOracleRuntime
from rc7_runtime.runtime_execution import StrictScriptExecutionBundleLoader
from rc7_runtime.truth_overlay import append_entity

from .execution_environment import ExecutionEnvironmentLoader


RELEASE_ID = "RC7-EXECUTION-REALITY"


class ExecutionQualificationError(RuntimeError):
    pass


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _runtime_key(state_root: Path) -> bytes:
    path = state_root / "control" / "authority.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(secrets.token_bytes(32))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    value = path.read_bytes()
    if len(value) < 16:
        raise ExecutionQualificationError("AUTHORITY_KEY_INVALID")
    return value


def _mission_event_count(truth: TruthRuntime, mission_id: str) -> int:
    return sum(
        1
        for event in truth.store.iter_raw()
        if isinstance(event.get("payload"), dict)
        and event["payload"].get("mission_id") == mission_id
    )


def _result_path(state_root: Path) -> Path:
    return state_root / "qualification" / "rc7-execution-result.json"


@dataclass(frozen=True)
class RC7ExecutionQualificationResult:
    status: str
    reason: Optional[str]
    mission_id: str
    task_id: Optional[str]
    script_result: str
    upstream_script_mission_id: Optional[str]
    upstream_script_task_id: Optional[str]
    upstream_script_evaluation_id: Optional[str]
    imported_script_artifact_id: Optional[str]
    environment_module: str
    environment_adapter_id: Optional[str]
    environment_admission_artifact_id: Optional[str]
    environment_evidence_ids: Tuple[str, ...]
    target_id: str
    layer: Optional[str]
    tc_id: Optional[str]
    initial_attempt_id: str
    preparation_artifact_id: Optional[str]
    preparation_evidence_ids: Tuple[str, ...]
    attempt_summaries: Tuple[Dict[str, Any], ...]
    retry_authorizations: Tuple[Dict[str, Any], ...]
    final_task_state: Optional[str]
    stopped_reason: Optional[str]
    converged: bool
    test_result: Optional[str]
    execution_conclusion: Optional[str]
    final_evaluation_id: Optional[str]
    gap_ids: Tuple[str, ...]
    gap_categories: Tuple[str, ...]
    product_defect_gap_ids: Tuple[str, ...]
    defect_task_ids: Tuple[str, ...]
    r1_event_count: int
    started_at: int
    finished_at: int


def _write_result(root: Path, result: RC7ExecutionQualificationResult) -> None:
    path = _result_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(result), ensure_ascii=False, sort_keys=True, indent=2, default=str),
        encoding="utf-8",
    )


def _base_result(
    *, root: Path,
    started: int,
    status: str,
    reason: Optional[str],
    mission_id: str,
    script_result: str,
    environment_module: str,
    target_id: str,
    attempt_id: str,
) -> RC7ExecutionQualificationResult:
    result = RC7ExecutionQualificationResult(
        status=status,
        reason=reason,
        mission_id=mission_id,
        task_id=None,
        script_result=script_result,
        upstream_script_mission_id=None,
        upstream_script_task_id=None,
        upstream_script_evaluation_id=None,
        imported_script_artifact_id=None,
        environment_module=environment_module,
        environment_adapter_id=None,
        environment_admission_artifact_id=None,
        environment_evidence_ids=(),
        target_id=target_id,
        layer=None,
        tc_id=None,
        initial_attempt_id=attempt_id,
        preparation_artifact_id=None,
        preparation_evidence_ids=(),
        attempt_summaries=(),
        retry_authorizations=(),
        final_task_state=None,
        stopped_reason=None,
        converged=False,
        test_result=None,
        execution_conclusion=None,
        final_evaluation_id=None,
        gap_ids=(),
        gap_categories=(),
        product_defect_gap_ids=(),
        defect_task_ids=(),
        r1_event_count=0,
        started_at=started,
        finished_at=int(time.time()),
    )
    _write_result(root, result)
    return result


def _import_script_pass(
    control: ClosedLoopControlPlane,
    *,
    state_root: Path,
    script_result_path: Path,
    bundle,
) -> Tuple[str, str]:
    raw = script_result_path.read_bytes()
    source_digest = hashlib.sha256(raw).hexdigest()
    mission_id = control.mission_id
    task_id = _stable_id("TASK-IMPORT-SCRIPT", mission_id, str(script_result_path), source_digest)
    artifact_id = _stable_id("ART-IMPORT-SCRIPT", mission_id, str(script_result_path), source_digest)
    evidence_id = _stable_id("EVD-IMPORT-SCRIPT", mission_id, str(script_result_path), source_digest)
    evaluation_id = _stable_id("EVAL-IMPORT-SCRIPT", mission_id, str(script_result_path), source_digest)

    folder = state_root / "qualification" / "imported-script"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (artifact_id + ".json")
    payload = {
        "upstream_result_file": str(script_result_path),
        "upstream_mission_id": bundle.upstream_mission_id,
        "upstream_task_id": bundle.upstream_task_id,
        "upstream_evaluation_id": bundle.upstream_evaluation_id,
        "spec_ref": bundle.spec_ref,
        "script_id": bundle.script.script_id,
        "source_ref": bundle.script.source_ref,
        "source_sha256": bundle.source_sha256,
        "validation_id": bundle.validation.validation_id,
        "validation_status": bundle.validation.status,
        "result_sha256": source_digest,
    }
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    target.write_bytes(encoded)
    imported_digest = hashlib.sha256(encoded).hexdigest()

    append_entity(
        control.truth,
        Evidence(
            evidence_id=evidence_id,
            mission_id=mission_id,
            kind="UPSTREAM_SCRIPT_READY_PASS_PROOF",
            source_ref=str(script_result_path),
            content_ref="file://" + str(target),
            subject_refs=[task_id, artifact_id, bundle.upstream_task_id, bundle.upstream_evaluation_id],
            content_hash="sha256:" + source_digest,
        ),
        release_id=control.release_id,
        artifact_version=1,
    )
    append_entity(
        control.truth,
        Artifact(
            artifact_id=artifact_id,
            mission_id=mission_id,
            artifact_type="SCRIPT_READY_IMPORT",
            producer_task_id=task_id,
            content_ref="file://" + str(target),
            evidence_refs=[evidence_id],
            content_hash="sha256:" + imported_digest,
        ),
        release_id=control.release_id,
        artifact_version=1,
    )
    append_entity(
        control.truth,
        Evaluation(
            evaluation_id=evaluation_id,
            mission_id=mission_id,
            node="SCRIPT_READINESS",
            artifact_refs=[artifact_id],
            result=EvaluationResult.PASS,
            evaluator_ref="rc7-strict-script-execution-bundle-loader",
            dimensions={
                "strict_script_truth_reverified": True,
                "validation_status": bundle.validation.status,
                "upstream_mission_id": bundle.upstream_mission_id,
                "upstream_task_id": bundle.upstream_task_id,
                "upstream_evaluation_id": bundle.upstream_evaluation_id,
            },
            evidence_refs=[evidence_id],
        ),
        release_id=control.release_id,
        artifact_version=1,
    )
    append_entity(
        control.truth,
        Task(
            task_id=task_id,
            mission_id=mission_id,
            node="SCRIPT_READINESS",
            task_type="IMPORTED_UPSTREAM_PASS",
            objective="import strict SCRIPT_READY truth for formal Execution",
            state=TaskStatus.PASS,
            output_artifact_refs=[artifact_id],
            evaluation_id=evaluation_id,
        ),
        release_id=control.release_id,
        artifact_version=1,
    )
    return task_id, artifact_id


def _safe_execution_env(adapter, *, target_id: str, layer: str, workspace: Path, run_cwd: Path) -> Dict[str, str]:
    raw = adapter.execution_env(target_id=target_id, layer=layer)
    if not isinstance(raw, Mapping):
        raise ExecutionQualificationError("EXECUTION_ENVIRONMENT_ENV_MAPPING_REQUIRED")
    env = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key or not isinstance(value, str):
            raise ExecutionQualificationError("EXECUTION_ENVIRONMENT_ENV_STRING_REQUIRED")
        env[key] = value
    existing_pythonpath = os.environ.get("PYTHONPATH")
    paths = [str(run_cwd), str(workspace)]
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["PFC_WORKSPACE"] = str(workspace)
    env["PFC_AITEST_HOME"] = str(workspace)
    return env


def _attempt_summary(item) -> Dict[str, Any]:
    evaluation = item.loop_result.evaluation
    return {
        "attempt_id": item.execution_record.attempt_id,
        "status": item.execution_record.status,
        "integrity_passed": item.execution_record.integrity_passed,
        "assertion_passed": item.execution_record.assertion_passed,
        "reason": item.execution_record.reason,
        "test_result": item.loop_result.test_result,
        "task_state": item.task_state,
        "evaluation_id": evaluation.evaluation_id,
        "evaluation_result": evaluation.result.value,
        "failure_class": evaluation.dimensions.get("failure_class"),
        "recovery_action": evaluation.dimensions.get("recovery_action"),
        "gap_refs": list(evaluation.gap_refs),
        "evidence_ids": list(item.evidence_ids),
    }


def run_execution_qualification(
    *,
    state_root: str,
    workspace: str,
    script_result: str,
    environment_module: str,
    target_id: str,
    attempt_id: Optional[str] = None,
    execution_cwd: Optional[str] = None,
    target_base_url: Optional[str] = None,
    timeout_seconds: int = 300,
    max_cycles: int = 4,
    max_transient_retries: int = 2,
) -> RC7ExecutionQualificationResult:
    started = int(time.time())
    root = Path(state_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    workspace_path = Path(workspace).expanduser().resolve()
    mission_id = "RC7-EXECUTION-" + uuid.uuid4().hex[:12]
    attempt = attempt_id or ("ATT-RC7-" + uuid.uuid4().hex)

    if not workspace_path.is_dir():
        return _base_result(
            root=root, started=started, status="NOT_PROVEN", reason="WORKSPACE_NOT_FOUND",
            mission_id=mission_id, script_result=script_result,
            environment_module=environment_module, target_id=target_id, attempt_id=attempt,
        )
    if not script_result:
        return _base_result(
            root=root, started=started, status="NOT_PROVEN", reason="SCRIPT_RESULT_REQUIRED",
            mission_id=mission_id, script_result=script_result,
            environment_module=environment_module, target_id=target_id, attempt_id=attempt,
        )
    if not environment_module:
        return _base_result(
            root=root, started=started, status="NOT_PROVEN", reason="EXECUTION_ENVIRONMENT_MODULE_REQUIRED",
            mission_id=mission_id, script_result=script_result,
            environment_module=environment_module, target_id=target_id, attempt_id=attempt,
        )
    if not target_id:
        return _base_result(
            root=root, started=started, status="NOT_PROVEN", reason="EXECUTION_TARGET_ID_REQUIRED",
            mission_id=mission_id, script_result=script_result,
            environment_module=environment_module, target_id=target_id, attempt_id=attempt,
        )

    run_cwd = Path(execution_cwd).expanduser().resolve() if execution_cwd else workspace_path
    if not run_cwd.is_dir():
        return _base_result(
            root=root, started=started, status="NOT_PROVEN", reason="EXECUTION_CWD_NOT_FOUND",
            mission_id=mission_id, script_result=script_result,
            environment_module=environment_module, target_id=target_id, attempt_id=attempt,
        )

    script_path = Path(script_result).expanduser().resolve()
    try:
        bundle = StrictScriptExecutionBundleLoader(
            evidence_root=str(root / "evidence" / "script-revalidation"),
            validation_timeout_seconds=timeout_seconds,
        ).load(str(script_path), cwd=str(run_cwd), env={"PYTHONPATH": str(run_cwd) + os.pathsep + str(workspace_path)})
        if bundle.spec.layer == "L3" and not target_base_url:
            raise ExecutionQualificationError("L3_TARGET_BASE_URL_REQUIRED")

        if str(workspace_path) not in sys.path:
            sys.path.insert(0, str(workspace_path))
        loaded = ExecutionEnvironmentLoader.load(environment_module)

        truth = TruthRuntime(root / "r1.jsonl")
        control = ClosedLoopControlPlane.bootstrap(
            truth,
            Mission(
                mission_id=mission_id,
                release_id=RELEASE_ID,
                goal="prove runtime-owned formal Execution from strict SCRIPT_READY truth",
            ),
        )
        imported_task_id, imported_artifact_id = _import_script_pass(
            control,
            state_root=root,
            script_result_path=script_path,
            bundle=bundle,
        )
        execution_task_id = _stable_id("TASK-EXECUTION", mission_id, bundle.spec.tc_id, attempt)
        control.register_task(
            Task(
                task_id=execution_task_id,
                mission_id=mission_id,
                node="EXECUTION",
                task_type="EXECUTE",
                objective="prepare and formally execute %s using runtime-owned evidence" % bundle.spec.tc_id,
                required_capabilities=["test_execution"],
                dependency_task_ids=[imported_task_id],
                input_artifact_refs=[imported_artifact_id],
            )
        )
        task = control.scheduler.task(execution_task_id)
        if task.state != TaskStatus.READY:
            raise ExecutionQualificationError("EXECUTION_TASK_NOT_READY_AFTER_SCRIPT_IMPORT")

        admission_service = ExecutionEnvironmentAdmissionService(
            evidence_root=str(root / "evidence")
        )
        admission = admission_service.admit(
            control,
            execution_task_id,
            adapter=loaded.adapter,
            target_id=target_id,
            layer=bundle.spec.layer,
        )
        precondition_resolvers, data_strategies, data_verifier, human_gate = (
            admission_service.preparation_callbacks(loaded.adapter, bundle.frozen_case)
        )
        env = _safe_execution_env(
            loaded.adapter,
            target_id=target_id,
            layer=bundle.spec.layer,
            workspace=workspace_path,
            run_cwd=run_cwd,
        )

        service = AutonomousClosedLoopExecutionService(
            evidence_root=str(root / "evidence"),
            timeout_seconds=timeout_seconds,
            max_cycles=max_cycles,
            max_transient_retries=max_transient_retries,
        )
        common = dict(
            control=control,
            task_id=execution_task_id,
            bundle=bundle,
            attempt_id=attempt,
            target_id=target_id,
            precondition_resolvers=precondition_resolvers,
            data_strategies=data_strategies,
            data_verifier=data_verifier,
            human_gate=human_gate,
            authority=RC7AuthorityRuntime(_runtime_key(root)),
            tool_broker=admission.broker,
            cwd=str(run_cwd),
            env=env,
            diagnosis_trust=admission.diagnosis_trust,
            cat_query=loaded.adapter.query_cat if "cat" in admission.diagnostic_tools else None,
        )
        if bundle.spec.layer == "L3":
            closed = service.prepare_and_execute_l3(
                target_base_url=str(target_base_url),
                **common
            )
        else:
            closed = service.prepare_and_execute_generic(
                oracle_evaluator=DeterministicOracleRuntime(),
                **common
            )

        attempts = tuple(_attempt_summary(item) for item in closed.execution.attempts)
        authorizations = tuple(
            {
                "source_task_id": item.source_task_id,
                "repair_task_id": item.repair_task_id,
                "gap_id": item.gap_id,
                "plan_artifact_id": item.plan_artifact_id,
                "plan_evidence_id": item.plan_evidence_id,
                "successor_attempt_id": item.successor_attempt_id,
            }
            for item in closed.execution.authorizations
        )
        final = closed.execution.attempts[-1] if closed.execution.attempts else None
        final_test_result = final.loop_result.test_result if final is not None else None
        final_evaluation_id = final.loop_result.evaluation.evaluation_id if final is not None else None

        gap_rows = truth.query("rc7_gap", mission_id=mission_id)
        gap_ids = tuple(str(row["gap_id"]) for row in gap_rows)
        gap_categories = tuple(str(row["category"]) for row in gap_rows)
        product_gap_ids = tuple(
            str(row["gap_id"]) for row in gap_rows if row.get("category") == "PRODUCT_DEFECT"
        )
        defect_task_ids = tuple(
            str(row["task_id"])
            for row in truth.query("rc7_task", mission_id=mission_id)
            if row.get("node") == "DEFECT" and row.get("task_type") == "QUALIFY_DEFECT"
        )

        final_state = closed.execution.final_task_state
        if closed.execution.converged and final_state == "PASS":
            status = "PASS"
            reason = None
        elif final_state == "BLOCKED":
            status = "BLOCKED"
            reason = closed.execution.stopped_reason
        elif final_state in {"REPAIR_REQUIRED", "HUMAN_REQUIRED"}:
            status = "REPAIR_REQUIRED"
            reason = closed.execution.stopped_reason
        else:
            status = "FAIL"
            reason = closed.execution.stopped_reason

        if final_test_result == "PASS" and status == "PASS":
            conclusion = "TRUSTWORTHY_PASS"
        elif final_test_result == "FAIL" and product_gap_ids and status == "PASS":
            conclusion = "TRUSTWORTHY_PRODUCT_FAIL"
        elif final_test_result == "BLOCKED" or final_state == "BLOCKED":
            conclusion = "TRUSTWORTHY_BLOCKED"
        else:
            conclusion = "NOT_YET_CONCLUSIVE"

        result = RC7ExecutionQualificationResult(
            status=status,
            reason=reason,
            mission_id=mission_id,
            task_id=execution_task_id,
            script_result=str(script_path),
            upstream_script_mission_id=bundle.upstream_mission_id,
            upstream_script_task_id=bundle.upstream_task_id,
            upstream_script_evaluation_id=bundle.upstream_evaluation_id,
            imported_script_artifact_id=imported_artifact_id,
            environment_module=loaded.module_name,
            environment_adapter_id=admission.adapter_id,
            environment_admission_artifact_id=admission.artifact_id,
            environment_evidence_ids=admission.evidence_ids,
            target_id=target_id,
            layer=bundle.spec.layer,
            tc_id=bundle.spec.tc_id,
            initial_attempt_id=attempt,
            preparation_artifact_id=closed.preparation.artifact_id,
            preparation_evidence_ids=closed.preparation.evidence_ids,
            attempt_summaries=attempts,
            retry_authorizations=authorizations,
            final_task_state=final_state,
            stopped_reason=closed.execution.stopped_reason,
            converged=closed.execution.converged,
            test_result=final_test_result,
            execution_conclusion=conclusion,
            final_evaluation_id=final_evaluation_id,
            gap_ids=gap_ids,
            gap_categories=gap_categories,
            product_defect_gap_ids=product_gap_ids,
            defect_task_ids=defect_task_ids,
            r1_event_count=_mission_event_count(truth, mission_id),
            started_at=started,
            finished_at=int(time.time()),
        )
    except Exception as exc:
        result = _base_result(
            root=root,
            started=started,
            status="FAIL",
            reason="%s:%s" % (type(exc).__name__, exc),
            mission_id=mission_id,
            script_result=str(script_path),
            environment_module=environment_module,
            target_id=target_id,
            attempt_id=attempt,
        )
        return result

    _write_result(root, result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="RC7 strict runtime-owned Execution qualification")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--workspace", default=os.environ.get("PFC_WORKSPACE") or str(Path.cwd()))
    parser.add_argument("--script-result", default=os.environ.get("PFC_RC7_SCRIPT_RESULT") or "")
    parser.add_argument("--environment-module", default=os.environ.get("PFC_RC7_EXECUTION_ENV_MODULE") or "")
    parser.add_argument("--target-id", default=os.environ.get("PFC_RC7_EXECUTION_TARGET_ID") or "")
    parser.add_argument("--attempt-id", default=os.environ.get("PFC_RC7_EXECUTION_ATTEMPT_ID"))
    parser.add_argument("--execution-cwd", default=os.environ.get("PFC_RC7_EXECUTION_CWD"))
    parser.add_argument("--target-base-url", default=os.environ.get("PFC_RC7_TARGET_BASE_URL"))
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--max-cycles", type=int, default=4)
    parser.add_argument("--max-transient-retries", type=int, default=2)
    args = parser.parse_args(argv)
    result = run_execution_qualification(
        state_root=args.state_root,
        workspace=args.workspace,
        script_result=args.script_result,
        environment_module=args.environment_module,
        target_id=args.target_id,
        attempt_id=args.attempt_id,
        execution_cwd=args.execution_cwd,
        target_base_url=args.target_base_url,
        timeout_seconds=args.timeout_seconds,
        max_cycles=args.max_cycles,
        max_transient_retries=args.max_transient_retries,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True, default=str))
    if result.status == "PASS":
        return 0
    if result.status in {"NOT_PROVEN", "BLOCKED", "REPAIR_REQUIRED"}:
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
