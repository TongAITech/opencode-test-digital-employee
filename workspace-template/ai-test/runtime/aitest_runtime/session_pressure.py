"""Bounded, content-free OpenCode observation when session metrics are absent.

The byte estimate is deliberately conservative (one UTF-8 byte per token plus
framing/output reserve). It is a Runtime budget, never an assertion about a
model's tokenizer or advertised context window. Raw messages stay transient.
"""
from __future__ import annotations

import json
import math
from typing import Any, Mapping

MESSAGE_SAMPLE_LIMIT = 60
MAX_OBSERVATION_BYTES = 8 * 1024 * 1024
ESTIMATED_CONTEXT_BUDGET = 32768
CONTEXT_RESERVE = 4096
ROTATE_TURN_BUDGET = 24
ROTATE_ACTIVITY_BUDGET = 48
ROTATE_BLIND_ACTIVITY_BUDGET = 12
ROTATE_BLIND_SECONDS = 300
POLICY_ID = "g2.1-opencode-1.18.3-pressure-v1"


class ObservationBudgetExceeded(RuntimeError):
    pass


def number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def message_metrics(payload: Any, session_id: str) -> dict[str, Any]:
    if not isinstance(payload, list):
        raise ValueError("OPENCODE_MESSAGE_LIST_INVALID")
    turns = activities = compactions = content_bytes = 0
    latest_tokens: int | None = None
    latest_token_time = -1.0
    seen: set[str] = set()
    for message in payload:
        if not isinstance(message, Mapping) or not isinstance(message.get("info"), Mapping) or not isinstance(message.get("parts"), list):
            raise ValueError("OPENCODE_MESSAGE_ENTRY_INVALID")
        info = message["info"]
        if info.get("sessionID") != session_id or not isinstance(info.get("id"), str):
            raise ValueError("OPENCODE_MESSAGE_SESSION_MISMATCH")
        if info["id"] in seen:
            continue
        seen.add(info["id"])
        # Serializing transient parts accounts for text, reasoning, tool input,
        # output and structured attachments without persisting their content.
        content_bytes += len(json.dumps(message["parts"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 128
        turns += int(info.get("role") == "assistant")
        for part in message["parts"]:
            if not isinstance(part, Mapping):
                raise ValueError("OPENCODE_MESSAGE_PART_INVALID")
            compactions += int(part.get("type") == "compaction")
            activities += int(part.get("type") in {"tool", "step-finish"})
        tokens = info.get("tokens")
        stamp = number((info.get("time") or {}).get("created")) if isinstance(info.get("time"), Mapping) else None
        if isinstance(tokens, Mapping):
            cache = tokens.get("cache") if isinstance(tokens.get("cache"), Mapping) else {}
            values = [number(tokens.get("input")), number(tokens.get("output")), number(cache.get("read")), number(cache.get("write"))]
            if values[0] is not None and (stamp or 0) >= latest_token_time:
                latest_tokens = int(sum(value or 0 for value in values))
                latest_token_time = stamp or 0
    estimate = content_bytes + CONTEXT_RESERVE
    return {
        "message_count": len(seen), "compaction_count": compactions,
        "turn_count": turns, "activity_count": activities,
        "estimated_context_used": estimate, "estimated_context_budget": ESTIMATED_CONTEXT_BUDGET,
        "estimated_context_utilization": estimate / ESTIMATED_CONTEXT_BUDGET,
        "observed_message_tokens": latest_tokens,
        "message_sample_limit": MESSAGE_SAMPLE_LIMIT,
        "message_sample_saturated": len(seen) >= MESSAGE_SAMPLE_LIMIT,
        "metrics_source": "OPENCODE_MESSAGE_API", "estimate_method": "UTF8_BYTES_PLUS_FRAMING_AND_4096_RESERVE",
        "pressure_policy": POLICY_ID,
    }
