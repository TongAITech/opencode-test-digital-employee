"""RC7.2 N2 revision receipt -> fresh DSH Attempt -> canonical candidate bridge.

A revision receipt proves only that a fresh Requirement WorkItem/worker lease
exists. This module executes that exact generation in a fresh DSH session,
anchors the raw JSONL bytes at Attempt admission, and later promotes only the
hash-matching traceable candidate into canonical RC7 Artifact/Evidence truth.

Promotion stops at OUTPUT_PRODUCED. Independent Requirement review remains the
sole acceptance authority; this module never emits Evaluation, NodeDelivery,
NodeGate, N3 execution, field_verified, Q7 PASS or BANK_FINAL.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher, WorkerAssignment, WorkerInvocation
from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .models import Artifact, ContractError, Evidence, TaskStatus
from .rc72_authority import RC72AuthorityRuntime, REQUIREMENT_ANALYSIS_WORKER
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_n2_candidate_guard import N2TraceableRequirementDshHandoffService
from .rc72_n2_revision import install_rc72_n2_revision_overlay
from .truth_overlay import install_rc7_truth_overlay


_ATTEMPT_ARTIFACT = "rc72_n2_revision_attempt"
_ATTEMPT_EVENT = "RC72_N2_REVISION_ATTEMPT_UPSERTED"
_ATTEMPT_BUCKET = "rc72_n2_revision_attempts"
_NODE_TYPE = AutonomousMissionNode.N2_REQUIREMENT.value
_STAGE = "REQUIREMENT_ANALYSIS"
_TEAM_ROLE = REQUIREMENT_ANALYSIS_WORKER
_AGENT_ID = "requirement-analysis"
_PHASE = "MISSION_NODE_EXECUTION"
_RECEIPT_STATUS = "LEASED_FOR_HANDOFF"
_ATTEMPT_STATE = "WORKER_COMPLETED_PENDING_DELIVERY"
_HANDOFF_STATUS = "DSH_SESSION_OBSERVED"
_PROCESS_OUTCOME = "SUCCEEDED"
_CANDIDATE_SCHEMA = "RC72_N2_REQUIREMENT_CANDIDATE_V1_TRACEABLE"
_ARTIFACT_TYPE = "REQUIREMENT_ANALYSIS_OUTPUT"

_ANALYSIS_DIMENSIONS = (
    "atomic_statements", "source_assertions", "business_rules", "roles",
    "preconditions", "normal_paths", "negative_paths", "boundaries", "states",
    "data_constraints", "dependencies", "side_effects", "dimension_exclusions",
)


class N2RevisionExecutionError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N2RevisionExecutionError("RC72_N2_REVEXEC_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _strings(value: Any, name: str, *, required: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_%s_INVALID" % name.upper())
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_%s_INVALID" % name.upper())
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_%s_DUPLICATE" % name.upper())
    if required and not value:
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_%s_REQUIRED" % name.upper())
    return list(value)


def _tool_calls(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_TOOL_CALLS_REQUIRED")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise _contracts.DomainValidationError("RC72_N2_REVEXEC_TOOL_CALL_INVALID")
        call_ref = item.get("call_ref")
        tool_name = item.get("tool_name")
        if not isinstance(call_ref, str) or not call_ref.strip():
            raise _contracts.DomainValidationError("RC72_N2_REVEXEC_TOOL_CALL_REF_REQUIRED")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise _contracts.DomainValidationError("RC72_N2_REVEXEC_TOOL_NAME_REQUIRED")
        key = (call_ref.strip(), tool_name.strip())
        if key in seen:
            raise _contracts.DomainValidationError("RC72_N2_REVEXEC_TOOL_CALL_DUPLICATE")
        seen.add(key)
        result.append({"call_ref": key[0], "tool_name": key[1]})
    return result


def validate_rc72_n2_revision_attempt(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "attempt_id", "release_id", "mission_id", "release_batch_id", "source_commit",
        "revision_id", "failed_gate_id", "failed_delivery_id", "mission_node_id",
        "node_type", "stage", "requirement_id", "workitem_id", "worker_instance_id",
        "team_role", "agent_id", "runtime_assignment_id", "authority_lease_id",
        "dsh_session_id", "runtime_event_id", "candidate_output_ref", "candidate_schema",
        "raw_output_ref", "raw_output_sha256", "state", "handoff_status", "process_outcome",
    ):
        out[name] = _contracts._require_str(out, name)
    generation = out.get("revision_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 2:
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_GENERATION_INVALID")
    out["revision_generation"] = generation
    if out["node_type"] != _NODE_TYPE or out["stage"] != _STAGE:
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_NODE_INVALID")
    if out["team_role"] != _TEAM_ROLE or out["agent_id"] != _AGENT_ID:
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_WORKER_ROLE_INVALID")
    if not out["dsh_session_id"].startswith("session-"):
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_DSH_SESSION_INVALID")
    if out["candidate_schema"] != _CANDIDATE_SCHEMA:
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_CANDIDATE_SCHEMA_INVALID")
    if not out["raw_output_ref"].startswith("file://"):
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_RAW_OUTPUT_REF_INVALID")
    if not out["raw_output_sha256"].startswith("sha256:") or len(out["raw_output_sha256"]) != 71:
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_RAW_SHA256_INVALID")
    if out["state"] != _ATTEMPT_STATE or out["handoff_status"] != _HANDOFF_STATUS:
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_ATTEMPT_STATE_INVALID")
    if out["process_outcome"] != _PROCESS_OUTCOME:
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_PROCESS_OUTCOME_INVALID")
    out["authorized_tools"] = _strings(out.get("authorized_tools"), "authorized_tools", required=True)
    out["runtime_evidence_refs"] = _strings(
        out.get("runtime_evidence_refs"), "runtime_evidence_refs", required=True
    )
    out["observed_tool_calls"] = _tool_calls(out.get("observed_tool_calls"))
    if not {item["tool_name"] for item in out["observed_tool_calls"]}.issubset(set(out["authorized_tools"])):
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_UNAUTHORIZED_TOOL_OBSERVED")
    for name in ("worker_started_at", "worker_finished_at", "created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError("RC72_N2_REVEXEC_%s_INVALID" % name.upper())
    if out["worker_finished_at"] < out["worker_started_at"]:
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_TIME_ORDER_INVALID")
    for forbidden in (
        "evaluation", "evaluation_result", "node_delivery_id", "node_gate", "node_pass",
        "n3_started", "q7_pass", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N2_REVEXEC_ACCEPTANCE_CLAIM_FORBIDDEN:%s" % forbidden
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N2_REVEXEC_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ATTEMPT_ARTIFACT
    return out


def install_rc72_n2_revision_execution_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_n2_revision_overlay()
    _contracts.VALIDATORS[_ATTEMPT_ARTIFACT] = validate_rc72_n2_revision_attempt
    _truth.BUCKETS[_ATTEMPT_ARTIFACT] = _ATTEMPT_BUCKET
    _truth.IDENTITY_FIELDS[_ATTEMPT_ARTIFACT] = "attempt_id"
    _truth.EVENT_TYPES[_ATTEMPT_EVENT] = (_ATTEMPT_ARTIFACT, "attempt_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _ATTEMPT_BUCKET):
        setattr(projection, _ATTEMPT_BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ATTEMPT_ARTIFACT, {})


class N2RevisionDshHandoffService:
    """Execute the active revision receipt with its exact fresh worker identity."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        launcher: DshHeadlessWorkerLauncher,
        allowed_tools: Sequence[str],
    ) -> None:
        install_rc72_n2_revision_execution_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.launcher = launcher
        tools = [str(item).strip() for item in allowed_tools if isinstance(item, str) and item.strip()]
        if not tools or len(set(tools)) != len(tools):
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_ALLOWED_TOOLS_INVALID")
        self.allowed_tools = tuple(tools)
        if not isinstance(self.launcher.authority, RC72AuthorityRuntime):
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_RC72_AUTHORITY_REQUIRED")

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N2RevisionExecutionError(
                "RC72_N2_REVEXEC_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows))
            )
        return rows[0]

    def _receipt(self, release_batch_id: str, requirement_id: str) -> Dict[str, Any]:
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = str(batch["mission_id"])
        node = self._one("rc72_mission_node", mission_id=mission_id, node_type=_NODE_TYPE)
        if node.get("state") != MissionNodeState.RUNNING.value:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_N2_NOT_RUNNING")
        gate_refs = list(node.get("gate_refs") or [])
        if not gate_refs:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_FAILED_GATE_REQUIRED")
        active_gate_id = str(gate_refs[-1])
        rows = self.truth.query("rc72_n2_revision_receipt", release_batch_id=release_batch_id)
        exact = [
            row for row in rows
            if row.get("source_commit") == self.source_commit
            and row.get("requirement_id") == requirement_id
            and row.get("failed_gate_id") == active_gate_id
            and row.get("status") == _RECEIPT_STATUS
        ]
        if len(exact) != 1:
            raise N2RevisionExecutionError(
                "RC72_N2_REVEXEC_ACTIVE_RECEIPT_REQUIRED:%d" % len(exact)
            )
        receipt = exact[0]
        task = self._one("rc7_task", task_id=str(receipt["revision_workitem_id"]))
        if (
            task.get("mission_id") != mission_id
            or task.get("node") != _STAGE
            or task.get("state") != TaskStatus.LEASED.value
            or task.get("lease_owner") != receipt.get("revision_worker_instance_id")
            or list(task.get("gap_refs") or []) != list(receipt.get("gap_refs") or [])
        ):
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_WORKITEM_LEASE_MISMATCH")
        if receipt.get("mission_node_id") != node.get("mission_node_id"):
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_NODE_LINEAGE_MISMATCH")
        return receipt

    @staticmethod
    def _attempt_id(revision_id: str) -> str:
        return _stable_id("N2REVATT", revision_id, "DSH_ATTEMPT")

    @staticmethod
    def _runtime_assignment_id(revision_id: str) -> str:
        return _stable_id("N2REVDSH", revision_id, "RUNTIME_HANDOFF")

    def _handoff_events(self, mission_id: str, runtime_assignment_id: str) -> List[Dict[str, Any]]:
        return [
            row for row in self.truth.query("agent_runtime_event", mission_id=mission_id)
            if row.get("event_name") == "HANDOFF_RETURNED"
            and row.get("assignment_id") == runtime_assignment_id
        ]

    def _assert_fresh_session(self, session_id: str, attempt_id: str, runtime_assignment_id: str) -> None:
        for artifact_type in ("rc72_n2_requirement_attempt", _ATTEMPT_ARTIFACT):
            for row in self.truth.query(artifact_type):
                if row.get("attempt_id") != attempt_id and row.get("dsh_session_id") == session_id:
                    raise N2RevisionExecutionError("RC72_N2_REVEXEC_DSH_SESSION_REUSED")
        for row in self.truth.query("agent_runtime_event"):
            if (
                row.get("event_name") == "HANDOFF_RETURNED"
                and row.get("assignment_id") != runtime_assignment_id
                and row.get("dsh_session_id") == session_id
            ):
                raise N2RevisionExecutionError("RC72_N2_REVEXEC_DSH_SESSION_REUSED")

    def _raw(self, invocation: WorkerInvocation, requirement_id: str) -> Tuple[str, str, Dict[str, Any]]:
        refs = [
            ref for ref in invocation.evidence_refs
            if isinstance(ref, str) and ref.startswith("file://")
        ]
        if len(refs) != 1:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_RAW_EVIDENCE_NOT_UNIQUE")
        ref = refs[0]
        path = Path(ref[len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.launcher.state_root)
        except ValueError as exc:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_RAW_EVIDENCE_OUTSIDE_STATE_ROOT") from exc
        if not path.is_file():
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_RAW_EVIDENCE_MISSING")
        raw = path.read_bytes()
        if not raw:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_RAW_EVIDENCE_EMPTY")
        events = tuple(self.launcher._parse_json_lines(raw.decode("utf-8")))
        candidate = self.launcher._final_json(events)
        try:
            normalized = N2TraceableRequirementDshHandoffService._validate_candidate(
                candidate, requirement_id
            )
        except Exception as exc:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_CANDIDATE_INVALID:%s" % exc) from exc
        if self.launcher._session_id(events) != invocation.dsh_session_id:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_SESSION_EVIDENCE_MISMATCH")
        parsed_calls = tuple(self.launcher._tool_calls(events))
        observed_calls = tuple(
            {"call_ref": str(item.get("call_ref") or ""), "tool_name": str(item.get("tool_name") or "")}
            for item in invocation.tool_calls
        )
        if parsed_calls != observed_calls:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_TOOL_EVIDENCE_MISMATCH")
        return ref, _sha256(raw), normalized

    def _prompt(self, receipt: Mapping[str, Any]) -> str:
        requirement_id = str(receipt["requirement_id"])
        context = {
            "revision_id": receipt["revision_id"],
            "revision_generation": receipt["revision_generation"],
            "requirement_id": requirement_id,
            "workitem_id": receipt["revision_workitem_id"],
            "gap_refs": list(receipt.get("gap_refs") or []),
            "input_artifact_refs": list(receipt.get("input_artifact_refs") or []),
            "authorized_tools": list(self.allowed_tools),
        }
        schema = {
            "status": "CANDIDATE",
            "facts": {
                "requirement_id": requirement_id,
                "sst_ids": ["evidence-proven SST ids; [] only with explicit gap"],
                "source_refs": ["real source/tool locators"],
                "analysis": {name: [] for name in _ANALYSIS_DIMENSIONS},
            },
            "unknowns": [],
            "gaps": [],
        }
        trace_rule = {
            "trace_links": [{
                "source_id": "source_assertions id",
                "atomic_id": "atomic_statements id",
                "evidence_ref": "exact locator from facts.source_refs",
            }],
            "rule": "Never invent evidence aliases; evidence_ref must equal one facts.source_refs locator.",
        }
        return (
            "You are a fresh RC7.2 N2 REQUIREMENT_ANALYSIS_WORKER revising exactly one Requirement. "
            "Use the repaired gap lineage and previous canonical candidate only as inputs; independently "
            "re-read real source evidence with authorized tools. Never reuse prior conclusions without "
            "evidence. Never guess SST ids. Never claim PASS/Evaluation/NodeGate/N3/field/BANK_FINAL. "
            "Return exactly one traceable JSON candidate. CONTEXT="
            + json.dumps(context, ensure_ascii=False, sort_keys=True)
            + " REQUIRED_SHAPE=" + json.dumps(schema, ensure_ascii=False, sort_keys=True)
            + " TRACE_CONTRACT=" + json.dumps(trace_rule, ensure_ascii=False, sort_keys=True)
        )

    def _invocation_from_event(self, event: Mapping[str, Any]) -> WorkerInvocation:
        return WorkerInvocation(
            worker_instance_id=str(event.get("worker_instance_id") or ""),
            agent_id=str(event.get("agent_id") or ""),
            mission_id=str(event.get("mission_id") or ""),
            attempt_id=str(event.get("attempt_id") or ""),
            assignment_id=str(event.get("assignment_id") or ""),
            lease_id=str(event.get("lease_id") or ""),
            parent_worker_id=str(event.get("parent_worker_id") or ""),
            scope=str(event.get("scope") or ""),
            input_refs=list(event.get("input_refs") or []),
            tool_calls=list(event.get("tool_calls") or []),
            output_refs=list(event.get("output_refs") or []),
            evidence_refs=list(event.get("evidence_refs") or []),
            started_at=int(event.get("started_at") or 0),
            finished_at=int(event.get("finished_at") or 0),
            result=str(event.get("result") or ""),
            dsh_session_id=str(event.get("dsh_session_id") or "") or None,
            exit_code=event.get("exit_code") if isinstance(event.get("exit_code"), int) else None,
        )

    def _persist(
        self,
        *,
        receipt: Mapping[str, Any],
        invocation: WorkerInvocation,
        event: Mapping[str, Any],
        authority_lease_id: str,
        validate_live_authority: bool,
    ) -> Dict[str, Any]:
        revision_id = str(receipt["revision_id"])
        attempt_id = self._attempt_id(revision_id)
        runtime_assignment_id = self._runtime_assignment_id(revision_id)
        worker_id = str(receipt["revision_worker_instance_id"])
        workitem_id = str(receipt["revision_workitem_id"])
        requirement_id = str(receipt["requirement_id"])
        if (
            invocation.worker_instance_id != worker_id
            or invocation.mission_id != receipt.get("mission_id")
            or invocation.attempt_id != attempt_id
            or invocation.assignment_id != runtime_assignment_id
            or invocation.result != "PASS"
            or invocation.exit_code != 0
            or not invocation.dsh_session_id
            or not invocation.output_refs
            or not invocation.tool_calls
        ):
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_INVOCATION_INVALID")
        for call in invocation.tool_calls:
            if str(call.get("tool_name") or "") not in self.allowed_tools:
                raise N2RevisionExecutionError(
                    "RC72_N2_REVEXEC_UNAUTHORIZED_TOOL:%s" % str(call.get("tool_name") or "")
                )
        if validate_live_authority:
            authority = self.launcher.authority
            control_session = "control-revision://%s" % revision_id
            authority.validate_identity(
                worker_id,
                role=_TEAM_ROLE,
                phase=_PHASE,
                generation=int(receipt["revision_generation"]),
                session_id=control_session,
            )
            authority.validate_lease(
                worker_id,
                authority_lease_id,
                scope_ref="task:%s" % workitem_id,
                allowed_artifact_types=(),
                allowed_tools=self.allowed_tools,
            )
            for call in invocation.tool_calls:
                authority.authorize_tool(worker_id, authority_lease_id, str(call["tool_name"]))
        session_id = str(invocation.dsh_session_id)
        self._assert_fresh_session(session_id, attempt_id, runtime_assignment_id)
        raw_ref, raw_hash, _candidate = self._raw(invocation, requirement_id)
        payload = {
            "attempt_id": attempt_id,
            "release_id": str(receipt["release_id"]),
            "mission_id": str(receipt["mission_id"]),
            "release_batch_id": str(receipt["release_batch_id"]),
            "source_commit": self.source_commit,
            "revision_id": revision_id,
            "revision_generation": int(receipt["revision_generation"]),
            "failed_gate_id": str(receipt["failed_gate_id"]),
            "failed_delivery_id": str(receipt["failed_delivery_id"]),
            "mission_node_id": str(receipt["mission_node_id"]),
            "node_type": _NODE_TYPE,
            "stage": _STAGE,
            "requirement_id": requirement_id,
            "workitem_id": workitem_id,
            "worker_instance_id": worker_id,
            "team_role": _TEAM_ROLE,
            "agent_id": _AGENT_ID,
            "runtime_assignment_id": runtime_assignment_id,
            "authority_lease_id": authority_lease_id,
            "dsh_session_id": session_id,
            "runtime_event_id": _required(event.get("id"), "runtime_event_id"),
            "candidate_output_ref": str(invocation.output_refs[-1]),
            "candidate_schema": _CANDIDATE_SCHEMA,
            "authorized_tools": list(self.allowed_tools),
            "observed_tool_calls": [
                {"call_ref": str(item["call_ref"]), "tool_name": str(item["tool_name"])}
                for item in invocation.tool_calls
            ],
            "runtime_evidence_refs": list(dict.fromkeys(invocation.evidence_refs)),
            "raw_output_ref": raw_ref,
            "raw_output_sha256": raw_hash,
            "worker_started_at": int(invocation.started_at),
            "worker_finished_at": int(invocation.finished_at),
            "state": _ATTEMPT_STATE,
            "handoff_status": _HANDOFF_STATUS,
            "process_outcome": _PROCESS_OUTCOME,
        }
        existing = self.truth.query(_ATTEMPT_ARTIFACT, attempt_id=attempt_id)
        if existing:
            if len(existing) != 1:
                raise N2RevisionExecutionError("RC72_N2_REVEXEC_ATTEMPT_NOT_UNIQUE")
            comparable = dict(payload)
            for key, value in comparable.items():
                if existing[0].get(key) != value:
                    raise N2RevisionExecutionError("RC72_N2_REVEXEC_ATTEMPT_CONFLICT:%s" % key)
            return existing[0]
        now = _now()
        payload.update({"created_at": now, "updated_at": now, "artifact_version": 1})
        self.truth.append_atomic(_ATTEMPT_EVENT, payload)
        return self._one(_ATTEMPT_ARTIFACT, attempt_id=attempt_id)

    def handoff(self, *, release_batch_id: str, requirement_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        requirement_id = _required(requirement_id, "requirement_id")
        receipt = self._receipt(release_batch_id, requirement_id)
        revision_id = str(receipt["revision_id"])
        attempt_id = self._attempt_id(revision_id)
        runtime_assignment_id = self._runtime_assignment_id(revision_id)
        existing = self.truth.query(_ATTEMPT_ARTIFACT, attempt_id=attempt_id)
        if existing:
            if len(existing) != 1:
                raise N2RevisionExecutionError("RC72_N2_REVEXEC_ATTEMPT_NOT_UNIQUE")
            row = existing[0]
            return {
                "status": "RESUMED", "attempt_id": attempt_id,
                "revision_id": revision_id, "revision_generation": receipt["revision_generation"],
                "requirement_id": requirement_id, "worker_instance_id": row["worker_instance_id"],
                "dsh_session_id": row["dsh_session_id"], "raw_output_sha256": row["raw_output_sha256"],
                "attempt_state": row["state"], "workitem_state": "LEASED",
            }
        events = self._handoff_events(str(receipt["mission_id"]), runtime_assignment_id)
        if len(events) > 1:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_RUNTIME_EVENT_NOT_UNIQUE")
        if events:
            invocation = self._invocation_from_event(events[0])
            row = self._persist(
                receipt=receipt,
                invocation=invocation,
                event=events[0],
                authority_lease_id=invocation.lease_id,
                validate_live_authority=False,
            )
            return {
                "status": "RECOVERED", "attempt_id": attempt_id,
                "revision_id": revision_id, "revision_generation": receipt["revision_generation"],
                "requirement_id": requirement_id, "worker_instance_id": row["worker_instance_id"],
                "dsh_session_id": row["dsh_session_id"], "raw_output_sha256": row["raw_output_sha256"],
                "attempt_state": row["state"], "workitem_state": "LEASED",
            }
        authority = self.launcher.authority
        worker_id = str(receipt["revision_worker_instance_id"])
        identity = authority.adopt_identity(
            worker_id=worker_id,
            role=_TEAM_ROLE,
            phase=_PHASE,
            layer=None,
            generation=int(receipt["revision_generation"]),
            session_id="control-revision://%s" % revision_id,
        )
        scope_ref = "task:%s" % str(receipt["revision_workitem_id"])
        lease = authority.issue_lease(
            worker_id, scope_ref, (), self.allowed_tools,
            ttl_seconds=max(self.launcher.timeout_seconds + 120, 300),
        )
        assignment = WorkerAssignment(
            identity=identity,
            lease=lease,
            worker_instance_id=worker_id,
            agent_id=_AGENT_ID,
            mission_id=str(receipt["mission_id"]),
            attempt_id=attempt_id,
            assignment_id=runtime_assignment_id,
            parent_worker_id=self.launcher.coordinator_instance_id,
            scope=scope_ref,
            input_refs=tuple(receipt.get("input_artifact_refs") or []),
            allowed_artifact_types=(),
            allowed_tools=tuple(self.allowed_tools),
        )
        invocation, candidate = self.launcher.execute(assignment, self._prompt(receipt))
        try:
            N2TraceableRequirementDshHandoffService._validate_candidate(candidate, requirement_id)
        except Exception as exc:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_CANDIDATE_INVALID:%s" % exc) from exc
        events = self._handoff_events(str(receipt["mission_id"]), runtime_assignment_id)
        if len(events) != 1:
            raise N2RevisionExecutionError(
                "RC72_N2_REVEXEC_HANDOFF_RETURNED_REQUIRED:%d" % len(events)
            )
        row = self._persist(
            receipt=receipt,
            invocation=invocation,
            event=events[0],
            authority_lease_id=lease.lease_id,
            validate_live_authority=True,
        )
        return {
            "status": "SESSION_OBSERVED", "attempt_id": attempt_id,
            "revision_id": revision_id, "revision_generation": receipt["revision_generation"],
            "requirement_id": requirement_id, "worker_instance_id": row["worker_instance_id"],
            "dsh_session_id": row["dsh_session_id"], "raw_output_sha256": row["raw_output_sha256"],
            "attempt_state": row["state"], "workitem_state": "LEASED",
        }


class N2RevisionCandidatePromotionService:
    """Promote one hash-anchored revision Attempt to canonical OUTPUT_PRODUCED."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        mission_id: str,
        source_commit: str,
        state_root: str,
    ) -> None:
        install_rc72_n2_revision_execution_overlay()
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.mission_id = _required(mission_id, "mission_id")
        self.source_commit = _required(source_commit, "source_commit")
        self.state_root = Path(_required(state_root, "state_root")).expanduser().resolve()
        self.control = ClosedLoopControlPlane(truth, self.release_id, self.mission_id)
        self.reader = CandidatePayloadReader()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N2RevisionExecutionError(
                "RC72_N2_REVEXEC_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows))
            )
        return rows[0]

    @staticmethod
    def _artifact_id(mission_id: str, task_id: str) -> str:
        raw = "\x1f".join((mission_id, task_id)).encode("utf-8")
        return "ART-TASK-%s" % hashlib.sha256(raw).hexdigest()[:20]

    def _attempt(self, release_batch_id: str, requirement_id: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        receipts = self.truth.query("rc72_n2_revision_receipt", release_batch_id=release_batch_id)
        candidates = [
            row for row in receipts
            if row.get("source_commit") == self.source_commit
            and row.get("requirement_id") == requirement_id
        ]
        if not candidates:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_REVISION_RECEIPT_REQUIRED")
        candidates.sort(key=lambda row: int(row.get("revision_generation") or 0))
        receipt = candidates[-1]
        if len([row for row in candidates if row.get("revision_generation") == receipt.get("revision_generation")]) != 1:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_REVISION_GENERATION_NOT_UNIQUE")
        attempts = self.truth.query(_ATTEMPT_ARTIFACT, revision_id=str(receipt["revision_id"]))
        if len(attempts) != 1:
            raise N2RevisionExecutionError(
                "RC72_N2_REVEXEC_REVISION_ATTEMPT_REQUIRED:%d" % len(attempts)
            )
        attempt = attempts[0]
        task = self._one("rc7_task", task_id=str(receipt["revision_workitem_id"]))
        if (
            attempt.get("source_commit") != self.source_commit
            or attempt.get("requirement_id") != requirement_id
            or attempt.get("workitem_id") != receipt.get("revision_workitem_id")
            or attempt.get("worker_instance_id") != receipt.get("revision_worker_instance_id")
            or task.get("lease_owner") != receipt.get("revision_worker_instance_id")
        ):
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_PROMOTION_LINEAGE_MISMATCH")
        return receipt, attempt, task

    def _candidate(self, attempt: Mapping[str, Any], requirement_id: str) -> Dict[str, Any]:
        ref = _required(attempt.get("raw_output_ref"), "raw_output_ref")
        path = Path(ref[len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.state_root)
        except ValueError as exc:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_PROMOTION_RAW_OUTSIDE_STATE_ROOT") from exc
        if not path.is_file():
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_PROMOTION_RAW_MISSING")
        raw = path.read_bytes()
        if _sha256(raw) != attempt.get("raw_output_sha256"):
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_PROMOTION_RAW_HASH_MISMATCH")
        events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(raw.decode("utf-8")))
        candidate = DshHeadlessWorkerLauncher._final_json(events)
        try:
            return N2TraceableRequirementDshHandoffService._validate_candidate(
                candidate, requirement_id
            )
        except Exception as exc:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_PROMOTION_CANDIDATE_INVALID:%s" % exc) from exc

    def _evidence(
        self,
        receipt: Mapping[str, Any],
        attempt: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> Tuple[Evidence, ...]:
        task_id = str(receipt["revision_workitem_id"])
        requirement_id = str(receipt["requirement_id"])
        result = [
            Evidence(
                evidence_id=_stable_id(
                    "EVD-N2-REV-RAW", self.mission_id, task_id,
                    str(attempt["attempt_id"]), str(attempt["raw_output_sha256"]),
                ),
                mission_id=self.mission_id,
                kind="N2_REQUIREMENT_REVISION_DSH_RAW_PROOF",
                source_ref="dsh://session/%s" % str(attempt["dsh_session_id"]),
                content_ref=str(attempt["raw_output_ref"]),
                subject_refs=[task_id, str(attempt["attempt_id"]), requirement_id],
                content_hash=str(attempt["raw_output_sha256"]),
            )
        ]
        for index, source_ref in enumerate(list(candidate["facts"]["source_refs"])):
            result.append(Evidence(
                evidence_id=_stable_id(
                    "EVD-N2-REV-SOURCE", self.mission_id, task_id,
                    requirement_id, str(index), str(source_ref),
                ),
                mission_id=self.mission_id,
                kind="N2_REQUIREMENT_SOURCE_PROOF",
                source_ref=str(source_ref),
                content_ref=str(source_ref),
                subject_refs=[task_id, requirement_id],
            ))
        return tuple(result)

    def _semantic(self, candidate: Mapping[str, Any]) -> Dict[str, Any]:
        facts = candidate["facts"]
        payload = dict(facts["analysis"])
        payload.update({
            "requirement_id": facts["requirement_id"],
            "sst_ids": list(facts["sst_ids"]),
            "source_refs": list(facts["source_refs"]),
            "candidate_unknowns": list(candidate.get("unknowns") or []),
            "candidate_gaps": list(candidate.get("gaps") or []),
            "sufficiency_v2_required": True,
        })
        return payload

    def _persist_envelope(
        self,
        *,
        task: Mapping[str, Any],
        receipt: Mapping[str, Any],
        attempt: Mapping[str, Any],
        artifact_id: str,
        evidence_ids: Sequence[str],
        semantic: Mapping[str, Any],
    ) -> Tuple[str, str]:
        target_dir = self.state_root / "rc7-worker-candidates"
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = _stable_id(
            "candidate", self.mission_id, str(task["task_id"]),
            str(attempt["attempt_id"]), str(attempt["worker_instance_id"]),
        ) + ".json"
        target = target_dir / filename
        envelope = {
            "task_id": str(task["task_id"]),
            "artifact": {
                "artifact_id": artifact_id,
                "artifact_type": _ARTIFACT_TYPE,
                "content_ref": str(attempt["raw_output_ref"]),
                "parent_refs": list(task.get("input_artifact_refs") or []),
                "evidence_refs": list(evidence_ids),
            },
            "semantic_payload": dict(semantic),
            "runtime_lineage": {
                "revision_id": receipt["revision_id"],
                "revision_generation": receipt["revision_generation"],
                "attempt_id": attempt["attempt_id"],
                "dsh_session_id": attempt["dsh_session_id"],
                "raw_output_sha256": attempt["raw_output_sha256"],
                "source_commit": attempt["source_commit"],
            },
        }
        encoded = (
            json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": "))
            + "\n"
        ).encode("utf-8")
        content_hash = _sha256(encoded)
        fd, temp_name = tempfile.mkstemp(prefix=filename + ".", suffix=".tmp", dir=str(target_dir))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return "file://" + str(target.resolve()), content_hash

    def promote(self, *, release_batch_id: str, requirement_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        requirement_id = _required(requirement_id, "requirement_id")
        receipt, attempt, task = self._attempt(release_batch_id, requirement_id)
        task_id = str(receipt["revision_workitem_id"])
        artifact_id = self._artifact_id(self.mission_id, task_id)
        if task.get("state") in {
            TaskStatus.OUTPUT_PRODUCED.value, TaskStatus.EVALUATING.value,
            TaskStatus.PASS.value, TaskStatus.REPAIR_REQUIRED.value,
        }:
            payload = self.reader.load(
                self.truth, artifact_id,
                expected_mission_id=self.mission_id,
                expected_task_id=task_id,
            )
            return {
                "status": "RESUMED", "task_id": task_id, "artifact_id": artifact_id,
                "content_ref": payload.content_ref, "content_hash": payload.content_hash,
                "task_state": str(task["state"]),
            }
        candidate = self._candidate(attempt, requirement_id)
        evidence = self._evidence(receipt, attempt, candidate)
        evidence_ids = list(dict.fromkeys(item.evidence_id for item in evidence))
        content_ref, content_hash = self._persist_envelope(
            task=task, receipt=receipt, attempt=attempt, artifact_id=artifact_id,
            evidence_ids=evidence_ids, semantic=self._semantic(candidate),
        )
        if task.get("state") == TaskStatus.LEASED.value:
            self.control.start(task_id, worker_ref=str(receipt["revision_worker_instance_id"]))
            task = self._one("rc7_task", task_id=task_id)
        if task.get("state") != TaskStatus.RUNNING.value:
            raise N2RevisionExecutionError(
                "RC72_N2_REVEXEC_PROMOTION_TASK_NOT_RUNNING:%s" % str(task.get("state") or "UNKNOWN")
            )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=self.mission_id,
            artifact_type=_ARTIFACT_TYPE,
            producer_task_id=task_id,
            content_ref=content_ref,
            parent_refs=list(task.get("input_artifact_refs") or []),
            evidence_refs=evidence_ids,
            content_hash=content_hash,
        )
        updated = self.control.submit_worker_output(WorkerOutput(
            task_id=task_id,
            worker_ref=str(receipt["revision_worker_instance_id"]),
            artifacts=(artifact,),
            evidence=evidence,
        ))
        if updated.state != TaskStatus.OUTPUT_PRODUCED:
            raise N2RevisionExecutionError("RC72_N2_REVEXEC_PROMOTION_OUTPUT_STATE_INVALID")
        self.reader.load(
            self.truth, artifact_id,
            expected_mission_id=self.mission_id,
            expected_task_id=task_id,
        )
        return {
            "status": "PROMOTED", "task_id": task_id, "artifact_id": artifact_id,
            "content_ref": content_ref, "content_hash": content_hash,
            "task_state": updated.state.value,
            "revision_id": receipt["revision_id"],
            "revision_generation": receipt["revision_generation"],
        }


install_rc72_n2_revision_execution_overlay()
