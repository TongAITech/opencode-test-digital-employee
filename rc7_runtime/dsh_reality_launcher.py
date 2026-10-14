"""RC7 DSH launcher hardening for argument-level runtime proof.

RC6/BANK_FINAL already fail closed on signed lease tool authorization. RC7 adds
one missing evidence detail without modifying the frozen RC6 runtime: preserve
the arguments/input/params carried by each DSH tool-call event so R1 can prove
not only which tool ran, but what target/query it was invoked with.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from rc6_runtime.agent_runtime_hardening import BankFinalDshHeadlessWorkerLauncher


_ARGUMENT_KEYS = {"arguments", "args", "input", "parameters", "params"}


class RC7BankFinalDshHeadlessWorkerLauncher(BankFinalDshHeadlessWorkerLauncher):
    """BANK_FINAL launcher plus best-effort argument extraction from DSH events."""

    @classmethod
    def _tool_calls(cls, events: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        calls = super()._tool_calls(events)
        enriched: List[Dict[str, Any]] = []
        for call in calls:
            row = dict(call)
            event = cls._event_for_call_ref(events, str(call.get("call_ref") or ""))
            arguments = cls._extract_arguments(event) if event is not None else None
            if arguments is not None:
                row["arguments"] = arguments
            enriched.append(row)
        return enriched

    @staticmethod
    def _event_for_call_ref(
        events: Sequence[Dict[str, Any]],
        call_ref: str,
    ) -> Optional[Dict[str, Any]]:
        prefix = "dsh-event://tool-call/"
        if not call_ref.startswith(prefix):
            return None
        try:
            index = int(call_ref[len(prefix):])
        except (TypeError, ValueError):
            return None
        if index < 0 or index >= len(events):
            return None
        event = events[index]
        return event if isinstance(event, dict) else None

    @classmethod
    def _extract_arguments(cls, value: Any) -> Optional[Any]:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in _ARGUMENT_KEYS and child is not None:
                    return cls._normalize_arguments(child)
            for child in value.values():
                nested = cls._extract_arguments(child)
                if nested is not None:
                    return nested
        elif isinstance(value, list):
            for child in value:
                nested = cls._extract_arguments(child)
                if nested is not None:
                    return nested
        return None

    @staticmethod
    def _normalize_arguments(value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped and stripped[:1] in {"{", "["}:
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    return value
                if isinstance(parsed, (dict, list)):
                    return parsed
        return value
