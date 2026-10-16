"""Durable node/tool execution contracts for RC7 Mission Graph v2.

A tool being packaged, discoverable or READY is not evidence that the worker
actually used it for the Mission task.  This module binds producer nodes to
capability-oriented tool groups and accepts only R1 evidence emitted by the
RC7 MCP runtime after a successful real tool call.

The contract is intentionally tool-version agnostic.  A capability can admit
multiple implementation tool IDs; field/runtime discovery decides which
implementation is executable on the bank host.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .models import Evidence, Task
from .truth_overlay import append_entity


NODE_TOOL_CONTRACT_KIND = "NODE_TOOL_CONTRACT"
NODE_TOOL_CALL_KIND = "NODE_TOOL_CALL"
CONTRACT_VERSION = "v1"
CONTRACT_SOURCE_REF = "runtime://node-tool-contract/%s" % CONTRACT_VERSION


class NodeToolConformanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolCapabilityRequirement:
    capability: str
    any_of_tools: Tuple[str, ...]

    def as_dict(self) -> Dict[str, object]:
        return {"capability": self.capability, "any_of_tools": list(self.any_of_tools)}


# REALITY_RECON is runtime-owned and already has its own immutable Reality
# Snapshot evidence.  Producer nodes below are fail-closed before PASS when the
# Mission carries NODE_TOOL_CONTRACT evidence.
NODE_TOOL_REQUIREMENTS: Mapping[str, Tuple[ToolCapabilityRequirement, ...]] = {
    "REQUIREMENT_ANALYSIS": (
        ToolCapabilityRequirement("REQUIREMENT_SOURCE_READ", ("read_text", "truth_query")),
        ToolCapabilityRequirement("REQUIREMENT_TRUTH_QUERY", ("truth_query",)),
    ),
    "CODE_ANALYSIS": (
        ToolCapabilityRequirement("SOURCE_REVISION_READ", ("git_show_revision",)),
        ToolCapabilityRequirement("SOURCE_DIFF", ("git_diff",)),
        ToolCapabilityRequirement("CODEGRAPH_DISCOVERY", ("codegraph_mcp_tools", "codegraph_probe")),
        ToolCapabilityRequirement("CODEGRAPH_QUERY", ("codegraph_mcp_call", "codegraph_query")),
    ),
    "TEST_DESIGN": (
        ToolCapabilityRequirement("INPUT_TRUTH_QUERY", ("truth_query",)),
        ToolCapabilityRequirement("TEST_DESIGN_PERSIST", ("artifact_record",)),
    ),
    "SCRIPT_READINESS": (
        ToolCapabilityRequirement("EXECUTABLE_SPEC_BUILD", ("executable_spec_build",)),
        ToolCapabilityRequirement("AUTOMATION_REUSE_RESOLVE", ("automation_reuse_resolve",)),
        ToolCapabilityRequirement("SCRIPT_BUILD", ("script_build",)),
        ToolCapabilityRequirement("SCRIPT_VALIDATE", ("script_validate",)),
    ),
    "EXECUTION": (
        ToolCapabilityRequirement("REAL_RUNNER_EXECUTE", ("runner_execute",)),
        ToolCapabilityRequirement("EXECUTION_CONVERGENCE", ("execution_convergence",)),
    ),
}


def _contract_payload() -> Dict[str, object]:
    return {
        "schema_version": "pfc.aitest.rc7.node-tool-contract.v1",
        "contract_version": CONTRACT_VERSION,
        "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
        "evidence_kind": NODE_TOOL_CALL_KIND,
        "requirements": {
            node: [requirement.as_dict() for requirement in requirements]
            for node, requirements in sorted(NODE_TOOL_REQUIREMENTS.items())
        },
    }


def contract_sha256() -> str:
    body = json.dumps(_contract_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _contract_evidence_id(mission_id: str) -> str:
    raw = (mission_id + "\x1f" + CONTRACT_VERSION + "\x1f" + contract_sha256()).encode("utf-8")
    return "EVD-NODE-TOOLS-" + hashlib.sha256(raw).hexdigest()[:20]


def persist_contract(
    truth: TruthRuntime,
    *,
    mission_id: str,
    release_id: str,
    task_ids: Sequence[str],
) -> Evidence:
    existing = [
        row for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == NODE_TOOL_CONTRACT_KIND
    ]
    if existing:
        if len(existing) != 1:
            raise NodeToolConformanceError("NODE_TOOL_CONTRACT_NOT_UNIQUE")
        if str(existing[0].get("content_hash") or "") != contract_sha256():
            raise NodeToolConformanceError("NODE_TOOL_CONTRACT_HASH_MISMATCH")
        return Evidence(
            evidence_id=str(existing[0]["evidence_id"]),
            mission_id=mission_id,
            kind=NODE_TOOL_CONTRACT_KIND,
            source_ref=str(existing[0]["source_ref"]),
            content_ref=str(existing[0]["content_ref"]),
            subject_refs=list(existing[0].get("subject_refs") or []),
            content_hash=str(existing[0].get("content_hash") or ""),
            created_at=int(existing[0].get("created_at", 0)),
        )
    evidence = Evidence(
        evidence_id=_contract_evidence_id(mission_id),
        mission_id=mission_id,
        kind=NODE_TOOL_CONTRACT_KIND,
        source_ref=CONTRACT_SOURCE_REF,
        content_ref="node-tool-contract://%s/%s" % (CONTRACT_VERSION, contract_sha256()),
        subject_refs=list(task_ids),
        content_hash=contract_sha256(),
    )
    append_entity(truth, evidence, release_id=release_id, artifact_version=1)
    return evidence


def contract_row(truth: TruthRuntime, mission_id: str) -> Optional[Mapping[str, object]]:
    rows = [
        row for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == NODE_TOOL_CONTRACT_KIND
    ]
    if not rows:
        return None
    if len(rows) != 1:
        raise NodeToolConformanceError("NODE_TOOL_CONTRACT_NOT_UNIQUE")
    row = rows[0]
    if str(row.get("source_ref") or "") != CONTRACT_SOURCE_REF:
        raise NodeToolConformanceError("NODE_TOOL_CONTRACT_VERSION_MISMATCH")
    if str(row.get("content_hash") or "") != contract_sha256():
        raise NodeToolConformanceError("NODE_TOOL_CONTRACT_HASH_MISMATCH")
    return row


def contract_enabled(truth: TruthRuntime, mission_id: str) -> bool:
    return contract_row(truth, mission_id) is not None


def _task_row(truth: TruthRuntime, mission_id: str, task_id: str) -> Mapping[str, object]:
    rows = truth.query("rc7_task", task_id=task_id)
    if len(rows) != 1:
        raise NodeToolConformanceError("NODE_TOOL_TASK_NOT_UNIQUE")
    row = rows[0]
    if str(row.get("mission_id") or "") != mission_id:
        raise NodeToolConformanceError("NODE_TOOL_TASK_MISSION_MISMATCH")
    return row


def validate_call_context(
    truth: TruthRuntime,
    *,
    mission_id: str,
    task_id: str,
    worker_id: str,
) -> Mapping[str, object]:
    mission_id = str(mission_id or "").strip()
    task_id = str(task_id or "").strip()
    worker_id = str(worker_id or "").strip()
    if not mission_id or not task_id or not worker_id:
        raise NodeToolConformanceError("NODE_TOOL_CALL_CONTEXT_REQUIRED")
    contract_row(truth, mission_id)
    row = _task_row(truth, mission_id, task_id)
    node = str(row.get("node") or "")
    if node not in NODE_TOOL_REQUIREMENTS:
        raise NodeToolConformanceError("NODE_TOOL_CONTRACT_NODE_NOT_PRODUCER:%s" % node)
    state = str(row.get("state") or "")
    if state not in {"LEASED", "RUNNING"}:
        raise NodeToolConformanceError("NODE_TOOL_CALL_REQUIRES_ACTIVE_TASK:%s" % state)
    lease_owner = str(row.get("lease_owner") or "")
    if lease_owner and lease_owner != worker_id:
        raise NodeToolConformanceError("NODE_TOOL_CALL_WORKER_NOT_TASK_OWNER")
    return row


def _call_evidence_id(mission_id: str, task_id: str, worker_id: str, tool_name: str, result_hash: str) -> str:
    body = "\x1f".join((mission_id, task_id, worker_id, tool_name, result_hash)).encode("utf-8")
    return "EVD-TOOL-CALL-" + hashlib.sha256(body).hexdigest()[:24]


def record_successful_call(
    truth: TruthRuntime,
    *,
    mission_id: str,
    task_id: str,
    worker_id: str,
    tool_name: str,
    result: object,
) -> Evidence:
    row = validate_call_context(
        truth,
        mission_id=mission_id,
        task_id=task_id,
        worker_id=worker_id,
    )
    tool_name = str(tool_name or "").strip()
    if not tool_name:
        raise NodeToolConformanceError("NODE_TOOL_NAME_REQUIRED")
    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    result_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    evidence = Evidence(
        evidence_id=_call_evidence_id(mission_id, task_id, worker_id, tool_name, result_hash),
        mission_id=mission_id,
        kind=NODE_TOOL_CALL_KIND,
        source_ref="mcp://pfc-aitest-rc7/%s" % tool_name,
        content_ref="tool-call://%s/%s" % (tool_name, result_hash),
        subject_refs=[task_id, worker_id, str(row.get("node") or ""), tool_name],
        content_hash=result_hash,
    )
    existing = truth.query("rc7_evidence", evidence_id=evidence.evidence_id)
    if existing:
        return evidence
    mission_rows = truth.query("rc7_mission", mission_id=mission_id)
    if len(mission_rows) != 1:
        raise NodeToolConformanceError("NODE_TOOL_MISSION_NOT_UNIQUE")
    release_id = str(mission_rows[0].get("release_id") or "")
    if not release_id:
        raise NodeToolConformanceError("NODE_TOOL_RELEASE_ID_MISSING")
    append_entity(truth, evidence, release_id=release_id, artifact_version=1)
    return evidence


@dataclass(frozen=True)
class NodeToolConformanceResult:
    mission_id: str
    task_id: str
    node: str
    status: str
    missing_capabilities: Tuple[str, ...]
    observed_tools: Tuple[str, ...]
    evidence_ids: Tuple[str, ...]

    def as_dict(self) -> Dict[str, object]:
        return {
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "node": self.node,
            "status": self.status,
            "missing_capabilities": list(self.missing_capabilities),
            "observed_tools": list(self.observed_tools),
            "evidence_ids": list(self.evidence_ids),
        }


class NodeToolConformanceChecker:
    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth

    def check_task(self, mission_id: str, task_id: str) -> NodeToolConformanceResult:
        enabled = contract_row(self.truth, mission_id)
        row = _task_row(self.truth, mission_id, task_id)
        node = str(row.get("node") or "")
        if enabled is None or node not in NODE_TOOL_REQUIREMENTS:
            return NodeToolConformanceResult(
                mission_id=mission_id,
                task_id=task_id,
                node=node,
                status="NOT_ENFORCED",
                missing_capabilities=(),
                observed_tools=(),
                evidence_ids=(),
            )
        evidence_rows = [
            item for item in self.truth.query("rc7_evidence", mission_id=mission_id)
            if item.get("kind") == NODE_TOOL_CALL_KIND and task_id in list(item.get("subject_refs") or [])
        ]
        observed: List[str] = []
        evidence_ids: List[str] = []
        for item in evidence_rows:
            source_ref = str(item.get("source_ref") or "")
            if not source_ref.startswith("mcp://pfc-aitest-rc7/"):
                continue
            tool = source_ref.rsplit("/", 1)[-1]
            if tool:
                observed.append(tool)
                evidence_ids.append(str(item.get("evidence_id") or ""))
        observed_set = set(observed)
        missing = [
            requirement.capability
            for requirement in NODE_TOOL_REQUIREMENTS[node]
            if not observed_set.intersection(requirement.any_of_tools)
        ]
        return NodeToolConformanceResult(
            mission_id=mission_id,
            task_id=task_id,
            node=node,
            status="PASS" if not missing else "FAIL",
            missing_capabilities=tuple(missing),
            observed_tools=tuple(sorted(observed_set)),
            evidence_ids=tuple(sorted(set(evidence_ids))),
        )

    def require_task_pass_ready(self, task: Task) -> NodeToolConformanceResult:
        result = self.check_task(task.mission_id, task.task_id)
        if result.status == "FAIL":
            raise NodeToolConformanceError(
                "NODE_TOOL_CONFORMANCE_FAILED:%s:%s" % (
                    task.node,
                    ",".join(result.missing_capabilities),
                )
            )
        return result


def mission_contract_summary(truth: TruthRuntime, mission_id: str) -> Dict[str, object]:
    row = contract_row(truth, mission_id)
    task_rows = truth.query("rc7_task", mission_id=mission_id)
    checker = NodeToolConformanceChecker(truth)
    task_results = []
    if row is not None:
        for task in task_rows:
            if str(task.get("node") or "") in NODE_TOOL_REQUIREMENTS:
                task_results.append(
                    checker.check_task(mission_id, str(task.get("task_id") or "")).as_dict()
                )
    return {
        "mission_id": mission_id,
        "contract_enabled": row is not None,
        "contract_version": CONTRACT_VERSION if row is not None else None,
        "contract_sha256": contract_sha256() if row is not None else None,
        "tasks": task_results,
    }
