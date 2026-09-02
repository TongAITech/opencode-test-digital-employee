from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION, R34State
from .handlers import R34CommandContribution
from .projections import R34MigrationContribution, R34ProjectionContribution
from .reducer import R34ReducerContribution


class R34StateContribution:
    def initial_state(self, mission_id: str) -> R34State:
        return R34State(mission_id)

    def encode(self, state: R34State) -> dict:
        return state.to_dict()

    def decode(self, value: dict) -> R34State:
        return R34State.from_dict(value)

    def hash(self, state: R34State) -> str:
        return canonical_sha256(self.encode(state))


def r3_4_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R34StateContribution(),
        command_contribution=R34CommandContribution(),
        reducer_contribution=R34ReducerContribution(),
        projection_contribution=R34ProjectionContribution(),
        migration_contribution=R34MigrationContribution(),
    )
