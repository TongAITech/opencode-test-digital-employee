from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol

from aitest_runtime.durable_core import RuntimeError

from .contracts import (
    OpenCodeBridgeRequest,
    TransportObservation,
    TransportOperation,
)


class TransportFailure(RuntimeError):
    """A fake transport failure which must never become a Runtime fact."""


class TransportTimeout(TransportFailure):
    def __init__(self, message: str = "fake transport timed out") -> None:
        super().__init__("OPENCODE_BRIDGE_TIMEOUT", message)


class TransportUnknown(TransportFailure):
    def __init__(self, message: str = "fake transport returned UNKNOWN") -> None:
        super().__init__("OPENCODE_BRIDGE_UNKNOWN", message)


class TransportDuplicate(TransportFailure):
    def __init__(self, message: str = "fake transport returned a duplicate") -> None:
        super().__init__("OPENCODE_BRIDGE_DUPLICATE", message)


@dataclass(frozen=True)
class TransportCall:
    operation: TransportOperation
    bridge_request_id: str
    attempt_id: str
    runtime_session_id: str
    correlation_id: str
    context_cursor: Any
    context_semantic_digest: str
    provider_request_id: str | None
    external_transport_handle: str | None
    provider: str
    model: str


class OpenCodeTransport(Protocol):
    def request(self, call: TransportCall) -> TransportObservation:
        ...


def _observation_from_mapping(value: Mapping[str, Any], call: TransportCall) -> TransportObservation:
    data = dict(value)
    if "status" not in data:
        data["status"] = "ACCEPTED"
    for name, item in (
        ("operation", call.operation.value),
        ("bridge_request_id", call.bridge_request_id),
        ("attempt_id", call.attempt_id),
        ("runtime_session_id", call.runtime_session_id),
        ("context_cursor", call.context_cursor),
        ("context_semantic_digest", call.context_semantic_digest),
        ("correlation_id", call.correlation_id),
        ("provider_request_id", call.provider_request_id or f"fake-provider-request:{call.bridge_request_id}"),
        ("external_transport_handle", call.external_transport_handle),
    ):
        data.setdefault(name, item.to_dict() if hasattr(item, "to_dict") else item)
    return TransportObservation.from_dict(data)


class FakeOpenCodeTransport:
    """Deterministic, in-process transport used by the R1.3D bridge only."""

    def __init__(self, responses: Iterable[TransportObservation | Mapping[str, Any] | BaseException] = ()) -> None:
        self._responses = list(responses)
        self.calls: list[TransportCall] = []

    def enqueue(self, response: TransportObservation | Mapping[str, Any] | BaseException) -> None:
        self._responses.append(response)

    queue = enqueue

    def request(self, call: TransportCall) -> TransportObservation:
        if not isinstance(call, TransportCall):
            raise RuntimeError("OPENCODE_BRIDGE_TRANSPORT_SCHEMA_INVALID", "transport call has an invalid type")
        self.calls.append(call)
        if self._responses:
            response = self._responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            if isinstance(response, Mapping):
                return _observation_from_mapping(response, call)
            if not isinstance(response, TransportObservation):
                raise RuntimeError("OPENCODE_BRIDGE_TRANSPORT_SCHEMA_INVALID", "fake response has an invalid type")
            return response
        provider_request_id = call.provider_request_id or f"fake-provider-request:{call.bridge_request_id}"
        external_handle = call.external_transport_handle
        if external_handle is None:
            external_handle = f"fake-transport-handle:{call.bridge_request_id}"
        return TransportObservation(
            status="ACCEPTED",
            operation=call.operation,
            bridge_request_id=call.bridge_request_id,
            attempt_id=call.attempt_id,
            runtime_session_id=call.runtime_session_id,
            context_cursor=call.context_cursor,
            context_semantic_digest=call.context_semantic_digest,
            correlation_id=call.correlation_id,
            provider_request_id=provider_request_id,
            external_transport_handle=external_handle,
        )

    invoke = request
    send = request


FakeTransport = FakeOpenCodeTransport


__all__ = [
    "FakeOpenCodeTransport",
    "FakeTransport",
    "OpenCodeTransport",
    "TransportCall",
    "TransportDuplicate",
    "TransportFailure",
    "TransportTimeout",
    "TransportUnknown",
]
