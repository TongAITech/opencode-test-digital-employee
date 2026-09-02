from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION, HumanGateState
from .handlers import R26CommandContribution
from .projections import R26MigrationContribution, R26ProjectionContribution
from .reducer import R26ReducerContribution


class R26StateContribution:
    def initial_state(self, mission_id: str) -> HumanGateState:
        return HumanGateState(mission_id)

    def encode(self, state: HumanGateState) -> dict:
        return state.to_dict()

    def decode(self, value: dict) -> HumanGateState:
        return HumanGateState.from_dict(value)

    def hash(self, state: HumanGateState) -> str:
        return canonical_sha256(self.encode(state))


def r2_6_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R26StateContribution(),
        command_contribution=R26CommandContribution(),
        reducer_contribution=R26ReducerContribution(),
        projection_contribution=R26ProjectionContribution(),
        migration_contribution=R26MigrationContribution(),
    )


human_gate_extension = r2_6_extension
