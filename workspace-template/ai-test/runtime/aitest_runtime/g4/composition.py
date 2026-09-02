from __future__ import annotations

import importlib
import inspect
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aitest_runtime.durable_core import RuntimeError


@dataclass(frozen=True)
class G4ProviderBundle:
    """Process-local execution provider composition.

    Provider objects are runtime adapters only; they are never durable truth. The
    R1 Event Stream stores authoritative G4 facts/evidence references. Bank-specific
    bindings are supplied by deployment/Field Validation and are never guessed.
    """

    browser_provider: Any | None = None
    capability_executors: Mapping[str, Any] | None = None
    resume_condition_verifier: Any | None = None
    source_ref: str = "UNCONFIGURED"


def _factory_ref(profile: Mapping[str, Any] | None) -> str | None:
    env = str(os.environ.get("AITEST_G4_PROVIDER_FACTORY") or "").strip()
    if env:
        return env
    raw = dict(profile or {})
    g4 = raw.get("g4")
    if isinstance(g4, Mapping):
        value = str(g4.get("provider_factory") or "").strip()
        if value:
            return value
    value = str(raw.get("g4_provider_factory") or "").strip()
    return value or None


def _load_factory(ref: str) -> Any:
    module_name, sep, attr = ref.partition(":")
    if not sep or not module_name.strip() or not attr.strip():
        raise RuntimeError("G4_PROVIDER_FACTORY_REF_INVALID", ref)
    try:
        module = importlib.import_module(module_name.strip())
    except Exception as exc:
        raise RuntimeError("G4_PROVIDER_FACTORY_IMPORT_FAILED", ref) from exc
    factory = getattr(module, attr.strip(), None)
    if not callable(factory):
        raise RuntimeError("G4_PROVIDER_FACTORY_NOT_CALLABLE", ref)
    return factory


def load_provider_bundle(root: Path, profile: Mapping[str, Any] | None = None) -> G4ProviderBundle:
    """Load an explicitly configured provider bundle; absent config is fail-closed.

    This is intentionally not a plugin discovery mechanism. Nothing is guessed or
    auto-imported. A deployment must name the exact ``module:function`` factory.
    """

    ref = _factory_ref(profile)
    if ref is None:
        return G4ProviderBundle()
    factory = _load_factory(ref)
    try:
        signature = inspect.signature(factory)
        kwargs: dict[str, Any] = {}
        if "root" in signature.parameters:
            kwargs["root"] = root
        if "profile" in signature.parameters:
            kwargs["profile"] = dict(profile or {})
        value = factory(**kwargs)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("G4_PROVIDER_FACTORY_FAILED", ref) from exc
    if isinstance(value, G4ProviderBundle):
        return G4ProviderBundle(value.browser_provider, dict(value.capability_executors or {}), value.resume_condition_verifier, ref)
    if not isinstance(value, Mapping):
        raise RuntimeError("G4_PROVIDER_BUNDLE_INVALID", ref)
    allowed = {"browser_provider", "capability_executors", "resume_condition_verifier"}
    unknown = set(value) - allowed
    if unknown:
        raise RuntimeError("G4_PROVIDER_BUNDLE_FIELD_UNSUPPORTED", ",".join(sorted(str(x) for x in unknown)))
    executors = value.get("capability_executors")
    if executors is not None and not isinstance(executors, Mapping):
        raise RuntimeError("G4_PROVIDER_EXECUTORS_INVALID", ref)
    return G4ProviderBundle(value.get("browser_provider"), dict(executors or {}), value.get("resume_condition_verifier"), ref)
