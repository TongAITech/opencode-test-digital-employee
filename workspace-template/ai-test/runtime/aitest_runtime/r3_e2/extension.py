from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION
from .handlers import R3E2CommandContribution
from .projections import R3E2MigrationContribution, R3E2ProjectionContribution
from .reducer import R3E2ReducerContribution, R3E2StateContribution


def r3_e2_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R3E2StateContribution(),
        command_contribution=R3E2CommandContribution(),
        reducer_contribution=R3E2ReducerContribution(),
        projection_contribution=R3E2ProjectionContribution(),
        migration_contribution=R3E2MigrationContribution(),
    )
