"""Autonomous bank Reality runner for RC8 code analysis.

One invocation performs the structural loop once, generates a bounded semantic
request, launches a fresh real DSH headless worker, validates its evidence-bound
semantic claims, then publishes Artifact/R1/Capability truth.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from rc8_runtime import CapabilityState, RuntimeEventEnvelope, RuntimeProducerKind

from .agent import HttpCenterClient, NodeAgent, NodeAgentError, NodeIdentityStore, detect_platform
from .code_analysis import CodeAnalysisError, EvidenceBackedCodeAnalysisEngine
from .code_analysis_semantic import build_semantic_request, promote_with_semantic
from .codegraph import CodeGraphAdapterError, capture_git_snapshot
from .dsh_semantic_worker import DshSemanticWorker, DshSemanticWorkerError
from .reality_code_analysis import CodeAnalysisRealityError, _load_json, _report, _upload, _write_json


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _dsh_provenance(result) -> Dict[str, object]:
    return {
        "session_id": result.session_id,
        "classification": result.classification,
        "exit_code": result.exit_code,
        "tool_calls": list(result.tool_calls),
        "tool_results": list(result.tool_results),
        "stdout_encoding": result.stdout_encoding,
        "stderr_encoding": result.stderr_encoding,
        "raw_jsonl_path": result.raw_jsonl_path,
        "provenance_path": result.provenance_path,
    }


def run_auto_code_analysis_reality(
    *,
    center_url: str,
    node_id: str,
    operator_ref: str,
    state_dir: str,
    project_dir: str,
    codegraph_command: str,
    dsh_command: str,
    run_id: str,
    base_ref: str,
    head_ref: str,
    target_file: Optional[str] = None,
    target_line: Optional[int] = None,
    context_json: Optional[str] = None,
    dsh_patch: Optional[str] = None,
    dsh_timeout_seconds: int = 600,
    max_rounds: int = 3,
    initial_points: int = 1,
    points_step: int = 2,
    max_points: int = 12,
) -> Tuple[int, Dict[str, object]]:
    run_id = (run_id or "").strip()
    if not run_id or not _SAFE_RUN_ID.match(run_id):
        raise CodeAnalysisRealityError("CODE_ANALYSIS_RUN_ID_INVALID")
    if not node_id.strip() or not operator_ref.strip():
        raise CodeAnalysisRealityError("CODE_ANALYSIS_NODE_IDENTITY_REQUIRED")
    project = Path(project_dir).resolve()
    git_marker = project / ".git"
    if not project.is_dir() or (not git_marker.is_dir() and not git_marker.is_file()):
        raise CodeAnalysisRealityError("CODE_ANALYSIS_GIT_REPOSITORY_REQUIRED:%s" % project)

    context = _load_json(context_json) or {}
    state_root = Path(state_dir).resolve()
    evidence_root = state_root / "reality" / run_id
    structural_root = evidence_root / "analysis"
    semantic_root = evidence_root / "semantic-worker"
    preflight_path = evidence_root / "preflight.json"
    result_path = evidence_root / "reality-result.json"
    semantic_request_path = semantic_root / "semantic-request.json"
    final_analysis_path = evidence_root / "code-analysis-final.json"
    platform_info = detect_platform()

    client = HttpCenterClient(center_url)
    health = client.get("/health")
    if health.get("status") != "READY":
        raise CodeAnalysisRealityError("CENTER_NOT_READY")

    initial_snapshot = capture_git_snapshot(str(project))
    preflight: Dict[str, object] = {
        "schema_version": 1,
        "status": "PREFLIGHT_PASS",
        "run_id": run_id,
        "node_id": node_id,
        "center": center_url,
        "project_dir": str(project),
        "base_ref": base_ref,
        "head_ref": head_ref,
        "target_file": target_file,
        "target_line": target_line,
        "codegraph_command": codegraph_command,
        "dsh_command": dsh_command,
        "dsh_patch_configured": bool(dsh_patch),
        "platform": platform_info,
        "snapshot_id": initial_snapshot.snapshot_id,
        "truth_note": "Full PASS requires unchanged source snapshot, structurally sufficient real CodeGraph evidence and a real fresh DSH semantic worker handoff whose claims validate against the same evidence allowlist.",
    }
    _write_json(preflight_path, preflight)

    identity = NodeIdentityStore(str(state_root / "node-identity.json")).load_or_create(
        node_id=node_id.strip(),
        operator_ref=operator_ref.strip(),
        os_family=platform_info["os_family"],
        architecture=platform_info["architecture"],
        shell=platform_info["shell"],
    )
    agent = NodeAgent(identity, client)
    agent.register()
    agent.heartbeat()

    work_item_id = "%s-code-analysis" % run_id
    client.post(
        "/api/v1/work-items/register",
        {
            "work_item_id": work_item_id,
            "test_run_id": run_id,
            "stage": "CODE_ANALYSIS",
            "scope_refs": [str(project), base_ref, head_ref, initial_snapshot.snapshot_id],
            "required_capabilities": [],
        },
    )
    agent.lease(work_item_id, ttl_seconds=max(1800, dsh_timeout_seconds + 900))
    agent.start(work_item_id)
    _report(agent, CapabilityState.PROBING, str(preflight_path), [])

    engine = EvidenceBackedCodeAnalysisEngine(
        str(structural_root),
        codegraph_command=codegraph_command,
        timeout_seconds=120,
        max_rounds=max_rounds,
        initial_points=initial_points,
        points_step=points_step,
        max_points=max_points,
    )
    structural = engine.execute(
        repo_path=str(project),
        base_ref=base_ref,
        head_ref=head_ref,
        target_file=target_file,
        target_line=target_line,
        context=context,
        semantic_analysis=None,
    )

    artifact_ids: List[str] = []
    for item in structural.rounds:
        round_path = Path(str(item["evidence_path"]))
        artifact_ids.append(
            _upload(
                agent,
                run_id=run_id,
                work_item_id=work_item_id,
                path=round_path,
                kind="codegraph-round-evidence",
                role="round-%02d" % int(item["round"]),
                metadata={
                    "snapshot_id": structural.snapshot_id,
                    "graph_digest": item["graph_digest"],
                    "round": item["round"],
                    "sufficiency_state": item["sufficiency"]["state"],
                },
            )
        )

    structural_artifact = _upload(
        agent,
        run_id=run_id,
        work_item_id=work_item_id,
        path=Path(structural.analysis_path),
        kind="code-analysis-structural",
        role="structural-analysis",
        metadata={
            "snapshot_id": structural.snapshot_id,
            "classification": structural.classification,
            "structural_sufficiency": structural.structural_sufficiency.state,
            "evidence_digest": structural.evidence_digest,
        },
    )
    artifact_ids.append(structural_artifact)

    if structural.structural_sufficiency.state != "PASS":
        _report(agent, CapabilityState.DEGRADED, structural.analysis_path, artifact_ids)
        event = RuntimeEventEnvelope(
            event_id="%s-code-analysis" % run_id,
            test_run_id=run_id,
            work_item_id=work_item_id,
            node_id=identity.node_id,
            producer_kind=RuntimeProducerKind.WORKER,
            producer_ref="rc8:code-analysis",
            event_type="CODE_ANALYSIS_INSUFFICIENT_RECORDED",
            sequence=1,
            refs=list(artifact_ids),
            data={
                "classification": structural.classification,
                "overall_sufficiency": structural.overall_sufficiency,
                "snapshot_id": structural.snapshot_id,
                "structural_sufficiency": structural.structural_sufficiency.state,
                "gaps": list(structural.structural_sufficiency.gaps),
            },
        )
        receipt_response = agent.append_runtime_event(event)
        receipt = receipt_response.get("receipt") if isinstance(receipt_response.get("receipt"), dict) else receipt_response
        agent.complete(work_item_id)
        summary = {
            "schema_version": 1,
            "reality_status": "EXECUTION_CHAIN_VERIFIED_ANALYSIS_NOT_FULL_PASS",
            "classification": structural.classification,
            "overall_sufficiency": structural.overall_sufficiency,
            "capability_state": CapabilityState.DEGRADED.value,
            "snapshot_id": structural.snapshot_id,
            "round_count": len(structural.rounds),
            "artifact_ids": artifact_ids,
            "r1_receipt": dict(receipt),
            "work_item_state": "COMPLETED",
        }
        _write_json(result_path, summary)
        return 31, summary

    semantic_root.mkdir(parents=True, exist_ok=True)
    semantic_request = build_semantic_request(structural, output_path=str(semantic_request_path))
    request_artifact = _upload(
        agent,
        run_id=run_id,
        work_item_id=work_item_id,
        path=semantic_request_path,
        kind="code-analysis-semantic-request",
        role="semantic-request",
        metadata={
            "snapshot_id": structural.snapshot_id,
            "request_digest": semantic_request["request_digest"],
        },
    )
    artifact_ids.append(request_artifact)

    # Run DSH in the semantic evidence directory so the request stays small on
    # the command line; the worker must use a real runtime-visible read tool.
    worker = DshSemanticWorker(
        str(semantic_root),
        dsh_command=dsh_command,
        patch=dsh_patch,
        timeout_seconds=dsh_timeout_seconds,
    )
    dsh = worker.execute(
        request_path=str(semantic_request_path),
        env={
            "RC8_CODE_ANALYSIS_RUN_ID": run_id,
            "RC8_CODE_ANALYSIS_SNAPSHOT_ID": structural.snapshot_id,
            "RC8_CODE_ANALYSIS_PROJECT_DIR": str(project),
        },
    )

    # DSH may take minutes. A source edit during that time invalidates semantic
    # reasoning even though the structural evidence itself was once valid.
    publish_snapshot = capture_git_snapshot(str(project))
    if publish_snapshot.snapshot_id != structural.snapshot_id:
        raise CodeAnalysisRealityError("CODE_ANALYSIS_SNAPSHOT_STALE_AFTER_SEMANTIC")

    provenance = _dsh_provenance(dsh)
    promoted = promote_with_semantic(
        structural,
        dsh.semantic_analysis,
        output_path=str(final_analysis_path),
        semantic_source="DSH_HEADLESS_WORKER",
        dsh_provenance=provenance,
    )

    for role, path, kind in (
        ("dsh-raw", Path(dsh.raw_jsonl_path), "dsh-semantic-jsonl"),
        ("dsh-provenance", Path(dsh.provenance_path), "dsh-semantic-provenance"),
        ("final-analysis", final_analysis_path, "code-analysis-final"),
    ):
        artifact_ids.append(
            _upload(
                agent,
                run_id=run_id,
                work_item_id=work_item_id,
                path=path,
                kind=kind,
                role=role,
                metadata={
                    "snapshot_id": structural.snapshot_id,
                    "dsh_session_id": dsh.session_id,
                    "semantic_source": "DSH_HEADLESS_WORKER",
                    "classification": promoted.get("classification"),
                },
            )
        )

    full_pass = promoted.get("overall_sufficiency") == "PASS" and promoted.get("classification") == "CODE_ANALYSIS_SUFFICIENT"
    capability_state = CapabilityState.VERIFIED if full_pass else CapabilityState.DEGRADED
    _report(agent, capability_state, str(final_analysis_path), artifact_ids)
    event_type = "CODE_ANALYSIS_SUFFICIENT_RECORDED" if full_pass else "CODE_ANALYSIS_INSUFFICIENT_RECORDED"
    event = RuntimeEventEnvelope(
        event_id="%s-code-analysis" % run_id,
        test_run_id=run_id,
        work_item_id=work_item_id,
        node_id=identity.node_id,
        producer_kind=RuntimeProducerKind.WORKER,
        producer_ref="rc8:code-analysis+dsh",
        event_type=event_type,
        sequence=1,
        refs=list(artifact_ids),
        data={
            "classification": promoted.get("classification"),
            "overall_sufficiency": promoted.get("overall_sufficiency"),
            "snapshot_id": structural.snapshot_id,
            "git_head": structural.git_head,
            "changed_java_files": list(structural.changed_java_files),
            "round_count": len(structural.rounds),
            "structural_sufficiency": structural.structural_sufficiency.state,
            "semantic_source": "DSH_HEADLESS_WORKER",
            "semantic_sufficiency": dict(promoted.get("semantic_analysis") or {}).get("sufficiency"),
            "dsh_session_id": dsh.session_id,
            "dsh_tool_calls": list(dsh.tool_calls),
            "evidence_digest": promoted.get("evidence_digest"),
            "assertion": "same snapshot + structural PASS + fresh real DSH tool-backed semantic handoff + evidence allowlist validation",
        },
    )
    receipt_response = agent.append_runtime_event(event)
    receipt = receipt_response.get("receipt") if isinstance(receipt_response.get("receipt"), dict) else receipt_response
    if str(receipt.get("status") or "") not in {"PERSISTENCE_VERIFIED", "IDEMPOTENT_REPLAY"}:
        raise CodeAnalysisRealityError("CODE_ANALYSIS_R1_NOT_PERSISTED")
    completed = agent.complete(work_item_id)
    work = completed.get("work_item") if isinstance(completed, dict) and isinstance(completed.get("work_item"), dict) else completed
    if not isinstance(work, dict) or work.get("state") != "COMPLETED":
        raise CodeAnalysisRealityError("CODE_ANALYSIS_WORK_ITEM_NOT_COMPLETED")

    summary: Dict[str, object] = {
        "schema_version": 1,
        "reality_status": "EXECUTION_CHAIN_VERIFIED" if full_pass else "EXECUTION_CHAIN_VERIFIED_ANALYSIS_NOT_FULL_PASS",
        "run_id": run_id,
        "node_id": identity.node_id,
        "capability_state": capability_state.value,
        "classification": promoted.get("classification"),
        "overall_sufficiency": promoted.get("overall_sufficiency"),
        "project_dir": str(project),
        "base_ref": base_ref,
        "head_ref": head_ref,
        "git_head": structural.git_head,
        "snapshot_id": structural.snapshot_id,
        "changed_java_files": list(structural.changed_java_files),
        "round_count": len(structural.rounds),
        "structural_sufficiency": {
            "state": structural.structural_sufficiency.state,
            "score": structural.structural_sufficiency.score,
            "changed_file_count": structural.structural_sufficiency.changed_file_count,
            "covered_file_count": structural.structural_sufficiency.covered_file_count,
            "query_point_count": structural.structural_sufficiency.query_point_count,
            "successful_tool_calls": structural.structural_sufficiency.successful_tool_calls,
            "total_tool_calls": structural.structural_sufficiency.total_tool_calls,
        },
        "semantic_source": "DSH_HEADLESS_WORKER",
        "semantic_sufficiency": dict(promoted.get("semantic_analysis") or {}).get("sufficiency"),
        "dsh_session_id": dsh.session_id,
        "dsh_tool_call_count": len(dsh.tool_calls),
        "dsh_tool_result_count": len(dsh.tool_results),
        "semantic_request_path": str(semantic_request_path),
        "final_analysis_path": str(final_analysis_path),
        "artifact_ids": artifact_ids,
        "evidence_digest": promoted.get("evidence_digest"),
        "r1_receipt": dict(receipt),
        "work_item_state": "COMPLETED",
        "truth_note": "BANK_REALITY_VERIFIED is allowed only when this runner used the actual bank CodeGraph and actual bank DSH headless worker; CI doubles prove contracts only.",
    }
    _write_json(result_path, summary)
    return (0 if full_pass else 32), summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="RC8 自动代码分析 Reality：CodeGraph + DSH")
    parser.add_argument("--center", default=os.environ.get("RC8_CENTER_URL", "http://127.0.0.1:4098"))
    parser.add_argument("--node-id", default=os.environ.get("RC8_NODE_ID", ""))
    parser.add_argument("--operator", default=os.environ.get("RC8_NODE_OPERATOR", ""))
    parser.add_argument("--state-dir", default=os.environ.get("RC8_NODE_STATE_DIR", "runtime/rc8-node"))
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--codegraph", default=os.environ.get("RC8_CODEGRAPH_BIN") or os.environ.get("PFC_CODEGRAPH_BIN") or "codegraph")
    parser.add_argument("--dsh", default=os.environ.get("RC8_DSH_BIN") or "dsh")
    parser.add_argument("--dsh-patch", default=os.environ.get("RC8_DSH_PATCH") or "")
    parser.add_argument("--dsh-timeout", type=int, default=int(os.environ.get("RC8_DSH_TIMEOUT_SECONDS", "600")))
    parser.add_argument("--base-ref", default="HEAD~1")
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument("--target-file", default="")
    parser.add_argument("--target-line", type=int, default=0)
    parser.add_argument("--context-json", default="")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--initial-points", type=int, default=1)
    parser.add_argument("--points-step", type=int, default=2)
    parser.add_argument("--max-points", type=int, default=12)
    parser.add_argument("--run-id", default="")
    args = parser.parse_args(argv)
    if not args.run_id:
        args.run_id = "REALITY-CA-AUTO-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), (args.node_id or "node").replace(" ", "-"))
    try:
        code, summary = run_auto_code_analysis_reality(
            center_url=args.center,
            node_id=args.node_id,
            operator_ref=args.operator,
            state_dir=args.state_dir,
            project_dir=args.project_dir,
            codegraph_command=args.codegraph,
            dsh_command=args.dsh,
            run_id=args.run_id,
            base_ref=args.base_ref,
            head_ref=args.head_ref,
            target_file=args.target_file or None,
            target_line=args.target_line or None,
            context_json=args.context_json or None,
            dsh_patch=args.dsh_patch or None,
            dsh_timeout_seconds=args.dsh_timeout,
            max_rounds=args.max_rounds,
            initial_points=args.initial_points,
            points_step=args.points_step,
            max_points=args.max_points,
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
        return code
    except (CodeAnalysisRealityError, CodeAnalysisError, CodeGraphAdapterError, DshSemanticWorkerError, NodeAgentError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "REALITY_VALIDATION_FAILED", "error": str(exc)}, ensure_ascii=False, sort_keys=True), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
