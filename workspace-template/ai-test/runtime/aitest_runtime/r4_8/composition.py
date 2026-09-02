from __future__ import annotations

from pathlib import Path
from typing import Any

from aitest_runtime.durable_core import Clock, ExtensionManifest, RuntimeService

from .contracts import (
    EXTENSION_ID,
    R48AuthorityBinding,
    R48AuthorityKind,
    R48BindingSource,
    R48CompositionSpec,
    R48CompositionValidationResult,
)
from .errors import R48Error, R48ErrorCode
from .extension import r4_8_extension


_BASE_AUTHORITIES = frozenset(
    {
        R48AuthorityKind.R2,
        R48AuthorityKind.R2_6,
        R48AuthorityKind.R3,
        R48AuthorityKind.R3_7,
        R48AuthorityKind.R4_1,
        R48AuthorityKind.R4_2,
        R48AuthorityKind.R4_3,
        R48AuthorityKind.R4_4,
        R48AuthorityKind.R4_5,
        R48AuthorityKind.R4_6,
        R48AuthorityKind.R4_7,
    }
)


def _required_authorities(spec: R48CompositionSpec) -> frozenset[R48AuthorityKind]:
    values = set(_BASE_AUTHORITIES)
    if spec.field_validation_binding_required:
        values.add(R48AuthorityKind.FIELD_VALIDATION)
    return frozenset(values)


def validate_r4_8_composition(spec: R48CompositionSpec) -> R48CompositionValidationResult:
    errors: list[R48ErrorCode] = []
    manifests = tuple(spec.upstream_extensions)
    ids = tuple(manifest.extension_id for manifest in manifests)
    if EXTENSION_ID in ids:
        errors.append(R48ErrorCode.EXTENSION_ID_CONFLICT)
    if len(ids) != len(set(ids)):
        errors.append(R48ErrorCode.EXTENSION_ID_CONFLICT)
    available = set(ids)
    if not set(spec.required_extension_ids).issubset(available):
        errors.append(R48ErrorCode.REQUIRED_EXTENSION_MISSING)
    bindings: dict[R48AuthorityKind, R48AuthorityBinding] = {}
    for binding in spec.authority_bindings:
        if binding.authority in bindings:
            errors.append(R48ErrorCode.AUTHORITY_BINDING_MISSING)
            continue
        bindings[binding.authority] = binding
        if binding.source is R48BindingSource.UNSUPPORTED or not callable(binding.bind):
            errors.append(R48ErrorCode.AUTHORITY_BINDING_UNSUPPORTED)
    required = _required_authorities(spec)
    for authority in required:
        binding = bindings.get(authority)
        if binding is None or (binding.required and binding.source is R48BindingSource.UNSUPPORTED):
            errors.append(R48ErrorCode.AUTHORITY_BINDING_MISSING)
    return R48CompositionValidationResult(
        ok=not errors,
        errors=tuple(dict.fromkeys(errors)),
        normalized_extension_ids=tuple(sorted(ids)),
        required_authorities=required,
    )


def _assert_composition(spec: R48CompositionSpec) -> None:
    result = validate_r4_8_composition(spec)
    if not result.ok:
        raise R48Error(
            "COMPOSITION_INVALID",
            "R4.8 composition preflight failed",
            {"errors": [item.name for item in result.errors]},
        )


def compose_r4_8_closed_loop_runtime(
    db_path: str | Path,
    composition_spec: R48CompositionSpec,
    clock: Clock | None = None,
    failure_injector: Any | None = None,
) -> RuntimeService:
    _assert_composition(composition_spec)
    extensions = tuple(composition_spec.upstream_extensions) + (r4_8_extension(),)
    return RuntimeService(db_path, clock=clock, failure_injector=failure_injector, extensions=extensions)


__all__ = ["validate_r4_8_composition", "compose_r4_8_closed_loop_runtime"]
