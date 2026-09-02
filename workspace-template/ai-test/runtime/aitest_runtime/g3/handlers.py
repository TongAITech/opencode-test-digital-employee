from __future__ import annotations

from typing import Any
from aitest_runtime.durable_core import ComposedRuntimeState, PendingEvent, RuntimeError
from .contracts import EXTENSION_ID, FACT_RECORDED, G3State, RECORD_FACT, FACT_KINDS


class G3CommandContribution:
    def handle(self, command: Any, composed: ComposedRuntimeState) -> list[PendingEvent]:
        if command.type != RECORD_FACT:
            raise RuntimeError("G3_COMMAND_UNSUPPORTED", command.type)
        if command.session_id is not None:
            raise RuntimeError("G3_COMMAND_INVALID", "G3 durable facts are session-independent")
        state = composed.extension_state(EXTENSION_ID)
        if not isinstance(state, G3State):
            raise RuntimeError("G3_EXTENSION_NOT_REGISTERED", EXTENSION_ID)
        payload = dict(command.payload)
        required = {"fact_id", "fact_kind", "payload", "provenance_refs"}
        if set(payload) != required:
            raise RuntimeError("G3_COMMAND_INVALID", "G3_RECORD_FACT payload fields mismatch")
        fact_id = str(payload["fact_id"])
        fact_kind = str(payload["fact_kind"]).upper()
        if fact_kind not in FACT_KINDS:
            raise RuntimeError("G3_FACT_KIND_UNSUPPORTED", fact_kind)
        if state.by_id(fact_id) is not None:
            raise RuntimeError("G3_FACT_ID_CONFLICT", fact_id)
        expected_key = f"g3:fact:{fact_id}"
        if command.idempotency_key != expected_key:
            raise RuntimeError("G3_IDEMPOTENCY_INVALID", f"idempotency_key must be {expected_key}")
        return [PendingEvent(FACT_RECORDED, fact_kind, fact_id, payload, None)]
