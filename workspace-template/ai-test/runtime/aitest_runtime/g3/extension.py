from __future__ import annotations
from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256
from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION, G3State
from .handlers import G3CommandContribution
from .projections import G3MigrationContribution, G3ProjectionContribution
from .reducer import G3ReducerContribution

class G3StateContribution:
    def initial_state(self, mission_id: str) -> G3State: return G3State(mission_id)
    def encode(self, state: G3State) -> dict: return state.to_dict()
    def decode(self, value: dict) -> G3State: return G3State.from_dict(value)
    def hash(self, state: G3State) -> str: return canonical_sha256(state.to_dict())

def g3_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID, extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES, event_types=EVENT_TYPES,
        state_contribution=G3StateContribution(), command_contribution=G3CommandContribution(),
        reducer_contribution=G3ReducerContribution(), projection_contribution=G3ProjectionContribution(),
        migration_contribution=G3MigrationContribution(),
    )
