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
from typing import Dict, List, Optional, Sequence, Tuple

from rc6_runtime.agent_runtime import AgentRuntimeError
from rc6_runtime.truth import TruthRuntime
from rc7_runtime import Artifact, DshTestDesignEvaluator, Evidence, EvaluationResult, Mission, TaskStatus
from rc7_runtime.authority import RC7AuthorityRuntime
from rc7_runtime.closed_loop_control import ClosedLoopControlPlane
from rc7_runtime.dsh_proof import DshR1ProofReader, DshToolCallProof
from rc7_runtime.dsh_reality_launcher import RC7BankFinalDshHeadlessWorkerLauncher
from rc7_runtime.dsh_worker_bridge import DshNodePolicy, DshTaskWorkerBridge
from rc7_runtime.mission_graph import MissionTaskGraphCompiler
from rc7_runtime.truth_overlay import append_entity

from .code_qualification_strict import _verify_worker_targets
from .dsh import write_patch
from .professional_tools import ProfessionalToolError, codegraph_probe


RELEASE_ID = "RC7-DSH-TEST-DESIGN-REALITY"
READ_TEXT_TOOL = "mcp__pfc_aitest_rc7__read_text"
CODEGRAPH_QUERY_TOOL = "mcp__pfc_aitest_rc7__codegraph_query"


@dataclass(frozen=True)
class RC7TestDesignQualificationResult:
    status: str
    reason: Optional[str]
    mission_id: str
    task_id: Optional[str]
    requirement_result: str
    code_result: str
    repo_path: str
    designer_worker_id: Optional[str]
    designer_session_id: Optional[str]
    reviewer_worker_id: Optional[str]
    reviewer_session_id: Optional[str]
    parent_obligation_source_total: int
    parent_obligation_missing_total: int
    semantic_coverage: Optional[float]
    case_count: int
    task_state: Optional[str]
    evaluation_id: Optional[str]
    evaluation_result: Optional[str]
    artifact_ref: Optional[str]
    raw_output_ref: Optional[str]
    r1_event_count: int
    started_at: int
    finished_at: int


class _TestDesignQualificationLauncher(RC7BankFinalDshHeadlessWorkerLauncher):
    def __init__(self, *args, reviewer_guidance: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.reviewer_guidance = reviewer_guidance

    def execute(self, assignment, prompt):
        if getattr(assignment, "agent_id", "") == "rc7-test-design-sufficiency":
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
    return state_root / "qualification" / "rc7-dsh-test-design-result.json"


def _write_result(state_root: Path, result: RC7TestDesignQualificationResult) -> None:
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


def _load_upstream_result(path_value: str, *, expected_artifact_type: str) -> Tuple[Path, Dict[str, object], Dict[str, object], bytes]:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise AgentRuntimeError("UPSTREAM_RESULT_NOT_FOUND:%s" % path_value)
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentRuntimeError("UPSTREAM_RESULT_JSON_INVALID:%s" % path_value) from exc
    if not isinstance(result, dict):
        raise AgentRuntimeError("UPSTREAM_RESULT_NOT_OBJECT:%s" % path_value)
    if result.get("status") != "PASS" or result.get("evaluation_result") != "PASS":
        raise AgentRuntimeError("UPSTREAM_QUALIFICATION_NOT_PASS:%s" % path_value)
    artifact_ref = result.get("artifact_ref")
    if not isinstance(artifact_ref, str) or not artifact_ref.startswith("file://"):
        raise AgentRuntimeError("UPSTREAM_ARTIFACT_FILE_REF_REQUIRED:%s" % path_value)
    artifact_path = Path(artifact_ref[len("file://"):]).resolve()
    if not artifact_path.is_file():
        raise AgentRuntimeError("UPSTREAM_ARTIFACT_FILE_MISSING:%s" % artifact_ref)
    raw = artifact_path.read_bytes()
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentRuntimeError("UPSTREAM_ARTIFACT_JSON_INVALID:%s" % artifact_ref) from exc
    if not isinstance(envelope, dict) or not isinstance(envelope.get("semantic_payload"), dict):
        raise AgentRuntimeError("UPSTREAM_ARTIFACT_SEMANTIC_PAYLOAD_REQUIRED:%s" % artifact_ref)
    declared = envelope.get("artifact")
    if not isinstance(declared, dict) or declared.get("artifact_type") != expected_artifact_type:
        raise AgentRuntimeError("UPSTREAM_ARTIFACT_TYPE_MISMATCH:%s" % expected_artifact_type)
    return path, result, envelope, raw


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _import_parent(
    truth: TruthRuntime,
    *,
    state_root: Path,
    mission_id: str,
    label: str,
    artifact_type: str,
    upstream_result_path: Path,
    upstream_envelope: Dict[str, object],
    upstream_raw: bytes,
) -> Tuple[str, str]:
    folder = state_root / "qualification" / "imported-parents"
    folder.mkdir(parents=True, exist_ok=True)
    artifact_id = _stable_id("ART-QUAL-PARENT", mission_id, label)
    producer_task_id = _stable_id("TASK-QUAL-IMPORT", mission_id, label)
    evidence_id = _stable_id("EVD-QUAL-UPSTREAM", mission_id, label)
    semantic_payload = dict(upstream_envelope["semantic_payload"])
    imported = {
        "task_id": producer_task_id,
        "artifact": {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "content_ref": "upstream-result://%s" % upstream_result_path,
            "parent_refs": [],
            "evidence_refs": [evidence_id],
        },
        "semantic_payload": semantic_payload,
        "evidence": [],
        "upstream_provenance": {
            "result_file": str(upstream_result_path),
            "source_sha256": hashlib.sha256(upstream_raw).hexdigest(),
        },
    }
    encoded = (json.dumps(imported, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    relative = Path("qualification") / "imported-parents" / (artifact_id + ".json")
    target = state_root / relative
    target.write_bytes(encoded)
    append_entity(
        truth,
        Evidence(
            evidence_id=evidence_id,
            mission_id=mission_id,
            kind="UPSTREAM_QUALIFICATION_PROOF",
            source_ref=str(upstream_result_path),
            content_ref="file://" + str(target),
            subject_refs=[artifact_id],
            content_hash="sha256:" + hashlib.sha256(upstream_raw).hexdigest(),
        ),
        release_id=RELEASE_ID,
        artifact_version=1,
    )
    append_entity(
        truth,
        Artifact(
            artifact_id=artifact_id,
            mission_id=mission_id,
            artifact_type=artifact_type,
            producer_task_id=producer_task_id,
            content_ref="file://" + str(target),
            evidence_refs=[evidence_id],
            content_hash="sha256:" + hashlib.sha256(encoded).hexdigest(),
        ),
        release_id=RELEASE_ID,
        artifact_version=1,
    )
    return artifact_id, relative.as_posix()


def _arguments_contain(actual, expected) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and _arguments_contain(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and actual == expected
    return actual == expected


def _has_tool_target(
    proofs: Sequence[DshToolCallProof],
    *,
    tool_name: str,
    expected_arguments: Dict[str, object],
) -> bool:
    return any(
        proof.tool_name == tool_name and _arguments_contain(proof.arguments, expected_arguments)
        for proof in proofs
    )


def _verify_design_worker_targets(
    truth: TruthRuntime,
    *,
    mission_id: str,
    worker_id: Optional[str],
    requirement_relative_path: str,
    code_relative_path: str,
    repo_path: str,
    codegraph_args: List[str],
    label: str,
) -> Optional[str]:
    if not worker_id:
        return "%s_WORKER_ID_MISSING" % label
    proofs = DshR1ProofReader().tool_calls(truth, mission_id=mission_id, worker_instance_id=worker_id)
    for path in (requirement_relative_path, code_relative_path):
        if not _has_tool_target(
            proofs,
            tool_name=READ_TEXT_TOOL,
            expected_arguments={"path": path, "scope": "state"},
        ):
            return "%s_PARENT_READ_ARGUMENT_PROOF_MISSING:%s" % (label, path)
    if not _has_tool_target(
        proofs,
        tool_name=CODEGRAPH_QUERY_TOOL,
        expected_arguments={"repo_path": repo_path, "args": list(codegraph_args)},
    ):
        return "%s_CODEGRAPH_ARGUMENT_PROOF_MISSING" % label
    return None


def _design_objective(*, requirement_path: str, code_path: str, repo_path: str, codegraph_args: List[str]) -> str:
    return (
        "Perform a real RC7 Test Design qualification from two accepted upstream parent candidates. "
        "You MUST call %s twice with scope=state and path=%s then path=%s, and MUST call %s with "
        "repo_path=%s and args=%s. Derive mandatory Test Obligations from every source id in the parent "
        "Requirement atomic_statements/business_rules/normal_paths/negative_paths/boundaries/states/roles/"
        "data_constraints/side_effects and every Code changed_symbols id. semantic_payload.obligations MUST "
        "contain obligation_id, kind, layer, risk, required=true, source_refs and evidence_refs. source_refs "
        "must preserve the exact parent source ids. semantic_payload.cases MUST cover every obligation_id with "
        "durable evidence aliases and executable oracles. Use evidence entries whose content_ref aliases are "
        "reused by obligation, coverage and oracle evidence_ref fields. Do not use case count as sufficiency. "
        "Do not declare PASS and do not emit Evaluation/Task state."
    ) % (
        READ_TEXT_TOOL,
        requirement_path,
        code_path,
        CODEGRAPH_QUERY_TOOL,
        repo_path,
        json.dumps(codegraph_args, ensure_ascii=False),
    )


def _reviewer_guidance(*, requirement_path: str, code_path: str, repo_path: str, codegraph_args: List[str]) -> str:
    return json.dumps(
        {
            "must_call": [
                {"tool": READ_TEXT_TOOL, "arguments": {"path": requirement_path, "scope": "state"}},
                {"tool": READ_TEXT_TOOL, "arguments": {"path": code_path, "scope": "state"}},
                {"tool": CODEGRAPH_QUERY_TOOL, "arguments": {"repo_path": repo_path, "args": codegraph_args}},
            ],
            "rule": "Review parent-derived obligation completeness and semantic coverage independently. Missing source obligations must be GAPS.",
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _not_proven(
    *,
    root: Path,
    started: int,
    mission_id: str,
    reason: str,
    requirement_result: str,
    code_result: str,
    repo_path: str,
) -> RC7TestDesignQualificationResult:
    result = RC7TestDesignQualificationResult(
        status="NOT_PROVEN",
        reason=reason,
        mission_id=mission_id,
        task_id=None,
        requirement_result=requirement_result,
        code_result=code_result,
        repo_path=repo_path,
        designer_worker_id=None,
        designer_session_id=None,
        reviewer_worker_id=None,
        reviewer_session_id=None,
        parent_obligation_source_total=0,
        parent_obligation_missing_total=0,
        semantic_coverage=None,
        case_count=0,
        task_state=None,
        evaluation_id=None,
        evaluation_result=None,
        artifact_ref=None,
        raw_output_ref=None,
        r1_event_count=0,
        started_at=started,
        finished_at=int(time.time()),
    )
    _write_result(root, result)
    return result


def run_real_test_design_qualification(
    *,
    state_root: str,
    workspace: str,
    requirement_result: str,
    code_result: str,
    repo_path: str,
    codegraph_args: Optional[List[str]],
    dsh_bin: Optional[str] = None,
    timeout_seconds: int = 300,
) -> RC7TestDesignQualificationResult:
    started = int(time.time())
    root = Path(state_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    workspace_path = Path(workspace).resolve()
    mission_id = "RC7-DSH-TD-" + uuid.uuid4().hex[:12]
    if not workspace_path.is_dir():
        return _not_proven(root=root, started=started, mission_id=mission_id, reason="WORKSPACE_NOT_FOUND", requirement_result=requirement_result, code_result=code_result, repo_path=repo_path)
    if not codegraph_args:
        return _not_proven(root=root, started=started, mission_id=mission_id, reason="CODEGRAPH_QUERY_ARGS_REQUIRED", requirement_result=requirement_result, code_result=code_result, repo_path=repo_path)
    resolved_dsh = _resolve_dsh(dsh_bin)
    if not resolved_dsh:
        return _not_proven(root=root, started=started, mission_id=mission_id, reason="DSH_NOT_AVAILABLE", requirement_result=requirement_result, code_result=code_result, repo_path=repo_path)
    os.environ["PFC_WORKSPACE"] = str(workspace_path)
    os.environ["PFC_AITEST_STATE_DIR"] = str(root)
    try:
        req_result_path, req_result, req_envelope, req_raw = _load_upstream_result(requirement_result, expected_artifact_type="REQUIREMENT_MODEL")
        code_result_path, code_result_json, code_envelope, code_raw = _load_upstream_result(code_result, expected_artifact_type="CODE_IMPACT_MODEL")
        upstream_code_state = code_result_path.parent.parent
        upstream_truth = TruthRuntime(upstream_code_state / "r1.jsonl")
        upstream_reason = _verify_worker_targets(
            upstream_truth,
            mission_id=str(code_result_json.get("mission_id") or ""),
            worker_id=code_result_json.get("analyzer_worker_id") if isinstance(code_result_json.get("analyzer_worker_id"), str) else None,
            repo_path=str(code_result_json.get("repo_path") or repo_path),
            base_ref=str(code_result_json.get("base_ref") or ""),
            head_ref=str(code_result_json.get("head_ref") or ""),
            codegraph_args=list(codegraph_args),
            label="UPSTREAM_ANALYZER",
        )
        if upstream_reason is None:
            upstream_reason = _verify_worker_targets(
                upstream_truth,
                mission_id=str(code_result_json.get("mission_id") or ""),
                worker_id=code_result_json.get("reviewer_worker_id") if isinstance(code_result_json.get("reviewer_worker_id"), str) else None,
                repo_path=str(code_result_json.get("repo_path") or repo_path),
                base_ref=str(code_result_json.get("base_ref") or ""),
                head_ref=str(code_result_json.get("head_ref") or ""),
                codegraph_args=list(codegraph_args),
                label="UPSTREAM_REVIEWER",
            )
        if upstream_reason is not None:
            raise AgentRuntimeError("UPSTREAM_CODE_STRICT_PROOF_REQUIRED:%s" % upstream_reason)
        codegraph_probe(repo_path=repo_path)
    except (AgentRuntimeError, ProfessionalToolError) as exc:
        return _not_proven(root=root, started=started, mission_id=mission_id, reason=str(exc), requirement_result=requirement_result, code_result=code_result, repo_path=repo_path)

    truth = TruthRuntime(root / "r1.jsonl")
    control = ClosedLoopControlPlane.bootstrap(
        truth,
        Mission(mission_id=mission_id, release_id=RELEASE_ID, goal="prove real parent-aware DSH Test Design producer/reviewer/gate"),
    )
    req_artifact, req_relative = _import_parent(
        truth,
        state_root=root,
        mission_id=mission_id,
        label="requirement",
        artifact_type="REQUIREMENT_MODEL",
        upstream_result_path=req_result_path,
        upstream_envelope=req_envelope,
        upstream_raw=req_raw,
    )
    code_artifact, code_relative = _import_parent(
        truth,
        state_root=root,
        mission_id=mission_id,
        label="code",
        artifact_type="CODE_IMPACT_MODEL",
        upstream_result_path=code_result_path,
        upstream_envelope=code_envelope,
        upstream_raw=code_raw,
    )

    authority = RC7AuthorityRuntime(_runtime_key(root))
    patch_path = write_patch(root / "control" / "rc7.cordis.yml", workspace_path, sys.executable)
    launcher = _TestDesignQualificationLauncher(
        dsh_bin=resolved_dsh,
        patch_path=str(patch_path),
        cwd=str(workspace_path),
        truth=truth,
        authority=authority,
        coordinator_instance_id="rc7-test-design-qualifier-" + uuid.uuid4().hex,
        release_id=RELEASE_ID,
        state_root=str(root),
        timeout_seconds=timeout_seconds,
        env={
            "PFC_AITEST_HOME": str(workspace_path),
            "PFC_AITEST_STATE_DIR": str(root),
            "PFC_WORKSPACE": str(workspace_path),
            "PYTHONPATH": str(workspace_path) + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""),
        },
        reviewer_guidance=_reviewer_guidance(
            requirement_path=req_relative,
            code_path=code_relative,
            repo_path=repo_path,
            codegraph_args=list(codegraph_args),
        ),
    )

    compiler = MissionTaskGraphCompiler()
    graph = compiler.compile(mission_id)
    task = graph.task("TEST_DESIGN")
    task.dependency_task_ids = []
    task.input_artifact_refs = [req_artifact, code_artifact]
    task.objective = _design_objective(
        requirement_path=req_relative,
        code_path=code_relative,
        repo_path=repo_path,
        codegraph_args=list(codegraph_args),
    )
    control.register_task(task)
    policy = DshNodePolicy(
        agent_id="test-design",
        role="RC7_TEST_DESIGN_WORKER",
        phase="DESIGN",
        allowed_artifact_types=("rc7_test_design_candidate",),
        allowed_tools=(READ_TEXT_TOOL, CODEGRAPH_QUERY_TOOL),
    )
    bridge = DshTaskWorkerBridge(control, launcher, node_policies={"TEST_DESIGN": policy})

    designer_id = None
    designer_session = None
    reviewer_id = None
    reviewer_session = None
    artifact_ref = None
    raw_output_ref = None
    evaluation_id = None
    evaluation_result = None
    semantic_coverage = None
    case_count = 0
    source_total = 0
    missing_total = 0
    try:
        run = bridge.run_next()
        if run is None:
            raise AgentRuntimeError("RC7_DSH_TEST_DESIGN_TASK_NOT_EXECUTED")
        designer_id = run.worker_instance_id
        designer_session = run.dsh_session_id
        raw_output_ref = run.raw_output_ref
        design_artifact_id = graph.artifact_ids["TEST_DESIGN"]
        rows = truth.query("rc7_artifact", artifact_id=design_artifact_id)
        if len(rows) != 1:
            raise AgentRuntimeError("RC7_TEST_DESIGN_ARTIFACT_MISSING")
        artifact_ref = str(rows[0].get("content_ref") or "")
        reason = _verify_design_worker_targets(
            truth,
            mission_id=mission_id,
            worker_id=designer_id,
            requirement_relative_path=req_relative,
            code_relative_path=code_relative,
            repo_path=repo_path,
            codegraph_args=list(codegraph_args),
            label="DESIGNER",
        )
        if reason is not None:
            raise AgentRuntimeError(reason)

        evaluated = DshTestDesignEvaluator(
            launcher,
            reviewer_allowed_tools=(READ_TEXT_TOOL, CODEGRAPH_QUERY_TOOL),
        ).evaluate_and_apply(control, task.task_id, design_artifact_id)
        reviewer_id = evaluated.reviewer_worker_id
        reviewer_session = evaluated.reviewer_session_id
        reason = _verify_design_worker_targets(
            truth,
            mission_id=mission_id,
            worker_id=reviewer_id,
            requirement_relative_path=req_relative,
            code_relative_path=code_relative,
            repo_path=repo_path,
            codegraph_args=list(codegraph_args),
            label="REVIEWER",
        )
        if reason is not None:
            raise AgentRuntimeError(reason)
        evaluation = evaluated.loop_result.evaluation
        evaluation_id = evaluation.evaluation_id
        evaluation_result = evaluation.result.value
        semantic_coverage = evaluated.loop_result.semantic_coverage
        case_count = evaluated.loop_result.case_count
        source_total = int(evaluation.dimensions.get("parent_obligation_source_total", 0))
        missing_total = int(evaluation.dimensions.get("parent_obligation_missing_total", 0))
        if source_total <= 0:
            raise AgentRuntimeError("PARENT_OBLIGATION_SOURCE_INVENTORY_EMPTY")
        if missing_total != 0 or evaluation.dimensions.get("parent_obligation_coverage") != "PASS":
            raise AgentRuntimeError("PARENT_OBLIGATION_COVERAGE_NOT_PASS")
        if evaluation.result != EvaluationResult.PASS:
            raise AgentRuntimeError("RC7_REAL_TEST_DESIGN_GATE_NOT_PASS")
        accepted = control.scheduler.task(task.task_id)
        if accepted.state != TaskStatus.PASS:
            raise AgentRuntimeError("RC7_TEST_DESIGN_TASK_NOT_ACCEPTED_AFTER_GATE")
        result = RC7TestDesignQualificationResult(
            status="PASS",
            reason=None,
            mission_id=mission_id,
            task_id=task.task_id,
            requirement_result=str(req_result_path),
            code_result=str(code_result_path),
            repo_path=repo_path,
            designer_worker_id=designer_id,
            designer_session_id=designer_session,
            reviewer_worker_id=reviewer_id,
            reviewer_session_id=reviewer_session,
            parent_obligation_source_total=source_total,
            parent_obligation_missing_total=missing_total,
            semantic_coverage=semantic_coverage,
            case_count=case_count,
            task_state=accepted.state.value,
            evaluation_id=evaluation_id,
            evaluation_result=evaluation_result,
            artifact_ref=artifact_ref,
            raw_output_ref=raw_output_ref,
            r1_event_count=_mission_event_count(truth, mission_id),
            started_at=started,
            finished_at=int(time.time()),
        )
    except Exception as exc:
        state = control.scheduler.task(task.task_id).state.value
        result = RC7TestDesignQualificationResult(
            status="FAIL",
            reason="%s:%s" % (type(exc).__name__, exc),
            mission_id=mission_id,
            task_id=task.task_id,
            requirement_result=str(req_result_path),
            code_result=str(code_result_path),
            repo_path=repo_path,
            designer_worker_id=designer_id,
            designer_session_id=designer_session,
            reviewer_worker_id=reviewer_id,
            reviewer_session_id=reviewer_session,
            parent_obligation_source_total=source_total,
            parent_obligation_missing_total=missing_total,
            semantic_coverage=semantic_coverage,
            case_count=case_count,
            task_state=state,
            evaluation_id=evaluation_id,
            evaluation_result=evaluation_result,
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
    parser = argparse.ArgumentParser(description="RC7 real parent-aware DSH Test Design qualification")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--workspace", default=os.environ.get("PFC_WORKSPACE") or str(Path.cwd()))
    parser.add_argument("--requirement-result", default=os.environ.get("PFC_RC7_REQUIREMENT_RESULT") or "")
    parser.add_argument("--code-result", default=os.environ.get("PFC_RC7_CODE_RESULT") or "")
    parser.add_argument("--repo-path", default=os.environ.get("PFC_RC7_CODE_REPO") or ".")
    parser.add_argument("--codegraph-args-json", default=os.environ.get("PFC_RC7_CODEGRAPH_QUERY_ARGS_JSON"))
    parser.add_argument("--dsh-bin", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        codegraph_args = _parse_query_args(args.codegraph_args_json)
    except Exception as exc:
        print(json.dumps({"status": "NOT_PROVEN", "reason": str(exc)}, ensure_ascii=False, sort_keys=True))
        return 2
    result = run_real_test_design_qualification(
        state_root=args.state_root,
        workspace=args.workspace,
        requirement_result=args.requirement_result,
        code_result=args.code_result,
        repo_path=args.repo_path,
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
