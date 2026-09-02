from __future__ import annotations
from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256
from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION, G4State
from .handlers import G4CommandContribution
from .projections import G4MigrationContribution, G4ProjectionContribution
from .reducer import G4ReducerContribution

class G4StateContribution:
    def initial_state(self, mission_id: str) -> G4State: return G4State(mission_id)
    def encode(self, state: G4State) -> dict: return state.to_dict()
    def decode(self, value: dict) -> G4State: return G4State.from_dict(value)
    def hash(self, state: G4State) -> str: return canonical_sha256(state.to_dict())

def g4_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID, extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES, event_types=EVENT_TYPES,
        state_contribution=G4StateContribution(), command_contribution=G4CommandContribution(),
        reducer_contribution=G4ReducerContribution(), projection_contribution=G4ProjectionContribution(),
        migration_contribution=G4MigrationContribution(),
    )
