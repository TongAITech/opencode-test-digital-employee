from __future__ import annotations

from typing import Any

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION, R41State
from .handlers import R41CommandContribution
from .projections import R41MigrationContribution, R41ProjectionContribution
from .reducer import R41ReducerContribution


class R41StateContribution:
    def initial_state(self, mission_id: str) -> R41State:
        return R41State(mission_id)

    def encode(self, state: R41State) -> dict[str, Any]:
        return state.to_dict()

    def decode(self, value: dict[str, Any]) -> R41State:
        return R41State.from_dict(value)

    def hash(self, state: R41State) -> str:
        return canonical_sha256(self.encode(state))


def r4_1_extension() -> ExtensionManifest:
    """Return the explicit additive R4.1 extension manifest."""
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R41StateContribution(),
        command_contribution=R41CommandContribution(),
        reducer_contribution=R41ReducerContribution(),
        projection_contribution=R41ProjectionContribution(),
        migration_contribution=R41MigrationContribution(),
    )

