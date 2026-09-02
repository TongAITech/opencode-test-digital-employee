from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from .canonical import Clock, SystemClock, canonical_json, canonical_sha256, command_fingerprint
from .contracts import (
    ActorRef,
    CommandEnvelope,
    CommandResult,
    ComposedRuntimeState,
    EventEnvelope,
    ExtensionRegistry,
    RuntimeError,
)
from .event_store import _insert_events, get_head_seq, list_events
from .handlers import handle
from .projections import _apply_composed_projection, _apply_projection, replay_composed_state
from .reducer import initial_state, reduce, reduce_composed
from .schema import connect, immediate_transaction


FailureInjector = Callable[[str], None]


def normalize_command(value: CommandEnvelope | Mapping[str, Any]) -> CommandEnvelope:
    if isinstance(value, CommandEnvelope):
        raw = value.to_dict()
    elif isinstance(value, Mapping):
        raw = dict(value)
    else:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "command must be an object")
    try:
        command_id = raw["command_id"]
        command_type = raw["type"]
        mission_id = raw["mission_id"]
        expected_seq = raw["expected_seq"]
        actor_raw = raw["actor"]
    except KeyError as exc:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", f"missing command field: {exc.args[0]}") from exc
    for name, item in (("command_id", command_id), ("type", command_type), ("mission_id", mission_id)):
        if not isinstance(item, str) or not item.strip():
            raise RuntimeError("COMMAND_SCHEMA_INVALID", f"{name} must be a non-empty string")
    if not isinstance(expected_seq, int) or isinstance(expected_seq, bool) or expected_seq < 0:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "expected_seq must be a non-negative integer")
    if not isinstance(actor_raw, Mapping):
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "actor must be an object")
    try:
        actor_type = actor_raw["type"]
        actor_id = actor_raw["id"]
        if not isinstance(actor_type, str) or not isinstance(actor_id, str):
            raise ValueError("actor.type and actor.id must be strings")
        actor = ActorRef(actor_type, actor_id)
    except (KeyError, ValueError) as exc:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", str(exc)) from exc
    payload = raw.get("payload", {})
    if not isinstance(payload, Mapping):
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "payload must be an object")
    try:
        canonical_json(payload)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "payload must contain canonical JSON values") from exc
    schema_version = raw.get("schema_version", 1)
    if schema_version != 1:
        raise RuntimeError("COMMAND_SCHEMA_INVALID", f"unsupported command schema: {schema_version}")
    session_id = raw.get("session_id")
    if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "session_id must be null or a non-empty string")
    idempotency_key = raw.get("idempotency_key")
    if idempotency_key is not None and (not isinstance(idempotency_key, str) or not idempotency_key.strip()):
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "idempotency_key must be null or a non-empty string")
    correlation_id = raw.get("correlation_id") or command_id
    if not isinstance(correlation_id, str) or not correlation_id.strip():
        raise RuntimeError("COMMAND_SCHEMA_INVALID", "correlation_id must be a non-empty string")
    return CommandEnvelope(
        command_id=command_id,
        type=command_type,
        mission_id=mission_id,
        session_id=session_id,
        expected_seq=expected_seq,
        actor=actor,
        payload=dict(payload),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        schema_version=1,
    )


class CommandBus:
    def __init__(
        self,
        db_path: str | Path,
        clock: Clock | None = None,
        failure_injector: FailureInjector | None = None,
        extension_registry: ExtensionRegistry | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._clock = clock or SystemClock()
        self._failure_injector = failure_injector
        self._extension_registry = extension_registry or ExtensionRegistry()

    def _inject(self, point: str) -> None:
        if self._failure_injector is not None:
            self._failure_injector(point)

    def _state(self, conn: sqlite3.Connection, mission_id: str):
        if self._extension_registry.enabled:
            return replay_composed_state(conn, mission_id, self._extension_registry)
        state = initial_state(mission_id)
        for event in list_events(conn, mission_id):
            state = reduce(state, event)
        return state

    def _conflict_result(self, command: CommandEnvelope, code: str, message: str) -> CommandResult:
        return CommandResult("REJECTED", command.command_id, command.mission_id, error=RuntimeError(code, message))

    def _insert_command(
        self,
        conn: sqlite3.Connection,
        command: CommandEnvelope,
        fingerprint: str,
        result: CommandResult,
        received_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO commands(
                command_id,mission_id,session_id,command_type,expected_seq,actor_type,actor_id,
                idempotency_key,correlation_id,command_fingerprint,payload_json,schema_version,
                status,first_seq,last_seq,result_json,error_code,error_message,received_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                command.command_id,
                command.mission_id,
                command.session_id,
                command.type,
                command.expected_seq,
                command.actor.type,
                command.actor.id,
                command.idempotency_key,
                command.correlation_id,
                fingerprint,
                canonical_json(command.payload),
                command.schema_version,
                "APPLIED" if result.outcome == "APPLIED" else "REJECTED",
                result.first_seq,
                result.last_seq,
                canonical_json(result.to_dict()),
                result.error_code,
                result.error.message if result.error else None,
                received_at,
            ),
        )

    def execute(self, raw_command: CommandEnvelope | Mapping[str, Any]) -> CommandResult:
        try:
            command = normalize_command(raw_command)
        except RuntimeError as exc:
            raw = dict(raw_command) if isinstance(raw_command, Mapping) else {}
            return CommandResult(
                "REJECTED",
                str(raw.get("command_id") or ""),
                str(raw.get("mission_id") or ""),
                error=exc,
            )
        fingerprint = command_fingerprint(command)
        received_at = self._clock.now()
        conn: sqlite3.Connection | None = None
        try:
            conn = connect(self._db_path)
            with immediate_transaction(conn):
                existing = conn.execute("SELECT * FROM commands WHERE command_id=?", (command.command_id,)).fetchone()
                if existing is not None:
                    if existing["command_fingerprint"] == fingerprint:
                        return CommandResult.from_dict(json.loads(existing["result_json"]))
                    return self._conflict_result(
                        command,
                        "COMMAND_ID_CONFLICT",
                        f"command_id already used with different intent: {command.command_id}",
                    )
                if command.idempotency_key is not None:
                    owner = conn.execute(
                        "SELECT * FROM commands WHERE idempotency_key=? AND status='APPLIED'",
                        (command.idempotency_key,),
                    ).fetchone()
                    if owner is not None:
                        if owner["command_fingerprint"] == fingerprint:
                            original = CommandResult.from_dict(json.loads(owner["result_json"]))
                            return CommandResult(
                                "DUPLICATE",
                                command.command_id,
                                command.mission_id,
                                original.first_seq,
                                original.last_seq,
                                duplicate_of=owner["command_id"],
                                state_hash=original.state_hash,
                            )
                        return self._conflict_result(
                            command,
                            "IDEMPOTENCY_CONFLICT",
                            f"idempotency_key already owns different intent: {command.idempotency_key}",
                        )

                state = self._state(conn, command.mission_id)
                head = get_head_seq(conn, command.mission_id)
                try:
                    owner = self._extension_registry.command_owner(command.type)
                    if owner is None:
                        raise RuntimeError("UNSUPPORTED_COMMAND_TYPE", f"unsupported command: {command.type}")
                    core_state = state.core_state if isinstance(state, ComposedRuntimeState) else state
                    if command.type == "CREATE_MISSION":
                        if command.expected_seq != 0:
                            raise RuntimeError("EXPECTED_SEQ_MISMATCH", "CREATE_MISSION expected_seq must be 0")
                    else:
                        if core_state.mission is None:
                            raise RuntimeError("MISSION_NOT_FOUND", f"Mission not found: {command.mission_id}")
                        if command.expected_seq != head:
                            raise RuntimeError(
                                "EXPECTED_SEQ_MISMATCH",
                                f"expected_seq {command.expected_seq} does not match stream head {head}",
                            )
                    if owner == "CORE":
                        pending = handle(command, core_state)
                    else:
                        if not isinstance(state, ComposedRuntimeState):
                            raise RuntimeError("EXTENSION_NOT_REGISTERED", f"Extension not registered: {owner.extension_id}")
                        pending = owner.command_contribution.handle(command, state)
                        for item in pending:
                            if item.event_type not in owner.event_types:
                                raise RuntimeError(
                                    "EXTENSION_EVENT_NOT_OWNED",
                                    f"Extension {owner.extension_id} does not own event: {item.event_type}",
                                )
                    if not pending:
                        raise RuntimeError("RUNTIME_INVARIANT_VIOLATION", "command handler produced no events")
                except RuntimeError as exc:
                    rejected = CommandResult("REJECTED", command.command_id, command.mission_id, error=exc)
                    self._insert_command(conn, command, fingerprint, rejected, received_at)
                    return rejected

                events: list[EventEnvelope] = []
                new_state = state
                for offset, item in enumerate(pending, 1):
                    event = EventEnvelope(
                        event_id=uuid.uuid4().hex,
                        mission_id=command.mission_id,
                        session_id=item.session_id,
                        seq=head + offset,
                        event_type=item.event_type,
                        entity_type=item.entity_type,
                        entity_id=item.entity_id,
                        command_id=command.command_id,
                        correlation_id=command.correlation_id or command.command_id,
                        initiator_type=command.actor.type,
                        initiator_id=command.actor.id,
                        payload=dict(item.payload),
                        created_at=self._clock.now(),
                        schema_version=1,
                    )
                    if isinstance(new_state, ComposedRuntimeState):
                        new_state = reduce_composed(new_state, event, self._extension_registry)
                    else:
                        new_state = reduce(new_state, event)
                    events.append(event)
                applied = CommandResult(
                    "APPLIED",
                    command.command_id,
                    command.mission_id,
                    first_seq=events[0].seq,
                    last_seq=events[-1].seq,
                    state_hash=canonical_sha256(new_state.to_dict()),
                )
                self._insert_command(conn, command, fingerprint, applied, received_at)
                self._inject("after_command_insert")
                _insert_events(conn, events)
                self._inject("after_event_insert")
                if isinstance(new_state, ComposedRuntimeState):
                    _apply_composed_projection(conn, new_state, self._extension_registry)
                else:
                    _apply_projection(conn, new_state)
                self._inject("after_projection_apply")
                self._inject("before_commit")
                return applied
        except sqlite3.OperationalError as exc:
            code = "STORAGE_BUSY" if "locked" in str(exc).lower() or "busy" in str(exc).lower() else "STORAGE_FAILURE"
            return self._conflict_result(command, code, str(exc))
        except sqlite3.DatabaseError as exc:
            return self._conflict_result(command, "STORAGE_FAILURE", str(exc))
        finally:
            if conn is not None:
                conn.close()
