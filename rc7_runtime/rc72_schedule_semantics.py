"""RC7.2 explicit WorkItem scheduling semantics backed by canonical R1.

Cost-window scheduling may optimize WHEN semantic work runs, but it must never
invent criticality or cost from Task IDs, node names, objectives, prompts, roles
or other strings.  This module therefore stores only explicit scheduling
semantics.  Missing truth resolves conservatively to UNKNOWN/UNKNOWN and RUN_NOW
through the existing mission-first selector.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Mapping, Optional

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError, Task
from .rc72_context_economy import ExecutionMode, SemanticWorkDescriptor
from .rc72_model_economy import MissionCriticality, SemanticCostClass
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT_TYPE = "rc72_work_schedule_semantics"
_EVENT_TYPE = "RC72_WORK_SCHEDULE_SEMANTICS_UPSERTED"
_BUCKET = "rc72_work_schedule_semantics"


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("SCHEDULE_SEMANTICS_%s_REQUIRED" % name.upper())
    return value.strip()


def _enum_value(value: Any, enum_type: Any, name: str) -> str:
    raw = value.value if isinstance(value, enum_type) else str(value or "").strip().upper()
    try:
        return enum_type(raw).value
    except ValueError as exc:
        raise ContractError("SCHEDULE_SEMANTICS_%s_INVALID" % name.upper()) from exc


def validate_rc72_work_schedule_semantics(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "schedule_semantics_id", "release_id", "mission_id", "workitem_id", "source_ref",
    ):
        out[name] = _contracts._require_str(out, name)
    for name, enum_type in (
        ("execution_mode", ExecutionMode),
        ("mission_criticality", MissionCriticality),
        ("semantic_cost_class", SemanticCostClass),
    ):
        raw = _contracts._require_str(out, name).upper()
        try:
            out[name] = enum_type(raw).value
        except ValueError as exc:
            raise _contracts.DomainValidationError(
                "SCHEDULE_SEMANTICS_%s_INVALID" % name.upper()
            ) from exc
    recorded_at = out.get("recorded_at")
    if isinstance(recorded_at, bool) or not isinstance(recorded_at, int) or recorded_at < 0:
        raise _contracts.DomainValidationError("SCHEDULE_SEMANTICS_RECORDED_AT_INVALID")
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("SCHEDULE_SEMANTICS_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT_TYPE
    return out


def install_rc72_schedule_semantics_overlay() -> None:
    install_rc7_truth_overlay()
    _contracts.VALIDATORS[_ARTIFACT_TYPE] = validate_rc72_work_schedule_semantics
    _truth.BUCKETS[_ARTIFACT_TYPE] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT_TYPE] = "schedule_semantics_id"
    _truth.EVENT_TYPES[_EVENT_TYPE] = (_ARTIFACT_TYPE, "schedule_semantics_id")


def _ensure_projection_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT_TYPE, {})


def _semantics_id(release_id: str, mission_id: str, workitem_id: str) -> str:
    digest = hashlib.sha256(
        "\x1f".join((release_id, mission_id, workitem_id)).encode("utf-8")
    ).hexdigest()[:24]
    return "SCHEDSEM-" + digest


class WorkScheduleSemanticsService:
    """Persist and resolve explicit WorkItem scheduling semantics.

    Absence is not an error and never triggers heuristics. It produces a
    SemanticWorkDescriptor with UNKNOWN criticality/cost, which the scheduler
    executes immediately rather than risking an unjustified delay.
    """

    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_schedule_semantics_overlay()
        _ensure_projection_bucket(truth)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")

    def _task_row(self, task_id: str) -> Mapping[str, Any]:
        rows = self.truth.query("rc7_task", task_id=task_id)
        if len(rows) != 1:
            raise ContractError("SCHEDULE_SEMANTICS_TASK_NOT_UNIQUE:%d" % len(rows))
        row = rows[0]
        if row.get("release_id") != self.release_id:
            raise ContractError("SCHEDULE_SEMANTICS_TASK_RELEASE_MISMATCH")
        return row

    def record(
        self,
        *,
        mission_id: str,
        workitem_id: str,
        execution_mode: Any,
        mission_criticality: Any,
        semantic_cost_class: Any,
        source_ref: str,
    ) -> Dict[str, Any]:
        mission_id = _required(mission_id, "mission_id")
        workitem_id = _required(workitem_id, "workitem_id")
        source_ref = _required(source_ref, "source_ref")
        row = self._task_row(workitem_id)
        if row.get("mission_id") != mission_id:
            raise ContractError("SCHEDULE_SEMANTICS_TASK_MISSION_MISMATCH")
        payload: Dict[str, Any] = {
            "schedule_semantics_id": _semantics_id(self.release_id, mission_id, workitem_id),
            "release_id": self.release_id,
            "mission_id": mission_id,
            "workitem_id": workitem_id,
            "execution_mode": _enum_value(execution_mode, ExecutionMode, "execution_mode"),
            "mission_criticality": _enum_value(
                mission_criticality, MissionCriticality, "mission_criticality"
            ),
            "semantic_cost_class": _enum_value(
                semantic_cost_class, SemanticCostClass, "semantic_cost_class"
            ),
            "source_ref": source_ref,
            "recorded_at": _now(),
        }
        existing = self.truth.query(
            _ARTIFACT_TYPE, schedule_semantics_id=payload["schedule_semantics_id"]
        )
        if len(existing) > 1:
            raise ContractError("SCHEDULE_SEMANTICS_TRUTH_NOT_UNIQUE")
        if existing:
            previous = existing[0]
            semantic_fields = (
                "mission_id", "workitem_id", "execution_mode", "mission_criticality",
                "semantic_cost_class", "source_ref",
            )
            if all(previous.get(name) == payload.get(name) for name in semantic_fields):
                return previous
            payload["artifact_version"] = int(previous.get("artifact_version", 1)) + 1
        else:
            payload["artifact_version"] = 1
        self.truth.append_atomic(_EVENT_TYPE, payload)
        rows = self.truth.query(
            _ARTIFACT_TYPE, schedule_semantics_id=payload["schedule_semantics_id"]
        )
        if len(rows) != 1:
            raise ContractError("SCHEDULE_SEMANTICS_PERSISTENCE_FAILED")
        return rows[0]

    def resolve(self, task: Task) -> SemanticWorkDescriptor:
        if not isinstance(task, Task):
            raise ContractError("SCHEDULE_SEMANTICS_TASK_REQUIRED")
        rows = self.truth.query(_ARTIFACT_TYPE, workitem_id=task.task_id)
        if not rows:
            return SemanticWorkDescriptor.from_task(
                task,
                execution_mode=ExecutionMode.SEMANTIC,
                mission_criticality=MissionCriticality.UNKNOWN,
                semantic_cost_class=SemanticCostClass.UNKNOWN,
            )
        if len(rows) != 1:
            raise ContractError("SCHEDULE_SEMANTICS_TRUTH_NOT_UNIQUE")
        row = rows[0]
        if row.get("release_id") != self.release_id:
            raise ContractError("SCHEDULE_SEMANTICS_RELEASE_MISMATCH")
        if row.get("mission_id") != task.mission_id:
            raise ContractError("SCHEDULE_SEMANTICS_MISSION_MISMATCH")
        if row.get("workitem_id") != task.task_id:
            raise ContractError("SCHEDULE_SEMANTICS_WORKITEM_MISMATCH")
        return SemanticWorkDescriptor.from_task(
            task,
            execution_mode=ExecutionMode(str(row["execution_mode"])),
            mission_criticality=MissionCriticality(str(row["mission_criticality"])),
            semantic_cost_class=SemanticCostClass(str(row["semantic_cost_class"])),
        )


class CanonicalScheduleDescriptorResolver:
    """Callable adapter used by the economy scheduler."""

    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        self.service = WorkScheduleSemanticsService(truth, release_id=release_id)

    def __call__(self, task: Task) -> SemanticWorkDescriptor:
        return self.service.resolve(task)
