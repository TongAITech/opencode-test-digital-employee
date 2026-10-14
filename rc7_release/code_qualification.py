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
from typing import List, Optional, Tuple

from rc6_runtime.agent_runtime import AgentRuntimeError
from rc6_runtime.agent_runtime_hardening import BankFinalDshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.dsh_code_evaluator import DshCodeEvaluator
from rc7_runtime.dsh_proof import DshR1ProofReader
from rc7_runtime.dsh_worker_bridge import DshNodePolicy, DshTaskWorkerBridge
from rc7_runtime.mission_graph import MissionTaskGraphCompiler
from rc7_runtime.models import EvaluationResult, Mission, TaskStatus

from .dsh import write_patch
from .professional_tools import ProfessionalToolError, codegraph_probe, git_diff


RELEASE_ID = "RC7-DSH-CODE-REALITY"
GIT_SHOW_TOOL = "mcp__pfc_aitest_rc7__git_show_revision"
GIT_DIFF_TOOL = "mcp__pfc_aitest_rc7__git_diff"
CODEGRAPH_QUERY_TOOL = "mcp__pfc_aitest_rc7__codegraph_query"
QUAL_REQUIREMENT_ID = "QUAL-CODE-REQ-001"


@dataclass(frozen=True)
class RC7CodeQualificationResult:
    status: str
    reason: Optional[str]
    mission_id: str
    task_id: Optional[str]
    target_id: str
    repo_path: str
    base_ref: str
    head_ref: str
    analyzer_worker_id: Optional[str]
    analyzer_session_id: Optional[str]
    reviewer_worker_id: Optional[str]
    reviewer_session_id: Optional[str]
    analyzer_git_call_count: int
    analyzer_codegraph_call_count: int
    task_state: Optional[str]
    evaluation_id: Optional[str]
    evaluation_result: Optional[str]
    evaluation_reasons: Tuple[str, ...]
    artifact_ref: Optional[str]
    raw_output_ref: Optional[str]
    r1_event_count: int
    started_at: int
    finished_at: int


class _CodeQualificationLauncher(BankFinalDshHeadlessWorkerLauncher):
    def __init__(self, *args, reviewer_guidance: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.reviewer_guidance = reviewer_guidance

    def execute(self, assignment, prompt):
        if getattr(assignment, "agent_id", "") == "rc7-code-sufficiency":
            prompt = prompt + "\nQUALIFICATION_REALITY_GUIDANCE=" + self.reviewer_guidance
        return super().execute(assignment, prompt)


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
    return state_root / "qualification" / "rc7-dsh-code-result.json"


def _write_result(state_root: Path, result: RC7CodeQualificationResult) -> None:
    path = _result_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def _mission_event_count(truth: TruthRuntime, mission_id: str) -> int:
    return sum(
        1
        for event in truth.store.iter_raw()
        if isinstance(event.get("payload"), dict)
        and event["payload"].get("mission_id") == mission_id
    )


def _not_proven(
    *,
    root: Path,
    started: int,
    mission_id: str,
    reason: str,
    target_id: str,
    repo_path: str,
    base_ref: str,
    head_ref: str,
) -> RC7CodeQualificationResult:
    result = RC7CodeQualificationResult(
        status="NOT_PROVEN",
        reason=reason,
        mission_id=mission_id,
        task_id=None,
        target_id=target_id,
        repo_path=repo_path,
        base_ref=base_ref,
        head_ref=head_ref,
        analyzer_worker_id=None,
        analyzer_session_id=None,
        reviewer_worker_id=None,
        reviewer_session_id=None,
        analyzer_git_call_count=0,
        analyzer_codegraph_call_count=0,
        task_state=None,
        evaluation_id=None,
        evaluation_result=None,
        evaluation_reasons=(),
        artifact_ref=None,
        raw_output_ref=None,
        r1_event_count=0,
        started_at=started,
        finished_at=int(time.time()),
    )
    _write_result(root, result)
    return result


def _code_objective(
    *,
    repo_path: str,
    base_ref: str,
    head_ref: str,
    target_id: str,
    codegraph_args: List[str],
) -> str:
    return (
        "Perform a real RC7 Code Analysis qualification. You MUST call %s with repo_path=%s, "
        "base_ref=%s, head_ref=%s and MUST call %s with repo_path=%s and args=%s. "
        "Do not replace these calls with capability_record_call or prose. semantic_payload MUST contain "
        "requirement_ids=[%s], source_revisions with key %s, changed_files, changed_symbols, "
        "symbol_explanations, reverse_requirement_mappings, evidence_refs and codegraph_required=true. "
        "Every changed symbol needs an evidence-backed explanation; every requirement needs reverse mapping. "
        "Return evidence entries whose content_ref values are reused by semantic evidence_refs. "
        "Do not declare PASS and do not emit Evaluation/Task state."
    ) % (
        GIT_DIFF_TOOL,
        repo_path,
        base_ref,
        head_ref,
        CODEGRAPH_QUERY_TOOL,
        repo_path,
        json.dumps(codegraph_args, ensure_ascii=False),
        QUAL_REQUIREMENT_ID,
        target_id,
    )


def _reviewer_guidance(
    *,
    repo_path: str,
    base_ref: str,
    head_ref: str,
    codegraph_args: List[str],
) -> str:
    return json.dumps(
        {
            "must_call": [
                {
                    "tool": GIT_DIFF_TOOL,
                    "arguments": {
                        "repo_path": repo_path,
                        "base_ref": base_ref,
                        "head_ref": head_ref,
                    },
                },
                {
                    "tool": CODEGRAPH_QUERY_TOOL,
                    "arguments": {"repo_path": repo_path, "args": codegraph_args},
                },
            ],
            "rule": "Both calls must be real. If either cannot be executed, return decision=GAPS.",
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def run_real_code_qualification(
    *,
    state_root: str,
    workspace: str,
    repo_path: str,
    base_ref: str,
    head_ref: str,
    target_id: str,
    codegraph_args: Optional[List[str]],
    dsh_bin: Optional[str] = None,
    timeout_seconds: int = 300,
) -> RC7CodeQualificationResult:
    started = int(time.time())
    root = Path(state_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    workspace_path = Path(workspace).resolve()
    mission_id = "RC7-DSH-CODE-" + uuid.uuid4().hex[:12]
    repo_path = repo_path or "."
    base_ref = base_ref or ""
    head_ref = head_ref or ""
    target_id = target_id or ""

    if not workspace_path.is_dir():
        return _not_proven(
            root=root,
            started=started,
            mission_id=mission_id,
            reason="WORKSPACE_NOT_FOUND",
            target_id=target_id,
            repo_path=repo_path,
            base_ref=base_ref,
            head_ref=head_ref,
        )
    os.environ["PFC_WORKSPACE"] = str(workspace_path)
    if not base_ref or not head_ref or not target_id:
        return _not_proven(
            root=root,
            started=started,
            mission_id=mission_id,
            reason="CODE_TARGET_AND_REVISIONS_REQUIRED",
            target_id=target_id,
            repo_path=repo_path,
            base_ref=base_ref,
            head_ref=head_ref,
        )
    if not codegraph_args:
        return _not_proven(
            root=root,
            started=started,
            mission_id=mission_id,
            reason="CODEGRAPH_QUERY_ARGS_REQUIRED",
            target_id=target_id,
            repo_path=repo_path,
            base_ref=base_ref,
            head_ref=head_ref,
        )
    resolved_dsh = _resolve_dsh(dsh_bin)
    if not resolved_dsh:
        return _not_proven(
            root=root,
            started=started,
            mission_id=mission_id,
            reason="DSH_NOT_AVAILABLE",
            target_id=target_id,
            repo_path=repo_path,
            base_ref=base_ref,
            head_ref=head_ref,
        )

    try:
        git_reality = git_diff(
            repo_path=repo_path,
            base_ref=base_ref,
            head_ref=head_ref,
            max_chars=100000,
        )
        codegraph_probe(repo_path=repo_path)
    except ProfessionalToolError as exc:
        return _not_proven(
            root=root,
            started=started,
            mission_id=mission_id,
            reason="PROFESSIONAL_TOOL_PREREQUISITE_NOT_PROVEN:%s" % exc,
            target_id=target_id,
            repo_path=repo_path,
            base_ref=base_ref,
            head_ref=head_ref,
        )

    truth = TruthRuntime(root / "r1.jsonl")
    authority = RC7AuthorityRuntime(_runtime_key(root))
    patch_path = write_patch(root / "control" / "rc7.cordis.yml", workspace_path, sys.executable)
    reviewer_guidance = _reviewer_guidance(
        repo_path=repo_path,
        base_ref=base_ref,
        head_ref=head_ref,
        codegraph_args=list(codegraph_args),
    )
    launcher = _CodeQualificationLauncher(
        dsh_bin=resolved_dsh,
        patch_path=str(patch_path),
        cwd=str(workspace_path),
        truth=truth,
        authority=authority,
        coordinator_instance_id="rc7-code-qualifier-" + uuid.uuid4().hex,
        release_id=RELEASE_ID,
        state_root=str(root),
        timeout_seconds=timeout_seconds,
        env={
            "PFC_AITEST_HOME": str(workspace_path),
            "PFC_AITEST_STATE_DIR": str(root),
            "PFC_WORKSPACE": str(workspace_path),
            "PYTHONPATH": str(workspace_path)
            + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
        },
        reviewer_guidance=reviewer_guidance,
    )

    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(
            mission_id=mission_id,
            release_id=RELEASE_ID,
            goal="prove real DSH Code analyzer/reviewer/Git/CodeGraph gate",
        ),
    )
    compiler = MissionTaskGraphCompiler()
    graph = compiler.compile(mission_id)
    code_task = graph.task("CODE_ANALYSIS")
    code_task.dependency_task_ids = []
    code_task.input_artifact_refs = [
        "git://%s/%s..%s" % (repo_path, git_reality["base_revision"], git_reality["head_revision"]),
        "codegraph://%s" % target_id,
    ]
    code_task.objective = _code_objective(
        repo_path=repo_path,
        base_ref=base_ref,
        head_ref=head_ref,
        target_id=target_id,
        codegraph_args=list(codegraph_args),
    )
    control.register_task(code_task)

    policy = DshNodePolicy(
        agent_id="code-analysis",
        role="RC7_CODE_WORKER",
        phase="ANALYSIS",
        allowed_artifact_types=("rc7_code_candidate",),
        allowed_tools=(GIT_SHOW_TOOL, GIT_DIFF_TOOL, CODEGRAPH_QUERY_TOOL),
    )
    bridge = DshTaskWorkerBridge(control, launcher, node_policies={"CODE_ANALYSIS": policy})

    analyzer_id = None
    analyzer_session = None
    artifact_ref = None
    raw_output_ref = None
    evaluation_id = None
    evaluation_result = None
    evaluation_reasons: Tuple[str, ...] = ()
    reviewer_id = None
    reviewer_session = None
    try:
        run = bridge.run_next()
        if run is None:
            raise AgentRuntimeError("RC7_DSH_CODE_TASK_NOT_EXECUTED")
        analyzer_id = run.worker_instance_id
        analyzer_session = run.dsh_session_id
        raw_output_ref = run.raw_output_ref
        task = control.scheduler.task(code_task.task_id)
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise AgentRuntimeError("RC7_CODE_ANALYZER_DID_NOT_STOP_AT_OUTPUT_PRODUCED")

        artifact_id = graph.artifact_ids["CODE_ANALYSIS"]
        artifact_rows = truth.query("rc7_artifact", artifact_id=artifact_id)
        if len(artifact_rows) != 1:
            raise AgentRuntimeError("RC7_CODE_ARTIFACT_MISSING")
        artifact_ref = str(artifact_rows[0].get("content_ref") or "")

        grouped = DshR1ProofReader().code_tool_calls(
            truth,
            mission_id=mission_id,
            worker_instance_id=run.worker_instance_id,
        )
        if not grouped["git"]:
            raise AgentRuntimeError("RC7_CODE_ANALYZER_REAL_GIT_CALL_MISSING")
        if not grouped["codegraph"]:
            raise AgentRuntimeError("RC7_CODE_ANALYZER_REAL_CODEGRAPH_CALL_MISSING")

        evaluated = DshCodeEvaluator(
            launcher,
            reviewer_allowed_tools=(GIT_DIFF_TOOL, CODEGRAPH_QUERY_TOOL),
        ).evaluate_and_apply(
            control,
            code_task.task_id,
            artifact_id,
            target_id=target_id,
        )
        reviewer_id = evaluated.reviewer_worker_id
        reviewer_session = evaluated.reviewer_session_id
        evaluation_id = evaluated.loop_result.evaluation.evaluation_id
        evaluation_result = evaluated.loop_result.evaluation.result.value
        evaluation_reasons = tuple(
            str(item) for item in evaluated.loop_result.evaluation.dimensions.get("reasons", [])
        )
        if evaluated.loop_result.evaluation.result != EvaluationResult.PASS:
            raise AgentRuntimeError("RC7_REAL_CODE_GATE_NOT_PASS:%s" % ",".join(evaluation_reasons))
        accepted = control.scheduler.task(code_task.task_id)
        if accepted.state != TaskStatus.PASS:
            raise AgentRuntimeError("RC7_CODE_TASK_NOT_ACCEPTED_AFTER_GATE")
        result = RC7CodeQualificationResult(
            status="PASS",
            reason=None,
            mission_id=mission_id,
            task_id=code_task.task_id,
            target_id=target_id,
            repo_path=repo_path,
            base_ref=base_ref,
            head_ref=head_ref,
            analyzer_worker_id=analyzer_id,
            analyzer_session_id=analyzer_session,
            reviewer_worker_id=reviewer_id,
            reviewer_session_id=reviewer_session,
            analyzer_git_call_count=len(grouped["git"]),
            analyzer_codegraph_call_count=len(grouped["codegraph"]),
            task_state=accepted.state.value,
            evaluation_id=evaluation_id,
            evaluation_result=evaluation_result,
            evaluation_reasons=evaluation_reasons,
            artifact_ref=artifact_ref,
            raw_output_ref=raw_output_ref,
            r1_event_count=_mission_event_count(truth, mission_id),
            started_at=started,
            finished_at=int(time.time()),
        )
    except Exception as exc:
        task_state = control.scheduler.task(code_task.task_id).state.value
        grouped = (
            DshR1ProofReader().code_tool_calls(
                truth,
                mission_id=mission_id,
                worker_instance_id=analyzer_id,
            )
            if analyzer_id
            else {"git": (), "codegraph": ()}
        )
        result = RC7CodeQualificationResult(
            status="FAIL",
            reason="%s:%s" % (type(exc).__name__, exc),
            mission_id=mission_id,
            task_id=code_task.task_id,
            target_id=target_id,
            repo_path=repo_path,
            base_ref=base_ref,
            head_ref=head_ref,
            analyzer_worker_id=analyzer_id,
            analyzer_session_id=analyzer_session,
            reviewer_worker_id=reviewer_id,
            reviewer_session_id=reviewer_session,
            analyzer_git_call_count=len(grouped.get("git", ())),
            analyzer_codegraph_call_count=len(grouped.get("codegraph", ())),
            task_state=task_state,
            evaluation_id=evaluation_id,
            evaluation_result=evaluation_result,
            evaluation_reasons=evaluation_reasons,
            artifact_ref=artifact_ref,
            raw_output_ref=raw_output_ref,
            r1_event_count=_mission_event_count(truth, mission_id),
            started_at=started,
            finished_at=int(time.time()),
        )

    _write_result(root, result)
    return result


def _parse_query_args(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError("CODEGRAPH_QUERY_ARGS_JSON_MUST_BE_STRING_ARRAY")
    return parsed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="RC7 real DSH Code analysis qualification")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--workspace", default=os.environ.get("PFC_WORKSPACE") or str(Path.cwd()))
    parser.add_argument("--repo-path", default=os.environ.get("PFC_RC7_CODE_REPO") or ".")
    parser.add_argument("--base-ref", default=os.environ.get("PFC_RC7_CODE_BASE_REF") or "")
    parser.add_argument("--head-ref", default=os.environ.get("PFC_RC7_CODE_HEAD_REF") or "")
    parser.add_argument("--target-id", default=os.environ.get("PFC_RC7_CODE_TARGET_ID") or "")
    parser.add_argument("--codegraph-args-json", default=os.environ.get("PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON"))
    parser.add_argument("--dsh-bin", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        codegraph_args = _parse_query_args(args.codegraph_args_json)
    except Exception as exc:
        print(json.dumps({"status": "NOT_PROVEN", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    result = run_real_code_qualification(
        state_root=args.state_root,
        workspace=args.workspace,
        repo_path=args.repo_path,
        base_ref=args.base_ref,
        head_ref=args.head_ref,
        target_id=args.target_id,
        codegraph_args=codegraph_args,
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
