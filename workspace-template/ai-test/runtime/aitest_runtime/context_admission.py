"""Pre-provider context admission and governed recovery.

OpenCode hooks collect the final pre-provider components.  This module owns the
budget contract and recovery decision so JavaScript plugins never become a
second Runtime truth.

UTF-8 serialized bytes are treated as a conservative token upper bound for
model-visible text/schema content.  This is deliberately pessimistic; exact
provider tokenizers remain telemetry, not permission to exceed the bound.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from .canonical_runtime import create_canonical_runtime
from .durable_core import RuntimeError
from .autonomous_orchestration import DirectoryScopedOpenCodeSessionProvider, _utc_now
from .g2_1.managed_orchestration import default_g21_service
from .g2_1.supervisor import SessionObservation
from .primary_sessions import PrimarySessionOwner

SCHEMA = "aitest.context-admission.v1"
MAX_COMPONENT_BYTES = 64 * 1024 * 1024
MAX_PRIMARY_REPLAY_BYTES = 8 * 1024
MIN_CONTEXT_LIMIT = 8192
MAX_CONTEXT_LIMIT = 2_000_000
DEFAULT_OUTPUT_RESERVE = 4096


def _integer(value: Any, name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ValueError(name + " must be an integer")
    result = int(value)
    if result < minimum or (maximum is not None and result > maximum):
        raise ValueError(name + " is outside the allowed range")
    return result


def evaluate(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("context admission input must be an object")
    context_limit = _integer(value.get("context_limit"), "context_limit",
                             minimum=MIN_CONTEXT_LIMIT, maximum=MAX_CONTEXT_LIMIT)
    output = value.get("max_output_tokens")
    output_reserve = DEFAULT_OUTPUT_RESERVE if output is None else _integer(
        output, "max_output_tokens", minimum=1, maximum=context_limit - 1)
    # Reserve the real configured/advertised output budget. Never shrink a
    # large output allowance merely to make more input fit.
    output_reserve = max(output_reserve, 1024)

    raw_input_limit = value.get("input_limit")
    input_limit = None if raw_input_limit is None else _integer(
        raw_input_limit, "input_limit", minimum=1, maximum=MAX_CONTEXT_LIMIT)

    component_names = ("system_bytes", "messages_bytes", "tools_bytes", "extra_bytes")
    components = {
        name: _integer(value.get(name, 0), name, maximum=MAX_COMPONENT_BYTES)
        for name in component_names
    }
    message_count = _integer(value.get("message_count", 0), "message_count", maximum=100000)
    tool_count = _integer(value.get("tool_count", 0), "tool_count", maximum=10000)

    # Framing covers provider role/content wrappers and transformation growth
    # after the public hooks.  The byte-as-token method already overestimates
    # ordinary BPE/SentencePiece inputs; this reserve protects structural drift.
    framing = 1024 + message_count * 64 + tool_count * 128
    request_upper_bound = sum(components.values()) + framing
    safety = max(2048, int(math.ceil(context_limit * 0.05)))
    context_input_limit = context_limit - output_reserve
    effective_input_limit = min(
        context_input_limit,
        input_limit if input_limit is not None else context_input_limit,
    )
    input_budget = effective_input_limit - safety
    if input_budget <= 0:
        raise ValueError("model limits leave no positive input budget")

    identity = {
        "context_limit": context_limit,
        "model_input_limit": input_limit,
        "context_input_limit": context_input_limit,
        "effective_input_limit": effective_input_limit,
        "output_reserve": output_reserve,
        "safety_reserve": safety,
        "input_budget": input_budget,
        "request_upper_bound": request_upper_bound,
        "components": components,
        "message_count": message_count,
        "tool_count": tool_count,
        "estimation_method": "UTF8_BYTES_AS_TOKEN_UPPER_BOUND_PLUS_FRAMING",
    }
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()
    return {
        "schema": SCHEMA,
        "status": "ALLOW" if request_upper_bound <= input_budget else "BLOCK",
        "admission_digest": digest,
        **identity,
    }


def _provider(root: Path):
    endpoint = os.environ.get("AITEST_OPENCODE_ENDPOINT")
    if not endpoint:
        raise RuntimeError("CONTEXT_ADMISSION_HOST_ENDPOINT_REQUIRED", "OpenCode Host endpoint is required")
    return DirectoryScopedOpenCodeSessionProvider(
        root,
        base_url=endpoint,
        username=os.environ.get("OPENCODE_SERVER_USERNAME"),
        password=os.environ.get("OPENCODE_SERVER_PASSWORD"),
    )


def _recover_primary(runtime, root: Path, provider, payload: Mapping[str, Any],
                     decision: Mapping[str, Any]) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "")
    agent = str(payload.get("agent") or "")
    text = payload.get("current_user_text")
    if agent != "aitest-director" or not session_id:
        raise RuntimeError("PRIMARY_CONTEXT_ADMISSION_IDENTITY_INVALID", "Primary admission requires the exact Director Session")
    identity_exact = payload.get("current_user_identity_exact")
    replay_safe = payload.get("current_user_replay_safe")
    part_types = payload.get("current_user_part_types")
    if identity_exact is not True:
        raise RuntimeError("PRIMARY_CONTEXT_REPLAY_IDENTITY_UNRESOLVED", "current Host user message identity was not resolved exactly")
    if replay_safe is not True:
        kinds = ",".join(str(x) for x in part_types) if isinstance(part_types, list) else "UNKNOWN"
        raise RuntimeError("PRIMARY_CONTEXT_REPLAY_NON_TEXT_UNSUPPORTED", kinds[:256])
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("PRIMARY_CONTEXT_REPLAY_TEXT_REQUIRED", "a replayable current user text turn is required")
    if len(text.encode("utf-8")) > MAX_PRIMARY_REPLAY_BYTES:
        raise RuntimeError("PRIMARY_CONTEXT_REPLAY_TEXT_OVER_BUDGET", "current user turn exceeds the durable replay budget")

    owner = PrimarySessionOwner(runtime, root, provider)
    current = owner.current(session_id)

    # If this exact Host user message is the replay receipt of an already
    # accepted Primary recovery and a clean successor still cannot admit it,
    # another rotation cannot reduce static system/tool bytes. Fail closed
    # instead of creating an unbounded successor loop.
    current_message_id = payload.get("current_user_message_id")
    if isinstance(current_message_id, str) and current_message_id:
        context_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        state = owner.state()
        for binding in state.bindings.values():
            recovery = binding.get("context_recovery") if isinstance(binding, dict) else None
            receipt = recovery.get("receipt") if isinstance(recovery, dict) else None
            if (
                isinstance(recovery, dict)
                and recovery.get("state") == "ACCEPTED"
                and recovery.get("target_session_id") == session_id
                and recovery.get("context_digest") == context_digest
                and isinstance(receipt, dict)
                and receipt.get("message_id") == current_message_id
            ):
                raise RuntimeError(
                    "PRIMARY_CONTEXT_RECOVERY_NON_CONVERGENT",
                    "the exact replayed user turn still exceeds budget on its clean successor",
                )

    recovery_id = owner.claim_context_recovery(
        session_id, agent, text, str(decision["admission_digest"])
    )
    recovered = owner.recover_pending_context()
    if recovered.get("status") != "ACCEPTED":
        raise RuntimeError(
            "PRIMARY_CONTEXT_REPLAY_RECONCILIATION_REQUIRED",
            str(recovered.get("reason") or recovered.get("status") or "UNKNOWN"),
        )
    successor_session_id = str(recovered["successor_session_id"])
    if successor_session_id == session_id:
        raise RuntimeError("PRIMARY_CONTEXT_SUCCESSOR_REQUIRED", "context recovery must create a distinct successor Session")
    return {
        "kind": "PRIMARY",
        "status": "ROTATED",
        "recovery_id": recovery_id,
        "predecessor_session_id": session_id,
        "successor_session_id": successor_session_id,
        "logical_agent_id": current["logical_agent_id"],
        "epoch": recovered["epoch"],
        "replayed_current_user_turn": True,
        "replay_receipt": recovered["receipt"],
        "tui_follow": "SELECTED_SUCCESSOR",
    }


def _recover_general(runtime, root: Path, provider, payload: Mapping[str, Any]) -> dict[str, Any]:
    from .general_work.execution import GeneralExecutionService
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        raise RuntimeError("GENERAL_CONTEXT_SESSION_ID_REQUIRED", "General context recovery requires a Session id")
    return GeneralExecutionService(runtime, root, provider).rotate_for_context_admission(session_id)


def _signal_mission(runtime, root: Path, provider, payload: Mapping[str, Any],
                    decision: Mapping[str, Any]) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        raise RuntimeError("MISSION_CONTEXT_SESSION_ID_REQUIRED", "Mission context recovery requires a Session id")
    service = default_g21_service(runtime, root, session_provider=provider)
    matches: list[str] = []
    for mission_id in service._active_mission_ids():
        composed = runtime.replay_composed(mission_id)
        if any(s.session_id == session_id and s.status.value == "OPEN" for s in composed.core_state.sessions):
            matches.append(mission_id)
    if len(matches) != 1:
        raise RuntimeError("MISSION_CONTEXT_SESSION_BINDING_AMBIGUOUS", "Session must bind to exactly one active Mission")
    mission_id = matches[0]
    pressure = {
        "final_request_admission_blocked": True,
        "admission_digest": decision["admission_digest"],
        "request_upper_bound": decision["request_upper_bound"],
        "input_budget": decision["input_budget"],
        "model_context_limit": decision["context_limit"],
    }
    observation = SessionObservation(
        session_id=session_id,
        observed_at=_utc_now(),
        reachable=True,
        healthy=True,
        context_used=None,
        context_limit=decision["context_limit"],
        context_utilization=None,
        provider_state={"provider": "AITEST_CONTEXT_GOVERNOR", "pressure": pressure},
    )
    service.session_control.record_observation(mission_id, observation.to_dict())
    return {
        "kind": "MISSION",
        "status": "PRESSURE_RECORDED",
        "mission_id": mission_id,
        "session_id": session_id,
        "rotation_owner": "G2_1_CONTROL_LOOP",
    }


def admit(payload: Mapping[str, Any], *, runtime=None, provider=None, root: Path | None = None) -> dict[str, Any]:
    decision = evaluate(payload)
    if decision["status"] == "ALLOW":
        return {**decision, "recovery": None}

    root = (root or Path(os.environ.get("AITEST_WORKSPACE_ROOT") or ".")).resolve()
    runtime = runtime or create_canonical_runtime(root)
    provider = provider or _provider(root)
    agent = str(payload.get("agent") or "")
    if agent == "aitest-director":
        recovery = _recover_primary(runtime, root, provider, payload, decision)
    elif agent in {"aitest-general-worker", "aitest-runtime-diagnosis"}:
        recovery = _recover_general(runtime, root, provider, payload)
    else:
        recovery = _signal_mission(runtime, root, provider, payload, decision)
    return {**decision, "recovery": recovery}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aitest-context-admission")
    parser.add_argument("--stdin-json", action="store_true", default=True)
    parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
        result = admit(payload)
        sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
        return 0
    except Exception as exc:
        sys.stdout.write(json.dumps({
            "schema": SCHEMA,
            "status": "ERROR",
            "error": getattr(exc, "code", type(exc).__name__),
            "message": str(exc)[:1000],
        }, ensure_ascii=False, sort_keys=True) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
