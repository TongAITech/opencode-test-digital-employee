from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import EXTENSION_ID, EXTENSION_VERSION, SessionOrchestrationState
from .handlers import COMMAND_TYPES, EVENT_TYPES, R25CommandContribution
from .projections import R25MigrationContribution, R25ProjectionContribution
from .reducer import R25ReducerContribution


class R25StateContribution:
    def initial_state(self, mission_id: str) -> SessionOrchestrationState:
        return SessionOrchestrationState(mission_id)

    def encode(self, state: SessionOrchestrationState) -> dict:
        return state.to_dict()

    def decode(self, value: dict) -> SessionOrchestrationState:
        return SessionOrchestrationState.from_dict(value)

    def hash(self, state: SessionOrchestrationState) -> str:
        return canonical_sha256(self.encode(state))


def r2_5_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R25StateContribution(),
        command_contribution=R25CommandContribution(),
        reducer_contribution=R25ReducerContribution(),
        projection_contribution=R25ProjectionContribution(),
        migration_contribution=R25MigrationContribution(),
    )


session_orchestration_extension = r2_5_extension
