from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol

from aitest_runtime.durable_core import RuntimeError, canonical_sha256

from .contracts import SideEffectPolicy, SideEffectState, ToolCall, ToolObservation


class ToolAdapterFailure(RuntimeError):
    """A classified adapter failure which is never silently treated as success."""


class ToolExecutionTimeout(ToolAdapterFailure):
    def __init__(self, message: str = "tool adapter timed out") -> None:
        super().__init__("TOOL_EXECUTION_TIMEOUT", message)


class ToolExecutionUnknown(ToolAdapterFailure):
    def __init__(self, message: str = "tool adapter returned an unknown result") -> None:
        super().__init__("TOOL_EXECUTION_UNKNOWN", message)


class ToolExecutionRejected(ToolAdapterFailure):
    def __init__(self, message: str = "tool adapter rejected the execution") -> None:
        super().__init__("TOOL_EXECUTION_REJECTED", message)


class ToolAdapter(Protocol):
    constrained: bool

    def invoke(self, call: ToolCall) -> ToolObservation:
        ...


ToolExecutionAdapter = ToolAdapter


@dataclass(frozen=True)
class AdapterResult:
    observation: ToolObservation


class ConstrainedToolAdapter:
    """Base for adapters allowed to perform policy-bound external operations."""

    constrained = True

    def __init__(self, capabilities: Iterable[str] = ()) -> None:
        self._capabilities = frozenset(capabilities)

    def can_execute(self, call: ToolCall) -> bool:
        return not self._capabilities or call.capability_id in self._capabilities

    def invoke(self, call: ToolCall) -> ToolObservation:
        raise NotImplementedError

    execute = invoke
    request = invoke


class FakeToolAdapter(ConstrainedToolAdapter):
    """Deterministic adapter for the R1.4 boundary and lifecycle tests."""

    def __init__(self, responses: Iterable[ToolObservation | Mapping[str, object] | BaseException] = ()) -> None:
        super().__init__()
        self._responses = list(responses)
        self.calls: list[ToolCall] = []

    def enqueue(self, response: ToolObservation | Mapping[str, object] | BaseException) -> None:
        self._responses.append(response)

    queue = enqueue

    def invoke(self, call: ToolCall) -> ToolObservation:
        if not isinstance(call, ToolCall):
            raise RuntimeError("TOOL_EXECUTION_ADAPTER_SCHEMA_INVALID", "adapter call has an invalid type")
        self.calls.append(call)
        if self._responses:
            response = self._responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            if isinstance(response, Mapping):
                response = ToolObservation.from_dict(response)
            if not isinstance(response, ToolObservation):
                raise RuntimeError("TOOL_EXECUTION_ADAPTER_SCHEMA_INVALID", "fake response has an invalid type")
            return response
        digest = canonical_sha256(
            {
                "tool_execution_id": call.tool_execution_id,
                "capability_id": call.capability_id,
                "input_digest": call.input_digest,
            }
        )
        state = SideEffectState.NOT_ATTEMPTED if call.side_effect_policy == SideEffectPolicy.NONE else SideEffectState.CONFIRMED
        return ToolObservation(
            status=SideEffectState.CONFIRMED,
            side_effect_state=state,
            result_digest=digest,
            result_reference=f"fake://tool-execution/{call.tool_execution_id}",
            redacted_result={"adapter": "fake", "result_digest": digest},
            external_request_id=f"fake-request:{call.tool_execution_id}",
        )

    execute = invoke
    request = invoke
    send = invoke


FakeAdapter = FakeToolAdapter


__all__ = [
    "AdapterResult", "ConstrainedToolAdapter", "FakeAdapter", "FakeToolAdapter", "ToolAdapter", "ToolExecutionAdapter",
    "ToolAdapterFailure", "ToolExecutionRejected", "ToolExecutionTimeout", "ToolExecutionUnknown",
]
