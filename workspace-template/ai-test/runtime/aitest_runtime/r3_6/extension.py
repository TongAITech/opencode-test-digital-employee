from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION
from .handlers import R36CommandContribution
from .projections import R36MigrationContribution, R36ProjectionContribution
from .reducer import R36StateContribution, R36ReducerContribution


def r3_6_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R36StateContribution(),
        command_contribution=R36CommandContribution(),
        reducer_contribution=R36ReducerContribution(),
        projection_contribution=R36ProjectionContribution(),
        migration_contribution=R36MigrationContribution(),
    )
