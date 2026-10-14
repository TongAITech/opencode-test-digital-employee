from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .agent_runtime import (
    AgentRuntimeError,
    DshHeadlessWorkerLauncher,
    WorkerAssignment,
    WorkerInvocation,
    append_gap,
    append_requirement_analysis,
    append_requirement_review,
)
from .authority import AuthorityError, AuthorityRuntime
from .truth import TruthRuntime


WORKER_RUNTIME_KIND = "DSH_HEADLESS_FRESH_AGENT"
EXPECTED_REQUIREMENT_SLICE = (
    ("pfc-requirement-analysis", "analysis-attempt-1"),
    ("pfc-requirement-sufficiency", "sufficiency-attempt-1"),
    ("pfc-requirement-analysis", "analysis-attempt-2"),
    ("pfc-requirement-sufficiency", "sufficiency-attempt-2"),
)
_WORKER_LIFECYCLE = (
    "WORKER_ASSIGN_REQUESTED",
    "WORKER_ADMITTED",
    "WORKER_STARTED",
    "WORKER_TOOL_CALLED",
    "WORKER_OUTPUT_PRODUCED",
    "WORKER_COMPLETED",
    "HANDOFF_RETURNED",
)


class BankFinalDshHeadlessWorkerLauncher(DshHeadlessWorkerLauncher):
    """Fail-closed DSH worker launcher used by the BANK_FINAL qualifier.

    The base launcher establishes fresh DSH sessions and R1 lifecycle events.
    This hardening layer makes the signed TaskLease authoritative for every
    observed tool call and requires terminal DSH output before a handoff can be
    accepted. There is no Coordinator fallback path.
    """

    def _emit(
        self,
        event_name: str,
        invocation: WorkerInvocation,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        enriched = dict(extra or {})
        enriched.setdefault("worker_runtime", WORKER_RUNTIME_KIND)
        if event_name == "WORKER_TOOL_CALLED":
            call = enriched.get("tool_call")
            tool_name = call.get("tool_name") if isinstance(call, dict) else None
            if not isinstance(tool_name, str) or not tool_name:
                self._emit_routing_fail(invocation.mission_id, "TOOL_CALL_NAME_MISSING")
                raise AgentRuntimeError("ROUTING_INTEGRITY_FAIL:TOOL_CALL_NAME_MISSING")
            try:
                self.authority.authorize_tool(
                    invocation.worker_instance_id,
                    invocation.lease_id,
                    tool_name,
                )
            except AuthorityError as exc:
                self._emit_routing_fail(
                    invocation.mission_id,
                    "LEASE_TOOL_AUTHORIZATION_FAILED:%s" % exc,
                )
                raise AgentRuntimeError(
                    "ROUTING_INTEGRITY_FAIL:LEASE_TOOL_AUTHORIZATION_FAILED"
                ) from exc
        if event_name == "HANDOFF_RETURNED":
            if invocation.result != "PASS":
                raise AgentRuntimeError("HANDOFF_REQUIRES_WORKER_PASS")
            if not invocation.dsh_session_id:
                raise AgentRuntimeError("HANDOFF_REQUIRES_DSH_SESSION")
            if not invocation.tool_calls or not invocation.output_refs or not invocation.evidence_refs:
                raise AgentRuntimeError("HANDOFF_PROOF_INCOMPLETE")
            for call in invocation.tool_calls:
                tool_name = call.get("tool_name") if isinstance(call, dict) else None
                try:
                    self.authority.authorize_tool(
                        invocation.worker_instance_id,
                        invocation.lease_id,
                        str(tool_name or ""),
                    )
                except AuthorityError as exc:
                    self._emit_routing_fail(
                        invocation.mission_id,
                        "HANDOFF_TOOL_AUTHORIZATION_FAILED:%s" % exc,
                    )
                    raise AgentRuntimeError(
                        "ROUTING_INTEGRITY_FAIL:HANDOFF_TOOL_AUTHORIZATION_FAILED"
                    ) from exc
        return super()._emit(event_name, invocation, enriched)

    @classmethod
    def _final_json(cls, events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        """Accept professional output only from a terminal DSH `final` event."""
        finals: List[Dict[str, Any]] = []
        for event in events:
            kind = str(event.get("type") or event.get("event") or event.get("kind") or "").lower()
            if kind == "final":
                finals.append(event)
        if not finals:
            return {}
        final = finals[-1]
        values = cls._walk_values(final, {"text", "content", "message", "output"})
        for value in reversed(values):
            if not isinstance(value, str):
                continue
            obj = cls._last_json_object(value)
            if isinstance(obj, dict):
                payload = obj.get("qualification_payload")
                return payload if isinstance(payload, dict) else obj
        return {}


class BankFinalAgentRuntimeProofValidator:
    """Validate the exact first RC6 real Agent Runtime vertical slice from R1."""

    def validate(
        self,
        truth: TruthRuntime,
        mission_id: str,
        coordinator_instance_id: str,
    ) -> Tuple[str, Tuple[str, ...]]:
        events = [
            event
            for event in truth.store.iter_raw()
            if isinstance(event.get("payload"), dict)
            and event["payload"].get("mission_id") == mission_id
        ]
        if not events:
            raise AgentRuntimeError("R1_AGENT_RUNTIME_PROOF_EMPTY")
        if any(e.get("event_type") == "ROUTING_INTEGRITY_FAIL" for e in events):
            raise AgentRuntimeError("R1_PROOF_CONTAINS_ROUTING_INTEGRITY_FAIL")

        handoffs = [e for e in events if e.get("event_type") == "HANDOFF_RETURNED"]
        if len(handoffs) != 4:
            raise AgentRuntimeError("REQUIREMENT_SLICE_REQUIRES_EXACTLY_FOUR_HANDOFFS")

        worker_ids: List[str] = []
        sessions: List[str] = []
        handoff_indexes: List[int] = []
        for index, (event, expected) in enumerate(zip(handoffs, EXPECTED_REQUIREMENT_SLICE)):
            payload = event["payload"]
            agent_id, attempt_id = expected
            if payload.get("agent_id") != agent_id or payload.get("attempt_id") != attempt_id:
                raise AgentRuntimeError("REQUIREMENT_SLICE_HANDOFF_SEQUENCE_MISMATCH:%d" % (index + 1))
            if payload.get("parent_worker_id") != coordinator_instance_id:
                raise AgentRuntimeError("WORKER_PARENT_NOT_COORDINATOR:%d" % (index + 1))
            if payload.get("worker_runtime") != WORKER_RUNTIME_KIND:
                raise AgentRuntimeError("WORKER_RUNTIME_IDENTITY_MISSING:%d" % (index + 1))
            worker_id = str(payload.get("worker_instance_id") or "")
            session_id = str(payload.get("dsh_session_id") or "")
            if not worker_id or worker_id == coordinator_instance_id:
                raise AgentRuntimeError("COORDINATOR_WORKER_IDENTITY_COLLISION")
            if not session_id or session_id == coordinator_instance_id:
                raise AgentRuntimeError("WORKER_SESSION_NOT_INDEPENDENT")
            if payload.get("result") != "PASS":
                raise AgentRuntimeError("WORKER_HANDOFF_NOT_PASS")
            if not payload.get("tool_calls"):
                raise AgentRuntimeError("REAL_TOOL_CALL_MISSING")
            if not payload.get("output_refs") or not payload.get("evidence_refs"):
                raise AgentRuntimeError("WORKER_HANDOFF_PROOF_INCOMPLETE")
            worker_ids.append(worker_id)
            sessions.append(session_id)
            handoff_indexes.append(events.index(event))
            self._validate_worker_lifecycle(events, payload)

        if len(set(worker_ids)) != 4:
            raise AgentRuntimeError("WORKER_INSTANCE_REUSED")
        if len(set(sessions)) != 4:
            raise AgentRuntimeError("DSH_SESSION_REUSED")

        gap_event = self._single(events, "SUFFICIENCY_GAP_FOUND")
        repair_event = self._single(events, "REPAIR_REQUESTED")
        start_event = self._single(events, "SUFFICIENCY_STARTED")
        reassigned_event = self._single(events, "WORKER_REASSIGNED")
        reevaluated_event = self._single(events, "SUFFICIENCY_REEVALUATED")
        passed_event = self._single(events, "SUFFICIENCY_PASSED")

        if gap_event["payload"].get("gap_id") != "missing_boundary_rule":
            raise AgentRuntimeError("EXPECTED_MISSING_BOUNDARY_GAP_NOT_PROVEN")
        if repair_event["payload"].get("gap_id") != "missing_boundary_rule":
            raise AgentRuntimeError("REPAIR_NOT_ROUTED_FOR_MISSING_BOUNDARY")
        if passed_event["payload"].get("gate_status") != "SUFFICIENT":
            raise AgentRuntimeError("FINAL_SUFFICIENCY_GATE_NOT_SUFFICIENT")
        if start_event["payload"].get("reviewer_worker_instance_id") != worker_ids[1]:
            raise AgentRuntimeError("FIRST_REVIEWER_IDENTITY_MISMATCH")
        if reevaluated_event["payload"].get("reviewer_worker_instance_id") != worker_ids[3]:
            raise AgentRuntimeError("SECOND_REVIEWER_IDENTITY_MISMATCH")
        if passed_event["payload"].get("reviewer_worker_instance_id") != worker_ids[3]:
            raise AgentRuntimeError("FINAL_REVIEWER_IDENTITY_MISMATCH")
        if reassigned_event["payload"].get("worker_instance_id") != worker_ids[2]:
            raise AgentRuntimeError("REPAIR_WORKER_REASSIGNMENT_MISMATCH")
        if reassigned_event["payload"].get("previous_worker_instance_id") != worker_ids[0]:
            raise AgentRuntimeError("REPAIR_PREDECESSOR_MISMATCH")

        positions = {
            "a1": handoff_indexes[0],
            "s_start": events.index(start_event),
            "r1": handoff_indexes[1],
            "gap": events.index(gap_event),
            "repair": events.index(repair_event),
            "reassigned": events.index(reassigned_event),
            "a2": handoff_indexes[2],
            "reevaluated": events.index(reevaluated_event),
            "r2": handoff_indexes[3],
            "passed": events.index(passed_event),
        }
        ordered = [
            positions["a1"],
            positions["s_start"],
            positions["r1"],
            positions["gap"],
            positions["repair"],
            positions["reassigned"],
            positions["a2"],
            positions["reevaluated"],
            positions["r2"],
            positions["passed"],
        ]
        if ordered != sorted(ordered) or len(set(ordered)) != len(ordered):
            raise AgentRuntimeError("REQUIREMENT_SLICE_EVENT_ORDER_INVALID")

        proof_ids = tuple(str(event.get("event_id")) for event in events)
        return "PASS", proof_ids

    @staticmethod
    def _single(events: Sequence[Dict[str, Any]], event_type: str) -> Dict[str, Any]:
        matches = [event for event in events if event.get("event_type") == event_type]
        if len(matches) != 1:
            raise AgentRuntimeError("R1_EVENT_CARDINALITY_INVALID:%s" % event_type)
        return matches[0]

    @staticmethod
    def _validate_worker_lifecycle(events: Sequence[Dict[str, Any]], handoff: Dict[str, Any]) -> None:
        assignment_id = handoff.get("assignment_id")
        worker_events = [
            event
            for event in events
            if event.get("event_type") in _WORKER_LIFECYCLE
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("assignment_id") == assignment_id
        ]
        names = [str(event.get("event_type")) for event in worker_events]
        cursor = -1
        for required in _WORKER_LIFECYCLE:
            try:
                cursor = names.index(required, cursor + 1)
            except ValueError as exc:
                raise AgentRuntimeError(
                    "WORKER_LIFECYCLE_MISSING_OR_OUT_OF_ORDER:%s:%s" % (assignment_id, required)
                ) from exc


def authorize_requirement_analysis_write(
    authority: AuthorityRuntime,
    assignment: WorkerAssignment,
    truth: TruthRuntime,
    artifact: Dict[str, Any],
) -> None:
    authority.authorize_artifact(
        assignment.worker_instance_id,
        assignment.lease.lease_id,
        "requirement_analysis",
    )
    append_requirement_analysis(truth, artifact)


def authorize_requirement_review_write(
    authority: AuthorityRuntime,
    assignment: WorkerAssignment,
    truth: TruthRuntime,
    review: Dict[str, Any],
) -> None:
    authority.authorize_artifact(
        assignment.worker_instance_id,
        assignment.lease.lease_id,
        "requirement_review",
    )
    append_requirement_review(truth, review)


def authorize_gap_write(
    authority: AuthorityRuntime,
    assignment: WorkerAssignment,
    truth: TruthRuntime,
    review: Dict[str, Any],
    gap_id: str,
    status: str,
) -> str:
    authority.authorize_artifact(
        assignment.worker_instance_id,
        assignment.lease.lease_id,
        "analysis_gap",
    )
    return append_gap(truth, review, gap_id, status)
