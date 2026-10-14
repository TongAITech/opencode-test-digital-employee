from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Tuple

from rc6_release.dsh import write_patch
from rc6_runtime.agent_runtime import AgentRuntimeError
from rc6_runtime.agent_runtime_hardening import BankFinalDshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.dsh_requirement_evaluator import DshRequirementEvaluator
from rc7_runtime.dsh_worker_bridge import (
    DEFAULT_NODE_POLICIES,
    DshNodePolicy,
    DshTaskWorkerBridge,
)
from rc7_runtime.mission_graph import MissionTaskGraphCompiler
from rc7_runtime.models import EvaluationResult, Mission, TaskStatus


RELEASE_ID = "RC7-DSH-BRIDGE-REALITY"
QUAL_REQUIREMENT_ID = "QUAL-REQ-BOUNDARY-001"
QUAL_SOURCE_REF = "qualification-fixture://rate-boundary-requirement"
QUAL_SOURCE_REQUIREMENT = (
    "交易金额必须大于0且不超过500000.00元；500000.00元必须允许通过；"
    "500000.01元及以上必须拒绝，并返回明确的超限业务结果。"
)
_RUNTIME_STATUS_TOOL = "mcp__pfc_aitest_rc6__runtime_status"
_EXPECTED_LIFECYCLE = (
    "WORKER_ASSIGN_REQUESTED",
    "WORKER_ADMITTED",
    "WORKER_STARTED",
    "WORKER_TOOL_CALLED",
    "WORKER_OUTPUT_PRODUCED",
    "WORKER_COMPLETED",
    "HANDOFF_RETURNED",
)


@dataclass(frozen=True)
class RC7DshBridgeQualificationResult:
    status: str
    reason: Optional[str]
    mission_id: str
    task_id: Optional[str]
    worker_instance_id: Optional[str]
    dsh_session_id: Optional[str]
    reviewer_worker_instance_id: Optional[str]
    reviewer_dsh_session_id: Optional[str]
    tool_call_count: int
    task_state: Optional[str]
    downstream_task_state: Optional[str]
    evaluation_id: Optional[str]
    evaluation_result: Optional[str]
    artifact_ref: Optional[str]
    raw_output_ref: Optional[str]
    r1_event_count: int
    lifecycle_event_ids: Tuple[str, ...]
    started_at: int
    finished_at: int


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
    configured = os.environ.get("PFC_DSH_BIN")
    if configured:
        return configured
    return shutil.which("dsh") or ""


def _result_path(state_root: Path) -> Path:
    return state_root / "qualification" / "rc7-dsh-bridge-result.json"


def _patch_path(state_root: Path) -> Path:
    return state_root / "control" / "rc7.cordis.yml"


def _write_result(state_root: Path, result: RC7DshBridgeQualificationResult) -> None:
    path = _result_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def _mission_events(truth: TruthRuntime, mission_id: str):
    return [
        event
        for event in truth.store.iter_raw()
        if isinstance(event.get("payload"), dict)
        and event["payload"].get("mission_id") == mission_id
    ]


def _mission_event_count(truth: TruthRuntime, mission_id: str) -> int:
    return len(_mission_events(truth, mission_id))


def _lifecycle_proof(truth: TruthRuntime, mission_id: str, worker_id: str) -> Tuple[str, ...]:
    mission_events = _mission_events(truth, mission_id)
    if any(event.get("event_type") == "ROUTING_INTEGRITY_FAIL" for event in mission_events):
        raise AgentRuntimeError("R1_PROOF_CONTAINS_ROUTING_INTEGRITY_FAIL")
    events = [
        event
        for event in mission_events
        if event["payload"].get("worker_instance_id") == worker_id
    ]
    names = [str(event.get("event_type")) for event in events]
    cursor = -1
    proof = []
    for required in _EXPECTED_LIFECYCLE:
        try:
            cursor = names.index(required, cursor + 1)
        except ValueError as exc:
            raise AgentRuntimeError("RC7_DSH_LIFECYCLE_MISSING_OR_OUT_OF_ORDER:%s" % required) from exc
        proof.append(str(events[cursor].get("event_id")))
    return tuple(proof)


def _requirement_objective() -> str:
    return (
        "Analyze one qualification requirement into an evaluator-ready requirement model. "
        "SOURCE_REQUIREMENT=%s REQUIREMENT_ID=%s. semantic_payload MUST contain requirement_id=%s, "
        "source_assertions, atomic_statements, trace_links, business_rules, roles, preconditions, "
        "normal_paths, negative_paths, boundaries, states, data_constraints, dependencies and side_effects. "
        "Every atomic statement MUST have id, source_ref and testable=true; every source and atomic statement "
        "MUST be covered by valid trace_links with evidence_ref. The boundaries MUST explicitly preserve "
        "500000.00 as allowed inclusive upper boundary and 500000.01 as rejected above-boundary value. "
        "Do not declare PASS or emit an Evaluation."
    ) % (QUAL_SOURCE_REQUIREMENT, QUAL_REQUIREMENT_ID, QUAL_REQUIREMENT_ID)


def run_real_qualification(
    *,
    state_root: str,
    repo_root: str,
    dsh_bin: Optional[str] = None,
    timeout_seconds: int = 300,
) -> RC7DshBridgeQualificationResult:
    started = int(time.time())
    root = Path(state_root).resolve()
    repository = Path(repo_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    mission_id = "RC7-DSH-REALITY-" + uuid.uuid4().hex[:12]
    resolved_dsh = _resolve_dsh(dsh_bin)

    if not resolved_dsh:
        result = RC7DshBridgeQualificationResult(
            status="NOT_PROVEN",
            reason="DSH_NOT_AVAILABLE",
            mission_id=mission_id,
            task_id=None,
            worker_instance_id=None,
            dsh_session_id=None,
            reviewer_worker_instance_id=None,
            reviewer_dsh_session_id=None,
            tool_call_count=0,
            task_state=None,
            downstream_task_state=None,
            evaluation_id=None,
            evaluation_result=None,
            artifact_ref=None,
            raw_output_ref=None,
            r1_event_count=0,
            lifecycle_event_ids=(),
            started_at=started,
            finished_at=int(time.time()),
        )
        _write_result(root, result)
        return result

    truth = TruthRuntime(root / "r1.jsonl")
    authority = RC7AuthorityRuntime(_runtime_key(root))
    patch_file = _patch_path(root)
    patch_file.parent.mkdir(parents=True, exist_ok=True)
    patch_path = write_patch(patch_file, repository, sys.executable)
    launcher = BankFinalDshHeadlessWorkerLauncher(
        dsh_bin=resolved_dsh,
        patch_path=str(patch_path),
        cwd=str(repository),
        truth=truth,
        authority=authority,
        coordinator_instance_id="rc7-qualifier-coordinator-" + uuid.uuid4().hex,
        release_id=RELEASE_ID,
        state_root=str(root),
        timeout_seconds=timeout_seconds,
        env={
            "PFC_AITEST_HOME": str(repository),
            "PFC_AITEST_STATE_DIR": str(root),
            "PYTHONPATH": str(repository)
            + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
        },
    )

    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=mission_id,
            release_id=RELEASE_ID,
            goal="prove real independent DSH Requirement producer/reviewer/gate handoff",
        ),
    )
    compiler = MissionTaskGraphCompiler()
    graph = compiler.compile(
        mission_id,
        external_inputs={"REQUIREMENT_ANALYSIS": (QUAL_SOURCE_REF,)},
    )
    requirement = graph.task("REQUIREMENT_ANALYSIS")
    requirement.objective = _requirement_objective()
    for task in graph.tasks:
        control.register_task(task)

    policies = dict(DEFAULT_NODE_POLICIES)
    base = policies["REQUIREMENT_ANALYSIS"]
    policies["REQUIREMENT_ANALYSIS"] = DshNodePolicy(
        agent_id=base.agent_id,
        role=base.role,
        phase=base.phase,
        allowed_artifact_types=base.allowed_artifact_types,
        allowed_tools=(_RUNTIME_STATUS_TOOL,),
    )
    bridge = DshTaskWorkerBridge(control, launcher, node_policies=policies)

    producer_worker_id = None
    producer_session_id = None
    artifact_ref = None
    raw_output_ref = None
    try:
        run = bridge.run_next()
        if run is None:
            raise AgentRuntimeError("RC7_DSH_READY_TASK_NOT_EXECUTED")
        producer_worker_id = run.worker_instance_id
        producer_session_id = run.dsh_session_id
        raw_output_ref = run.raw_output_ref

        task = control.scheduler.task(requirement.task_id)
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise AgentRuntimeError("RC7_DSH_WORKER_DID_NOT_STOP_AT_OUTPUT_PRODUCED")
        if task.evaluation_id is not None:
            raise AgentRuntimeError("RC7_DSH_WORKER_ILLEGALLY_ACCEPTED_OWN_OUTPUT")
        code_task_id = graph.task("CODE_ANALYSIS").task_id
        code = control.scheduler.task(code_task_id)
        if code.state != TaskStatus.REGISTERED:
            raise AgentRuntimeError("RC7_DSH_DOWNSTREAM_RELEASED_BEFORE_EVALUATION")
        if run.tool_call_count < 1 or not run.dsh_session_id:
            raise AgentRuntimeError("RC7_DSH_RUNTIME_PROOF_INCOMPLETE")
        if not run.raw_output_ref.startswith("file://"):
            raise AgentRuntimeError("RC7_DSH_RAW_OUTPUT_NOT_DURABLE")

        artifact_id = graph.artifact_ids["REQUIREMENT_ANALYSIS"]
        artifact_rows = truth.query("rc7_artifact", artifact_id=artifact_id)
        if len(artifact_rows) != 1:
            raise AgentRuntimeError("RC7_DSH_CANONICAL_ARTIFACT_MISSING")
        artifact_ref = str(artifact_rows[0].get("content_ref") or "")
        if not artifact_ref.startswith("file://"):
            raise AgentRuntimeError("RC7_DSH_CANONICAL_ARTIFACT_NOT_DURABLE")
        artifact_path = Path(artifact_ref[len("file://"):])
        if not artifact_path.is_file():
            raise AgentRuntimeError("RC7_DSH_CANONICAL_ARTIFACT_FILE_MISSING")

        producer_proof = _lifecycle_proof(truth, mission_id, run.worker_instance_id)

        evaluated = DshRequirementEvaluator(
            launcher,
            allowed_tools=(_RUNTIME_STATUS_TOOL,),
        ).evaluate_and_apply(
            control,
            requirement.task_id,
            artifact_id,
        )
        if evaluated.loop_result.evaluation.result != EvaluationResult.PASS:
            reasons = evaluated.loop_result.evaluation.dimensions.get("reasons", [])
            raise AgentRuntimeError(
                "RC7_REAL_REQUIREMENT_GATE_NOT_PASS:%s" % ",".join(str(reason) for reason in reasons)
            )
        if evaluated.reviewer_worker_id == run.worker_instance_id:
            raise AgentRuntimeError("RC7_REQUIREMENT_REVIEWER_NOT_INDEPENDENT")
        if evaluated.reviewer_session_id == run.dsh_session_id:
            raise AgentRuntimeError("RC7_REQUIREMENT_REVIEWER_SESSION_NOT_INDEPENDENT")
        if not evaluated.reviewer_evidence_ids:
            raise AgentRuntimeError("RC7_REQUIREMENT_REVIEWER_EVIDENCE_MISSING")

        accepted_requirement = control.scheduler.task(requirement.task_id)
        downstream = control.scheduler.task(code_task_id)
        if accepted_requirement.state != TaskStatus.PASS:
            raise AgentRuntimeError("RC7_REQUIREMENT_NOT_ACCEPTED_AFTER_GATE")
        if downstream.state != TaskStatus.READY:
            raise AgentRuntimeError("RC7_CODE_NOT_RELEASED_AFTER_REQUIREMENT_PASS")
        evaluation_rows = truth.query(
            "rc7_evaluation",
            evaluation_id=evaluated.loop_result.evaluation.evaluation_id,
        )
        if len(evaluation_rows) != 1 or evaluation_rows[0].get("result") != "PASS":
            raise AgentRuntimeError("RC7_REQUIREMENT_EVALUATION_NOT_DURABLE")

        reviewer_proof = _lifecycle_proof(truth, mission_id, evaluated.reviewer_worker_id)
        proof_ids = producer_proof + reviewer_proof
        result = RC7DshBridgeQualificationResult(
            status="PASS",
            reason=None,
            mission_id=mission_id,
            task_id=run.task_id,
            worker_instance_id=run.worker_instance_id,
            dsh_session_id=run.dsh_session_id,
            reviewer_worker_instance_id=evaluated.reviewer_worker_id,
            reviewer_dsh_session_id=evaluated.reviewer_session_id,
            tool_call_count=run.tool_call_count,
            task_state=accepted_requirement.state.value,
            downstream_task_state=downstream.state.value,
            evaluation_id=evaluated.loop_result.evaluation.evaluation_id,
            evaluation_result=evaluated.loop_result.evaluation.result.value,
            artifact_ref=artifact_ref,
            raw_output_ref=run.raw_output_ref,
            r1_event_count=_mission_event_count(truth, mission_id),
            lifecycle_event_ids=proof_ids,
            started_at=started,
            finished_at=int(time.time()),
        )
    except Exception as exc:
        result = RC7DshBridgeQualificationResult(
            status="FAIL",
            reason="%s:%s" % (type(exc).__name__, exc),
            mission_id=mission_id,
            task_id=requirement.task_id,
            worker_instance_id=producer_worker_id,
            dsh_session_id=producer_session_id,
            reviewer_worker_instance_id=None,
            reviewer_dsh_session_id=None,
            tool_call_count=0,
            task_state=control.scheduler.task(requirement.task_id).state.value,
            downstream_task_state=control.scheduler.task(graph.task("CODE_ANALYSIS").task_id).state.value,
            evaluation_id=control.scheduler.task(requirement.task_id).evaluation_id,
            evaluation_result=None,
            artifact_ref=artifact_ref,
            raw_output_ref=raw_output_ref,
            r1_event_count=_mission_event_count(truth, mission_id),
            lifecycle_event_ids=(),
            started_at=started,
            finished_at=int(time.time()),
        )

    _write_result(root, result)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="RC7 real DSH Requirement vertical qualification")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--repo-root", default=str(Path.cwd()))
    parser.add_argument("--dsh-bin", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    result = run_real_qualification(
        state_root=args.state_root,
        repo_root=args.repo_root,
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