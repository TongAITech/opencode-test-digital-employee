from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION
from .handlers import R3E1CommandContribution
from .projections import R3E1MigrationContribution, R3E1ProjectionContribution
from .reducer import R3E1ReducerContribution, R3E1StateContribution


def r3_e1_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R3E1StateContribution(),
        command_contribution=R3E1CommandContribution(),
        reducer_contribution=R3E1ReducerContribution(),
        projection_contribution=R3E1ProjectionContribution(),
        migration_contribution=R3E1MigrationContribution(),
    )
