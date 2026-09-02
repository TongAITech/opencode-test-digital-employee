from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import EXTENSION_ID, WorkGraphState
from .handlers import COMMAND_TYPES, WorkGraphCommandContribution
from .projections import WorkGraphMigrationContribution, WorkGraphProjectionContribution
from .reducer import EVENT_TYPES, WorkGraphReducerContribution


class WorkGraphStateContribution:
    def initial_state(self, mission_id: str) -> WorkGraphState:
        return WorkGraphState(mission_id=mission_id)

    def encode(self, state: WorkGraphState) -> dict:
        return state.to_dict()

    def decode(self, value: dict) -> WorkGraphState:
        return WorkGraphState.from_dict(value)

    def hash(self, state: WorkGraphState) -> str:
        return canonical_sha256(self.encode(state))


def work_graph_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version="1",
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=WorkGraphStateContribution(),
        command_contribution=WorkGraphCommandContribution(),
        reducer_contribution=WorkGraphReducerContribution(),
        projection_contribution=WorkGraphProjectionContribution(),
        migration_contribution=WorkGraphMigrationContribution(),
    )
