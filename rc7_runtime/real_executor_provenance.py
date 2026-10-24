"""Attempt-bound trusted provenance for RC7.1 L2-L7 real executors.

Runner manifests are worker/script output and therefore cannot prove that a
professional executor really ran. This module accepts only provenance emitted
by a trusted Runtime/MCP boundary after a successful external invocation and
binds that invocation to the durable AgentTeams execution identity for the same
Mission/Task/Attempt.

The provenance gate is independently versioned. Existing durable Missions are
never hash-drifted by this hardening; new Bank graph-v2 Missions explicitly
persist ``REAL_EXECUTOR_PROVENANCE_CONTRACT`` and become fail-closed at the
canonical EXECUTION PASS boundary.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from rc6_runtime.execution import ExecutionRecord
from rc6_runtime.truth import TruthRuntime

from .autonomous_contract import LAYER_REQUIRED_TOOLS, require_layer
from .models import Evidence
from .truth_overlay import append_entity


REAL_EXECUTOR_INVOCATION_KIND = "REAL_EXECUTOR_INVOCATION"
REAL_EXECUTOR_SOURCE_PREFIX = "runtime-tool://pfc-aitest-rc7/"
EXECUTION_BINDING_KIND = "DSH_AGENT_TEAMS_EXECUTION_BINDING"
RUNTIME_EXECUTION_RECORD_KIND = "RUNTIME_EXECUTION_RECORD"
RUNTIME_EXECUTION_RECORD_SOURCE = "runtime://formal-execution"

CONTRACT_KIND = "REAL_EXECUTOR_PROVENANCE_CONTRACT"
CONTRACT_VERSION = "v1"
CONTRACT_SOURCE_REF = "runtime://real-executor-provenance-contract/%s" % CONTRACT_VERSION
_REQUIRED_LAYERS = tuple("L%d" % i for i in range(2, 8))


class RealExecutorProvenanceError(RuntimeError):
    pass


def _required(value: Any, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RealExecutorProvenanceError(code)
    return text


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _contract_payload() -> Dict[str, object]:
    return {
        "schema_version": "pfc.aitest.rc7.1.real-executor-provenance-contract.v1",
        "contract_version": CONTRACT_VERSION,
        "version_policy": "CAPABILITY_BASED_NO_EXACT_VERSION_PIN",
        "enforced_layers": list(_REQUIRED_LAYERS),
        "authority": "TRUSTED_RUNTIME_OR_MCP_INVOCATION_ONLY",
        "runner_manifest_is_authority": False,
        "current_attempt_required": True,
        "agent_teams_execution_binding_required": True,
        "engineering_fixture_satisfies_bank_reality": False,
    }


def contract_sha256() -> str:
    body = json.dumps(_contract_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _contract_evidence_id(mission_id: str) -> str:
    return "EVD-REAL-EXEC-CONTRACT-" + hashlib.sha256(
        (mission_id + "\x1f" + CONTRACT_VERSION + "\x1f" + contract_sha256()).encode("utf-8")
    ).hexdigest()[:20]


def persist_contract(
    truth: TruthRuntime,
    *,
    mission_id: str,
    release_id: str,
    execution_task_id: str,
) -> Evidence:
    existing = [
        row for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == CONTRACT_KIND
    ]
    if existing:
        if len(existing) != 1:
            raise RealExecutorProvenanceError("REAL_EXECUTOR_CONTRACT_NOT_UNIQUE")
        row = existing[0]
        if str(row.get("source_ref") or "") != CONTRACT_SOURCE_REF:
            raise RealExecutorProvenanceError("REAL_EXECUTOR_CONTRACT_VERSION_MISMATCH")
        if str(row.get("content_hash") or "") != contract_sha256():
            raise RealExecutorProvenanceError("REAL_EXECUTOR_CONTRACT_HASH_MISMATCH")
        if execution_task_id not in list(row.get("subject_refs") or []):
            raise RealExecutorProvenanceError("REAL_EXECUTOR_CONTRACT_TASK_MISMATCH")
        return Evidence(
            evidence_id=str(row["evidence_id"]),
            mission_id=mission_id,
            kind=CONTRACT_KIND,
            source_ref=str(row["source_ref"]),
            content_ref=str(row["content_ref"]),
            subject_refs=list(row.get("subject_refs") or []),
            content_hash=str(row.get("content_hash") or ""),
            created_at=int(row.get("created_at", 0)),
        )
    evidence = Evidence(
        evidence_id=_contract_evidence_id(mission_id),
        mission_id=mission_id,
        kind=CONTRACT_KIND,
        source_ref=CONTRACT_SOURCE_REF,
        content_ref="real-executor-provenance-contract://%s/%s" % (CONTRACT_VERSION, contract_sha256()),
        subject_refs=[execution_task_id],
        content_hash=contract_sha256(),
    )
    append_entity(truth, evidence, release_id=release_id, artifact_version=1)
    return evidence


def contract_row(truth: TruthRuntime, mission_id: str) -> Optional[Mapping[str, object]]:
    rows = [
        row for row in truth.query("rc7_evidence", mission_id=mission_id)
        if row.get("kind") == CONTRACT_KIND
    ]
    if not rows:
        return None
    if len(rows) != 1:
        raise RealExecutorProvenanceError("REAL_EXECUTOR_CONTRACT_NOT_UNIQUE")
    row = rows[0]
    if str(row.get("source_ref") or "") != CONTRACT_SOURCE_REF:
        raise RealExecutorProvenanceError("REAL_EXECUTOR_CONTRACT_VERSION_MISMATCH")
    if str(row.get("content_hash") or "") != contract_sha256():
        raise RealExecutorProvenanceError("REAL_EXECUTOR_CONTRACT_HASH_MISMATCH")
    return row


def contract_enabled(truth: TruthRuntime, mission_id: str) -> bool:
    return contract_row(truth, mission_id) is not None


def _mission_release_id(truth: TruthRuntime, mission_id: str) -> str:
    rows = truth.query("rc7_mission", mission_id=mission_id)
    if len(rows) != 1:
        raise RealExecutorProvenanceError("REAL_EXECUTOR_MISSION_NOT_UNIQUE")
    return _required(rows[0].get("release_id"), "REAL_EXECUTOR_RELEASE_ID_REQUIRED")


def _verified_file_payload(row: Mapping[str, Any], code: str) -> Dict[str, Any]:
    ref = _required(row.get("content_ref"), code + "_CONTENT_REF_REQUIRED")
    if not ref.startswith("file://"):
        raise RealExecutorProvenanceError(code + "_FILE_REF_REQUIRED")
    path = Path(ref[len("file://") :])
    try:
        body = path.read_bytes()
        payload = json.loads(body.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RealExecutorProvenanceError(code + "_UNREADABLE") from exc
    if not isinstance(payload, dict):
        raise RealExecutorProvenanceError(code + "_NOT_OBJECT")
    expected = "sha256:" + hashlib.sha256(body).hexdigest()
    if str(row.get("content_hash") or "") != expected:
        raise RealExecutorProvenanceError(code + "_HASH_MISMATCH")
    return payload


def _execution_binding(
    truth: TruthRuntime,
    *,
    mission_id: str,
    task_id: str,
    attempt_id: str,
) -> Tuple[Mapping[str, Any], Dict[str, Any]]:
    matches = []
    for row in truth.query("rc7_evidence", mission_id=mission_id):
        if row.get("kind") != EXECUTION_BINDING_KIND:
            continue
        subjects = set(str(item) for item in (row.get("subject_refs") or []))
        if task_id in subjects and attempt_id in subjects:
            matches.append(row)
    if len(matches) != 1:
        raise RealExecutorProvenanceError("REAL_EXECUTOR_BINDING_NOT_UNIQUE:%d" % len(matches))
    row = matches[0]
    payload = _verified_file_payload(row, "REAL_EXECUTOR_BINDING")
    expected = {"mission_id": mission_id, "task_id": task_id, "attempt_id": attempt_id}
    for field, value in expected.items():
        if str(payload.get(field) or "") != value:
            raise RealExecutorProvenanceError("REAL_EXECUTOR_BINDING_%s_MISMATCH" % field.upper())
    return row, payload


def required_executor_tools(layer: str) -> Tuple[str, ...]:
    canonical = require_layer(str(layer).upper())
    if canonical.value not in _REQUIRED_LAYERS:
        return ()
    return tuple(LAYER_REQUIRED_TOOLS[canonical])


def _execution_record_from_payload(payload: Mapping[str, Any]) -> ExecutionRecord:
    raw = payload.get("record")
    if not isinstance(raw, dict):
        raise RealExecutorProvenanceError("REAL_EXECUTOR_RUNTIME_RECORD_PAYLOAD_REQUIRED")
    return ExecutionRecord(
        attempt_id=_required(raw.get("attempt_id"), "REAL_EXECUTOR_RUNTIME_ATTEMPT_REQUIRED"),
        tc_id=_required(raw.get("tc_id"), "REAL_EXECUTOR_RUNTIME_TC_REQUIRED"),
        case_version=int(raw.get("case_version", 0)),
        target_id=_required(raw.get("target_id"), "REAL_EXECUTOR_RUNTIME_TARGET_REQUIRED"),
        layer=_required(raw.get("layer"), "REAL_EXECUTOR_RUNTIME_LAYER_REQUIRED"),
        worker_id=_required(raw.get("worker_id"), "REAL_EXECUTOR_RUNTIME_WORKER_REQUIRED"),
        lease_id=_required(raw.get("lease_id"), "REAL_EXECUTOR_RUNTIME_LEASE_REQUIRED"),
        status=_required(raw.get("status"), "REAL_EXECUTOR_RUNTIME_STATUS_REQUIRED"),
        integrity_passed=bool(raw.get("integrity_passed")),
        actual_result=dict(raw.get("actual_result") or {}),
        tool_call_refs=tuple(raw.get("tool_call_refs") or ()),
        evidence_refs=tuple(raw.get("evidence_refs") or ()),
        assertion_ref=raw.get("assertion_ref"),
        assertion_passed=raw.get("assertion_passed"),
        reason=raw.get("reason"),
    )


def _runtime_execution_record(
    truth: TruthRuntime,
    *,
    mission_id: str,
    task_id: str,
    attempt_id: str,
) -> ExecutionRecord:
    matches = []
    for row in truth.query("rc7_evidence", mission_id=mission_id):
        if row.get("kind") != RUNTIME_EXECUTION_RECORD_KIND:
            continue
        if str(row.get("source_ref") or "") != RUNTIME_EXECUTION_RECORD_SOURCE:
            continue
        subjects = set(str(item) for item in (row.get("subject_refs") or []))
        if task_id in subjects and attempt_id in subjects:
            matches.append(row)
    if len(matches) != 1:
        raise RealExecutorProvenanceError("REAL_EXECUTOR_RUNTIME_RECORD_NOT_UNIQUE:%d" % len(matches))
    payload = _verified_file_payload(matches[0], "REAL_EXECUTOR_RUNTIME_RECORD")
    if payload.get("mission_id") not in (None, mission_id):
        raise RealExecutorProvenanceError("REAL_EXECUTOR_RUNTIME_RECORD_MISSION_MISMATCH")
    if payload.get("task_id") not in (None, task_id):
        raise RealExecutorProvenanceError("REAL_EXECUTOR_RUNTIME_RECORD_TASK_MISMATCH")
    record = _execution_record_from_payload(payload)
    if record.attempt_id != attempt_id:
        raise RealExecutorProvenanceError("REAL_EXECUTOR_RUNTIME_RECORD_ATTEMPT_MISMATCH")
    return record


@dataclass(frozen=True)
class RealExecutorProvenanceResult:
    mission_id: str
    task_id: str
    attempt_id: str
    layer: str
    status: str
    required_tools: Tuple[str, ...]
    observed_tools: Tuple[str, ...]
    evidence_ids: Tuple[str, ...]
    missing_tools: Tuple[str, ...]


def record_successful_execution_invocation(
    truth: TruthRuntime,
    *,
    evidence_root: str,
    mission_id: str,
    task_id: str,
    attempt_id: str,
    runtime_worker_id: str,
    layer: str,
    target_id: str,
    tool_name: str,
    invocation_ref: str,
    result: object,
) -> Evidence:
    """Persist trusted invocation evidence after the Runtime/MCP call succeeds.

    This function is intentionally not called from runner-manifest parsing. It
    must be invoked by the trusted adapter that performed the real external call.
    """
    mission_id = _required(mission_id, "REAL_EXECUTOR_MISSION_REQUIRED")
    task_id = _required(task_id, "REAL_EXECUTOR_TASK_REQUIRED")
    attempt_id = _required(attempt_id, "REAL_EXECUTOR_ATTEMPT_REQUIRED")
    runtime_worker_id = _required(runtime_worker_id, "REAL_EXECUTOR_RUNTIME_WORKER_REQUIRED")
    layer = _required(layer, "REAL_EXECUTOR_LAYER_REQUIRED").upper()
    target_id = _required(target_id, "REAL_EXECUTOR_TARGET_REQUIRED")
    tool_name = _required(tool_name, "REAL_EXECUTOR_TOOL_REQUIRED")
    invocation_ref = _required(invocation_ref, "REAL_EXECUTOR_INVOCATION_REF_REQUIRED")
    if invocation_ref.startswith(("engineering-fixture://", "fixture://", "mock://")):
        raise RealExecutorProvenanceError("REAL_EXECUTOR_FIXTURE_INVOCATION_FORBIDDEN")
    required = required_executor_tools(layer)
    if not required:
        raise RealExecutorProvenanceError("REAL_EXECUTOR_LAYER_NOT_REQUIRED:%s" % layer)
    if tool_name not in required:
        raise RealExecutorProvenanceError("REAL_EXECUTOR_TOOL_LAYER_MISMATCH:%s:%s" % (layer, tool_name))
    binding_row, binding = _execution_binding(
        truth, mission_id=mission_id, task_id=task_id, attempt_id=attempt_id
    )
    specialist_worker_id = _required(binding.get("worker_instance_id"), "REAL_EXECUTOR_SPECIALIST_WORKER_REQUIRED")
    team_id = _required(binding.get("team_id"), "REAL_EXECUTOR_TEAM_REQUIRED")
    team_task_id = _required(binding.get("team_task_id"), "REAL_EXECUTOR_TEAM_TASK_REQUIRED")
    member_id = _required(binding.get("member_id"), "REAL_EXECUTOR_MEMBER_REQUIRED")
    task_rows = truth.query("rc7_task", task_id=task_id)
    if len(task_rows) != 1 or str(task_rows[0].get("mission_id") or "") != mission_id:
        raise RealExecutorProvenanceError("REAL_EXECUTOR_TASK_NOT_UNIQUE")
    if str(task_rows[0].get("state") or "") not in {"LEASED", "RUNNING", "OUTPUT_PRODUCED"}:
        raise RealExecutorProvenanceError("REAL_EXECUTOR_REQUIRES_ACTIVE_TASK")

    canonical_result = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    result_hash = hashlib.sha256(canonical_result.encode("utf-8")).hexdigest()
    invocation_id = _stable_id(
        "EXEC-INV", mission_id, task_id, attempt_id, runtime_worker_id, tool_name, invocation_ref, result_hash
    )
    payload = {
        "schema": "pfc.aitest.rc7.1.real-executor-invocation.v1",
        "invocation_id": invocation_id,
        "mission_id": mission_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "layer": layer,
        "target_id": target_id,
        "tool_id": tool_name,
        "runtime_worker_id": runtime_worker_id,
        "specialist_worker_id": specialist_worker_id,
        "team_id": team_id,
        "team_task_id": team_task_id,
        "member_id": member_id,
        "execution_binding_evidence_id": str(binding_row.get("evidence_id") or ""),
        "invocation_ref": invocation_ref,
        "result_sha256": result_hash,
        "status": "SUCCESS",
        "runner_manifest_is_not_authority": True,
    }
    root = Path(evidence_root).expanduser().resolve() / "real-executor-provenance" / mission_id
    root.mkdir(parents=True, exist_ok=True)
    path = root / (invocation_id + ".json")
    body = _canonical_bytes(payload)
    path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    evidence = Evidence(
        evidence_id=_stable_id("EVD-REAL-EXEC", mission_id, invocation_id, digest),
        mission_id=mission_id,
        kind=REAL_EXECUTOR_INVOCATION_KIND,
        source_ref=REAL_EXECUTOR_SOURCE_PREFIX + tool_name,
        content_ref="file://" + str(path),
        subject_refs=[
            task_id, attempt_id, layer, target_id, tool_name, runtime_worker_id,
            specialist_worker_id, team_id, team_task_id, str(binding_row.get("evidence_id") or ""),
        ],
        content_hash="sha256:" + digest,
    )
    if not truth.query("rc7_evidence", evidence_id=evidence.evidence_id):
        append_entity(truth, evidence, release_id=_mission_release_id(truth, mission_id), artifact_version=1)
    return evidence


class RealExecutorProvenanceGate:
    def __init__(self, truth: TruthRuntime) -> None:
        self.truth = truth

    def check_record(self, mission_id: str, task_id: str, record: ExecutionRecord) -> RealExecutorProvenanceResult:
        layer = str(record.layer or "").upper()
        required = required_executor_tools(layer)
        if not required:
            return RealExecutorProvenanceResult(
                mission_id=mission_id, task_id=task_id, attempt_id=record.attempt_id,
                layer=layer, status="NOT_REQUIRED", required_tools=(), observed_tools=(),
                evidence_ids=(), missing_tools=(),
            )
        binding_row, binding = _execution_binding(
            self.truth, mission_id=mission_id, task_id=task_id, attempt_id=record.attempt_id
        )
        binding_evidence_id = str(binding_row.get("evidence_id") or "")
        immutable_identity = {
            "specialist_worker_id": _required(binding.get("worker_instance_id"), "REAL_EXECUTOR_SPECIALIST_WORKER_REQUIRED"),
            "team_id": _required(binding.get("team_id"), "REAL_EXECUTOR_TEAM_REQUIRED"),
            "team_task_id": _required(binding.get("team_task_id"), "REAL_EXECUTOR_TEAM_TASK_REQUIRED"),
            "member_id": _required(binding.get("member_id"), "REAL_EXECUTOR_MEMBER_REQUIRED"),
        }
        observed = []
        evidence_ids = []
        for row in self.truth.query("rc7_evidence", mission_id=mission_id):
            if row.get("kind") != REAL_EXECUTOR_INVOCATION_KIND:
                continue
            source_ref = str(row.get("source_ref") or "")
            if not source_ref.startswith(REAL_EXECUTOR_SOURCE_PREFIX):
                continue
            payload = _verified_file_payload(row, "REAL_EXECUTOR_INVOCATION")
            expected = {
                "mission_id": mission_id,
                "task_id": task_id,
                "attempt_id": record.attempt_id,
                "layer": layer,
                "target_id": record.target_id,
                "runtime_worker_id": record.worker_id,
                "execution_binding_evidence_id": binding_evidence_id,
                "status": "SUCCESS",
                **immutable_identity,
            }
            if any(str(payload.get(field) or "") != str(value) for field, value in expected.items()):
                continue
            tool = str(payload.get("tool_id") or "")
            if tool not in required or source_ref != REAL_EXECUTOR_SOURCE_PREFIX + tool:
                continue
            invocation_ref = str(payload.get("invocation_ref") or "")
            if not invocation_ref or invocation_ref.startswith(("engineering-fixture://", "fixture://", "mock://")):
                continue
            observed.append(tool)
            evidence_ids.append(str(row.get("evidence_id") or ""))
        observed_set = set(observed)
        missing = tuple(tool for tool in required if tool not in observed_set)
        return RealExecutorProvenanceResult(
            mission_id=mission_id,
            task_id=task_id,
            attempt_id=record.attempt_id,
            layer=layer,
            status="PASS" if not missing else "FAIL",
            required_tools=required,
            observed_tools=tuple(sorted(observed_set)),
            evidence_ids=tuple(sorted(set(evidence_ids))),
            missing_tools=missing,
        )

    def require_record(self, mission_id: str, task_id: str, record: ExecutionRecord) -> RealExecutorProvenanceResult:
        result = self.check_record(mission_id, task_id, record)
        if result.status == "FAIL":
            raise RealExecutorProvenanceError(
                "REAL_EXECUTOR_PROVENANCE_FAILED:%s:%s" % (result.layer, ",".join(result.missing_tools))
            )
        return result

    def require_attempt(
        self,
        mission_id: str,
        task_id: str,
        attempt_id: str,
        execution_row: Mapping[str, object],
    ) -> RealExecutorProvenanceResult:
        layer = _required(execution_row.get("layer"), "REAL_EXECUTOR_EXECUTION_LAYER_REQUIRED").upper()
        required = required_executor_tools(layer)
        if not required:
            return RealExecutorProvenanceResult(
                mission_id=mission_id, task_id=task_id, attempt_id=attempt_id,
                layer=layer, status="NOT_REQUIRED", required_tools=(), observed_tools=(),
                evidence_ids=(), missing_tools=(),
            )
        record = _runtime_execution_record(
            self.truth, mission_id=mission_id, task_id=task_id, attempt_id=attempt_id
        )
        expected = {
            "attempt_id": attempt_id,
            "tc_id": str(execution_row.get("tc_id") or ""),
            "target_id": str(execution_row.get("target_id") or ""),
            "layer": layer,
            "status": str(execution_row.get("status") or ""),
        }
        actual = {
            "attempt_id": record.attempt_id,
            "tc_id": record.tc_id,
            "target_id": record.target_id,
            "layer": str(record.layer).upper(),
            "status": str(record.status),
        }
        for field, value in expected.items():
            if str(actual[field]) != str(value):
                raise RealExecutorProvenanceError("REAL_EXECUTOR_RUNTIME_RECORD_%s_MISMATCH" % field.upper())
        return self.require_record(mission_id, task_id, record)
