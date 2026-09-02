from __future__ import annotations

from typing import Any

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION
from .handlers import R46CommandContribution
from .projections import R46MigrationContribution, R46ProjectionContribution
from .reducer import R46ReducerContribution, R46State


class R46StateContribution:
    def initial_state(self, mission_id: str) -> R46State:
        return R46State(mission_id)

    def encode(self, state: R46State) -> dict[str, Any]:
        return state.to_dict()

    def decode(self, value: dict[str, Any]) -> R46State:
        return R46State.from_dict(value)

    def hash(self, state: R46State) -> str:
        return canonical_sha256(self.encode(state))


def r4_6_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=str(EXTENSION_VERSION),
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R46StateContribution(),
        command_contribution=R46CommandContribution(),
        reducer_contribution=R46ReducerContribution(),
        projection_contribution=R46ProjectionContribution(),
        migration_contribution=R46MigrationContribution(),
    )


__all__ = ["R46StateContribution", "r4_6_extension"]
