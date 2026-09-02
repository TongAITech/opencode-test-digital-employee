from __future__ import annotations

from pathlib import Path
from typing import Iterable

from aitest_runtime.durable_core import ExtensionManifest, RuntimeService

from .contracts import EXTENSION_ID, R26Error
from .extension import r2_6_extension


def compose_extensions(base_extensions: Iterable[ExtensionManifest]) -> tuple[ExtensionManifest, ...]:
    base = tuple(base_extensions)
    if any(item.extension_id == EXTENSION_ID for item in base):
        raise R26Error("R2_6_CANONICAL_BINDING_CONFLICT", "R2.6 extension is already registered")
    return base + (r2_6_extension(),)


def compose_r2_6_runtime(
    db_path: str | Path,
    base_extensions: Iterable[ExtensionManifest],
    *,
    clock=None,
    failure_injector=None,
) -> RuntimeService:
    """Explicit additive composition; it does not alter R1.5 launch or own a second store."""
    return RuntimeService(
        db_path,
        clock=clock,
        failure_injector=failure_injector,
        extensions=compose_extensions(base_extensions),
    )
