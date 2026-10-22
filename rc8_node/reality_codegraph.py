"""Bank-reality runner for RC8 CodeGraph.

Qualification and execution both require real structural queries. Git is the
source snapshot/change authority; CodeGraph evidence is published only when the
repository stays on one immutable snapshot through query and publication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rc8_runtime import (
    ArtifactAvailability,
    CapabilityQualification,
    CapabilityState,
    RuntimeEventEnvelope,
    RuntimeProducerKind,
)
from rc8_runtime.artifacts import ArtifactManifest

from .agent import HttpCenterClient, NodeAgent, NodeAgentError, NodeIdentityStore, detect_platform
from .codegraph import (
    CodeGraphAdapterError,
    CodeGraphExecutableAdapter,
    CodeGraphExecutionResult,
    capture_git_snapshot,
    discover_java_query_points,
)


class CodeGraphRealityError(RuntimeError):
    pass


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_run_id(run_id: str) -> str:
    value = (run_id or "").strip()
    if not value:
        raise CodeGraphRealityError("REALITY_RUN_ID_REQUIRED")
    if not _SAFE_RUN_ID.match(value):
        raise CodeGraphRealityError("REALITY_RUN_ID_UNSAFE:%s" % value)
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(str(temp), str(path))


def _artifact_id(run_id: str, role: str, path: Path) -> str:
    seed = (run_id + "|" + role + "|" + _sha256(path)).encode("utf-8")
    return "cg-%s-%s" % (role, hashlib.sha256(seed).hexdigest()[:20])


def _upload_graph_evidence(
    agent: NodeAgent,
    *,
    run_id: str,
    test_run_id: str,
    work_item_id: str,
    result: CodeGraphExecutionResult,
    role: str,
) -> str:
    path = Path(result.evidence_path)
    if not path.is_file():
        raise CodeGraphRealityError("CODEGRAPH_EVIDENCE_FILE_MISSING")
    artifact_id = _artifact_id(run_id, role, path)
    manifest = ArtifactManifest(
        artifact_id=artifact_id,
        test_run_id=test_run_id,
        work_item_id=work_item_id,
        node_id=agent.identity.node_id,
        kind="codegraph-%s" % role,
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="rc8:codegraph",
        file_name=path.name,
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
        availability=ArtifactAvailability.PENDING_UPLOAD,
        refs=["snapshot:%s" % result.snapshot_before.snapshot_id, "graph:%s" % result.graph_digest],
        metadata={
            "base_ref": result.base_ref,
            "head_ref": result.head_ref,
            "git_head": result.snapshot_before.head_revision,
            "snapshot_id": result.snapshot_before.snapshot_id,
            "graph_digest": result.graph_digest,
            "classification": result.classification,
        },
    )
    response = agent.upload_artifact_file(manifest, str(path))
    artifact = response.get("artifact") if isinstance(response, dict) else None
    if not isinstance(artifact, dict) or artifact.get("availability") != ArtifactAvailability.AVAILABLE.value:
        raise CodeGraphRealityError("CODEGRAPH_EVIDENCE_NOT_AVAILABLE")
    if str(artifact.get("artifact_id") or "") != artifact_id:
        raise CodeGraphRealityError("CODEGRAPH_EVIDENCE_ARTIFACT_MISMATCH")
    return artifact_id


def _report_probe_state(agent: NodeAgent, state: CapabilityState, probe_ref: str, evidence_refs: List[str]) -> CapabilityQualification:
    qualification = CapabilityQualification(
        node_id=agent.identity.node_id,
        capability_id="codegraph",
        state=state,
        probe_ref=probe_ref,
        evidence_refs=evidence_refs,
        verified_at=int(time.time()) if state == CapabilityState.VERIFIED else None,
    )
    agent.report_capability(qualification)
    return qualification


def run_codegraph_reality(
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
    max_points: int = 2,
) -> Tuple[int, Dict[str, object]]:
    run_id = _validate_run_id(run_id)
    if not node_id.strip():
        raise CodeGraphRealityError("NODE_ID_REQUIRED")
    if not operator_ref.strip():
        raise CodeGraphRealityError("NODE_OPERATOR_REQUIRED")

    project = Path(project_dir).resolve()
    if not project.is_dir():
        raise CodeGraphRealityError("CODEGRAPH_PROJECT_DIR_NOT_FOUND:%s" % project)
    if not (project / ".git").exists():
        # Worktrees may use a .git file. Either form is accepted.
        git_marker = project / ".git"
        if not git_marker.is_file():
            raise CodeGraphRealityError("CODEGRAPH_GIT_REPOSITORY_REQUIRED:%s" % project)

    state_root = Path(state_dir).resolve()
    evidence_root = state_root / "reality" / run_id
    preflight_path = evidence_root / "preflight.json"
    summary_path = evidence_root / "reality-result.json"
    platform_info = detect_platform()

    client = HttpCenterClient(center_url)
    health = client.get("/health")
    if health.get("status") != "READY":
        raise CodeGraphRealityError("CENTER_NOT_READY")

    snapshot = capture_git_snapshot(str(project))
    changed_files, query_points = discover_java_query_points(
        str(project),
        base_ref=base_ref,
        head_ref=head_ref,
        target_file=target_file,
        target_line=target_line,
        max_points=max_points,
    )
    preflight: Dict[str, object] = {
        "schema_version": 1,
        "status": "PREFLIGHT_PASS",
        "run_id": run_id,
        "node_id": node_id.strip(),
        "center": center_url,
        "platform": platform_info,
        "project_dir": str(project),
        "base_ref": base_ref,
        "head_ref": head_ref,
        "git_snapshot": {
            "head_revision": snapshot.head_revision,
            "dirty": snapshot.dirty,
            "snapshot_id": snapshot.snapshot_id,
        },
        "changed_java_files": list(changed_files),
        "query_points": [
            {"file_path": point.file_path, "line_number": point.line_number, "source": point.source}
            for point in query_points
        ],
        "codegraph_command": codegraph_command,
        "generated_at": int(time.time()),
        "truth_note": "Git defines source change/snapshot truth. CodeGraph must execute real structural queries against this snapshot.",
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

    qualification_run = "%s-capability" % run_id
    qualification_work_item = "%s-capability" % run_id
    execution_work_item = "%s-execution" % run_id

    client.post(
        "/api/v1/work-items/register",
        {
            "work_item_id": qualification_work_item,
            "test_run_id": qualification_run,
            "stage": "CAPABILITY_QUALIFICATION",
            "scope_refs": [identity.node_id, "codegraph", snapshot.snapshot_id],
            "required_capabilities": [],
        },
    )
    agent.lease(qualification_work_item, ttl_seconds=600)
    agent.start(qualification_work_item)
    _report_probe_state(agent, CapabilityState.PROBING, str(preflight_path), [])

    qualification_adapter = CodeGraphExecutableAdapter(
        str(evidence_root / "capability"),
        codegraph_command=codegraph_command,
        timeout_seconds=120,
    )
    qualification_result = qualification_adapter.execute(
        repo_path=str(project),
        base_ref=base_ref,
        head_ref=head_ref,
        target_file=target_file,
        target_line=target_line,
        max_points=1,
    )
    qualification_artifact = _upload_graph_evidence(
        agent,
        run_id=run_id,
        test_run_id=qualification_run,
        work_item_id=qualification_work_item,
        result=qualification_result,
        role="capability",
    )
    if qualification_result.state != "PASS":
        _report_probe_state(
            agent,
            CapabilityState.DEGRADED,
            qualification_result.evidence_path,
            [qualification_artifact],
        )
        agent.complete(qualification_work_item)
        summary = {
            "schema_version": 1,
            "reality_status": "CAPABILITY_NOT_VERIFIED",
            "run_id": run_id,
            "node_id": identity.node_id,
            "classification": qualification_result.classification,
            "snapshot_id": qualification_result.snapshot_before.snapshot_id,
            "artifact_ids": [qualification_artifact],
        }
        _write_json(summary_path, summary)
        return 20, summary

    verified = _report_probe_state(
        agent,
        CapabilityState.VERIFIED,
        qualification_result.evidence_path,
        [qualification_artifact],
    )
    agent.complete(qualification_work_item)

    client.post(
        "/api/v1/work-items/register",
        {
            "work_item_id": execution_work_item,
            "test_run_id": run_id,
            "stage": "CODE_ANALYSIS",
            "scope_refs": [str(project), base_ref, head_ref, qualification_result.snapshot_before.snapshot_id],
            "required_capabilities": ["codegraph"],
        },
    )
    agent.lease(execution_work_item, ttl_seconds=1200)
    agent.start(execution_work_item)

    execution_adapter = CodeGraphExecutableAdapter(
        str(evidence_root / "execution"),
        codegraph_command=codegraph_command,
        timeout_seconds=120,
    )
    execution = execution_adapter.execute(
        repo_path=str(project),
        base_ref=base_ref,
        head_ref=head_ref,
        target_file=target_file,
        target_line=target_line,
        max_points=max_points,
    )
    execution_artifact = _upload_graph_evidence(
        agent,
        run_id=run_id,
        test_run_id=run_id,
        work_item_id=execution_work_item,
        result=execution,
        role="execution",
    )

    # Close the small but important publication race: source must still match
    # the snapshot on which CodeGraph queried immediately before R1 publication.
    publish_snapshot = capture_git_snapshot(str(project))
    if publish_snapshot.snapshot_id != execution.snapshot_after.snapshot_id:
        raise CodeGraphRealityError("CODEGRAPH_SNAPSHOT_STALE_BEFORE_PUBLISH")
    if execution.state != "PASS":
        raise CodeGraphRealityError("CODEGRAPH_EXECUTION_NOT_VERIFIED:%s" % execution.classification)

    event = RuntimeEventEnvelope(
        event_id="%s-codegraph-evidence" % run_id,
        test_run_id=run_id,
        work_item_id=execution_work_item,
        node_id=identity.node_id,
        producer_kind=RuntimeProducerKind.TOOL,
        producer_ref="rc8:codegraph",
        event_type="CODEGRAPH_GRAPH_EVIDENCE_RECORDED",
        sequence=1,
        refs=[execution_artifact],
        data={
            "classification": execution.classification,
            "git_head": execution.snapshot_before.head_revision,
            "snapshot_id": execution.snapshot_before.snapshot_id,
            "dirty": execution.snapshot_before.dirty,
            "base_ref": base_ref,
            "head_ref": head_ref,
            "changed_java_files": list(execution.changed_java_files),
            "query_points": [
                {"file_path": point.file_path, "line_number": point.line_number, "source": point.source}
                for point in execution.query_points
            ],
            "tool_call_count": len(execution.tool_calls),
            "tool_names": [str(item.get("tool") or "") for item in execution.tool_calls],
            "graph_digest": execution.graph_digest,
            "assertion": "all real CodeGraph structural calls succeeded and source snapshot stayed unchanged through publish",
            "truth_source": "Git snapshot + real CodeGraph graph-only structural queries",
        },
    )
    r1_response = agent.append_runtime_event(event)
    receipt = r1_response.get("receipt") if isinstance(r1_response.get("receipt"), dict) else r1_response
    if str(receipt.get("status") or "") not in {"PERSISTENCE_VERIFIED", "IDEMPOTENT_REPLAY"}:
        raise CodeGraphRealityError("CODEGRAPH_R1_NOT_PERSISTED")
    completed = agent.complete(execution_work_item)
    work_item = completed.get("work_item") if isinstance(completed, dict) and isinstance(completed.get("work_item"), dict) else completed
    if not isinstance(work_item, dict) or work_item.get("state") != "COMPLETED":
        raise CodeGraphRealityError("CODEGRAPH_WORK_ITEM_NOT_COMPLETED")

    summary = {
        "schema_version": 1,
        "reality_status": "EXECUTION_CHAIN_VERIFIED",
        "run_id": run_id,
        "node_id": identity.node_id,
        "capability_state": verified.state.value,
        "capability_evidence_refs": list(verified.evidence_refs),
        "classification": execution.classification,
        "project_dir": str(project),
        "base_ref": base_ref,
        "head_ref": head_ref,
        "git_head": execution.snapshot_before.head_revision,
        "snapshot_id": execution.snapshot_before.snapshot_id,
        "dirty": execution.snapshot_before.dirty,
        "changed_java_files": list(execution.changed_java_files),
        "query_point_count": len(execution.query_points),
        "tool_call_count": len(execution.tool_calls),
        "graph_digest": execution.graph_digest,
        "artifact_ids": [qualification_artifact, execution_artifact],
        "r1_receipt": dict(receipt),
        "work_item_state": "COMPLETED",
        "preflight_path": str(preflight_path),
        "graph_evidence_path": execution.evidence_path,
        "generated_at": int(time.time()),
        "truth_note": "Only a run against the actual bank CodeGraph executable may be promoted to BANK_REALITY_VERIFIED.",
    }
    _write_json(summary_path, summary)
    return 0, summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="RC8 CodeGraph 行内真实链路验证")
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
    parser.add_argument("--max-points", type=int, default=2)
    parser.add_argument("--run-id", default="")
    args = parser.parse_args(argv)
    if not args.run_id:
        args.run_id = "REALITY-CG-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), (args.node_id or "node").replace(" ", "-"))
    try:
        code, summary = run_codegraph_reality(
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
            max_points=args.max_points,
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
        return code
    except (CodeGraphRealityError, CodeGraphAdapterError, NodeAgentError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "REALITY_VALIDATION_FAILED", "error": str(exc)}, ensure_ascii=False, sort_keys=True), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
