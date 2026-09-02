from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import EXTENSION_ID, EXTENSION_VERSION, ProviderBindingState
from .handlers import COMMAND_TYPES, EVENT_TYPES, ProviderBindingCommandContribution
from .projections import ProviderBindingMigrationContribution, ProviderBindingProjectionContribution
from .reducer import ProviderBindingReducerContribution


class ProviderBindingStateContribution:
    def initial_state(self, mission_id: str) -> ProviderBindingState:
        return ProviderBindingState(mission_id=mission_id)

    def encode(self, state: ProviderBindingState) -> dict:
        return state.to_dict()

    def decode(self, value: dict) -> ProviderBindingState:
        return ProviderBindingState.from_dict(value)

    def hash(self, state: ProviderBindingState) -> str:
        return canonical_sha256(self.encode(state))


def provider_binding_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=ProviderBindingStateContribution(),
        command_contribution=ProviderBindingCommandContribution(),
        reducer_contribution=ProviderBindingReducerContribution(),
        projection_contribution=ProviderBindingProjectionContribution(),
        migration_contribution=ProviderBindingMigrationContribution(),
    )


__all__ = ["ProviderBindingStateContribution", "provider_binding_extension"]
