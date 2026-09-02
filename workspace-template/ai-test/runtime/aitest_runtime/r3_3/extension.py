from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION, R33State
from .handlers import R33CommandContribution
from .projections import R33MigrationContribution, R33ProjectionContribution
from .reducer import R33ReducerContribution


class R33StateContribution:
    def initial_state(self, mission_id: str) -> R33State:
        return R33State(mission_id)

    def encode(self, state: R33State) -> dict:
        return state.to_dict()

    def decode(self, value: dict) -> R33State:
        return R33State.from_dict(value)

    def hash(self, state: R33State) -> str:
        return canonical_sha256(self.encode(state))


def r3_3_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R33StateContribution(),
        command_contribution=R33CommandContribution(),
        reducer_contribution=R33ReducerContribution(),
        projection_contribution=R33ProjectionContribution(),
        migration_contribution=R33MigrationContribution(),
    )

