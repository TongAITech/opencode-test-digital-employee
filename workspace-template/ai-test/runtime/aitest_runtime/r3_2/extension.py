from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION, R32State
from .handlers import R32CommandContribution
from .projections import R32MigrationContribution, R32ProjectionContribution
from .reducer import R32ReducerContribution


class R32StateContribution:
    def initial_state(self, mission_id: str) -> R32State:
        return R32State(mission_id)

    def encode(self, state: R32State) -> dict:
        return state.to_dict()

    def decode(self, value: dict) -> R32State:
        return R32State.from_dict(value)

    def hash(self, state: R32State) -> str:
        return canonical_sha256(self.encode(state))


def r3_2_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R32StateContribution(),
        command_contribution=R32CommandContribution(),
        reducer_contribution=R32ReducerContribution(),
        projection_contribution=R32ProjectionContribution(),
        migration_contribution=R32MigrationContribution(),
    )
