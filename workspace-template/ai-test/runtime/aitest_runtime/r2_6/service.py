from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aitest_runtime.durable_core import ActorRef, CommandEnvelope, CommandResult, RuntimeError, RuntimeService, canonical_sha256
from aitest_runtime.durable_core.schema import connect

from .contracts import (
    CANCEL_HUMAN_GATE,
    CONTINUATION_PENDING,
    EXPIRE_HUMAN_GATE,
    ESCALATE_HUMAN_GATE,
    EXTENSION_ID,
    GOAL_REVISION,
    HUMAN_GATE_CONTINUATION_RECORDED,
    INLINE_NON_SECRET,
    NONE,
    OPEN_HUMAN_GATE,
    PLAN_REVISION,
    RECORD_CONTINUATION,
    RECORD_HUMAN_DECISION,
    RESUME_EXECUTION,
    R26Error,
    HumanGateRecord,
    HumanGateState,
    _digest,
    _mapping,
    _provenance,
    _text,
)

# Imported separately to keep the command service's canonical proof logic
# identical to the extension handler's replay validation.
from .handlers import _source_digest


WORK_GRAPH_EXTENSION_ID = "r1_2_work_graph"
EXECUTION_RESUME_EXTENSION_ID = "r1_3b_execution_resume"


@dataclass(frozen=True)
class R26OperationResult:
    command_result: CommandResult
    gate: HumanGateRecord | None

    @property
    def outcome(self) -> str:
        return self.command_result.outcome


def _actor(value: Any, default_id: str = "r2.6") -> ActorRef:
    if isinstance(value, ActorRef):
        return value
    raw = _mapping(value or {"type": "SYSTEM", "id": default_id}, "actor")
    return ActorRef(_text(raw.get("type"), "actor.type"), _text(raw.get("id"), "actor.id"))


def _mapping_request(value: Any, kwargs: Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, Mapping) else {}
    raw.update(kwargs)
    return raw


def _digest_or_compute(value: Any) -> str:
    return _digest(value, "payload_digest") if value is not None else canonical_sha256({})


class HumanGateApplicationService:
    """R2.6 application boundary over one shared RuntimeService."""

    def __init__(self, runtime_service: RuntimeService) -> None:
        if runtime_service is None:
            raise ValueError("runtime_service is required")
        runtime_service.extension_registry.manifest(EXTENSION_ID)
        runtime_service.extension_registry.manifest(WORK_GRAPH_EXTENSION_ID)
        runtime_service.extension_registry.manifest(EXECUTION_RESUME_EXTENSION_ID)
        self._runtime = runtime_service

    @property
    def runtime_service(self) -> RuntimeService:
        return self._runtime

    def state(self, mission_id: str) -> HumanGateState:
        state = self._runtime.replay_composed(_text(mission_id, "mission_id")).extension_state(EXTENSION_ID)
        if not isinstance(state, HumanGateState):
            raise R26Error("EXTENSION_SCHEMA_MISMATCH", "invalid R2.6 extension state")
        return state

    get_state = state

    def _command_row(self, command_id: str) -> sqlite3.Row | None:
        conn = connect(self._runtime.db_path)
        try:
            return conn.execute("SELECT * FROM commands WHERE command_id=?", (command_id,)).fetchone()
        finally:
            conn.close()

    @staticmethod
    def _row_envelope(row: sqlite3.Row) -> CommandEnvelope:
        return CommandEnvelope(
            command_id=row["command_id"], type=row["command_type"], mission_id=row["mission_id"],
            session_id=row["session_id"], expected_seq=int(row["expected_seq"]),
            actor=ActorRef(row["actor_type"], row["actor_id"]), payload=json.loads(row["payload_json"]),
            idempotency_key=row["idempotency_key"], correlation_id=row["correlation_id"], schema_version=int(row["schema_version"]),
        )

    def _verify_persisted_step(self, result: CommandResult, command_id: str) -> None:
        if result.first_seq is None or result.last_seq is None:
            raise R26Error("R2_6_RECONCILIATION_REQUIRED", "successful R2.6 command has no Event range")
        events = self._runtime.list_events(result.mission_id, after_seq=result.first_seq - 1, through_seq=result.last_seq)
        if not events or any(event.command_id != command_id for event in events):
            raise R26Error("R2_6_RECONCILIATION_REQUIRED", "Command result cannot be reconciled with Event Stream")

    def _run_step(
        self,
        *,
        command_id: str,
        command_type: str,
        mission_id: str,
        cursor: int,
        actor: ActorRef,
        payload: Mapping[str, Any],
        session_id: str | None = None,
        correlation_id: str | None = None,
    ) -> CommandResult:
        row = self._command_row(command_id)
        if row is not None:
            # Completed command replay must use the original complete envelope,
            # including the original expected_seq and payload.
            original = self._row_envelope(row)
            result = self._runtime.execute(original)
            if result.ok:
                self._verify_persisted_step(result, command_id)
            return result
        head = self._runtime.get_head_seq(mission_id)
        if head != cursor:
            raise R26Error("EXPECTED_SEQ_MISMATCH", "R2.6 cursor does not match the shared Event Stream head")
        envelope = CommandEnvelope(
            command_id=command_id, type=command_type, mission_id=mission_id, session_id=session_id,
            expected_seq=cursor, actor=actor, payload=dict(payload), idempotency_key=command_id,
            correlation_id=correlation_id or command_id, schema_version=1,
        )
        result = self._runtime.execute(envelope)
        if result.ok:
            self._verify_persisted_step(result, command_id)
        return result

    def _result(self, result: CommandResult) -> R26OperationResult:
        if not result.ok:
            if result.error is not None:
                raise result.error
            raise R26Error("R2_6_COMMAND_REJECTED", "R2.6 command was rejected")
        return R26OperationResult(result, self.state(result.mission_id).gate(result.command_id.split(":")[1]))

    def _operation(self, result: CommandResult, gate_id: str) -> R26OperationResult:
        if not result.ok:
            if result.error is not None:
                raise result.error
            raise R26Error("R2_6_COMMAND_REJECTED", "R2.6 command was rejected")
        return R26OperationResult(result, self.state(result.mission_id).gate(gate_id))

    def open_gate(self, request: Any = None, **kwargs: Any) -> R26OperationResult:
        raw = _mapping_request(request, kwargs)
        mission_id = _text(raw.get("mission_id"), "mission_id")
        gate_id = _text(raw.get("gate_id"), "gate_id")
        command_id = f"r2.6:{gate_id}:OPEN"
        if raw.get("command_id") is not None and raw["command_id"] != command_id:
            raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "OPEN command identity is not deterministic")
        payload = {
            "gate_id": gate_id, "mission_id": mission_id, "plan_id": _text(raw.get("plan_id"), "plan_id"),
            "plan_revision_id": _text(raw.get("plan_revision_id"), "plan_revision_id"), "task_id": _text(raw.get("task_id"), "task_id"),
            "root_attempt_id": _text(raw.get("root_attempt_id"), "root_attempt_id"), "origin_attempt_id": _text(raw.get("origin_attempt_id"), "origin_attempt_id"),
            "origin_session_id": _text(raw.get("origin_session_id"), "origin_session_id"), "gate_kind": _text(raw.get("gate_kind"), "gate_kind"),
            "request_payload_mode": raw.get("request_payload_mode", INLINE_NON_SECRET), "request_payload": raw.get("request_payload", {}),
            "request_digest": raw.get("request_digest") or canonical_sha256(raw.get("request_payload", {})),
            "response_schema": dict(raw.get("response_schema") or {}), "expires_at": raw.get("expires_at"), "expiry_policy": raw.get("expiry_policy", "NONE"),
            "decision_policy_id": _text(raw.get("decision_policy_id"), "decision_policy_id"), "decision_policy_version": raw.get("decision_policy_version", 1),
            "decision_policy_digest": _text(raw.get("decision_policy_digest"), "decision_policy_digest"), "allowed_outcomes": list(raw.get("allowed_outcomes") or ()),
            "allowed_routes_by_outcome": dict(raw.get("allowed_routes_by_outcome") or {}),
            "request_provenance": dict(raw.get("request_provenance") or {"source_ref": "r2.6", "source_digest": canonical_sha256(raw), "observed_at": "1970-01-01T00:00:00Z"}),
        }
        actor = _actor(raw.get("actor"))
        result = self._run_step(command_id=command_id, command_type=OPEN_HUMAN_GATE, mission_id=mission_id, cursor=raw.get("expected_seq", self._runtime.get_head_seq(mission_id)), actor=actor, payload=payload, session_id=payload["origin_session_id"], correlation_id=raw.get("correlation_id"))
        return self._operation(result, gate_id)

    def record_decision(self, request: Any = None, **kwargs: Any) -> R26OperationResult:
        raw = _mapping_request(request, kwargs)
        mission_id = _text(raw.get("mission_id"), "mission_id")
        gate_id = _text(raw.get("gate_id"), "gate_id")
        decision_id = _text(raw.get("decision_id"), "decision_id")
        command_id = f"r2.6:{gate_id}:DECIDE:{decision_id}"
        gate = self.state(mission_id).gate(gate_id)
        if gate is None:
            raise R26Error("R2_6_GATE_NOT_FOUND", f"Human Gate not found: {gate_id}")
        decision_payload = raw.get("decision_payload", {})
        payload = {
            "gate_id": gate_id, "expected_gate_revision": raw.get("expected_gate_revision", gate.gate_revision),
            "expected_continuation_revision": raw.get("expected_continuation_revision", gate.continuation_revision), "decision_id": decision_id,
            "outcome": _text(raw.get("outcome"), "outcome"), "route": _text(raw.get("route"), "route"),
            "decision_payload_mode": raw.get("decision_payload_mode", INLINE_NON_SECRET), "decision_payload": decision_payload,
            "decision_digest": raw.get("decision_digest") or canonical_sha256(decision_payload),
            "decision_provenance": dict(raw.get("decision_provenance") or {"source_ref": "r2.6", "source_digest": canonical_sha256(raw), "observed_at": "1970-01-01T00:00:00Z"}),
        }
        result = self._run_step(command_id=command_id, command_type=RECORD_HUMAN_DECISION, mission_id=mission_id, cursor=raw.get("expected_seq", self._runtime.get_head_seq(mission_id)), actor=_actor(raw.get("actor")), payload=payload, session_id=raw.get("session_id"), correlation_id=raw.get("correlation_id"))
        return self._operation(result, gate_id)

    def escalate(self, request: Any = None, **kwargs: Any) -> R26OperationResult:
        raw = _mapping_request(request, kwargs)
        mission_id, gate_id = _text(raw.get("mission_id"), "mission_id"), _text(raw.get("gate_id"), "gate_id")
        escalation_id = _text(raw.get("escalation_id"), "escalation_id")
        gate = self.state(mission_id).gate(gate_id)
        if gate is None:
            raise R26Error("R2_6_GATE_NOT_FOUND", f"Human Gate not found: {gate_id}")
        payload = {"gate_id": gate_id, "expected_gate_revision": raw.get("expected_gate_revision", gate.gate_revision), "escalation_id": escalation_id, "reason": _text(raw.get("reason"), "reason"), "target_reference": dict(raw.get("target_reference") or {}), "escalation_provenance": _provenance(raw.get("escalation_provenance") or {"source_ref": "r2.6", "source_digest": canonical_sha256(raw), "observed_at": "1970-01-01T00:00:00Z"}, "escalation_provenance")}
        result = self._run_step(command_id=f"r2.6:{gate_id}:ESCALATE:{escalation_id}", command_type=ESCALATE_HUMAN_GATE, mission_id=mission_id, cursor=raw.get("expected_seq", self._runtime.get_head_seq(mission_id)), actor=_actor(raw.get("actor")), payload=payload, session_id=raw.get("session_id"), correlation_id=raw.get("correlation_id"))
        return self._operation(result, gate_id)

    def cancel(self, request: Any = None, **kwargs: Any) -> R26OperationResult:
        raw = _mapping_request(request, kwargs)
        mission_id, gate_id = _text(raw.get("mission_id"), "mission_id"), _text(raw.get("gate_id"), "gate_id")
        gate = self.state(mission_id).gate(gate_id)
        if gate is None:
            raise R26Error("R2_6_GATE_NOT_FOUND", f"Human Gate not found: {gate_id}")
        operation_id = _text(raw.get("operation_id") or "cancel", "operation_id")
        payload = {"gate_id": gate_id, "expected_gate_revision": raw.get("expected_gate_revision", gate.gate_revision), "reason": _text(raw.get("reason"), "reason"), "cancellation_provenance": _provenance(raw.get("cancellation_provenance") or {"source_ref": "r2.6", "source_digest": canonical_sha256(raw), "observed_at": "1970-01-01T00:00:00Z"}, "cancellation_provenance")}
        result = self._run_step(command_id=f"r2.6:{gate_id}:CANCEL:{operation_id}", command_type=CANCEL_HUMAN_GATE, mission_id=mission_id, cursor=raw.get("expected_seq", self._runtime.get_head_seq(mission_id)), actor=_actor(raw.get("actor")), payload=payload, session_id=raw.get("session_id"), correlation_id=raw.get("correlation_id"))
        return self._operation(result, gate_id)

    def expire(self, request: Any = None, **kwargs: Any) -> R26OperationResult:
        raw = _mapping_request(request, kwargs)
        mission_id, gate_id = _text(raw.get("mission_id"), "mission_id"), _text(raw.get("gate_id"), "gate_id")
        gate = self.state(mission_id).gate(gate_id)
        if gate is None:
            raise R26Error("R2_6_GATE_NOT_FOUND", f"Human Gate not found: {gate_id}")
        operation_id = _text(raw.get("operation_id") or "expire", "operation_id")
        observed_at = _text(raw.get("observed_at"), "observed_at")
        payload = {"gate_id": gate_id, "expected_gate_revision": raw.get("expected_gate_revision", gate.gate_revision), "observed_at": observed_at, "expiry_provenance": _provenance(raw.get("expiry_provenance") or {"source_ref": "r2.6", "source_digest": canonical_sha256(raw), "observed_at": observed_at}, "expiry_provenance")}
        result = self._run_step(command_id=f"r2.6:{gate_id}:EXPIRE:{operation_id}", command_type=EXPIRE_HUMAN_GATE, mission_id=mission_id, cursor=raw.get("expected_seq", self._runtime.get_head_seq(mission_id)), actor=_actor(raw.get("actor")), payload=payload, session_id=raw.get("session_id"), correlation_id=raw.get("correlation_id"))
        return self._operation(result, gate_id)

    def _prepare_source(self, mission_id: str, route: str, reference: Mapping[str, Any]) -> tuple[dict[str, Any], int, str]:
        composed = self._runtime.replay_composed(mission_id)
        events = self._runtime.list_events(mission_id)
        reference = dict(reference)
        if route == RESUME_EXECUTION:
            attempt_id = _text(reference.get("successor_attempt_id"), "successor_attempt_id")
            session_id = _text(reference.get("successor_session_id"), "successor_session_id")
            predecessor_id = _text(reference.get("predecessor_attempt_id"), "predecessor_attempt_id")
            attempt_event = next((event for event in events if event.entity_id == attempt_id and event.event_type == "execution.attempt_resumed.v1"), None)
            session_event = next((event for event in events if event.entity_id == session_id and event.event_type == "session.opened"), None)
            predecessor_event = next((event for event in events if event.entity_id == predecessor_id and event.event_type in {"execution.attempt_started.v1", "execution.attempt_resumed.v1"}), None)
            if attempt_event is None or session_event is None or predecessor_event is None:
                raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "canonical RESUME source events are missing")
            attrs = dict(session_event.payload.get("attributes") or {})
            reference.setdefault("predecessor_session_id", attrs.get("predecessor_session_id"))
            reference.setdefault("rotation_operation_id", attrs.get("rotation_operation_id"))
            reference.update({"kind": "R1_3B_R2_5_SUCCESSOR", "successor_session_id": session_id, "successor_attempt_id": attempt_id, "successor_root_attempt_id": reference.get("successor_root_attempt_id"), "predecessor_attempt_id": predecessor_id, "predecessor_session_id": reference.get("predecessor_session_id"), "rotation_operation_id": reference.get("rotation_operation_id")})
            source_seq = attempt_event.seq
        elif route == GOAL_REVISION:
            goal_id = _text(reference.get("goal_id"), "goal_id")
            goal_event = next((event for event in events if event.entity_id == goal_id and event.event_type == "goal.revised" and event.payload.get("revision") == reference.get("revision")), None)
            if goal_event is None:
                raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "canonical Goal revision event is missing")
            goal = composed.core_state.goal(goal_id)
            reference.update({"kind": "R2_2_GOAL_REVISION", "goal_id": goal_id, "revision": goal.revision if goal else reference.get("revision"), "definition_digest": canonical_sha256(goal.definition) if goal else reference.get("definition_digest")})
            source_seq = goal_event.seq
        elif route == PLAN_REVISION:
            revision_id = _text(reference.get("revision_id"), "revision_id")
            revision_event = next((event for event in events if event.entity_id == revision_id and event.event_type == "plan.revision_recorded.v1"), None)
            if revision_event is None:
                raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "canonical Plan revision event is missing")
            work_graph = composed.extension_state(WORK_GRAPH_EXTENSION_ID)
            revision = work_graph.revision(revision_id)
            if revision is None:
                raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "canonical Plan revision state is missing")
            reference.update({"kind": "R2_3_R1_2_PLAN_REVISION", "plan_id": revision.plan_id, "revision_id": revision_id, "content_hash": revision.content_hash})
            source_seq = revision_event.seq
        else:
            raise R26Error("R2_6_CONTINUATION_SOURCE_CONFLICT", "Route does not accept a continuation source")
        digest = _source_digest(composed, reference, source_seq)
        return reference, source_seq, digest

    def record_continuation(self, request: Any = None, **kwargs: Any) -> R26OperationResult:
        raw = _mapping_request(request, kwargs)
        mission_id, gate_id = _text(raw.get("mission_id"), "mission_id"), _text(raw.get("gate_id"), "gate_id")
        gate = self.state(mission_id).gate(gate_id)
        if gate is None:
            raise R26Error("R2_6_GATE_NOT_FOUND", f"Human Gate not found: {gate_id}")
        route = _text(raw.get("route") or gate.continuation_route, "route")
        reference, source_seq, source_digest = self._prepare_source(mission_id, route, raw.get("canonical_reference") or {})
        operation_id = _text(raw.get("continuation_operation_id") or gate_id, "continuation_operation_id")
        payload = {"gate_id": gate_id, "expected_gate_revision": raw.get("expected_gate_revision", gate.gate_revision), "expected_continuation_revision": raw.get("expected_continuation_revision", gate.continuation_revision), "route": route, "canonical_reference": reference, "source_seq": source_seq, "source_digest": source_digest, "continuation_provenance": _provenance(raw.get("continuation_provenance") or {"source_ref": "r2.6", "source_digest": source_digest, "observed_at": "1970-01-01T00:00:00Z"}, "continuation_provenance")}
        result = self._run_step(command_id=f"r2.6:{gate_id}:CONTINUE:{operation_id}", command_type=RECORD_CONTINUATION, mission_id=mission_id, cursor=raw.get("expected_seq", self._runtime.get_head_seq(mission_id)), actor=_actor(raw.get("actor")), payload=payload, session_id=raw.get("session_id"), correlation_id=raw.get("correlation_id"))
        return self._operation(result, gate_id)


R26ApplicationService = HumanGateApplicationService
HumanGateService = HumanGateApplicationService
