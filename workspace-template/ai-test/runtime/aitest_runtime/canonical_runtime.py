"""Canonical R1-R4 product runtime composition.

This module is the single construction point for the durable AI Test runtime.
It intentionally owns no PFC-specific business rules.  PFC/KYB/etc. are
profiles/adapters that bind facts and capabilities to this runtime.

Runtime truth invariant:
    <canonical durable root>/state/runtime-spine.db is the sole durable runtime truth.
    Product code must resolve that authority explicitly or from the installation pointer;
    it must never synthesize a workspace-local Event Stream fallback.

The legacy ai-test/state/aitest.db may remain on disk only as a migration or
reference source while older assets are reconciled.  Product runtime code must
not write Mission/Plan/Task/Attempt/Session/HumanGate/Evidence/Defect truth to
that legacy store.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

from .durable_core import ExtensionManifest, RuntimeService
from .execution_resume.extension import execution_resume_extension
from .opencode_bridge.extension import opencode_bridge_extension
from .provider_binding.extension import provider_binding_extension
from .g2_1.extension import g2_1_extension
from .g3.extension import g3_extension
from .g4.extension import g4_extension
from .r2_5.extension import r2_5_extension
from .r2_6.extension import r2_6_extension
from .r3_1.extension import r3_1_extension
from .r3_2.extension import r3_2_extension
from .r3_3.extension import r3_3_extension
from .r3_4.extension import r3_4_extension
from .r3_5.extension import r3_5_extension
from .r3_6.extension import r3_6_extension
from .r3_7.extension import r3_7_extension
from .r3_e1.extension import r3_e1_extension
from .r3_e2.extension import r3_e2_extension
from .r4_1.extension import r4_1_extension
from .r4_2.extension import r4_2_extension
from .r4_3.extension import r4_3_extension
from .r4_4.extension import r4_4_extension
from .r4_5.extension import r4_5_extension
from .r4_6.extension import r4_6_extension
from .r4_7.extension import r4_7_extension
from .r4_8.extension import r4_8_extension
from .tool_execution.extension import tool_execution_extension
from .work_graph.extension import work_graph_extension


CANONICAL_RUNTIME_SCHEMA = "aitest.r1-r4.canonical-runtime.v1"
CANONICAL_DB_RELATIVE_PATH = Path("state/runtime-spine.db")
LEGACY_DB_RELATIVE_PATH = Path("ai-test/state/aitest.db")
LEGACY_STORE_MODE = "MIGRATION_REFERENCE_ONLY"


def canonical_extension_manifests() -> tuple[ExtensionManifest, ...]:
    """Return the complete additive R1-R4 plus G3 event-stream extension set.

    R2.1-R2.4 and R2.7 are orchestration/query services rather than durable
    extensions, and R3.E3 is a controlled browser runtime boundary.  Their
    durable dependencies are represented by the extensions below.
    """
    return (
        work_graph_extension(),
        execution_resume_extension(),
        provider_binding_extension(),
        opencode_bridge_extension(),
        tool_execution_extension(),
        r2_5_extension(),
        r2_6_extension(),
        g2_1_extension(),
        g3_extension(),
        g4_extension(),
        r3_1_extension(),
        r3_2_extension(),
        r3_3_extension(),
        r3_4_extension(),
        r3_5_extension(),
        r3_6_extension(),
        r3_7_extension(),
        r3_e1_extension(),
        r3_e2_extension(),
        r4_1_extension(),
        r4_2_extension(),
        r4_3_extension(),
        r4_4_extension(),
        r4_5_extension(),
        r4_6_extension(),
        r4_7_extension(),
        r4_8_extension(),
    )


def _installation_pointer_candidates(workspace_root: str | Path) -> tuple[Path, ...]:
    workspace = Path(workspace_root).expanduser().resolve()
    values: list[Path] = []
    configured_control = os.environ.get("PFC_CONTROL_ROOT")
    if configured_control:
        values.append(Path(configured_control).expanduser().resolve() / "current.json")
    configured_project = os.environ.get("PFC_REPO_ROOT")
    if configured_project:
        values.append(Path(configured_project).expanduser().resolve() / ".pfc-r1r4" / "current.json")
    for parent in (workspace, *workspace.parents):
        values.append(parent / ".pfc-r1r4" / "current.json")
    dedup: list[Path] = []
    seen: set[str] = set()
    for item in values:
        key = str(item)
        if key not in seen:
            seen.add(key)
            dedup.append(item)
    return tuple(dedup)


def _db_from_installation_pointer(workspace_root: str | Path) -> Path | None:
    workspace = Path(workspace_root).expanduser().resolve()
    for pointer in _installation_pointer_candidates(workspace):
        if not pointer.is_file():
            continue
        try:
            payload = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"CANONICAL_RUNTIME_POINTER_INVALID: {pointer}: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise RuntimeError(f"CANONICAL_RUNTIME_POINTER_INVALID: {pointer}: root must be object")
        durable_root = payload.get("durable_root")
        active_workspace = payload.get("active_workspace")
        if not isinstance(durable_root, str) or not durable_root.strip():
            raise RuntimeError(f"CANONICAL_RUNTIME_POINTER_MISSING_DURABLE_ROOT: {pointer}")
        if isinstance(active_workspace, str) and active_workspace.strip():
            active = Path(active_workspace).expanduser().resolve()
            if active != workspace:
                # A pointer for another release/workspace is not authority for this process.
                continue
        return Path(durable_root).expanduser().resolve() / "state" / "runtime-spine.db"
    return None


def canonical_db_path(workspace_root: str | Path) -> Path:
    """Resolve the sole physical R1 Event Stream authority.

    Product runtime must never silently create a second workspace-local spine.
    Tests and migration tools may pass ``db_path`` explicitly to
    ``create_canonical_runtime``.
    """
    configured = os.environ.get("AITEST_RUNTIME_SPINE_DB")
    from_pointer = _db_from_installation_pointer(workspace_root)
    if configured:
        explicit = Path(configured).expanduser().resolve()
        if from_pointer is not None and explicit != from_pointer:
            raise RuntimeError(
                f"CANONICAL_RUNTIME_AUTHORITY_CONFLICT: env={explicit} pointer={from_pointer}"
            )
        return explicit
    if from_pointer is not None:
        return from_pointer
    raise RuntimeError(
        "CANONICAL_RUNTIME_AUTHORITY_UNRESOLVED: set AITEST_RUNTIME_SPINE_DB or provide a valid .pfc-r1r4/current.json"
    )


def legacy_db_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root).resolve() / LEGACY_DB_RELATIVE_PATH


def create_canonical_runtime(
    workspace_root: str | Path,
    *,
    db_path: str | Path | None = None,
    clock: Any = None,
    failure_injector: Any = None,
    extensions: Iterable[ExtensionManifest] | None = None,
) -> RuntimeService:
    path = Path(db_path).resolve() if db_path is not None else canonical_db_path(workspace_root)
    manifests = tuple(extensions) if extensions is not None else canonical_extension_manifests()
    return RuntimeService(path, clock=clock, failure_injector=failure_injector, extensions=manifests)


def extension_inventory(runtime: RuntimeService) -> list[dict[str, str]]:
    return [
        {"extension_id": item.extension_id, "extension_version": item.extension_version}
        for item in runtime.extension_registry.manifests
    ]


def _projection_rows(runtime: RuntimeService) -> list[dict[str, Any]]:
    """Read canonical projections only; never scan the legacy store."""
    conn = sqlite3.connect(str(runtime.db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT mission_id, seq, state_json, state_hash FROM mission_projection ORDER BY seq DESC, mission_id"
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                state = json.loads(row["state_json"])
            except (TypeError, json.JSONDecodeError):
                state = {}
            result.append(
                {
                    "mission_id": row["mission_id"],
                    "seq": int(row["seq"]),
                    "state_hash": row["state_hash"],
                    "state": state,
                }
            )
        return result
    finally:
        conn.close()


def runtime_status(workspace_root: str | Path) -> dict[str, Any]:
    workspace = Path(workspace_root).resolve()
    runtime = create_canonical_runtime(workspace)
    missions = _projection_rows(runtime)
    return {
        "schema_version": CANONICAL_RUNTIME_SCHEMA,
        "status": "PASS",
        "truth_source": "R1_EVENT_STREAM",
        "conversation_is_not_truth": True,
        "runtime_db": str(runtime.db_path),
        "runtime_db_relative": CANONICAL_DB_RELATIVE_PATH.as_posix(),
        "legacy_store": {
            "path": str(legacy_db_path(workspace)),
            "mode": LEGACY_STORE_MODE,
            "product_runtime_writes_allowed": False,
        },
        "extension_count": len(runtime.extension_registry.manifests),
        "extensions": extension_inventory(runtime),
        "mission_count": len(missions),
        "missions": missions,
    }


def execute_core_command(
    runtime: RuntimeService,
    *,
    command_type: str,
    mission_id: str,
    payload: Mapping[str, Any] | None = None,
    actor_type: str = "SYSTEM",
    actor_id: str = "aitest-product-runtime",
    session_id: str | None = None,
    command_id: str | None = None,
) -> dict[str, Any]:
    seq = runtime.get_head_seq(mission_id)
    command_id = command_id or f"product:{command_type.lower()}:{uuid.uuid4()}"
    result = runtime.execute(
        {
            "command_id": command_id,
            "type": command_type,
            "mission_id": mission_id,
            "session_id": session_id,
            "expected_seq": seq,
            "actor": {"type": actor_type, "id": actor_id},
            "payload": dict(payload or {}),
            "idempotency_key": command_id,
            "correlation_id": command_id,
        }
    )
    value = result.to_dict()
    if not result.ok:
        raise RuntimeError(f"canonical command rejected: {value}")
    return value


def bootstrap_mission(
    workspace_root: str | Path,
    *,
    mission_id: str,
    goal_id: str,
    goal: Mapping[str, Any],
    attributes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Small canonical bootstrap used by product intake and convergence tests.

    Autonomous task planning is deliberately not performed here.  G2 owns the
    Planner/Session orchestration that creates PlanRevision/Task truth.
    """
    runtime = create_canonical_runtime(workspace_root)
    state = runtime.replay(mission_id)
    if state.mission is None:
        execute_core_command(
            runtime,
            command_type="CREATE_MISSION",
            mission_id=mission_id,
            payload=dict(attributes or {}),
        )
        execute_core_command(
            runtime,
            command_type="CREATE_GOAL",
            mission_id=mission_id,
            payload={"goal_id": goal_id, "goal": dict(goal)},
        )
        execute_core_command(runtime, command_type="ACTIVATE_MISSION", mission_id=mission_id)
    composed = runtime.replay_composed(mission_id)
    return {
        "status": "PASS",
        "truth_source": "R1_EVENT_STREAM",
        "mission": composed.core_state.to_dict(),
        "head_seq": runtime.get_head_seq(mission_id),
        "extension_count": len(runtime.extension_registry.manifests),
    }
