"""Durable execution-chain call evidence for RC7 conditional runtime roles.

Failure diagnosis/recovery workers are not the EXECUTION producer and must not
be forced to impersonate its task lease owner. Their underlying RC6 authority
contracts still validate worker role + attempt-scoped lease. This additive R1
receipt only binds a successful governed tool call back to the canonical
EXECUTION task and attempt so Mission recovery conformance can verify the chain.
"""
from __future__ import annotations

import hashlib
import json
from typing import Mapping, Tuple

from rc6_runtime.truth import TruthRuntime

from .models import Evidence
from .truth_overlay import append_entity


EXECUTION_CHAIN_CALL_KIND = "EXECUTION_CHAIN_CALL"
CHAIN_TOOLS = {"failure_diagnose", "recovery_decide", "recovery_execute"}


class ExecutionChainEvidenceError(RuntimeError):
    pass


def validate_chain_context(
    truth: TruthRuntime,
    *,
    mission_id: str,
    task_id: str,
    worker_id: str,
    tool_name: str,
    attempt_id: str,
) -> Mapping[str, object]:
    values = {
        "mission_id": str(mission_id or "").strip(),
        "task_id": str(task_id or "").strip(),
        "worker_id": str(worker_id or "").strip(),
        "tool_name": str(tool_name or "").strip(),
        "attempt_id": str(attempt_id or "").strip(),
    }
    if not all(values.values()):
        raise ExecutionChainEvidenceError("EXECUTION_CHAIN_CONTEXT_REQUIRED")
    if values["tool_name"] not in CHAIN_TOOLS:
        raise ExecutionChainEvidenceError("EXECUTION_CHAIN_TOOL_NOT_ALLOWED:%s" % values["tool_name"])
    tasks = truth.query("rc7_task", task_id=values["task_id"])
    if len(tasks) != 1:
        raise ExecutionChainEvidenceError("EXECUTION_CHAIN_TASK_NOT_UNIQUE")
    task = tasks[0]
    if str(task.get("mission_id") or "") != values["mission_id"]:
        raise ExecutionChainEvidenceError("EXECUTION_CHAIN_TASK_MISSION_MISMATCH")
    if str(task.get("node") or "") != "EXECUTION":
        raise ExecutionChainEvidenceError("EXECUTION_CHAIN_REQUIRES_EXECUTION_TASK")
    if str(task.get("state") or "") not in {"LEASED", "RUNNING", "OUTPUT_PRODUCED"}:
        raise ExecutionChainEvidenceError("EXECUTION_CHAIN_TASK_NOT_ACTIVE:%s" % str(task.get("state") or ""))
    attempts = truth.query("execution_attempt", attempt_id=values["attempt_id"])
    if len(attempts) != 1:
        raise ExecutionChainEvidenceError("EXECUTION_CHAIN_ATTEMPT_NOT_UNIQUE")
    if str(attempts[0].get("status") or "") != "FAIL":
        raise ExecutionChainEvidenceError("EXECUTION_CHAIN_REQUIRES_FAILED_ATTEMPT")
    return task


def record_chain_call(
    truth: TruthRuntime,
    *,
    mission_id: str,
    task_id: str,
    worker_id: str,
    tool_name: str,
    attempt_id: str,
    result: object,
) -> Evidence:
    validate_chain_context(
        truth,
        mission_id=mission_id,
        task_id=task_id,
        worker_id=worker_id,
        tool_name=tool_name,
        attempt_id=attempt_id,
    )
    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    result_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    identity = "\x1f".join((mission_id, task_id, worker_id, tool_name, attempt_id, result_hash))
    evidence = Evidence(
        evidence_id="EVD-EXEC-CHAIN-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
        mission_id=mission_id,
        kind=EXECUTION_CHAIN_CALL_KIND,
        source_ref="mcp://pfc-aitest-rc7-execution-chain/%s" % tool_name,
        content_ref="execution-chain-call://%s/%s" % (tool_name, result_hash),
        subject_refs=[task_id, worker_id, "EXECUTION", tool_name, attempt_id],
        content_hash=result_hash,
    )
    if truth.query("rc7_evidence", evidence_id=evidence.evidence_id):
        return evidence
    missions = truth.query("rc7_mission", mission_id=mission_id)
    if len(missions) != 1:
        raise ExecutionChainEvidenceError("EXECUTION_CHAIN_MISSION_NOT_UNIQUE")
    release_id = str(missions[0].get("release_id") or "")
    if not release_id:
        raise ExecutionChainEvidenceError("EXECUTION_CHAIN_RELEASE_ID_MISSING")
    append_entity(truth, evidence, release_id=release_id, artifact_version=1)
    return evidence


def observed_chain_tools(truth: TruthRuntime, *, mission_id: str, task_id: str, attempt_id: str) -> Tuple[str, ...]:
    names = []
    for row in truth.query("rc7_evidence", mission_id=mission_id):
        if row.get("kind") != EXECUTION_CHAIN_CALL_KIND:
            continue
        refs = list(row.get("subject_refs") or [])
        if task_id not in refs or attempt_id not in refs:
            continue
        source = str(row.get("source_ref") or "")
        if source.startswith("mcp://pfc-aitest-rc7-execution-chain/"):
            names.append(source.rsplit("/", 1)[-1])
    return tuple(sorted(set(names)))
