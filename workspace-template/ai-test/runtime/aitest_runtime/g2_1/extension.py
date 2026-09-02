from __future__ import annotations
from typing import Any
from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256
from .contracts import *
from .handlers import G21CommandContribution
from .reducer import G21ReducerContribution
from .projections import G21MigrationContribution, G21ProjectionContribution

class G21StateContribution:
    def initial_state(self, mission_id: str) -> SessionControlState: return SessionControlState(mission_id)
    def encode(self, state: SessionControlState) -> dict[str, Any]: return state.to_dict()
    def decode(self, value: dict[str, Any]) -> SessionControlState: return SessionControlState.from_dict(value)
    def hash(self, state: SessionControlState) -> str: return canonical_sha256(state.to_dict())

def g2_1_extension() -> ExtensionManifest:
    return ExtensionManifest(EXTENSION_ID, EXTENSION_VERSION, COMMAND_TYPES, EVENT_TYPES, G21StateContribution(), G21CommandContribution(), G21ReducerContribution(), G21ProjectionContribution(), G21MigrationContribution())
