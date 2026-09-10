from __future__ import annotations

import json
from dataclasses import replace
from aitest_runtime.durable_core import ExtensionManifest, MigrationStep, PendingEvent, RuntimeError, canonical_json, canonical_sha256
from .contracts import EXTENSION_ID, EXTENSION_VERSION, ROOTS, JobState, validate_create, validate_transition


class StateContribution:
    def initial_state(self, stream_id): return JobState(stream_id)
    def encode(self, state): return state.to_dict()
    def decode(self, value): return JobState.from_dict(value)
    def hash(self, state): return canonical_sha256(state.to_dict())
    def root_exists(self, state, subject):
        return isinstance(state, JobState) and state.job_id == subject.subject_id and state.subject_kind == subject.subject_kind and state.status is not None


class CommandContribution:
    def handle(self, command, composed):
        payload = dict(command.payload)
        root = next((r for r in ROOTS if command.type in r.command_types), None)
        if root is None:
            raise RuntimeError("JOB_COMMAND_UNSUPPORTED", "unknown job command")
        state = composed.extension_state(EXTENSION_ID)
        if command.type == root.creation_command:
            validate_create(payload)
            identity = "r1:job:create:" + canonical_sha256(payload["operation_id"])
            if command.command_id != identity or command.idempotency_key != identity:
                raise RuntimeError("JOB_IDEMPOTENCY_REQUIRED", "creation must consume the runtime-derived operation identity")
            event_type = root.creation_event
        else:
            if payload.get("from_status") != state.status:
                raise RuntimeError("JOB_TRANSITION_FORBIDDEN", "lifecycle cursor is stale")
            validate_transition(payload, state)
            event_type = next(e for e in root.event_types if e != root.creation_event)
        return [PendingEvent(event_type, root.entity_type, command.mission_id, payload)]


class ReducerContribution:
    def reduce(self, state, event, core_state):
        payload = dict(event.payload)
        if any(event.event_type == r.creation_event for r in ROOTS):
            if state.status is not None:
                raise RuntimeError("ROOT_ALREADY_EXISTS", "job already created")
            validate_create(payload)
            return JobState(event.mission_id, payload["subject"]["subject_kind"], "CREATED", payload["operation_id"], payload["intent"], payload["host_turn_ref"], created_at=event.created_at, updated_at=event.created_at)
        validate_transition(payload, state)
        return replace(state, status=payload["target_status"], summary=payload["summary"], evidence_ref=payload["evidence_ref"], updated_at=event.created_at)


SQL = """CREATE TABLE general_work_projection (
 job_id TEXT PRIMARY KEY, subject_kind TEXT NOT NULL, state_json TEXT NOT NULL,
 state_hash TEXT NOT NULL, projection_seq INTEGER NOT NULL
)"""


def migrate(conn): conn.execute(SQL)


class MigrationContribution:
    extension_id = EXTENSION_ID
    migrations = (MigrationStep(1, canonical_sha256(SQL), migrate),)


class ProjectionContribution:
    projection_tables = frozenset({"general_work_projection"})
    def clear(self, conn, stream_id=None):
        if stream_id is None: conn.execute("DELETE FROM general_work_projection")
        else: conn.execute("DELETE FROM general_work_projection WHERE job_id=?", (stream_id,))
    def apply(self, conn, composed):
        state = composed.extension_state(EXTENSION_ID)
        self.clear(conn, state.job_id)
        conn.execute("INSERT INTO general_work_projection VALUES(?,?,?,?,?)", (state.job_id, state.subject_kind, canonical_json(state.to_dict()), canonical_sha256(state.to_dict()), composed.seq))
    def read(self, conn, stream_id):
        row = conn.execute("SELECT state_json FROM general_work_projection WHERE job_id=?", (stream_id,)).fetchone()
        return JobState.from_dict(json.loads(row[0])) if row else JobState(stream_id)
    def projection_seq(self, conn, stream_id):
        row = conn.execute("SELECT projection_seq FROM general_work_projection WHERE job_id=?", (stream_id,)).fetchone()
        return int(row[0]) if row else None
    def verify(self, replayed, projected):
        a = canonical_sha256(replayed.to_dict()); b = canonical_sha256(projected.to_dict()) if projected else None
        return {"ok": a == b, "replay_hash": a, "projection_hash": b}


def general_work_extension():
    return ExtensionManifest(EXTENSION_ID, EXTENSION_VERSION,
                             frozenset(c for r in ROOTS for c in r.command_types),
                             frozenset(e for r in ROOTS for e in r.event_types),
                             StateContribution(), CommandContribution(), ReducerContribution(),
                             ProjectionContribution(), MigrationContribution(),
                             subject_kinds=frozenset(r.subject_kind for r in ROOTS), roots=ROOTS)
