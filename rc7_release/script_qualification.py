from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime.agent_runtime import AgentRuntimeError
from rc6_runtime.automation import AutomationReuseResolver
from rc6_runtime.truth import TruthRuntime
from rc7_runtime import Artifact, Evidence, Mission, Task, TaskStatus
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.candidate_payload import CandidatePayloadReader
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.dsh_proof import DshR1ProofReader
from rc7_runtime.dsh_reality_launcher import RC7BankFinalDshHeadlessWorkerLauncher
from rc7_runtime.dsh_script_evaluator import DshScriptReadinessEvaluator
from rc7_runtime.dsh_worker_bridge import DshNodePolicy, DshTaskWorkerBridge
from rc7_runtime.mission_graph import MissionTaskGraphCompiler
from rc7_runtime.script_contract import AcceptedTestDesignScriptContractCompiler, CompiledScriptContract
from rc7_runtime.truth_overlay import append_entity

from .dsh import write_patch


RELEASE_ID = "RC7-DSH-SCRIPT-REALITY"
READ_TEXT_TOOL = "mcp__pfc_aitest_rc7__read_text"


@dataclass(frozen=True)
class RC7ScriptQualificationResult:
    status: str
    reason: Optional[str]
    mission_id: str
    task_id: Optional[str]
    test_design_result: str
    tc_id: str
    runner_type: Optional[str]
    spec_id: Optional[str]
    spec_ref: Optional[str]
    case_fingerprint: Optional[str]
    oracle_fingerprint: Optional[str]
    automation_reuse_candidate_count: int
    automation_reuse_used_count: int
    worker_id: Optional[str]
    dsh_session_id: Optional[str]
    source_ref: Optional[str]
    validation_id: Optional[str]
    validation_status: Optional[str]
    validation_evidence_ids: Tuple[str, ...]
    task_state: Optional[str]
    evaluation_id: Optional[str]
    evaluation_result: Optional[str]
    candidate_artifact_ref: Optional[str]
    raw_output_ref: Optional[str]
    r1_event_count: int
    started_at: int
    finished_at: int


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
    key = path.read_bytes()
    if len(key) < 16:
        raise AgentRuntimeError("AUTHORITY_KEY_INVALID")
    return key


def _resolve_dsh(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    return os.environ.get("PFC_DSH_BIN") or shutil.which("dsh") or ""


def _result_path(state_root: Path) -> Path:
    return state_root / "qualification" / "rc7-dsh-script-result.json"


def _write_result(state_root: Path, result: RC7ScriptQualificationResult) -> None:
    path = _result_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def _mission_event_count(truth: TruthRuntime, mission_id: str) -> int:
    return sum(
        1
        for event in truth.store.iter_raw()
        if isinstance(event.get("payload"), dict) and event["payload"].get("mission_id") == mission_id
    )


def _load_strict_design_result(path_value: str) -> Tuple[Path, Dict[str, object], TruthRuntime, Dict[str, object], bytes]:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise AgentRuntimeError("TEST_DESIGN_RESULT_NOT_FOUND:%s" % path_value)
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentRuntimeError("TEST_DESIGN_RESULT_JSON_INVALID") from exc
    if not isinstance(result, dict):
        raise AgentRuntimeError("TEST_DESIGN_RESULT_NOT_OBJECT")
    if result.get("status") != "PASS" or result.get("evaluation_result") != "PASS":
        raise AgentRuntimeError("UPSTREAM_TEST_DESIGN_NOT_PASS")
    mission_id = result.get("mission_id")
    task_id = result.get("task_id")
    evaluation_id = result.get("evaluation_id")
    artifact_ref = result.get("artifact_ref")
    if not all(isinstance(value, str) and value for value in (mission_id, task_id, evaluation_id, artifact_ref)):
        raise AgentRuntimeError("UPSTREAM_TEST_DESIGN_IDENTITY_INCOMPLETE")
    if not str(artifact_ref).startswith("file://"):
        raise AgentRuntimeError("UPSTREAM_TEST_DESIGN_ARTIFACT_FILE_REQUIRED")
    state_root = path.parent.parent
    truth = TruthRuntime(state_root / "r1.jsonl")
    task_rows = truth.query("rc7_task", task_id=task_id)
    if len(task_rows) != 1 or task_rows[0].get("state") != "PASS" or task_rows[0].get("evaluation_id") != evaluation_id:
        raise AgentRuntimeError("UPSTREAM_TEST_DESIGN_TASK_TRUTH_NOT_PASS")
    evaluation_rows = truth.query("rc7_evaluation", evaluation_id=evaluation_id)
    if len(evaluation_rows) != 1 or evaluation_rows[0].get("result") != "PASS":
        raise AgentRuntimeError("UPSTREAM_TEST_DESIGN_EVALUATION_TRUTH_NOT_PASS")
    dimensions = evaluation_rows[0].get("dimensions", {})
    if not isinstance(dimensions, dict):
        raise AgentRuntimeError("UPSTREAM_TEST_DESIGN_DIMENSIONS_INVALID")
    if dimensions.get("parent_obligation_coverage") != "PASS":
        raise AgentRuntimeError("UPSTREAM_TEST_DESIGN_PARENT_COVERAGE_NOT_PASS")
    if dimensions.get("execution_contract_ready") is not True:
        raise AgentRuntimeError("UPSTREAM_TEST_DESIGN_EXECUTION_CONTRACT_NOT_READY")
    artifact_path = Path(str(artifact_ref)[len("file://"):]).resolve()
    if not artifact_path.is_file():
        raise AgentRuntimeError("UPSTREAM_TEST_DESIGN_ARTIFACT_MISSING")
    raw = artifact_path.read_bytes()
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentRuntimeError("UPSTREAM_TEST_DESIGN_ARTIFACT_JSON_INVALID") from exc
    if not isinstance(envelope, dict) or not isinstance(envelope.get("semantic_payload"), dict):
        raise AgentRuntimeError("UPSTREAM_TEST_DESIGN_SEMANTIC_PAYLOAD_REQUIRED")
    declared = envelope.get("artifact")
    if not isinstance(declared, dict) or declared.get("artifact_type") != "TEST_DESIGN_MODEL":
        raise AgentRuntimeError("UPSTREAM_TEST_DESIGN_ARTIFACT_TYPE_MISMATCH")
    return path, result, truth, envelope, raw


def _import_accepted_design(
    control: ClosedLoopControlPlane,
    *,
    state_root: Path,
    upstream_result_path: Path,
    upstream_result: Mapping[str, object],
    envelope: Mapping[str, object],
    raw: bytes,
) -> Tuple[str, str]:
    mission_id = control.mission_id
    producer_task_id = _stable_id("TASK-IMPORT-DESIGN", mission_id, str(upstream_result_path))
    artifact_id = _stable_id("ART-IMPORT-DESIGN", mission_id, str(upstream_result_path))
    evidence_id = _stable_id("EVD-IMPORT-DESIGN", mission_id, str(upstream_result_path))
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
    encoded = (json.dumps(imported, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
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
        Task(
            task_id=producer_task_id,
            mission_id=mission_id,
            node="TEST_DESIGN",
            task_type="IMPORTED_UPSTREAM_PASS",
            objective="import previously qualified Test Design truth for Script readiness",
            state=TaskStatus.PASS,
            output_artifact_refs=[artifact_id],
            evaluation_id=str(upstream_result.get("evaluation_id") or "imported-pass"),
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
    return artifact_id, relative.as_posix()


def _persist_contract(state_root: Path, contract: CompiledScriptContract) -> str:
    folder = state_root / "qualification" / "executable-specs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (contract.spec.spec_id + ".json")
    payload = {
        "design_artifact_id": contract.design_artifact_id,
        "design_content_hash": contract.design_content_hash,
        "tc_id": contract.tc_id,
        "frozen_case": contract.frozen_case,
        "spec": asdict(contract.spec),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str), encoding="utf-8")
    return "file://" + str(path)


def _reuse_candidate_refs(mapping: Mapping[str, object]) -> List[str]:
    reuse = mapping.get("reuse", {}) if isinstance(mapping, Mapping) else {}
    result = []
    if isinstance(reuse, dict):
        for values in reuse.values():
            if isinstance(values, list):
                result.extend(value for value in values if isinstance(value, str) and value)
    return list(dict.fromkeys(result))


def _workspace_read_targets(refs: Sequence[str], workspace: Path) -> Dict[str, str]:
    targets = {}
    root = workspace.resolve()
    for ref in refs:
        if not ref.startswith("file://"):
            continue
        path = Path(ref[len("file://"):]).resolve()
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        targets[ref] = relative.as_posix()
    return targets


def _worker_objective(
    *,
    contract: CompiledScriptContract,
    imported_design_path: str,
    reuse_targets: Mapping[str, str],
) -> str:
    binding = {
        "spec_id": contract.spec.spec_id,
        "tc_id": contract.spec.tc_id,
        "case_version": contract.spec.case_version,
        "runner_type": contract.spec.runner_type,
        "case_fingerprint": contract.spec.case_fingerprint,
        "oracle_fingerprint": contract.spec.oracle_fingerprint,
        "design_content_hash": contract.design_content_hash,
    }
    return (
        "Implement exactly one RC7 frozen ExecutableTestSpec. You MUST first call %s with "
        "{path:%s,scope:state} to read the accepted Test Design parent. Do not change any binding, Case step, "
        "precondition, expected result, Oracle, cleanup policy, data ref, or runner. Runtime will validate all of them. "
        "Automation reuse candidates are %s. If you actually reuse any candidate, include its file:// ref in "
        "semantic_payload.reuse_refs_used and call %s with its workspace-relative path before using it. "
        "If none is suitable, return reuse_refs_used=[] and implement a new script. Do NOT execute the business test "
        "and do NOT claim validation/SCRIPT_READY. semantic_payload MUST contain binding=%s, source_text with the full "
        "generated source, test_symbol, and reuse_refs_used. PYTEST source must contain real non-placeholder assertion/oracle "
        "logic; JUNIT source must implement the specified test method. Return only candidate output; Runtime owns validation. "
        "EXECUTABLE_SPEC=%s"
    ) % (
        READ_TEXT_TOOL,
        imported_design_path,
        json.dumps(reuse_targets, ensure_ascii=False, sort_keys=True),
        READ_TEXT_TOOL,
        json.dumps(binding, ensure_ascii=False, sort_keys=True),
        json.dumps(asdict(contract.spec), ensure_ascii=False, sort_keys=True, default=str),
    )


def _verify_read_proof(
    truth: TruthRuntime,
    *,
    mission_id: str,
    worker_id: str,
    design_path: str,
    used_refs: Sequence[str],
    reuse_targets: Mapping[str, str],
) -> Optional[str]:
    proofs = DshR1ProofReader().tool_calls(truth, mission_id=mission_id, worker_instance_id=worker_id)

    def has(path: str, scope: str) -> bool:
        for proof in proofs:
            if proof.tool_name != READ_TEXT_TOOL or not isinstance(proof.arguments, dict):
                continue
            if proof.arguments.get("path") == path and proof.arguments.get("scope") == scope:
                return True
        return False

    if not has(design_path, "state"):
        return "SCRIPT_WORKER_DESIGN_READ_ARGUMENT_PROOF_MISSING"
    for ref in used_refs:
        target = reuse_targets.get(ref)
        if target is None:
            return "SCRIPT_REUSE_REF_NOT_RUNTIME_CANDIDATE:%s" % ref
        if not has(target, "workspace"):
            return "SCRIPT_REUSE_READ_ARGUMENT_PROOF_MISSING:%s" % ref
    return None


def _not_proven(
    *, state_root: Path, started: int, mission_id: str, reason: str,
    test_design_result: str, tc_id: str,
) -> RC7ScriptQualificationResult:
    result = RC7ScriptQualificationResult(
        status="NOT_PROVEN", reason=reason, mission_id=mission_id, task_id=None,
        test_design_result=test_design_result, tc_id=tc_id, runner_type=None,
        spec_id=None, spec_ref=None, case_fingerprint=None, oracle_fingerprint=None,
        automation_reuse_candidate_count=0, automation_reuse_used_count=0,
        worker_id=None, dsh_session_id=None, source_ref=None, validation_id=None,
        validation_status=None, validation_evidence_ids=(), task_state=None,
        evaluation_id=None, evaluation_result=None, candidate_artifact_ref=None,
        raw_output_ref=None, r1_event_count=0, started_at=started,
        finished_at=int(time.time()),
    )
    _write_result(state_root, result)
    return result


def run_real_script_qualification(
    *,
    state_root: str,
    workspace: str,
    test_design_result: str,
    tc_id: str,
    execution_cwd: Optional[str] = None,
    dsh_bin: Optional[str] = None,
    timeout_seconds: int = 300,
) -> RC7ScriptQualificationResult:
    started = int(time.time())
    root = Path(state_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    workspace_path = Path(workspace).resolve()
    mission_id = "RC7-DSH-SCRIPT-" + uuid.uuid4().hex[:12]
    if not workspace_path.is_dir():
        return _not_proven(state_root=root, started=started, mission_id=mission_id, reason="WORKSPACE_NOT_FOUND", test_design_result=test_design_result, tc_id=tc_id)
    if not tc_id:
        return _not_proven(state_root=root, started=started, mission_id=mission_id, reason="SCRIPT_TC_ID_REQUIRED", test_design_result=test_design_result, tc_id=tc_id)
    resolved_dsh = _resolve_dsh(dsh_bin)
    if not resolved_dsh:
        return _not_proven(state_root=root, started=started, mission_id=mission_id, reason="DSH_NOT_AVAILABLE", test_design_result=test_design_result, tc_id=tc_id)
    try:
        design_result_path, design_result_json, _upstream_truth, design_envelope, design_raw = _load_strict_design_result(test_design_result)
    except AgentRuntimeError as exc:
        return _not_proven(state_root=root, started=started, mission_id=mission_id, reason=str(exc), test_design_result=test_design_result, tc_id=tc_id)

    truth = TruthRuntime(root / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=mission_id, release_id=RELEASE_ID, goal="prove TestCase to real DSH script readiness closed loop"),
    )
    imported_design, imported_relative = _import_accepted_design(
        control,
        state_root=root,
        upstream_result_path=design_result_path,
        upstream_result=design_result_json,
        envelope=design_envelope,
        raw=design_raw,
    )
    contract_compiler = AcceptedTestDesignScriptContractCompiler()
    try:
        initial = contract_compiler.compile(
            truth,
            mission_id=mission_id,
            design_artifact_id=imported_design,
            tc_id=tc_id,
        )
        search_roots = [str(workspace_path)]
        resolution = AutomationReuseResolver().resolve(
            spec=initial.spec,
            search_roots=search_roots,
            extra_keywords=(tc_id,),
        )
        contract = contract_compiler.compile(
            truth,
            mission_id=mission_id,
            design_artifact_id=imported_design,
            tc_id=tc_id,
            automation_mapping=resolution.mapping(),
        )
    except Exception as exc:
        return _not_proven(
            state_root=root, started=started, mission_id=mission_id,
            reason="SCRIPT_CONTRACT_COMPILE_FAILED:%s:%s" % (type(exc).__name__, exc),
            test_design_result=test_design_result, tc_id=tc_id,
        )
    spec_ref = _persist_contract(root, contract)
    reuse_refs = _reuse_candidate_refs(contract.spec.automation_mapping)
    reuse_targets = _workspace_read_targets(reuse_refs, workspace_path)

    run_cwd = Path(execution_cwd).resolve() if execution_cwd else workspace_path
    if not run_cwd.is_dir():
        return _not_proven(state_root=root, started=started, mission_id=mission_id, reason="SCRIPT_EXECUTION_CWD_NOT_FOUND", test_design_result=test_design_result, tc_id=tc_id)

    authority = RC7AuthorityRuntime(_runtime_key(root))
    patch_path = write_patch(root / "control" / "rc7.cordis.yml", workspace_path, sys.executable)
    launcher = RC7BankFinalDshHeadlessWorkerLauncher(
        dsh_bin=resolved_dsh,
        patch_path=str(patch_path),
        cwd=str(workspace_path),
        truth=truth,
        authority=authority,
        coordinator_instance_id="rc7-script-qualifier-" + uuid.uuid4().hex,
        release_id=RELEASE_ID,
        state_root=str(root),
        timeout_seconds=timeout_seconds,
        env={
            "PFC_AITEST_HOME": str(workspace_path),
            "PFC_AITEST_STATE_DIR": str(root),
            "PFC_WORKSPACE": str(workspace_path),
            "PYTHONPATH": str(run_cwd) + os.pathsep + str(workspace_path) + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
        },
    )

    graph = MissionTaskGraphCompiler().compile(mission_id)
    task = graph.task("SCRIPT_READINESS")
    task.dependency_task_ids = []
    task.input_artifact_refs = [imported_design]
    task.objective = _worker_objective(
        contract=contract,
        imported_design_path=imported_relative,
        reuse_targets=reuse_targets,
    )
    control.register_task(task)
    policy = DshNodePolicy(
        agent_id="test-automation",
        role="RC7_SCRIPT_WORKER",
        phase="AUTOMATION",
        allowed_artifact_types=("rc7_script_candidate",),
        allowed_tools=(READ_TEXT_TOOL,),
    )
    bridge = DshTaskWorkerBridge(control, launcher, node_policies={"SCRIPT_READINESS": policy})

    worker_id = None
    dsh_session_id = None
    source_ref = None
    validation_id = None
    validation_status = None
    validation_evidence_ids: Tuple[str, ...] = ()
    candidate_artifact_ref = None
    raw_output_ref = None
    evaluation_id = None
    evaluation_result = None
    used_refs: List[str] = []
    try:
        run = bridge.run_next()
        if run is None:
            raise AgentRuntimeError("RC7_DSH_SCRIPT_TASK_NOT_EXECUTED")
        worker_id = run.worker_instance_id
        dsh_session_id = run.dsh_session_id
        raw_output_ref = run.raw_output_ref
        artifact_id = graph.artifact_ids["SCRIPT_READINESS"]
        artifact_rows = truth.query("rc7_artifact", artifact_id=artifact_id)
        if len(artifact_rows) != 1:
            raise AgentRuntimeError("RC7_SCRIPT_CANDIDATE_ARTIFACT_MISSING")
        candidate_artifact_ref = str(artifact_rows[0].get("content_ref") or "")
        candidate = CandidatePayloadReader().load(
            truth,
            artifact_id,
            expected_mission_id=mission_id,
            expected_task_id=task.task_id,
        )
        raw_used = candidate.semantic_payload.get("reuse_refs_used", [])
        if not isinstance(raw_used, list) or not all(isinstance(value, str) and value for value in raw_used):
            raise AgentRuntimeError("SCRIPT_REUSE_REFS_USED_INVALID")
        used_refs = list(dict.fromkeys(raw_used))
        reason = _verify_read_proof(
            truth,
            mission_id=mission_id,
            worker_id=worker_id,
            design_path=imported_relative,
            used_refs=used_refs,
            reuse_targets=reuse_targets,
        )
        if reason is not None:
            raise AgentRuntimeError(reason)

        evaluated = DshScriptReadinessEvaluator(
            evidence_root=str(root / "evidence"),
            validation_timeout_seconds=timeout_seconds,
        ).evaluate_and_apply(
            control,
            task.task_id,
            artifact_id,
            contract=contract,
            cwd=str(run_cwd),
            env={"PYTHONPATH": str(run_cwd) + os.pathsep + str(workspace_path)},
        )
        source_ref = evaluated.source_ref
        if evaluated.validation is not None:
            validation_id = evaluated.validation.validation_id
            validation_status = evaluated.validation.status
            validation_evidence_ids = tuple(evaluated.validation.evidence_refs)
        evaluation_id = evaluated.loop_result.evaluation.evaluation_id
        evaluation_result = evaluated.loop_result.evaluation.result.value
        accepted = control.scheduler.task(task.task_id)
        if evaluation_result != "PASS" or accepted.state != TaskStatus.PASS:
            raise AgentRuntimeError("RC7_REAL_SCRIPT_READINESS_GATE_NOT_PASS")
        if validation_status != "SCRIPT_READY":
            raise AgentRuntimeError("RC7_REAL_SCRIPT_VALIDATION_NOT_READY")
        result = RC7ScriptQualificationResult(
            status="PASS", reason=None, mission_id=mission_id, task_id=task.task_id,
            test_design_result=str(design_result_path), tc_id=tc_id,
            runner_type=contract.spec.runner_type, spec_id=contract.spec.spec_id,
            spec_ref=spec_ref, case_fingerprint=contract.spec.case_fingerprint,
            oracle_fingerprint=contract.spec.oracle_fingerprint,
            automation_reuse_candidate_count=len(reuse_refs), automation_reuse_used_count=len(used_refs),
            worker_id=worker_id, dsh_session_id=dsh_session_id, source_ref=source_ref,
            validation_id=validation_id, validation_status=validation_status,
            validation_evidence_ids=validation_evidence_ids, task_state=accepted.state.value,
            evaluation_id=evaluation_id, evaluation_result=evaluation_result,
            candidate_artifact_ref=candidate_artifact_ref, raw_output_ref=raw_output_ref,
            r1_event_count=_mission_event_count(truth, mission_id), started_at=started,
            finished_at=int(time.time()),
        )
    except Exception as exc:
        state = control.scheduler.task(task.task_id).state.value
        result = RC7ScriptQualificationResult(
            status="FAIL", reason="%s:%s" % (type(exc).__name__, exc), mission_id=mission_id,
            task_id=task.task_id, test_design_result=str(design_result_path), tc_id=tc_id,
            runner_type=contract.spec.runner_type, spec_id=contract.spec.spec_id,
            spec_ref=spec_ref, case_fingerprint=contract.spec.case_fingerprint,
            oracle_fingerprint=contract.spec.oracle_fingerprint,
            automation_reuse_candidate_count=len(reuse_refs), automation_reuse_used_count=len(used_refs),
            worker_id=worker_id, dsh_session_id=dsh_session_id, source_ref=source_ref,
            validation_id=validation_id, validation_status=validation_status,
            validation_evidence_ids=validation_evidence_ids, task_state=state,
            evaluation_id=evaluation_id, evaluation_result=evaluation_result,
            candidate_artifact_ref=candidate_artifact_ref, raw_output_ref=raw_output_ref,
            r1_event_count=_mission_event_count(truth, mission_id), started_at=started,
            finished_at=int(time.time()),
        )
    _write_result(root, result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="RC7 real DSH Script readiness qualification")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--workspace", default=os.environ.get("PFC_WORKSPACE") or str(Path.cwd()))
    parser.add_argument("--test-design-result", default=os.environ.get("PFC_RC7_TEST_DESIGN_RESULT") or "")
    parser.add_argument("--tc-id", default=os.environ.get("PFC_RC7_SCRIPT_TC_ID") or "")
    parser.add_argument("--execution-cwd", default=os.environ.get("PFC_RC7_SCRIPT_CWD"))
    parser.add_argument("--dsh-bin", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    result = run_real_script_qualification(
        state_root=args.state_root,
        workspace=args.workspace,
        test_design_result=args.test_design_result,
        tc_id=args.tc_id,
        execution_cwd=args.execution_cwd,
        dsh_bin=args.dsh_bin,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    if result.status == "PASS":
        return 0
    if result.status == "NOT_PROVEN":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
