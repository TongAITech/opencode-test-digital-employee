from __future__ import annotations

from typing import Any

from aitest_runtime.durable_core import ExtensionManifest, canonical_sha256

from .contracts import COMMAND_TYPES, EVENT_TYPES, EXTENSION_ID, EXTENSION_VERSION, R48State
from .handlers import R48CommandContribution
from .projections import R48MigrationContribution, R48ProjectionContribution
from .reducer import R48ReducerContribution, R48StateContribution as _R48StateContribution


class R48StateContribution(_R48StateContribution):
    pass


def r4_8_extension() -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=EXTENSION_ID,
        extension_version=EXTENSION_VERSION,
        command_types=COMMAND_TYPES,
        event_types=EVENT_TYPES,
        state_contribution=R48StateContribution(),
        command_contribution=R48CommandContribution(),
        reducer_contribution=R48ReducerContribution(),
        projection_contribution=R48ProjectionContribution(),
        migration_contribution=R48MigrationContribution(),
    )


__all__ = ["R48StateContribution", "r4_8_extension"]
