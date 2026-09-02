from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION, ToolExecutionState
from .handlers import ToolExecutionCommandContribution
from .projections import ToolExecutionMigrationContribution, ToolExecutionProjectionContribution
from .reducer import ToolExecutionReducerContribution


class ToolExecutionStateContribution:
    def initial_state(self, mission_id: str) -> ToolExecutionState:
        return ToolExecutionState(mission_id=mission_id)

    def encode(self, state: ToolExecutionState) -> dict:
        return state.to_dict()

    def decode(self, value: dict) -> ToolExecutionState:
        return ToolExecutionState.from_dict(value)

    def hash(self, state: ToolExecutionState) -> str:
        return canonical_sha256(self.encode(state))


def tool_execution_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=ToolExecutionStateContribution(),
        command_contribution=ToolExecutionCommandContribution(),
        reducer_contribution=ToolExecutionReducerContribution(),
        projection_contribution=ToolExecutionProjectionContribution(),
        migration_contribution=ToolExecutionMigrationContribution(),
    )


tool_execution_extension_manifest = tool_execution_extension
tool_execution_runtime_extension = tool_execution_extension


__all__ = [
    "ToolExecutionStateContribution", "tool_execution_extension", "tool_execution_extension_manifest",
    "tool_execution_runtime_extension",
]
