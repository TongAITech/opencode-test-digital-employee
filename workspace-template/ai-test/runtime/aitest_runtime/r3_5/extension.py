from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION
from .handlers import R35CommandContribution
from .projections import R35MigrationContribution, R35ProjectionContribution
from .reducer import R35ReducerContribution, R35StateContribution


def r3_5_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R35StateContribution(),
        command_contribution=R35CommandContribution(),
        reducer_contribution=R35ReducerContribution(),
        projection_contribution=R35ProjectionContribution(),
        migration_contribution=R35MigrationContribution(),
    )

