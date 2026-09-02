from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

EXTENSION_ID = "g2_1_session_control"
EXTENSION_VERSION = "1"

ENABLE_ROUTING_AUTHORITY = "G21_ENABLE_ROUTING_AUTHORITY"
REGISTER_TASK_ROUTE = "G21_REGISTER_TASK_ROUTE"
REQUEST_SESSION_PROVISION = "G21_REQUEST_SESSION_PROVISION"
BIND_SESSION_PROVISION = "G21_BIND_SESSION_PROVISION"
CLOSE_ORPHAN_PROVISION = "G21_CLOSE_ORPHAN_PROVISION"
RECORD_SESSION_OBSERVATION = "G21_RECORD_SESSION_OBSERVATION"
REQUEST_SESSION_ROTATION = "G21_REQUEST_SESSION_ROTATION"
COMPLETE_SESSION_ROTATION = "G21_COMPLETE_SESSION_ROTATION"

ROUTING_AUTHORITY_ENABLED = "g2_1.routing_authority_enabled.v1"
TASK_ROUTE_REGISTERED = "g2_1.task_route_registered.v1"
SESSION_PROVISION_REQUESTED = "g2_1.session_provision_requested.v1"
SESSION_PROVISION_BOUND = "g2_1.session_provision_bound.v1"
ORPHAN_PROVISION_CLOSED = "g2_1.orphan_provision_closed.v1"
SESSION_OBSERVATION_RECORDED = "g2_1.session_observation_recorded.v1"
SESSION_ROTATION_REQUESTED = "g2_1.session_rotation_requested.v1"
SESSION_ROTATION_COMPLETED = "g2_1.session_rotation_completed.v1"

COMMAND_TYPES = frozenset({
    ENABLE_ROUTING_AUTHORITY, REGISTER_TASK_ROUTE, REQUEST_SESSION_PROVISION, BIND_SESSION_PROVISION,
    CLOSE_ORPHAN_PROVISION, RECORD_SESSION_OBSERVATION,
    REQUEST_SESSION_ROTATION, COMPLETE_SESSION_ROTATION,
})
EVENT_TYPES = frozenset({
    ROUTING_AUTHORITY_ENABLED, TASK_ROUTE_REGISTERED, SESSION_PROVISION_REQUESTED, SESSION_PROVISION_BOUND,
    ORPHAN_PROVISION_CLOSED, SESSION_OBSERVATION_RECORDED,
    SESSION_ROTATION_REQUESTED, SESSION_ROTATION_COMPLETED,
})


def _tuple_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("value must be an array")
    return tuple(str(item) for item in value)


@dataclass(frozen=True)
class TaskRouteRequirement:
    task_id: str
    role: str
    agent_name: str
    required_capabilities: tuple[str, ...]
    isolation_policy: str
    parallelism_policy: str
    source: str
    route_digest: str
    registered_seq: int
    registered_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id, "role": self.role, "agent_name": self.agent_name,
            "required_capabilities": list(self.required_capabilities),
            "isolation_policy": self.isolation_policy, "parallelism_policy": self.parallelism_policy,
            "source": self.source, "route_digest": self.route_digest,
            "registered_seq": self.registered_seq, "registered_at": self.registered_at,
        }

    @classmethod
    def from_dict(cls, v: Mapping[str, Any]) -> "TaskRouteRequirement":
        return cls(str(v["task_id"]), str(v["role"]), str(v["agent_name"]),
                   _tuple_str(v.get("required_capabilities")), str(v["isolation_policy"]),
                   str(v["parallelism_policy"]), str(v["source"]), str(v["route_digest"]),
                   int(v["registered_seq"]), str(v["registered_at"]))


@dataclass(frozen=True)
class ProvisionIntent:
    provision_token: str
    task_id: str | None
    root_attempt_id: str | None
    logical_agent_id: str
    role: str
    agent_name: str
    phase: str
    title: str
    status: str
    external_session_id: str | None
    requested_seq: int
    updated_seq: int
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provision_token": self.provision_token, "task_id": self.task_id,
            "root_attempt_id": self.root_attempt_id,
            "logical_agent_id": self.logical_agent_id, "role": self.role,
            "agent_name": self.agent_name, "phase": self.phase, "title": self.title,
            "status": self.status, "external_session_id": self.external_session_id,
            "requested_seq": self.requested_seq, "updated_seq": self.updated_seq,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, v: Mapping[str, Any]) -> "ProvisionIntent":
        return cls(str(v["provision_token"]), v.get("task_id"), v.get("root_attempt_id"), str(v["logical_agent_id"]),
                   str(v["role"]), str(v["agent_name"]), str(v["phase"]), str(v["title"]),
                   str(v["status"]), v.get("external_session_id"), int(v["requested_seq"]),
                   int(v["updated_seq"]), str(v["updated_at"]))


@dataclass(frozen=True)
class SessionObservationRecord:
    session_id: str
    observed_at: str
    reachable: bool
    healthy: bool | None
    message_count: int | None
    compaction_count: int | None
    context_used: int | None
    context_limit: int | None
    context_utilization: float | None
    last_activity_at: str | None
    provider_state: Mapping[str, Any]
    recorded_seq: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id, "observed_at": self.observed_at,
            "reachable": self.reachable, "healthy": self.healthy,
            "message_count": self.message_count, "compaction_count": self.compaction_count,
            "context_used": self.context_used, "context_limit": self.context_limit,
            "context_utilization": self.context_utilization,
            "last_activity_at": self.last_activity_at, "provider_state": dict(self.provider_state),
            "recorded_seq": self.recorded_seq,
        }

    @classmethod
    def from_dict(cls, v: Mapping[str, Any]) -> "SessionObservationRecord":
        return cls(str(v["session_id"]), str(v["observed_at"]), bool(v["reachable"]),
                   v.get("healthy"), v.get("message_count"), v.get("compaction_count"),
                   v.get("context_used"), v.get("context_limit"), v.get("context_utilization"),
                   v.get("last_activity_at"), dict(v.get("provider_state") or {}), int(v["recorded_seq"]))


@dataclass(frozen=True)
class RotationRequestRecord:
    rotation_id: str
    task_id: str
    root_attempt_id: str
    predecessor_session_id: str
    reasons: tuple[str, ...]
    status: str
    successor_session_id: str | None
    requested_seq: int
    updated_seq: int
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rotation_id": self.rotation_id, "task_id": self.task_id,
            "root_attempt_id": self.root_attempt_id,
            "predecessor_session_id": self.predecessor_session_id,
            "reasons": list(self.reasons), "status": self.status,
            "successor_session_id": self.successor_session_id,
            "requested_seq": self.requested_seq, "updated_seq": self.updated_seq,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, v: Mapping[str, Any]) -> "RotationRequestRecord":
        return cls(str(v["rotation_id"]), str(v["task_id"]), str(v["root_attempt_id"]),
                   str(v["predecessor_session_id"]), _tuple_str(v.get("reasons")),
                   str(v["status"]), v.get("successor_session_id"), int(v["requested_seq"]),
                   int(v["updated_seq"]), str(v["updated_at"]))


@dataclass(frozen=True)
class SessionControlState:
    mission_id: str
    routing_authority_enabled: bool = False
    routing_authority_enabled_seq: int | None = None
    task_routes: tuple[TaskRouteRequirement, ...] = ()
    provisions: tuple[ProvisionIntent, ...] = ()
    observations: tuple[SessionObservationRecord, ...] = ()
    rotations: tuple[RotationRequestRecord, ...] = ()

    def route(self, task_id: str) -> TaskRouteRequirement | None:
        return next((x for x in reversed(self.task_routes) if x.task_id == task_id), None)

    def provision(self, token: str) -> ProvisionIntent | None:
        return next((x for x in reversed(self.provisions) if x.provision_token == token), None)

    def observation(self, session_id: str) -> SessionObservationRecord | None:
        return next((x for x in reversed(self.observations) if x.session_id == session_id), None)

    def rotation(self, rotation_id: str) -> RotationRequestRecord | None:
        return next((x for x in reversed(self.rotations) if x.rotation_id == rotation_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "routing_authority_enabled": self.routing_authority_enabled,
            "routing_authority_enabled_seq": self.routing_authority_enabled_seq,
            "task_routes": [x.to_dict() for x in self.task_routes],
            "provisions": [x.to_dict() for x in self.provisions],
            "observations": [x.to_dict() for x in self.observations],
            "rotations": [x.to_dict() for x in self.rotations],
        }

    @classmethod
    def from_dict(cls, v: Mapping[str, Any]) -> "SessionControlState":
        return cls(
            str(v["mission_id"]),
            bool(v.get("routing_authority_enabled", False)),
            int(v["routing_authority_enabled_seq"]) if v.get("routing_authority_enabled_seq") is not None else None,
            tuple(TaskRouteRequirement.from_dict(x) for x in v.get("task_routes") or []),
            tuple(ProvisionIntent.from_dict(x) for x in v.get("provisions") or []),
            tuple(SessionObservationRecord.from_dict(x) for x in v.get("observations") or []),
            tuple(RotationRequestRecord.from_dict(x) for x in v.get("rotations") or []),
        )
