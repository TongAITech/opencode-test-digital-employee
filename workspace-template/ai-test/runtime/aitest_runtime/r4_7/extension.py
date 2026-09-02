from __future__ import annotations

from typing import Any

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION
from .handlers import R47CommandContribution
from .projections import R47MigrationContribution, R47ProjectionContribution
from .reducer import R47ReducerContribution, R47State


class R47StateContribution:
    def initial_state(self, mission_id: str) -> R47State:
        return R47State(mission_id)

    def encode(self, state: R47State) -> dict[str, Any]:
        return state.to_dict()

    def decode(self, value: dict[str, Any]) -> R47State:
        return R47State.from_dict(value)

    def hash(self, state: R47State) -> str:
        return canonical_sha256(self.encode(state))


def r4_7_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R47StateContribution(),
        command_contribution=R47CommandContribution(),
        reducer_contribution=R47ReducerContribution(),
        projection_contribution=R47ProjectionContribution(),
        migration_contribution=R47MigrationContribution(),
    )


__all__ = ["R47StateContribution", "r4_7_extension"]
