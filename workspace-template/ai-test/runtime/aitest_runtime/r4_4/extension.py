from __future__ import annotations

from typing import Any

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION
from .handlers import R44CommandContribution
from .projections import MIGRATION_SQL, R44MigrationContribution, R44ProjectionContribution
from .reducer import R44ReducerContribution, R44State


class R44StateContribution:
    def initial_state(self, mission_id: str) -> R44State:
        return R44State(mission_id)

    def encode(self, state: R44State) -> dict[str, Any]:
        return state.to_dict()

    def decode(self, value: dict[str, Any]) -> R44State:
        return R44State.from_dict(value)

    def hash(self, state: R44State) -> str:
        return canonical_sha256(self.encode(state))


def r4_4_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R44StateContribution(),
        command_contribution=R44CommandContribution(),
        reducer_contribution=R44ReducerContribution(),
        projection_contribution=R44ProjectionContribution(),
        migration_contribution=R44MigrationContribution(),
    )


__all__ = ["R44StateContribution", "r4_4_extension", "MIGRATION_SQL"]
