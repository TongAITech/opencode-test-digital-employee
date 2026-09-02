from __future__ import annotations
from dataclasses import replace
from typing import Any
from aitest_runtime.durable_core import RuntimeError
from .contracts import FACT_RECORDED, G4Fact, G4State

class G4ReducerContribution:
    def reduce(self, state: G4State, event: Any, core_state: Any) -> G4State:
        if event.event_type != FACT_RECORDED:
            raise RuntimeError("G4_EVENT_UNSUPPORTED", event.event_type)
        payload = dict(event.payload)
        fact = G4Fact(
            fact_id=str(payload["fact_id"]), fact_kind=str(payload["fact_kind"]), mission_id=event.mission_id,
            payload=dict(payload["payload"]), provenance_refs=tuple(payload.get("provenance_refs") or ()),
            idempotency_key=f"g4:fact:{payload['fact_id']}", correlation_id=event.correlation_id,
            created_seq=event.seq, created_at=event.created_at,
        )
        if state.by_id(fact.fact_id) is not None:
            raise RuntimeError("G4_FACT_ID_CONFLICT", fact.fact_id)
        return replace(state, facts=state.facts + (fact,))
