from __future__ import annotations

import importlib
import os
import sqlite3
import sys
from pathlib import Path
from typing import Callable

from .configuration import DeclaredConfiguration
from .contracts import CapabilityEvidence, utc_now


_EXTENSION_MODULES = {
    "r1_2_work_graph": "aitest_runtime.work_graph",
    "r1_3b_execution_resume": "aitest_runtime.execution_resume",
    "r1_3c_provider_binding": "aitest_runtime.provider_binding",
    "r1_3d_opencode_bridge": "aitest_runtime.opencode_bridge",
    "r1_4_tool_execution": "aitest_runtime.tool_execution",
}


def _available(capability_id: str, workspace: Path) -> tuple[bool, dict[str, object]]:
    if capability_id == "python":
        return sys.version_info >= (3, 10), {"version": ".".join(map(str, sys.version_info[:3]))}
    if capability_id == "sqlite":
        return bool(sqlite3.sqlite_version), {"version": sqlite3.sqlite_version}
    if capability_id == "filesystem":
        return workspace.is_dir() and os.access(workspace, os.R_OK), {"workspace": str(workspace), "mode": "READABLE"}
    if capability_id in {"durable-runtime", "command-bus", "event-stream", "event-store", "mission-sequence"}:
        try:
            importlib.import_module("aitest_runtime.durable_core")
            return True, {"provider": "aitest_runtime.durable_core", "shared": True}
        except ImportError:
            return False, {"provider": "aitest_runtime.durable_core", "shared": True}
    module = _EXTENSION_MODULES.get(capability_id)
    if module:
        try:
            importlib.import_module(module)
            return True, {"provider": module, "extension_id": capability_id}
        except ImportError:
            return False, {"provider": module, "extension_id": capability_id}
    return False, {"reason": "UNKNOWN_CAPABILITY"}


def discover_capabilities(
    configuration: DeclaredConfiguration,
    *,
    probe: Callable[[str, Path], tuple[bool, dict[str, object]]] | None = None,
) -> tuple[CapabilityEvidence, ...]:
    workspace = Path(str(configuration.runtime["workspace_root"])).resolve()
    required = set(configuration.capabilities["required"])
    authorized = set(configuration.capabilities["authorized"])
    ids = sorted(required | authorized)
    check = probe or _available
    records = []
    for capability_id in ids:
        available, evidence = check(capability_id, workspace)
        discovered = evidence.get("reason") != "UNKNOWN_CAPABILITY"
        validated = discovered and bool(available)
        records.append(
            CapabilityEvidence(
                capability_id=capability_id,
                discovered=discovered,
                required=capability_id in required,
                validated=validated,
                authorized=capability_id in authorized,
                available=validated and capability_id in authorized,
                evidence={**evidence, "observed_at": utc_now()},
            )
        )
    return tuple(records)
