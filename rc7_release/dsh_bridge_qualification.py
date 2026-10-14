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
from rc7_runtime.dsh_worker_bridge import (
    DEFAULT_NODE_POLICIES,
    DshNodePolicy,
    DshTaskWorkerBridge,
)
from rc7_runtime.mission_graph import MissionTaskGraphCompiler
from rc7_runtime.models import Mission, TaskStatus


RELEASE_ID = "RC7-DSH-BRIDGE-REALITY"
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
    tool_call_count: int
    task_state: Optional[str]
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


def _write_result(state_root: Path, result: RC7DshBridgeQualificationResult) -> None:
    path = _result_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def _lifecycle_proof(truth: TruthRuntime, mission_id: str, worker_id: str) -> Tuple[str, ...]:
    events = [
        event
        for event in truth.store.iter_raw()
        if isinstance(event.get("payload"), dict)
        and event["payload"].get("mission_id") == mission_id
        and event["payload"].get("worker_instance_id") == worker_id
    ]
    if any(event.get("event_type") == "ROUTING_INTEGRITY_FAIL" for event in truth.store.iter_raw()):
        raise AgentRuntimeError("R1_PROOF_CONTAINS_ROUTING_INTEGRITY_FAIL")
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
            tool_call_count=0,
            task_state=None,
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
    patch_path = write_patch(root, repository)
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
    )

    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=mission_id,
            release_id=RELEASE_ID,
            goal="prove a real independent DSH worker can execute one RC7 READY task",
        ),
    )
    compiler = MissionTaskGraphCompiler()
    graph = compiler.install(control, mission_id)
    requirement = graph.task("REQUIREMENT_ANALYSIS")

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

    try:
        run = bridge.run_next()
        if run is None:
            raise AgentRuntimeError("RC7_DSH_READY_TASK_NOT_EXECUTED")
        task = control.scheduler.task(requirement.task_id)
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise AgentRuntimeError("RC7_DSH_WORKER_DID_NOT_STOP_AT_OUTPUT_PRODUCED")
        if task.evaluation_id is not None:
            raise AgentRuntimeError("RC7_DSH_WORKER_ILLEGALLY_ACCEPTED_OWN_OUTPUT")
        code = control.scheduler.task(graph.task("CODE_ANALYSIS").task_id)
        if code.state != TaskStatus.REGISTERED:
            raise AgentRuntimeError("RC7_DSH_DOWNSTREAM_RELEASED_BEFORE_EVALUATION")
        if run.tool_call_count < 1 or not run.dsh_session_id:
            raise AgentRuntimeError("RC7_DSH_RUNTIME_PROOF_INCOMPLETE")
        if not run.raw_output_ref.startswith("file://"):
            raise AgentRuntimeError("RC7_DSH_RAW_OUTPUT_NOT_DURABLE")

        artifact_rows = truth.query("rc7_artifact", artifact_id=graph.artifact_ids["REQUIREMENT_ANALYSIS"])
        if len(artifact_rows) != 1:
            raise AgentRuntimeError("RC7_DSH_CANONICAL_ARTIFACT_MISSING")
        artifact_ref = str(artifact_rows[0].get("content_ref") or "")
        if not artifact_ref.startswith("file://"):
            raise AgentRuntimeError("RC7_DSH_CANONICAL_ARTIFACT_NOT_DURABLE")
        artifact_path = Path(artifact_ref[len("file://"):])
        if not artifact_path.is_file():
            raise AgentRuntimeError("RC7_DSH_CANONICAL_ARTIFACT_FILE_MISSING")

        proof_ids = _lifecycle_proof(truth, mission_id, run.worker_instance_id)
        result = RC7DshBridgeQualificationResult(
            status="PASS",
            reason=None,
            mission_id=mission_id,
            task_id=run.task_id,
            worker_instance_id=run.worker_instance_id,
            dsh_session_id=run.dsh_session_id,
            tool_call_count=run.tool_call_count,
            task_state=run.task_state,
            artifact_ref=artifact_ref,
            raw_output_ref=run.raw_output_ref,
            r1_event_count=sum(1 for _ in truth.store.iter_raw()),
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
            worker_instance_id=None,
            dsh_session_id=None,
            tool_call_count=0,
            task_state=control.scheduler.task(requirement.task_id).state.value,
            artifact_ref=None,
            raw_output_ref=None,
            r1_event_count=sum(1 for _ in truth.store.iter_raw()),
            lifecycle_event_ids=(),
            started_at=started,
            finished_at=int(time.time()),
        )

    _write_result(root, result)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="RC7 real DSH worker bridge qualification")
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
