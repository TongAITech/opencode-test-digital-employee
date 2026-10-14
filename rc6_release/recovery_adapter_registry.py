"""Runtime-scoped registry for verified RC6 recovery adapters.

DSH Workers may request a recovery action over MCP, but they may not submit an
arbitrary JSON object and call it a successful recovery. Real adapters are
installed by trusted bootstrap/runtime wiring for one RC6 state root and are
then invoked by the MCP control plane. Missing bindings fail closed.
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Dict

from rc6_runtime.recovery_adapters import RecoveryAdapterError, RecoveryAdapterRegistry, VerifiedRecoveryAdapter


_LOCK = RLock()
_REGISTRIES: Dict[str, RecoveryAdapterRegistry] = {}


def _key(state_root: Path) -> str:
    return str(Path(state_root).resolve())


def registry_for(state_root: Path) -> RecoveryAdapterRegistry:
    key = _key(state_root)
    with _LOCK:
        registry = _REGISTRIES.get(key)
        if registry is None:
            registry = RecoveryAdapterRegistry()
            _REGISTRIES[key] = registry
        return registry


def register_recovery_adapter(state_root: Path, adapter: VerifiedRecoveryAdapter) -> None:
    registry_for(state_root).register(adapter)


def require_recovery_adapter(state_root: Path, action: str) -> VerifiedRecoveryAdapter:
    try:
        return registry_for(state_root).require(action)
    except RecoveryAdapterError as exc:
        raise RuntimeError("RECOVERY_ADAPTER_NOT_BOUND:%s" % action) from exc


def clear_recovery_adapters(state_root: Path) -> None:
    with _LOCK:
        _REGISTRIES.pop(_key(state_root), None)
