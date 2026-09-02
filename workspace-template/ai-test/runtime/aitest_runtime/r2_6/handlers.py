from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from aitest_runtime.durable_core import CommandEnvelope, ComposedRuntimeState, PendingEvent, RuntimeError, canonical_sha256
from aitest_runtime.durable_core import MissionStatus
from aitest_runtime.execution_resume.contracts import ExecutionResumeState
from aitest_runtime.work_graph.contracts import PlanLifecycleState, TaskLifecycleState, WorkGraphState

from .contracts import (
    APPLIED,
    APPROVED_ROUTES,
    CANCELLED,
    CHOICE_SELECTED,
    CONTINUATION_PENDING,
    EXPIRED,
    CANCEL_HUMAN_GATE,
    EXTERNAL_ACTION_COMPLETED,
    EXPIRE_HUMAN_GATE,
    ESCALATE_HUMAN_GATE,
    EVENT_TYPES,
    GATE_KINDS,
    GOAL_REVISION,
    GOAL_REVISION as GOAL_REVISION_ROUTE,
    HUMAN_GATE_CANCELLED,
    HUMAN_GATE_CONTINUATION_RECORDED,
    HUMAN_GATE_DECISION_RECORDED,
    HUMAN_GATE_ESCALATED,
    HUMAN_GATE_EXPIRED,
    HUMAN_GATE_OPENED,
    INLINE_NON_SECRET,
    INFORMATION_PROVIDED,
    NONE,
    NOT_REQUIRED,
    OPEN_HUMAN_GATE,
    OUTCOMES,
    PLAN_REVISION,
    PENDING,
    RECORD_CONTINUATION,
    RECORD_HUMAN_DECISION,
    REJECTED,
    RESOLVED,
    RESUME_EXECUTION,
    ROUTES,
    R26Error,
    HumanGateRecord,
    HumanGateState,
    _allowed_routes,
    _digest,
    _mapping,
    _non_negative,
    _optional_text,
    _plain,
    _positive,
    _provenance,
    _text,
    _timestamp,
    policy_digest,
    replace_gate,
    validate_payload,
)


WORK_GRAPH_EXTENSION_ID = "r1_2_work_graph"
EXECUTION_RESUME_EXTENSION_ID = "r1_3b_execution_resume"


def _expect(payload: Mapping[str, Any], required: set[str]) -> dict[str, Any]:
    if set(payload) != required:
        raise R26Error("R2_6_SCHEMA_INVALID", "command payload contains unknown or missing fields")
    return dict(payload)


def _core_and_extensions(composed: ComposedRuntimeState) -> tuple[Any, WorkGraphState, ExecutionResumeState, HumanGateState]:
    try:
        work_graph = composed.extension_state(WORK_GRAPH_EXTENSION_ID)
        execution = composed.extension_state(EXECUTION_RESUME_EXTENSION_ID)
        gates = composed.extension_state("r2_6_human_gate")
    except RuntimeError as exc:
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "R2.6 dependencies are not registered") from exc
    if not isinstance(work_graph, WorkGraphState) or not isinstance(execution, ExecutionResumeState) or not isinstance(gates, HumanGateState):
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "R2.6 dependency state has an invalid type")
    return composed.core_state, work_graph, execution, gates


def _validate_open_binding(composed: ComposedRuntimeState, payload: Mapping[str, Any], gates: HumanGateState) -> None:
    core, work_graph, execution, _ = _core_and_extensions(composed)
    if core.mission is None or payload["mission_id"] != composed.mission_id:
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "Gate Mission identity is not canonical")
    if core.mission.status != MissionStatus.ACTIVE:
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "Human Gate requires an ACTIVE Mission")
    plan = work_graph.plan(payload["plan_id"])
    revision = work_graph.revision(payload["plan_revision_id"])
    task = work_graph.task(payload["task_id"])
    root = execution.attempt(payload["root_attempt_id"])
    origin = execution.attempt(payload["origin_attempt_id"])
    session = core.session(payload["origin_session_id"])
    if plan is None or revision is None or task is None or root is None or origin is None or session is None:
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "Gate binding references missing canonical facts")
    if plan.lifecycle_state != PlanLifecycleState.OPEN or plan.current_revision_id != payload["plan_revision_id"]:
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "Gate Plan Revision is not current and OPEN")
    if revision.plan_id != plan.plan_id or task.plan_id != plan.plan_id or task.plan_revision_id != revision.revision_id:
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "Gate Plan/Task binding is inconsistent")
    if task.lifecycle_state != TaskLifecycleState.ACTIVE:
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "Human Gate requires an ACTIVE Task")
    if (
        root.mission_id != composed.mission_id or root.root_attempt_id != payload["root_attempt_id"]
        or root.plan_id != plan.plan_id or root.task_id != task.task_id
        or root.plan_revision_id != revision.revision_id
    ):
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "root Attempt does not bind to Task and Plan Revision")
    if (
        origin.mission_id != composed.mission_id or origin.root_attempt_id != root.root_attempt_id
        or origin.plan_id != plan.plan_id or origin.plan_revision_id != revision.revision_id
        or origin.task_id != task.task_id or origin.runtime_session_id != session.session_id
    ):
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "origin Attempt/Session provenance is inconsistent")
    if session.mission_id != composed.mission_id:
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "origin Session Mission mismatch")
    if gates.current_cycle(payload["mission_id"], payload["task_id"], payload["root_attempt_id"]) is not None:
        raise R26Error("R2_6_ACTIVE_GATE_CONFLICT", "a blocking Human Gate already exists for this execution lineage")


def _validate_policy(payload: Mapping[str, Any]) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    allowed_outcomes = tuple(_text(item, "allowed_outcomes") for item in payload["allowed_outcomes"])
    if not allowed_outcomes or any(item not in OUTCOMES for item in allowed_outcomes) or len(set(allowed_outcomes)) != len(allowed_outcomes):
        raise R26Error("R2_6_DECISION_POLICY_VIOLATION", "policy allowed_outcomes is invalid")
    routes = _allowed_routes(payload["allowed_routes_by_outcome"])
    expected = policy_digest(
        _text(payload["decision_policy_id"], "decision_policy_id"),
        _positive(payload["decision_policy_version"], "decision_policy_version"),
        allowed_outcomes,
        routes,
    )
    if _digest(payload["decision_policy_digest"], "decision_policy_digest") != expected:
        raise R26Error("R2_6_DECISION_POLICY_VIOLATION", "decision policy digest mismatch")
    return allowed_outcomes, routes


def _validate_expiry(expiry_policy: str, expires_at: str | None) -> None:
    if expiry_policy == "NONE" and expires_at is not None:
        raise R26Error("R2_6_SCHEMA_INVALID", "NONE expiry policy cannot have expires_at")
    if expiry_policy != "NONE" and expires_at is None:
        raise R26Error("R2_6_SCHEMA_INVALID", "expiry policy requires expires_at")


def _gate(gates: HumanGateState, gate_id: str) -> HumanGateRecord:
    record = gates.gate(gate_id)
    if record is None:
        raise R26Error("R2_6_GATE_NOT_FOUND", f"Human Gate not found: {gate_id}")
    return record


def _assert_current_cycle(gates: HumanGateState, gate: HumanGateRecord) -> None:
    current = gates.current_cycle(gate.mission_id, gate.task_id, gate.root_attempt_id)
    if current is None:
        if gate.is_unfinished:
            raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "unfinished Gate is not the replayed current cycle")
        return
    if current.gate_id != gate.gate_id:
        raise R26Error("R2_6_ACTIVE_GATE_CONFLICT", "requested Gate is not the replayed current cycle")


def _cas_gate(payload: Mapping[str, Any], gate: HumanGateRecord) -> None:
    if payload["expected_gate_revision"] != gate.gate_revision:
        raise R26Error("R2_6_GATE_REVISION_CONFLICT", "Gate revision does not match replayed state")


def _cas_continuation(payload: Mapping[str, Any], gate: HumanGateRecord) -> None:
    if payload["expected_continuation_revision"] != gate.continuation_revision:
        raise R26Error("R2_6_CONTINUATION_REVISION_CONFLICT", "Continuation revision does not match replayed state")


def _require_pending(gate: HumanGateRecord) -> None:
    if gate.status != PENDING:
        if gate.decision_id is not None:
            raise R26Error("R2_6_DECISION_ALREADY_RECORDED", "Human Gate already has a canonical decision")
        raise R26Error("R2_6_GATE_NOT_PENDING", "Human Gate is not PENDING")


def _source_digest(composed: ComposedRuntimeState, reference: Mapping[str, Any], source_seq: int) -> str:
    core, work_graph, execution, _ = _core_and_extensions(composed)
    kind = reference.get("kind")
    if kind == "R1_3B_R2_5_SUCCESSOR":
        session = core.session(reference["successor_session_id"])
        attempt = execution.attempt(reference["successor_attempt_id"])
        predecessor = execution.attempt(reference["predecessor_attempt_id"])
        if session is None or attempt is None or predecessor is None:
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "successor continuation facts are missing")
        facts = {
            "kind": kind,
            "source_seq": source_seq,
            "session": {
                "session_id": session.session_id,
                "mission_id": session.mission_id,
                "created_at": session.created_at,
                "attributes": dict(session.attributes),
            },
            "attempt": attempt.to_dict(),
            "predecessor": predecessor.to_dict(),
            "predecessor_session_id": reference.get("predecessor_session_id"),
            "rotation_operation_id": reference.get("rotation_operation_id"),
        }
        return canonical_sha256(facts)
    if kind == "R2_2_GOAL_REVISION":
        goal = core.goal(reference["goal_id"])
        if goal is None:
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "Goal revision is missing")
        return canonical_sha256({
            "kind": kind,
            "source_seq": source_seq,
            "goal": {
                "goal_id": goal.goal_id,
                "mission_id": goal.mission_id,
                "revision": goal.revision,
                "definition": dict(goal.definition),
            },
        })
    if kind == "R2_3_R1_2_PLAN_REVISION":
        revision = work_graph.revision(reference["revision_id"])
        if revision is None:
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "Plan revision is missing")
        return canonical_sha256({"kind": kind, "source_seq": source_seq, "revision": revision.to_dict()})
    raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "unsupported continuation source kind")


def _validate_continuation_source(composed: ComposedRuntimeState, gate: HumanGateRecord, payload: Mapping[str, Any]) -> None:
    reference = _mapping(payload["canonical_reference"], "canonical_reference")
    route = payload["route"]
    source_seq = _positive(payload["source_seq"], "source_seq")
    if source_seq > composed.seq:
        raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "continuation source is ahead of the Event Stream")
    if route == RESUME_EXECUTION:
        required = {
            "kind", "successor_session_id", "successor_attempt_id", "successor_root_attempt_id",
            "predecessor_attempt_id", "predecessor_session_id", "rotation_operation_id",
        }
        if set(reference) != required or reference["kind"] != "R1_3B_R2_5_SUCCESSOR":
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "RESUME continuation reference is incomplete")
        for name in ("successor_session_id", "successor_attempt_id", "successor_root_attempt_id", "predecessor_attempt_id", "predecessor_session_id", "rotation_operation_id"):
            _text(reference[name], name)
        core, _, execution, _ = _core_and_extensions(composed)
        session = core.session(reference["successor_session_id"])
        attempt = execution.attempt(reference["successor_attempt_id"])
        predecessor = execution.attempt(reference["predecessor_attempt_id"])
        if session is None or attempt is None or predecessor is None:
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "RESUME continuation facts are missing")
        if attempt.attempt_kind != "RESUME" or attempt.predecessor_attempt_id != predecessor.attempt_id:
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "successor Attempt predecessor relation is invalid")
        if not isinstance(session.attributes, Mapping):
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "successor Session attributes are not canonical")
        if (
            session.attributes.get("predecessor_session_id") != reference["predecessor_session_id"]
            or session.attributes.get("rotation_operation_id") != reference["rotation_operation_id"]
        ):
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "successor Session rotation proof is invalid")
        if attempt.runtime_session_id != session.session_id or attempt.mission_id != gate.mission_id:
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "successor Session/Attempt Mission relation is invalid")
        if (
            attempt.plan_id != gate.plan_id or attempt.plan_revision_id != gate.plan_revision_id
            or attempt.task_id != gate.task_id or attempt.root_attempt_id != gate.root_attempt_id
        ):
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "successor Attempt does not preserve Gate lineage")
        if (
            predecessor.mission_id != gate.mission_id
            or predecessor.runtime_session_id != reference["predecessor_session_id"]
            or predecessor.plan_id != gate.plan_id or predecessor.plan_revision_id != gate.plan_revision_id
            or predecessor.task_id != gate.task_id or predecessor.root_attempt_id != gate.root_attempt_id
        ):
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "predecessor Attempt does not preserve Gate lineage")
        if reference["successor_root_attempt_id"] != attempt.root_attempt_id:
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "successor root Attempt mismatch")
        if source_seq != attempt.created_seq:
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "RESUME source_seq must anchor the successor Attempt")
    elif route == GOAL_REVISION_ROUTE:
        required = {"kind", "goal_id", "revision", "definition_digest"}
        if set(reference) != required or reference["kind"] != "R2_2_GOAL_REVISION":
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "Goal continuation reference is incomplete")
        core, _, _, _ = _core_and_extensions(composed)
        goal = core.goal(reference["goal_id"])
        if goal is None or goal.mission_id != gate.mission_id or goal.revision != reference["revision"] or canonical_sha256(goal.definition) != reference["definition_digest"]:
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "Goal revision proof does not match canonical state")
    elif route == PLAN_REVISION:
        required = {"kind", "plan_id", "revision_id", "content_hash"}
        if set(reference) != required or reference["kind"] != "R2_3_R1_2_PLAN_REVISION":
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "Plan continuation reference is incomplete")
        _, work_graph, _, _ = _core_and_extensions(composed)
        revision = work_graph.revision(reference["revision_id"])
        if revision is None or revision.plan_id != gate.plan_id or revision.plan_id != reference["plan_id"] or revision.content_hash != reference["content_hash"]:
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "Plan revision proof does not match canonical state")
    else:
        raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "Route does not require continuation source")
    if _digest(payload["source_digest"], "source_digest") != _source_digest(composed, reference, source_seq):
        raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "continuation source digest mismatch")


def _handle_open(command: CommandEnvelope, composed: ComposedRuntimeState, gates: HumanGateState) -> list[PendingEvent]:
    payload = _expect(
        command.payload,
        {
            "gate_id", "mission_id", "plan_id", "plan_revision_id", "task_id", "root_attempt_id",
            "origin_attempt_id", "origin_session_id", "gate_kind", "request_payload_mode", "request_payload",
            "request_digest", "response_schema", "expires_at", "expiry_policy", "decision_policy_id",
            "decision_policy_version", "decision_policy_digest", "allowed_outcomes", "allowed_routes_by_outcome",
            "request_provenance",
        },
    )
    _text(payload["gate_id"], "gate_id")
    if payload["gate_id"] != command.payload["gate_id"] or payload["mission_id"] != command.mission_id:
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "Gate command Mission identity mismatch")
    if payload["gate_kind"] not in GATE_KINDS:
        raise R26Error("R2_6_SCHEMA_INVALID", "unsupported Gate kind")
    validate_payload(payload["request_payload_mode"], payload["request_payload"], payload["request_digest"], "request")
    _timestamp(payload["expires_at"], "expires_at")
    _validate_expiry(_text(payload["expiry_policy"], "expiry_policy"), payload["expires_at"])
    _provenance(payload["request_provenance"], "request_provenance")
    allowed_outcomes, routes = _validate_policy(payload)
    _validate_open_binding(composed, payload, gates)
    if gates.gate(payload["gate_id"]) is not None:
        raise R26Error("R2_6_ACTIVE_GATE_CONFLICT", "Gate identity is already used")
    event_payload = dict(payload)
    event_payload["request_provenance"] = _provenance(payload["request_provenance"], "request_provenance")
    event_payload.update({"status": PENDING, "gate_revision": 1, "continuation_revision": 0, "continuation_state": NOT_REQUIRED})
    return [PendingEvent(HUMAN_GATE_OPENED, "HUMAN_GATE", payload["gate_id"], event_payload, session_id=command.session_id)]


def _handle_decision(command: CommandEnvelope, composed: ComposedRuntimeState, gates: HumanGateState) -> list[PendingEvent]:
    payload = _expect(
        command.payload,
        {
            "gate_id", "expected_gate_revision", "expected_continuation_revision", "decision_id", "outcome", "route",
            "decision_payload_mode", "decision_payload", "decision_digest", "decision_provenance",
        },
    )
    gate = _gate(gates, payload["gate_id"])
    _assert_current_cycle(gates, gate)
    _require_pending(gate)
    _cas_gate(payload, gate)
    _cas_continuation(payload, gate)
    outcome = _text(payload["outcome"], "outcome")
    route = _text(payload["route"], "route")
    if outcome not in OUTCOMES or route not in ROUTES or outcome not in gate.allowed_outcomes or route not in gate.allowed_routes_by_outcome[outcome]:
        raise R26Error("R2_6_DECISION_POLICY_VIOLATION", "Outcome and Route violate the immutable decision policy")
    validate_payload(payload["decision_payload_mode"], payload["decision_payload"], payload["decision_digest"], "decision")
    provenance = _provenance(payload["decision_provenance"], "decision_provenance")
    continuation_state = CONTINUATION_PENDING if route in {RESUME_EXECUTION, GOAL_REVISION, PLAN_REVISION} else NOT_REQUIRED
    continuation_revision = gate.continuation_revision + (1 if continuation_state == CONTINUATION_PENDING else 0)
    event_payload = dict(payload)
    event_payload.update({
        "gate_revision": gate.gate_revision + 1,
        "continuation_revision": continuation_revision,
        "continuation_state": continuation_state,
        "decision_provenance": provenance,
    })
    return [PendingEvent(HUMAN_GATE_DECISION_RECORDED, "HUMAN_GATE", gate.gate_id, event_payload, session_id=command.session_id)]


def _handle_escalate(command: CommandEnvelope, composed: ComposedRuntimeState, gates: HumanGateState) -> list[PendingEvent]:
    payload = _expect(command.payload, {"gate_id", "expected_gate_revision", "escalation_id", "reason", "target_reference", "escalation_provenance"})
    gate = _gate(gates, payload["gate_id"])
    _assert_current_cycle(gates, gate)
    _require_pending(gate)
    _cas_gate(payload, gate)
    event_payload = dict(payload)
    event_payload.update({"gate_revision": gate.gate_revision + 1, "escalation_provenance": _provenance(payload["escalation_provenance"], "escalation_provenance")})
    return [PendingEvent(HUMAN_GATE_ESCALATED, "HUMAN_GATE", gate.gate_id, event_payload, session_id=command.session_id)]


def _handle_cancel(command: CommandEnvelope, composed: ComposedRuntimeState, gates: HumanGateState) -> list[PendingEvent]:
    payload = _expect(command.payload, {"gate_id", "expected_gate_revision", "reason", "cancellation_provenance"})
    gate = _gate(gates, payload["gate_id"])
    _assert_current_cycle(gates, gate)
    _require_pending(gate)
    _cas_gate(payload, gate)
    event_payload = dict(payload)
    event_payload.update({"gate_revision": gate.gate_revision + 1, "cancellation_provenance": _provenance(payload["cancellation_provenance"], "cancellation_provenance")})
    return [PendingEvent(HUMAN_GATE_CANCELLED, "HUMAN_GATE", gate.gate_id, event_payload, session_id=command.session_id)]


def _handle_expire(command: CommandEnvelope, composed: ComposedRuntimeState, gates: HumanGateState) -> list[PendingEvent]:
    payload = _expect(command.payload, {"gate_id", "expected_gate_revision", "observed_at", "expiry_provenance"})
    gate = _gate(gates, payload["gate_id"])
    _assert_current_cycle(gates, gate)
    _require_pending(gate)
    _cas_gate(payload, gate)
    observed_at = _timestamp(payload["observed_at"], "observed_at")
    if observed_at is None:
        raise R26Error("R2_6_SCHEMA_INVALID", "observed_at is required")
    if gate.expires_at is None or gate.expiry_policy == "NONE" or datetime.fromisoformat(observed_at.replace("Z", "+00:00")) < datetime.fromisoformat(gate.expires_at.replace("Z", "+00:00")):
        raise R26Error("R2_6_EXPIRY_NOT_REACHED", "Gate expiry has not been reached")
    expiry_provenance = _provenance(payload["expiry_provenance"], "expiry_provenance")
    if expiry_provenance["observed_at"] != observed_at:
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "expiry provenance does not bind the observed_at value")
    event_payload = dict(payload)
    event_payload.update({"gate_revision": gate.gate_revision + 1, "expiry_provenance": expiry_provenance})
    return [PendingEvent(HUMAN_GATE_EXPIRED, "HUMAN_GATE", gate.gate_id, event_payload, session_id=command.session_id)]


def _handle_continuation(command: CommandEnvelope, composed: ComposedRuntimeState, gates: HumanGateState) -> list[PendingEvent]:
    payload = _expect(command.payload, {"gate_id", "expected_gate_revision", "expected_continuation_revision", "route", "canonical_reference", "source_seq", "source_digest", "continuation_provenance"})
    gate = _gate(gates, payload["gate_id"])
    _assert_current_cycle(gates, gate)
    if gate.status != RESOLVED:
        raise R26Error("R2_6_GATE_NOT_PENDING", "Continuation requires a resolved Gate")
    _cas_gate(payload, gate)
    _cas_continuation(payload, gate)
    if gate.continuation_state != CONTINUATION_PENDING or payload["route"] != gate.continuation_route:
        raise R26Error("R2_6_CONTINUATION_REVISION_CONFLICT", "Continuation is not pending for the requested Route")
    _validate_continuation_source(composed, gate, payload)
    event_payload = dict(payload)
    event_payload.update({
        "gate_revision": gate.gate_revision + 1,
        "continuation_revision": gate.continuation_revision + 1,
        "continuation_state": APPLIED,
        "continuation_provenance": _provenance(payload["continuation_provenance"], "continuation_provenance"),
    })
    return [PendingEvent(HUMAN_GATE_CONTINUATION_RECORDED, "HUMAN_GATE", gate.gate_id, event_payload, session_id=command.session_id)]


def handle(command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
    if command.type == OPEN_HUMAN_GATE:
        return _handle_open(command, composed, composed.extension_state("r2_6_human_gate"))
    _, _, _, gates = _core_and_extensions(composed)
    if command.type == RECORD_HUMAN_DECISION:
        return _handle_decision(command, composed, gates)
    if command.type == ESCALATE_HUMAN_GATE:
        return _handle_escalate(command, composed, gates)
    if command.type == CANCEL_HUMAN_GATE:
        return _handle_cancel(command, composed, gates)
    if command.type == EXPIRE_HUMAN_GATE:
        return _handle_expire(command, composed, gates)
    if command.type == RECORD_CONTINUATION:
        return _handle_continuation(command, composed, gates)
    raise R26Error("R2_6_UNSUPPORTED_COMMAND", f"unsupported R2.6 command: {command.type}")


class R26CommandContribution:
    def handle(self, command: CommandEnvelope, composed: ComposedRuntimeState) -> list[PendingEvent]:
        return handle(command, composed)
