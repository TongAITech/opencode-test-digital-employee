"""R2.4 dispatch port and deterministic R1.2 activation command builder."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from aitest_runtime.durable_core import CommandResult

from .contracts import (
    ACCEPTED,
    REJECTED,
    UNKNOWN,
    DispatchBinding,
    DispatchRequest,
    DispatchResult,
    R2_4Error,
)


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R2_4Error("R2_4_SCHEMA_INVALID", f"{name} must be a non-empty string")
    return value.strip()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise R2_4Error("R2_4_DISPATCH_INVALID", f"{name} must be an object")
    return value


def make_dispatch_request(
    *,
    mission_id: str,
    plan_id: str,
    plan_revision_id: str,
    task_id: str,
    binding: DispatchBinding | Mapping[str, Any],
) -> DispatchRequest:
    binding = binding if isinstance(binding, DispatchBinding) else DispatchBinding.from_mapping(binding)
    if (
        binding.mission_id != mission_id
        or binding.plan_id != plan_id
        or binding.plan_revision_id != plan_revision_id
        or binding.task_id != task_id
    ):
        raise R2_4Error("DISPATCH_BINDING_MISMATCH", "DispatchBinding does not match the current Task")
    return DispatchRequest(
        mission_id=mission_id,
        plan_id=plan_id,
        plan_revision_id=plan_revision_id,
        task_id=task_id,
        capability_id=binding.capability_id,
        capability_version=binding.capability_version,
        dispatch_binding_digest=binding.binding_digest,
        binding=binding,
    )


def activation_command(
    request: DispatchRequest,
    *,
    expected_seq: int,
    actor: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the only R1.2 command used by R2.4 to activate a Task."""
    if isinstance(expected_seq, bool) or not isinstance(expected_seq, int) or expected_seq < 0:
        raise R2_4Error("R2_4_INPUT_INVALID", "expected_seq must be a non-negative integer")
    actor = dict(actor or {"type": "SYSTEM", "id": "r2.4-dispatcher"})
    if not isinstance(actor.get("type"), str) or not actor.get("type") or not isinstance(actor.get("id"), str) or not actor.get("id"):
        raise R2_4Error("R2_4_INPUT_INVALID", "actor requires type and id")
    return {
        "command_id": request.activation_command_id,
        "type": "TRANSITION_TASK",
        "mission_id": request.mission_id,
        "expected_seq": expected_seq,
        "actor": actor,
        "payload": request.activation_payload(),
        "correlation_id": request.dispatch_id,
        "schema_version": 1,
    }


def _call_port(port: Any, request: Any) -> Any:
    if port is None:
        return None
    target = getattr(port, "dispatch", None) if not callable(port) else port
    if target is None:
        target = getattr(port, "send", None)
    if not callable(target):
        raise R2_4Error("DISPATCH_PORT_INVALID", "dispatcher port must be callable or expose dispatch/send")
    try:
        signature = inspect.signature(target)
        if len(signature.parameters) == 0:
            return target()
    except (TypeError, ValueError):
        pass
    return target(request)


def _normalize_result(request: DispatchRequest, raw: Any) -> DispatchResult:
    if isinstance(raw, DispatchResult):
        result = raw
    elif raw is True:
        result = DispatchResult(request.dispatch_id, ACCEPTED, receipt={"dispatch_id": request.dispatch_id})
    elif raw is False or raw is None:
        result = DispatchResult(request.dispatch_id, UNKNOWN, reason_code="DISPATCH_STATUS_UNKNOWN")
    elif isinstance(raw, str):
        result = DispatchResult(request.dispatch_id, raw.upper())
    elif isinstance(raw, Mapping):
        raw_id = raw.get("dispatch_id", request.dispatch_id)
        receipt = raw.get("receipt", raw.get("dispatch_receipt"))
        raw_status = raw.get("status", raw.get("outcome"))
        if raw_status is None:
            raw_status = ACCEPTED if receipt is not None else UNKNOWN
        result = DispatchResult(
            str(raw_id),
            str(raw_status).upper(),
            receipt=receipt if isinstance(receipt, Mapping) else ({"value": receipt} if receipt is not None else None),
            reason_code=raw.get("reason_code", raw.get("error_code")),
            reason=raw.get("reason"),
            attempt_count=raw.get("attempt_count", 1),
        )
    else:
        raise R2_4Error("DISPATCH_RESPONSE_INVALID", "dispatcher returned an unsupported result")
    if result.dispatch_id != request.dispatch_id:
        raise R2_4Error("DISPATCH_ID_MISMATCH", "dispatcher receipt identity differs from the deterministic dispatch_id")
    return result


def _execution_status(raw: Any) -> str:
    if raw is None:
        return "UNKNOWN"
    if isinstance(raw, DispatchResult):
        return raw.status
    if isinstance(raw, str):
        return raw.upper()
    if isinstance(raw, CommandResult):
        return ACCEPTED if raw.ok else UNKNOWN
    if isinstance(raw, Mapping):
        status = str(raw.get("status", raw.get("outcome", ""))).upper()
        if status in {ACCEPTED, REJECTED, UNKNOWN}:
            return status
        if any(raw.get(key) not in (None, "", {}, []) for key in ("receipt", "dispatch_receipt", "attempt_id", "execution_reference", "tool_execution_id")):
            return ACCEPTED
        if status in {"NONE", "ABSENT", "NOT_FOUND", "NOT_ATTEMPTED", "NO_EXECUTION"}:
            return "ABSENT"
        if status in {"IN_PROGRESS", "PENDING", "ATTEMPTED", "UNKNOWN", "UNRECONCILED"}:
            return UNKNOWN
    return UNKNOWN


class TaskDispatcher:
    """A stateless, idempotent dispatch port.

    Idempotency is carried by the deterministic ``dispatch_id`` and delegated
    to the external execution authority.  This object owns no cache or durable
    dispatch record.
    """

    def __init__(self, dispatch_port: Any = None, reconcile_port: Any = None) -> None:
        self._dispatch_port = dispatch_port
        self._reconcile_port = reconcile_port

    def reconcile(self, request: DispatchRequest) -> str:
        raw = _call_port(self._reconcile_port, request)
        return _execution_status(raw)

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        if not isinstance(request, DispatchRequest):
            raise R2_4Error("R2_4_DISPATCH_INVALID", "dispatch requires a DispatchRequest")
        raw = _call_port(self._dispatch_port, request)
        return _normalize_result(request, raw)

    def __call__(self, request: DispatchRequest) -> DispatchResult:
        return self.dispatch(request)


# Public aliases keep the port vocabulary explicit for callers.
build_activation_command = activation_command
build_dispatch_request = make_dispatch_request


__all__ = [
    "TaskDispatcher",
    "activation_command",
    "build_activation_command",
    "build_dispatch_request",
    "make_dispatch_request",
]
