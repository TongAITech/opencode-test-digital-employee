from __future__ import annotations

from typing import Any

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION, R43State
from .handlers import R43CommandContribution
from .projections import R43MigrationContribution, R43ProjectionContribution
from .reducer import R43ReducerContribution


class R43StateContribution:
    def initial_state(self, mission_id: str) -> R43State:
        return R43State(mission_id)

    def encode(self, state: R43State) -> dict[str, Any]:
        return state.to_dict()

    def decode(self, value: dict[str, Any]) -> R43State:
        return R43State.from_dict(value)

    def hash(self, state: R43State) -> str:
        return canonical_sha256(self.encode(state))


def r4_3_extension() -> ExtensionManifest:
    """Return the explicit additive R4.3 manifest; default launch is unchanged."""
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R43StateContribution(),
        command_contribution=R43CommandContribution(),
        reducer_contribution=R43ReducerContribution(),
        projection_contribution=R43ProjectionContribution(),
        migration_contribution=R43MigrationContribution(),
    )


__all__ = ["R43StateContribution", "r4_3_extension"]
