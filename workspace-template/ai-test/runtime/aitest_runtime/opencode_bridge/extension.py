from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import EXTENSION_ID, EXTENSION_VERSION, OpenCodeBridgeState
from .handlers import COMMAND_TYPES, EVENT_TYPES, OpenCodeBridgeCommandContribution
from .projections import OpenCodeBridgeMigrationContribution, OpenCodeBridgeProjectionContribution
from .reducer import OpenCodeBridgeReducerContribution


class OpenCodeBridgeStateContribution:
    def initial_state(self, mission_id: str) -> OpenCodeBridgeState:
        return OpenCodeBridgeState(mission_id=mission_id)

    def encode(self, state: OpenCodeBridgeState) -> dict:
        return state.to_dict()

    def decode(self, value: dict) -> OpenCodeBridgeState:
        return OpenCodeBridgeState.from_dict(value)

    def hash(self, state: OpenCodeBridgeState) -> str:
        return canonical_sha256(self.encode(state))


def opencode_bridge_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=OpenCodeBridgeStateContribution(),
        command_contribution=OpenCodeBridgeCommandContribution(),
        reducer_contribution=OpenCodeBridgeReducerContribution(),
        projection_contribution=OpenCodeBridgeProjectionContribution(),
        migration_contribution=OpenCodeBridgeMigrationContribution(),
    )


open_code_bridge_extension = opencode_bridge_extension


__all__ = ["OpenCodeBridgeStateContribution", "opencode_bridge_extension", "open_code_bridge_extension"]
