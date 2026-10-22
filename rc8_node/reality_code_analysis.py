"""Bank reality runner for evidence-backed RC8 code analysis."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from rc8_runtime import ArtifactAvailability, CapabilityQualification, CapabilityState, RuntimeEventEnvelope, RuntimeProducerKind
from rc8_runtime.artifacts import ArtifactManifest

from .agent import HttpCenterClient, NodeAgent, NodeAgentError, NodeIdentityStore, detect_platform
from .code_analysis import CodeAnalysisError, EvidenceBackedCodeAnalysisEngine
from .codegraph import CodeGraphAdapterError


class CodeAnalysisRealityError(RuntimeError):
    pass


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(str(temp), str(path))


def _load_json(path: Optional[str]) -> Optional[Dict[str, object]]:
    if not path:
        return None
    source = Path(path).resolve()
    if not source.is_file():
        raise CodeAnalysisRealityError("CODE_ANALYSIS_JSON_NOT_FOUND:%s" % source)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CodeAnalysisRealityError("CODE_ANALYSIS_JSON_MUST_BE_OBJECT:%s" % source)
    return payload


def _upload(
    agent: NodeAgent,
    *,
    run_id: str,
    work_item_id: str,
    path: Path,
    kind: str,
    role: str,
    metadata: Mapping[str, object],
) -> str:
    if not path.is_file():
        raise CodeAnalysisRealityError("CODE_ANALYSIS_ARTIFACT_MISSING:%s" % path)
    digest = _sha256(path)
    artifact_id = "ca-%s-%s" % (role, hashlib.sha256((run_id + "|" + role + "|" + digest).encode("utf-8")).hexdigest()[:20])
    manifest = ArtifactManifest(
        artifact_id=artifact_id,
        test_run_id=run_id,
        work_item_id=work_item_id,
        node_id=agent.identity.node_id,
        kind=kind,
        producer_kind=RuntimeProducerKind.WORKER,
        producer_ref="rc8:code-analysis",
        file_name=path.name,
        sha256=digest,
        size_bytes=path.stat().st_size,
        availability=ArtifactAvailability.PENDING_UPLOAD,
        refs=[],
        metadata=dict(metadata),
    )
    response = agent.upload_artifact_file(manifest, str(path))
    artifact = response.get("artifact") if isinstance(response, dict) else None
    if not isinstance(artifact, dict) or artifact.get("availability") != ArtifactAvailability.AVAILABLE.value:
        raise CodeAnalysisRealityError("CODE_ANALYSIS_ARTIFACT_NOT_AVAILABLE:%s" % role)
    return artifact_id


def _report(agent: NodeAgent, state: CapabilityState, probe_ref: str, refs: List[str]) -> None:
    agent.report_capability(
        CapabilityQualification(
            node_id=agent.identity.node_id,
            capability_id="code-analysis",
            state=state,
            probe_ref=probe_ref,
            evidence_refs=list(refs),
            verified_at=int(time.time()) if state == CapabilityState.VERIFIED else None,
        )
    )


def run_code_analysis_reality(
    *,
    center_url: str,
    node_id: str,
    operator_ref: str,
    state_dir: str,
    project_dir: str,
    codegraph_command: str,
    run_id: str,
    base_ref: str,
    head_ref: str,
    target_file: Optional[str] = None,
    target_line: Optional[int] = None,
    context_json: Optional[str] = None,
    semantic_json: Optional[str] = None,
    max_rounds: int = 3,
    initial_points: int = 1,
    points_step: int = 2,
    max_points: int = 12,
) -> Tuple[int, Dict[str, object]]:
    run_id = (run_id or "").strip()
    if not run_id or not _SAFE_RUN_ID.match(run_id):
        raise CodeAnalysisRealityError("CODE_ANALYSIS_RUN_ID_INVALID")
    project = Path(project_dir).resolve()
    if not project.is_dir() or not (project / ".git").exists():
        raise CodeAnalysisRealityError("CODE_ANALYSIS_GIT_REPOSITORY_REQUIRED:%s" % project)

    context = _load_json(context_json) or {}
    semantic = _load_json(semantic_json)
    state_root = Path(state_dir).resolve()
    evidence_root = state_root / "reality" / run_id
    preflight_path = evidence_root / "preflight.json"
    result_path = evidence_root / "reality-result.json"
    platform_info = detect_platform()

    client = HttpCenterClient(center_url)
    health = client.get("/health")
    if health.get("status") != "READY":
        raise CodeAnalysisRealityError("CENTER_NOT_READY")

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
        "semantic_input": str(Path(semantic_json).resolve()) if semantic_json else None,
        "context_input": str(Path(context_json).resolve()) if context_json else None,
        "platform": platform_info,
        "truth_note": "Full Code Analysis PASS requires both structurally sufficient real CodeGraph evidence and an evidence-bound semantic analysis PASS.",
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
            "scope_refs": [str(project), base_ref, head_ref],
            "required_capabilities": [],
        },
    )
    agent.lease(work_item_id, ttl_seconds=1800)
    agent.start(work_item_id)
    _report(agent, CapabilityState.PROBING, str(preflight_path), [])

    engine = EvidenceBackedCodeAnalysisEngine(
        str(evidence_root / "analysis"),
        codegraph_command=codegraph_command,
        timeout_seconds=120,
        max_rounds=max_rounds,
        initial_points=initial_points,
        points_step=points_step,
        max_points=max_points,
    )
    result = engine.execute(
        repo_path=str(project),
        base_ref=base_ref,
        head_ref=head_ref,
        target_file=target_file,
        target_line=target_line,
        context=context,
        semantic_analysis=semantic,
    )

    artifact_ids: List[str] = []
    for item in result.rounds:
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
                    "snapshot_id": result.snapshot_id,
                    "graph_digest": item["graph_digest"],
                    "round": item["round"],
                    "sufficiency_state": item["sufficiency"]["state"],
                },
            )
        )
    analysis_artifact = _upload(
        agent,
        run_id=run_id,
        work_item_id=work_item_id,
        path=Path(result.analysis_path),
        kind="code-analysis",
        role="analysis",
        metadata={
            "snapshot_id": result.snapshot_id,
            "classification": result.classification,
            "overall_sufficiency": result.overall_sufficiency,
            "evidence_digest": result.evidence_digest,
        },
    )
    artifact_ids.append(analysis_artifact)

    if result.overall_sufficiency == "PASS":
        capability_state = CapabilityState.VERIFIED
        event_type = "CODE_ANALYSIS_SUFFICIENT_RECORDED"
        exit_code = 0
    elif result.overall_sufficiency == "SEMANTIC_PENDING":
        capability_state = CapabilityState.PROBING
        event_type = "CODE_ANALYSIS_STRUCTURAL_EVIDENCE_RECORDED"
        exit_code = 30
    else:
        capability_state = CapabilityState.DEGRADED
        event_type = "CODE_ANALYSIS_INSUFFICIENT_RECORDED"
        exit_code = 31
    _report(agent, capability_state, result.analysis_path, artifact_ids)

    event = RuntimeEventEnvelope(
        event_id="%s-code-analysis" % run_id,
        test_run_id=run_id,
        work_item_id=work_item_id,
        node_id=identity.node_id,
        producer_kind=RuntimeProducerKind.WORKER,
        producer_ref="rc8:code-analysis",
        event_type=event_type,
        sequence=1,
        refs=list(artifact_ids),
        data={
            "classification": result.classification,
            "overall_sufficiency": result.overall_sufficiency,
            "snapshot_id": result.snapshot_id,
            "git_head": result.git_head,
            "changed_java_files": list(result.changed_java_files),
            "round_count": len(result.rounds),
            "structural_sufficiency": {
                "state": result.structural_sufficiency.state,
                "score": result.structural_sufficiency.score,
                "changed_file_count": result.structural_sufficiency.changed_file_count,
                "covered_file_count": result.structural_sufficiency.covered_file_count,
                "query_point_count": result.structural_sufficiency.query_point_count,
                "successful_tool_calls": result.structural_sufficiency.successful_tool_calls,
                "total_tool_calls": result.structural_sufficiency.total_tool_calls,
                "gaps": list(result.structural_sufficiency.gaps),
            },
            "semantic_analysis_present": result.semantic_analysis is not None,
            "evidence_digest": result.evidence_digest,
            "assertion": "full PASS requires structural sufficiency PASS and validated evidence-bound semantic sufficiency PASS",
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
        "reality_status": "EXECUTION_CHAIN_VERIFIED" if exit_code == 0 else "EXECUTION_CHAIN_VERIFIED_ANALYSIS_NOT_FULL_PASS",
        "run_id": run_id,
        "node_id": identity.node_id,
        "capability_state": capability_state.value,
        "classification": result.classification,
        "overall_sufficiency": result.overall_sufficiency,
        "project_dir": str(project),
        "base_ref": base_ref,
        "head_ref": head_ref,
        "git_head": result.git_head,
        "snapshot_id": result.snapshot_id,
        "changed_java_files": list(result.changed_java_files),
        "round_count": len(result.rounds),
        "structural_sufficiency": {
            "state": result.structural_sufficiency.state,
            "score": result.structural_sufficiency.score,
            "changed_file_count": result.structural_sufficiency.changed_file_count,
            "covered_file_count": result.structural_sufficiency.covered_file_count,
            "query_point_count": result.structural_sufficiency.query_point_count,
            "successful_tool_calls": result.structural_sufficiency.successful_tool_calls,
            "total_tool_calls": result.structural_sufficiency.total_tool_calls,
            "gaps": list(result.structural_sufficiency.gaps),
        },
        "semantic_analysis_present": result.semantic_analysis is not None,
        "artifact_ids": artifact_ids,
        "analysis_path": result.analysis_path,
        "evidence_digest": result.evidence_digest,
        "r1_receipt": dict(receipt),
        "work_item_state": "COMPLETED",
        "truth_note": "Without a validated semantic result, structural CodeGraph evidence is real but full Code Analysis remains pending.",
    }
    _write_json(result_path, summary)
    return exit_code, summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="RC8 完整代码分析 Reality 验证")
    parser.add_argument("--center", default=os.environ.get("RC8_CENTER_URL", "http://127.0.0.1:4098"))
    parser.add_argument("--node-id", default=os.environ.get("RC8_NODE_ID", ""))
    parser.add_argument("--operator", default=os.environ.get("RC8_NODE_OPERATOR", ""))
    parser.add_argument("--state-dir", default=os.environ.get("RC8_NODE_STATE_DIR", "runtime/rc8-node"))
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--codegraph", default=os.environ.get("RC8_CODEGRAPH_BIN") or os.environ.get("PFC_CODEGRAPH_BIN") or "codegraph")
    parser.add_argument("--base-ref", default="HEAD~1")
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument("--target-file", default="")
    parser.add_argument("--target-line", type=int, default=0)
    parser.add_argument("--context-json", default="")
    parser.add_argument("--semantic-json", default="")
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--initial-points", type=int, default=1)
    parser.add_argument("--points-step", type=int, default=2)
    parser.add_argument("--max-points", type=int, default=12)
    parser.add_argument("--run-id", default="")
    args = parser.parse_args(argv)
    if not args.run_id:
        args.run_id = "REALITY-CA-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), (args.node_id or "node").replace(" ", "-"))
    try:
        code, summary = run_code_analysis_reality(
            center_url=args.center,
            node_id=args.node_id,
            operator_ref=args.operator,
            state_dir=args.state_dir,
            project_dir=args.project_dir,
            codegraph_command=args.codegraph,
            run_id=args.run_id,
            base_ref=args.base_ref,
            head_ref=args.head_ref,
            target_file=args.target_file or None,
            target_line=args.target_line or None,
            context_json=args.context_json or None,
            semantic_json=args.semantic_json or None,
            max_rounds=args.max_rounds,
            initial_points=args.initial_points,
            points_step=args.points_step,
            max_points=args.max_points,
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
        return code
    except (CodeAnalysisRealityError, CodeAnalysisError, CodeGraphAdapterError, NodeAgentError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "REALITY_VALIDATION_FAILED", "error": str(exc)}, ensure_ascii=False, sort_keys=True), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
