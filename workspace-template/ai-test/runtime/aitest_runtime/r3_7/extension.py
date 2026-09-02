from __future__ import annotations

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION, R37State
from .handlers import R37CommandContribution
from .projections import R37MigrationContribution, R37ProjectionContribution
from .reducer import R37ReducerContribution, R37StateContribution


def r3_7_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R37StateContribution(),
        command_contribution=R37CommandContribution(),
        reducer_contribution=R37ReducerContribution(),
        projection_contribution=R37ProjectionContribution(),
        migration_contribution=R37MigrationContribution(),
    )
