from __future__ import annotations

from typing import Any

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION
from .handlers import R45CommandContribution
from .projections import R45MigrationContribution, R45ProjectionContribution
from .reducer import R45State, R45ReducerContribution


class R45StateContribution:
    def initial_state(self, mission_id: str) -> R45State:
        return R45State(mission_id)

    def encode(self, state: R45State) -> dict[str, Any]:
        return state.to_dict()

    def decode(self, value: dict[str, Any]) -> R45State:
        return R45State.from_dict(value)

    def hash(self, state: R45State) -> str:
        return canonical_sha256(self.encode(state))


def r4_5_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R45StateContribution(),
        command_contribution=R45CommandContribution(),
        reducer_contribution=R45ReducerContribution(),
        projection_contribution=R45ProjectionContribution(),
        migration_contribution=R45MigrationContribution(),
    )


__all__ = ["R45StateContribution", "r4_5_extension"]
