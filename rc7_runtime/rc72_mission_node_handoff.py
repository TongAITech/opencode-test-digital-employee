"""RC7.2 N1 AgentTeams assignment -> real DSH handoff bridge.

This atom consumes the durable N1 worker assignment and launches the inherited
production DSH headless worker without creating a second worker identity.  A
MissionNode worker Attempt is admitted only after the DSH runtime has returned a
fresh session id, at least one tool call, strict JSON output and a successful
process result.

The resulting Attempt is deliberately *not* a NodeDelivery or a NodeGate.  It
records only that the assigned worker actually ran and returned a candidate
handoff.  N1 remains RUNNING until a later independent delivery/gate atom.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher, WorkerAssignment, WorkerInvocation
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_authority import RC72AuthorityRuntime, REALITY_RECON_WORKER
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_mission_node_assignment import install_rc72_mission_node_assignment_overlay
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_mission_node_worker_attempt"
_EVENT = "RC72_MISSION_NODE_WORKER_ATTEMPT_UPSERTED"
_BUCKET = "rc72_mission_node_worker_attempts"
_NODE_TYPE = AutonomousMissionNode.N1_REALITY.value
_STAGE = "REALITY_RECON"
_TEAM_ROLE = REALITY_RECON_WORKER
_AGENT_ID = "reality-recon"
_PHASE = "MISSION_NODE_EXECUTION"
_ASSIGNMENT_STATUS = "LEASED_FOR_HANDOFF"
_ATTEMPT_STATE = "WORKER_COMPLETED_PENDING_DELIVERY"
_HANDOFF_STATUS = "DSH_SESSION_OBSERVED"
_PROCESS_OUTCOME = "SUCCEEDED"


class MissionNodeHandoffError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MissionNodeHandoffError("RC72_HANDOFF_%s_REQUIRED" % name.upper())
    return value.strip()


def _strings(value: Any, name: str, *, required: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError("RC72_HANDOFF_%s_INVALID" % name.upper())
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("RC72_HANDOFF_%s_INVALID" % name.upper())
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError("RC72_HANDOFF_%s_DUPLICATE" % name.upper())
    if required and not value:
        raise _contracts.DomainValidationError("RC72_HANDOFF_%s_REQUIRED" % name.upper())
    return list(value)


def _tool_calls(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise _contracts.DomainValidationError("RC72_HANDOFF_OBSERVED_TOOL_CALLS_REQUIRED")
    out: List[Dict[str, str]] = []
    seen = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise _contracts.DomainValidationError("RC72_HANDOFF_TOOL_CALL_INVALID")
        call_ref = raw.get("call_ref")
        tool_name = raw.get("tool_name")
        if not isinstance(call_ref, str) or not call_ref.strip():
            raise _contracts.DomainValidationError("RC72_HANDOFF_TOOL_CALL_REF_REQUIRED")
        if not isinstance(tool_name, str) or not tool_name.strip():
            raise _contracts.DomainValidationError("RC72_HANDOFF_TOOL_NAME_REQUIRED")
        key = (call_ref.strip(), tool_name.strip())
        if key in seen:
            raise _contracts.DomainValidationError("RC72_HANDOFF_TOOL_CALL_DUPLICATE")
        seen.add(key)
        out.append({"call_ref": key[0], "tool_name": key[1]})
    return out


def validate_rc72_mission_node_worker_attempt(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "attempt_id", "release_id", "mission_id", "release_batch_id", "source_commit",
        "assignment_id", "dispatch_id", "mission_node_id", "node_type", "stage",
        "workitem_id", "worker_instance_id", "team_role", "agent_id",
        "runtime_assignment_id", "authority_lease_id", "dsh_session_id",
        "runtime_event_id", "candidate_output_ref", "state", "handoff_status",
        "process_outcome",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["node_type"] != _NODE_TYPE:
        raise _contracts.DomainValidationError("RC72_HANDOFF_NODE_NOT_SUPPORTED")
    if out["stage"] != _STAGE:
        raise _contracts.DomainValidationError("RC72_HANDOFF_STAGE_INVALID")
    if out["team_role"] != _TEAM_ROLE:
        raise _contracts.DomainValidationError("RC72_HANDOFF_TEAM_ROLE_INVALID")
    if out["agent_id"] != _AGENT_ID:
        raise _contracts.DomainValidationError("RC72_HANDOFF_AGENT_ID_INVALID")
    if not out["dsh_session_id"].startswith("session-"):
        raise _contracts.DomainValidationError("RC72_HANDOFF_DSH_SESSION_INVALID")
    if out["state"] != _ATTEMPT_STATE:
        raise _contracts.DomainValidationError("RC72_HANDOFF_ATTEMPT_STATE_INVALID")
    if out["handoff_status"] != _HANDOFF_STATUS:
        raise _contracts.DomainValidationError("RC72_HANDOFF_STATUS_INVALID")
    if out["process_outcome"] != _PROCESS_OUTCOME:
        raise _contracts.DomainValidationError("RC72_HANDOFF_PROCESS_OUTCOME_INVALID")

    out["authorized_tools"] = _strings(out.get("authorized_tools"), "authorized_tools", required=True)
    out["runtime_evidence_refs"] = _strings(
        out.get("runtime_evidence_refs"), "runtime_evidence_refs", required=True
    )
    out["observed_tool_calls"] = _tool_calls(out.get("observed_tool_calls"))
    observed_names = {item["tool_name"] for item in out["observed_tool_calls"]}
    if not observed_names.issubset(set(out["authorized_tools"])):
        raise _contracts.DomainValidationError("RC72_HANDOFF_UNAUTHORIZED_TOOL_OBSERVED")

    for name in ("worker_started_at", "worker_finished_at", "created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError("RC72_HANDOFF_%s_INVALID" % name.upper())
    if out["worker_finished_at"] < out["worker_started_at"]:
        raise _contracts.DomainValidationError("RC72_HANDOFF_TIME_ORDER_INVALID")

    # This attempt proves only that a worker ran. Business truth is admitted by
    # the later NodeDelivery/NodeGate path and cannot be smuggled into this row.
    for forbidden in (
        "node_delivery_id", "node_gate", "node_gate_id", "node_pass", "q7_pass",
        "field_verified", "bank_final", "actual_result", "assertion_result",
        "business_evidence_refs",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_HANDOFF_BUSINESS_CLAIM_FORBIDDEN:%s" % forbidden
            )

    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_HANDOFF_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_mission_node_handoff_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_mission_node_assignment_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_mission_node_worker_attempt
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "attempt_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "attempt_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class N1DshHandoffService:
    """Run the assigned N1 worker through DSH and admit session-observed Attempt truth."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        launcher: DshHeadlessWorkerLauncher,
        allowed_tools: Sequence[str],
    ) -> None:
        install_rc72_mission_node_handoff_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.launcher = launcher
        tools = [str(item).strip() for item in allowed_tools if isinstance(item, str) and item.strip()]
        if not tools or len(set(tools)) != len(tools):
            raise MissionNodeHandoffError("RC72_HANDOFF_ALLOWED_TOOLS_INVALID")
        self.allowed_tools = tuple(tools)
        if not isinstance(self.launcher.authority, RC72AuthorityRuntime):
            raise MissionNodeHandoffError("RC72_HANDOFF_RC72_AUTHORITY_REQUIRED")

    @staticmethod
    def _attempt_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "N1_DSH_ATTEMPT"))
        return "N1ATT-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _runtime_assignment_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "DSH_RUNTIME_HANDOFF"))
        return "N1DSH-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise MissionNodeHandoffError(
                "RC72_HANDOFF_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows))
            )
        return rows[0]

    def _preflight(self, release_batch_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        assignments = self.truth.query(
            "rc72_mission_node_worker_assignment", release_batch_id=release_batch_id
        )
        exact = [
            row for row in assignments
            if row.get("source_commit") == self.source_commit
            and row.get("status") == _ASSIGNMENT_STATUS
            and row.get("node_type") == _NODE_TYPE
            and row.get("stage") == _STAGE
            and row.get("team_role") == _TEAM_ROLE
            and row.get("agent_id") == _AGENT_ID
        ]
        if len(exact) != 1:
            raise MissionNodeHandoffError(
                "RC72_HANDOFF_EXACT_ASSIGNMENT_REQUIRED:%d" % len(exact)
            )
        assignment = exact[0]
        mission_id = _required(assignment.get("mission_id"), "mission_id")
        release_id = _required(assignment.get("release_id"), "release_id")
        node_id = _required(assignment.get("mission_node_id"), "mission_node_id")
        workitem_id = _required(assignment.get("workitem_id"), "workitem_id")
        worker_id = _required(assignment.get("worker_instance_id"), "worker_instance_id")

        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        if batch.get("mission_id") != mission_id or batch.get("release_id") != release_id:
            raise MissionNodeHandoffError("RC72_HANDOFF_RELEASE_BATCH_LINEAGE_MISMATCH")

        dispatch = self._one(
            "rc72_mission_node_dispatch", dispatch_id=str(assignment["dispatch_id"])
        )
        if (
            dispatch.get("mission_id") != mission_id
            or dispatch.get("release_batch_id") != release_batch_id
            or dispatch.get("mission_node_id") != node_id
            or dispatch.get("workitem_id") != workitem_id
            or dispatch.get("source_commit") != self.source_commit
            or dispatch.get("status") != "READY_FOR_ASSIGNMENT"
        ):
            raise MissionNodeHandoffError("RC72_HANDOFF_DISPATCH_LINEAGE_MISMATCH")

        node = self._one("rc72_mission_node", mission_node_id=node_id)
        if (
            node.get("mission_id") != mission_id
            or node.get("node_type") != _NODE_TYPE
            or node.get("state") != MissionNodeState.RUNNING.value
        ):
            raise MissionNodeHandoffError("RC72_HANDOFF_N1_NOT_RUNNING")

        task = self._one("rc7_task", task_id=workitem_id)
        if (
            task.get("mission_id") != mission_id
            or task.get("node") != _STAGE
            or task.get("state") != "LEASED"
            or task.get("lease_owner") != worker_id
        ):
            raise MissionNodeHandoffError("RC72_HANDOFF_WORKITEM_LEASE_MISMATCH")
        return assignment, task

    def _handoff_events(self, mission_id: str, runtime_assignment_id: str) -> List[Dict[str, Any]]:
        rows = self.truth.query("agent_runtime_event", mission_id=mission_id)
        return [
            row for row in rows
            if row.get("event_name") == "HANDOFF_RETURNED"
            and row.get("assignment_id") == runtime_assignment_id
        ]

    def _assert_fresh_session(
        self,
        session_id: str,
        *,
        attempt_id: str,
        runtime_assignment_id: str,
    ) -> None:
        for row in self.truth.query(_ARTIFACT):
            if row.get("attempt_id") != attempt_id and row.get("dsh_session_id") == session_id:
                raise MissionNodeHandoffError("RC72_HANDOFF_DSH_SESSION_REUSED")
        for row in self.truth.query("agent_runtime_event"):
            if (
                row.get("event_name") == "HANDOFF_RETURNED"
                and row.get("assignment_id") != runtime_assignment_id
                and row.get("dsh_session_id") == session_id
            ):
                raise MissionNodeHandoffError("RC72_HANDOFF_DSH_SESSION_REUSED")

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "assignment_id", "dispatch_id", "mission_node_id", "node_type", "stage",
            "workitem_id", "worker_instance_id", "team_role", "agent_id",
            "runtime_assignment_id", "dsh_session_id", "candidate_output_ref", "state",
            "handoff_status", "process_outcome",
        )
        result = {key: payload.get(key) for key in keys}
        result["authorized_tools"] = list(payload.get("authorized_tools") or [])
        return result

    def _persist_from_invocation(
        self,
        *,
        assignment: Mapping[str, Any],
        attempt_id: str,
        runtime_assignment_id: str,
        invocation: WorkerInvocation,
        runtime_event: Mapping[str, Any],
        authority_lease_id: str,
        validate_live_authority: bool,
    ) -> Dict[str, Any]:
        worker_id = str(assignment["worker_instance_id"])
        mission_id = str(assignment["mission_id"])
        if invocation.worker_instance_id != worker_id or invocation.mission_id != mission_id:
            raise MissionNodeHandoffError("RC72_HANDOFF_RUNTIME_IDENTITY_MISMATCH")
        if invocation.attempt_id != attempt_id or invocation.assignment_id != runtime_assignment_id:
            raise MissionNodeHandoffError("RC72_HANDOFF_RUNTIME_ATTEMPT_MISMATCH")
        session_id = _required(invocation.dsh_session_id, "dsh_session_id")
        if not session_id.startswith("session-"):
            raise MissionNodeHandoffError("RC72_HANDOFF_DSH_SESSION_INVALID")
        if invocation.result != "PASS" or invocation.exit_code != 0:
            raise MissionNodeHandoffError("RC72_HANDOFF_DSH_PROCESS_NOT_SUCCESSFUL")
        if not invocation.output_refs:
            raise MissionNodeHandoffError("RC72_HANDOFF_CANDIDATE_OUTPUT_REQUIRED")
        if not invocation.tool_calls:
            raise MissionNodeHandoffError("RC72_HANDOFF_TOOL_CALL_REQUIRED")

        observed = []
        for raw in invocation.tool_calls:
            call_ref = _required(raw.get("call_ref"), "tool_call_ref")
            tool_name = _required(raw.get("tool_name"), "tool_name")
            if tool_name not in self.allowed_tools:
                raise MissionNodeHandoffError("RC72_HANDOFF_UNAUTHORIZED_TOOL:%s" % tool_name)
            observed.append({"call_ref": call_ref, "tool_name": tool_name})

        if validate_live_authority:
            authority = self.launcher.authority
            control_session = "control-assignment://%s" % str(assignment["assignment_id"])
            authority.validate_identity(
                worker_id,
                role=_TEAM_ROLE,
                phase=_PHASE,
                generation=int(assignment["assignment_generation"]),
                session_id=control_session,
            )
            authority.validate_lease(
                worker_id,
                authority_lease_id,
                scope_ref="mission-node://%s" % str(assignment["mission_node_id"]),
                allowed_artifact_types=(),
                allowed_tools=self.allowed_tools,
            )
            for item in observed:
                authority.authorize_tool(worker_id, authority_lease_id, item["tool_name"])

        self._assert_fresh_session(
            session_id,
            attempt_id=attempt_id,
            runtime_assignment_id=runtime_assignment_id,
        )
        payload = {
            "attempt_id": attempt_id,
            "release_id": str(assignment["release_id"]),
            "mission_id": mission_id,
            "release_batch_id": str(assignment["release_batch_id"]),
            "source_commit": self.source_commit,
            "assignment_id": str(assignment["assignment_id"]),
            "dispatch_id": str(assignment["dispatch_id"]),
            "mission_node_id": str(assignment["mission_node_id"]),
            "node_type": _NODE_TYPE,
            "stage": _STAGE,
            "workitem_id": str(assignment["workitem_id"]),
            "worker_instance_id": worker_id,
            "team_role": _TEAM_ROLE,
            "agent_id": _AGENT_ID,
            "runtime_assignment_id": runtime_assignment_id,
            "authority_lease_id": authority_lease_id,
            "dsh_session_id": session_id,
            "runtime_event_id": _required(runtime_event.get("id"), "runtime_event_id"),
            "candidate_output_ref": str(invocation.output_refs[-1]),
            "authorized_tools": list(self.allowed_tools),
            "observed_tool_calls": observed,
            "runtime_evidence_refs": list(dict.fromkeys(invocation.evidence_refs)),
            "worker_started_at": int(invocation.started_at),
            "worker_finished_at": int(invocation.finished_at),
            "state": _ATTEMPT_STATE,
            "handoff_status": _HANDOFF_STATUS,
            "process_outcome": _PROCESS_OUTCOME,
        }
        existing = self.truth.query(_ARTIFACT, attempt_id=attempt_id)
        if existing:
            if len(existing) != 1 or self._signature(existing[0]) != self._signature(payload):
                raise MissionNodeHandoffError("RC72_HANDOFF_ATTEMPT_IDENTITY_CONFLICT")
            return existing[0]
        now = _now()
        payload.update({"created_at": now, "updated_at": now, "artifact_version": 1})
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, attempt_id=attempt_id)
        if len(rows) != 1:
            raise MissionNodeHandoffError("RC72_HANDOFF_ATTEMPT_PERSISTENCE_FAILED")
        return rows[0]

    def _recover_handoff(
        self,
        *,
        assignment: Mapping[str, Any],
        attempt_id: str,
        runtime_assignment_id: str,
        event: Mapping[str, Any],
    ) -> Dict[str, Any]:
        invocation = WorkerInvocation(
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
        return self._persist_from_invocation(
            assignment=assignment,
            attempt_id=attempt_id,
            runtime_assignment_id=runtime_assignment_id,
            invocation=invocation,
            runtime_event=event,
            authority_lease_id=invocation.lease_id,
            validate_live_authority=False,
        )

    def _prompt(self, assignment: Mapping[str, Any]) -> str:
        body = {
            "mission_id": assignment["mission_id"],
            "release_batch_id": assignment["release_batch_id"],
            "mission_node_id": assignment["mission_node_id"],
            "workitem_id": assignment["workitem_id"],
            "input_refs": list(assignment.get("input_refs") or []),
            "authorized_tools": list(self.allowed_tools),
        }
        return (
            "You are the dsh-agent-teams REALITY_RECON_WORKER for canonical N1 Reality Recon. "
            "Inspect real deployment, environment and capability reality using only the authorized tools. "
            "Do not claim NodeGate PASS, Q7 PASS, field_verified or BANK_FINAL. Preserve unknowns and gaps. "
            "Return strict JSON with keys status,facts,unknowns,gaps. Context="
            + json.dumps(body, ensure_ascii=False, sort_keys=True)
        )

    def handoff(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        assignment, task = self._preflight(release_batch_id)
        attempt_id = self._attempt_id(str(assignment["assignment_id"]))
        runtime_assignment_id = self._runtime_assignment_id(str(assignment["assignment_id"]))

        existing = self.truth.query(_ARTIFACT, attempt_id=attempt_id)
        if existing:
            if len(existing) != 1:
                raise MissionNodeHandoffError("RC72_HANDOFF_ATTEMPT_NOT_UNIQUE")
            if existing[0].get("source_commit") != self.source_commit:
                raise MissionNodeHandoffError("RC72_HANDOFF_ATTEMPT_SOURCE_COMMIT_MISMATCH")
            if existing[0].get("worker_instance_id") != assignment.get("worker_instance_id"):
                raise MissionNodeHandoffError("RC72_HANDOFF_ATTEMPT_WORKER_MISMATCH")
            return {
                "status": "RESUMED",
                "attempt_id": attempt_id,
                "worker_instance_id": existing[0]["worker_instance_id"],
                "dsh_session_id": existing[0]["dsh_session_id"],
                "candidate_output_ref": existing[0]["candidate_output_ref"],
                "attempt_state": existing[0]["state"],
                "workitem_state": str(task["state"]),
            }

        recovered = self._handoff_events(str(assignment["mission_id"]), runtime_assignment_id)
        if len(recovered) > 1:
            raise MissionNodeHandoffError("RC72_HANDOFF_RUNTIME_EVENT_NOT_UNIQUE")
        if recovered:
            row = self._recover_handoff(
                assignment=assignment,
                attempt_id=attempt_id,
                runtime_assignment_id=runtime_assignment_id,
                event=recovered[0],
            )
            return {
                "status": "RECOVERED",
                "attempt_id": attempt_id,
                "worker_instance_id": row["worker_instance_id"],
                "dsh_session_id": row["dsh_session_id"],
                "candidate_output_ref": row["candidate_output_ref"],
                "attempt_state": row["state"],
                "workitem_state": str(task["state"]),
            }

        authority = self.launcher.authority
        worker_id = str(assignment["worker_instance_id"])
        control_session = "control-assignment://%s" % str(assignment["assignment_id"])
        identity = authority.adopt_identity(
            worker_id=worker_id,
            role=_TEAM_ROLE,
            phase=_PHASE,
            layer=None,
            generation=int(assignment["assignment_generation"]),
            session_id=control_session,
        )
        authority_lease = authority.issue_lease(
            worker_id,
            "mission-node://%s" % str(assignment["mission_node_id"]),
            (),
            self.allowed_tools,
            ttl_seconds=max(self.launcher.timeout_seconds + 120, 300),
        )
        runtime_assignment = WorkerAssignment(
            identity=identity,
            lease=authority_lease,
            worker_instance_id=worker_id,
            agent_id=_AGENT_ID,
            mission_id=str(assignment["mission_id"]),
            attempt_id=attempt_id,
            assignment_id=runtime_assignment_id,
            parent_worker_id=self.launcher.coordinator_instance_id,
            scope="mission-node://%s" % str(assignment["mission_node_id"]),
            input_refs=tuple(assignment.get("input_refs") or []),
            allowed_artifact_types=(),
            allowed_tools=tuple(self.allowed_tools),
        )
        invocation, _candidate = self.launcher.execute(runtime_assignment, self._prompt(assignment))
        events = self._handoff_events(str(assignment["mission_id"]), runtime_assignment_id)
        if len(events) != 1:
            raise MissionNodeHandoffError(
                "RC72_HANDOFF_HANDOFF_RETURNED_REQUIRED:%d" % len(events)
            )
        row = self._persist_from_invocation(
            assignment=assignment,
            attempt_id=attempt_id,
            runtime_assignment_id=runtime_assignment_id,
            invocation=invocation,
            runtime_event=events[0],
            authority_lease_id=authority_lease.lease_id,
            validate_live_authority=True,
        )
        return {
            "status": "SESSION_OBSERVED",
            "attempt_id": attempt_id,
            "worker_instance_id": row["worker_instance_id"],
            "dsh_session_id": row["dsh_session_id"],
            "candidate_output_ref": row["candidate_output_ref"],
            "attempt_state": row["state"],
            "workitem_state": str(task["state"]),
        }


install_rc72_mission_node_handoff_overlay()
