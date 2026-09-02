from __future__ import annotations

from typing import Any

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION, R42State
from .handlers import R42CommandContribution
from .projections import R42MigrationContribution, R42ProjectionContribution
from .reducer import R42ReducerContribution


class R42StateContribution:
    def initial_state(self, mission_id: str) -> R42State:
        return R42State(mission_id)

    def encode(self, state: R42State) -> dict[str, Any]:
        return state.to_dict()

    def decode(self, value: dict[str, Any]) -> R42State:
        return R42State.from_dict(value)

    def hash(self, state: R42State) -> str:
        return canonical_sha256(self.encode(state))


def r4_2_extension() -> ExtensionManifest:
    """Return the explicit additive R4.2 extension manifest."""
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R42StateContribution(),
        command_contribution=R42CommandContribution(),
        reducer_contribution=R42ReducerContribution(),
        projection_contribution=R42ProjectionContribution(),
        migration_contribution=R42MigrationContribution(),
    )


__all__ = ["R42StateContribution", "r4_2_extension"]

