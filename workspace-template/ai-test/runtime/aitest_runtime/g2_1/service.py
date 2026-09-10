from __future__ import annotations
from dataclasses import replace
from typing import Any, Mapping
from aitest_runtime.durable_core import ActorRef, CommandEnvelope, RuntimeService, canonical_sha256
from .contracts import *

def execute_control_command(runtime: RuntimeService, command: CommandEnvelope):
    """Rebase G2.1 control writes only across additive health observations.

    Rejected commands remain immutable in R1. Each bounded retry therefore has
    its own cursor-qualified command ID, with the original correlation and
    idempotency identity. No Plan, Task or other semantic event is crossed.
    """
    original_id = command.command_id
    for attempt in range(5):
        result = runtime.execute(command)
        if result.ok or not result.error or result.error.code != "EXPECTED_SEQ_MISMATCH":
            return result
        if command.type not in COMMAND_TYPES | {"CLOSE_SESSION"}:
            return result
        head = runtime.get_head_seq(command.mission_id)
        events = runtime.list_events(command.mission_id, after_seq=command.expected_seq, through_seq=head)
        if not events or any(event.event_type != SESSION_OBSERVATION_RECORDED for event in events):
            return result
        if attempt < 4:
            command = replace(command, expected_seq=head, command_id=f"{original_id}:observation-cursor:{head}")
    return result

class SessionControlApplicationService:
    def __init__(self, runtime: RuntimeService):
        runtime.extension_registry.manifest(EXTENSION_ID)
        self.runtime = runtime
    def state(self, mission_id: str) -> SessionControlState:
        value = self.runtime.replay_composed(mission_id).extension_state(EXTENSION_ID)
        if not isinstance(value, SessionControlState): raise RuntimeError("G2_1_STATE_INVALID")
        return value
    def _execute(self, mission_id: str, command_id: str, type_: str, payload: Mapping[str, Any], session_id: str | None = None):
        result=execute_control_command(self.runtime, CommandEnvelope(command_id, type_, mission_id, self.runtime.get_head_seq(mission_id), ActorRef("SYSTEM","g2.1-session-control"), dict(payload), session_id=session_id, idempotency_key=command_id, correlation_id=command_id, schema_version=1))
        if not result.ok:
            if result.error: raise result.error
            raise RuntimeError("G2_1_COMMAND_REJECTED")
        return result
    def enable_routing_authority(self, mission_id: str):
        state = self.state(mission_id)
        if state.routing_authority_enabled:
            return None
        return self._execute(mission_id, f"g2.1:routing-authority:{mission_id}:ENABLE", ENABLE_ROUTING_AUTHORITY, {})
    def register_task_route(self, mission_id: str, *, task_id: str, role: str, agent_name: str, required_capabilities: list[str], isolation_policy: str, parallelism_policy: str, source: str):
        stable={"task_id":task_id,"role":role,"agent_name":agent_name,"required_capabilities":required_capabilities,"isolation_policy":isolation_policy,"parallelism_policy":parallelism_policy,"source":source}
        stable["route_digest"]=canonical_sha256(stable)
        return self._execute(mission_id, f"g2.1:route:{task_id}:{stable['route_digest'][:16]}", REGISTER_TASK_ROUTE, stable)
    def request_provision(self, mission_id: str, **payload: Any):
        token=str(payload["provision_token"]); return self._execute(mission_id, f"g2.1:provision:{token}:REQUEST", REQUEST_SESSION_PROVISION, payload)
    def bind_provision(self, mission_id: str, token: str, session_id: str):
        return self._execute(mission_id, f"g2.1:provision:{token}:BIND:{session_id}", BIND_SESSION_PROVISION, {"provision_token":token,"external_session_id":session_id}, session_id)
    def close_orphan(self, mission_id: str, token: str, session_id: str, reason: str):
        return self._execute(mission_id, f"g2.1:provision:{token}:ORPHAN_CLOSED:{session_id}", CLOSE_ORPHAN_PROVISION, {"provision_token":token,"external_session_id":session_id,"reason":reason}, session_id)
    def record_observation(self, mission_id: str, payload: Mapping[str, Any]):
        sid=str(payload["session_id"]); digest=canonical_sha256(dict(payload))[:16]
        previous = self.state(mission_id).observation(sid)
        if previous is not None:
            prior = previous.to_dict(); prior.pop('recorded_seq', None)
            if prior == dict(payload):
                return None
        return self._execute(mission_id, f"g2.1:observe:{sid}:{digest}", RECORD_SESSION_OBSERVATION, payload, sid)
    def record_context_dispatch(self, mission_id: str, payload: Mapping[str, Any]):
        did=str(payload['dispatch_id']); phase=str(payload['phase'])
        return self._execute(mission_id, f'{did}:{phase}', RECORD_CONTEXT_DISPATCH, payload, str(payload['session_id']))
    def request_rotation(self, mission_id: str, payload: Mapping[str, Any]):
        rid=str(payload["rotation_id"]); return self._execute(mission_id, f"g2.1:rotation:{rid}:REQUEST", REQUEST_SESSION_ROTATION, payload, str(payload["predecessor_session_id"]))
    def complete_rotation(self, mission_id: str, rotation_id: str, successor_session_id: str):
        return self._execute(mission_id, f"g2.1:rotation:{rotation_id}:COMPLETE:{successor_session_id}", COMPLETE_SESSION_ROTATION, {"rotation_id":rotation_id,"successor_session_id":successor_session_id}, successor_session_id)
