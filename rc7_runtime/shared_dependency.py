"""Shared dependency/root-cause incident control for RC7.

One AUTH/ENV/DEPENDENCY outage that affects N tests is represented by one
Incident and one recovery Task. Affected Tasks are paused without being marked
as product FAIL and are resumed only after evidence-backed incident resolution.
"""

from __future__ import annotations

import hashlib
import time
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth

from .control_plane import TaskScheduler
from .models import Task, TaskStatus
from .state_machine import transition_task
from .truth_overlay import append_entity, install_rc7_truth_overlay


INCIDENT_EVENT = "RC7_SHARED_INCIDENT_UPSERTED"
INCIDENT_ARTIFACT = "rc7_shared_incident"


class SharedIncidentStatus(str, Enum):
    OPEN = "OPEN"
    RECOVERING = "RECOVERING"
    RESOLVED = "RESOLVED"


@dataclass
class SharedDependencyIncident:
    incident_id: str
    mission_id: str
    category: str
    dependency_key: str
    affected_task_ids: List[str]
    affected_case_refs: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    state: SharedIncidentStatus = SharedIncidentStatus.OPEN
    recovery_task_id: Optional[str] = None
    resolution_evaluation_id: Optional[str] = None
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self) -> None:
        for name in ("incident_id", "mission_id", "category", "dependency_key"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s_REQUIRED" % name.upper())
        if not self.affected_task_ids:
            raise ValueError("INCIDENT_AFFECTED_TASKS_REQUIRED")


def _validate_incident(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = deepcopy(payload)
    for field in ("incident_id", "mission_id", "release_id", "category", "dependency_key", "state"):
        out[field] = _contracts._require_str(out, field)
    out["artifact_version"] = _contracts._artifact_version(out)
    out["artifact_type"] = INCIDENT_ARTIFACT
    for field in ("affected_task_ids", "affected_case_refs", "evidence_refs"):
        _contracts._require_string_list(out, field)
    if not out["affected_task_ids"]:
        raise _contracts.DomainValidationError("INCIDENT_AFFECTED_TASKS_REQUIRED")
    for field in ("recovery_task_id", "resolution_evaluation_id"):
        value = out.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise _contracts.DomainValidationError("INVALID_%s" % field.upper())
    state = out["state"].upper()
    if state in {SharedIncidentStatus.RECOVERING.value, SharedIncidentStatus.RESOLVED.value}:
        if not isinstance(out.get("recovery_task_id"), str) or not out["recovery_task_id"].strip():
            raise _contracts.DomainValidationError("INCIDENT_RECOVERY_TASK_REQUIRED")
    if state == SharedIncidentStatus.RESOLVED.value:
        if not isinstance(out.get("resolution_evaluation_id"), str) or not out["resolution_evaluation_id"].strip():
            raise _contracts.DomainValidationError("INCIDENT_RESOLUTION_EVALUATION_REQUIRED")
        if not out["evidence_refs"]:
            raise _contracts.DomainValidationError("INCIDENT_RESOLUTION_EVIDENCE_REQUIRED")
    return out


def install_shared_incident_overlay() -> None:
    install_rc7_truth_overlay()
    _contracts.VALIDATORS[INCIDENT_ARTIFACT] = _validate_incident
    _truth.EVENT_TYPES[INCIDENT_EVENT] = (INCIDENT_ARTIFACT, "incident_id")
    _truth.BUCKETS[INCIDENT_ARTIFACT] = "rc7_shared_incidents"
    _truth.IDENTITY_FIELDS[INCIDENT_ARTIFACT] = "incident_id"


def _stable_id(mission_id: str, category: str, dependency_key: str) -> str:
    raw = "\x1f".join((mission_id, category, dependency_key)).encode("utf-8")
    return "INCIDENT-%s" % hashlib.sha256(raw).hexdigest()[:20]


def _payload(incident: SharedDependencyIncident, release_id: str, version: int) -> Dict[str, Any]:
    data = asdict(incident)
    data["state"] = incident.state.value
    data["release_id"] = release_id
    data["artifact_version"] = version
    return data


class SharedDependencyManager:
    RECOVERY_CAPABILITIES = {
        "AUTH": ("runtime_recovery", "auth_recovery"),
        "ENVIRONMENT": ("runtime_recovery", "environment_recovery"),
        "DEPENDENCY": ("runtime_recovery", "dependency_recovery"),
        "ROUTE": ("runtime_recovery", "route_recovery"),
        "TOOL": ("runtime_recovery", "tool_recovery"),
    }

    def __init__(self, truth: _truth.TruthRuntime, release_id: str) -> None:
        install_shared_incident_overlay()
        self.truth = truth
        self.release_id = release_id
        self.scheduler = TaskScheduler(truth, release_id)

    def open_or_merge(
        self,
        *,
        mission_id: str,
        category: str,
        dependency_key: str,
        affected_task_ids: Sequence[str],
        affected_case_refs: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
    ) -> SharedDependencyIncident:
        category = category.upper().strip()
        if category not in self.RECOVERY_CAPABILITIES:
            raise RuntimeError("SHARED_INCIDENT_CATEGORY_UNSUPPORTED")
        incident_id = _stable_id(mission_id, category, dependency_key)
        rows = self.truth.query(INCIDENT_ARTIFACT, incident_id=incident_id)
        if rows and rows[0]["state"] == SharedIncidentStatus.RESOLVED.value:
            raise RuntimeError("RESOLVED_INCIDENT_REQUIRES_NEW_DEPENDENCY_EPOCH")

        if rows:
            row = rows[0]
            incident = SharedDependencyIncident(
                incident_id=row["incident_id"],
                mission_id=row["mission_id"],
                category=row["category"],
                dependency_key=row["dependency_key"],
                affected_task_ids=list(row["affected_task_ids"]),
                affected_case_refs=list(row.get("affected_case_refs", [])),
                evidence_refs=list(row.get("evidence_refs", [])),
                state=SharedIncidentStatus(row["state"]),
                recovery_task_id=row.get("recovery_task_id"),
                resolution_evaluation_id=row.get("resolution_evaluation_id"),
                created_at=int(row.get("created_at", 0)),
                updated_at=int(row.get("updated_at", 0)),
            )
            version = int(row["artifact_version"]) + 1
        else:
            incident = SharedDependencyIncident(
                incident_id=incident_id,
                mission_id=mission_id,
                category=category,
                dependency_key=dependency_key,
                affected_task_ids=[],
            )
            version = 1

        for task_id in affected_task_ids:
            if task_id not in incident.affected_task_ids:
                incident.affected_task_ids.append(task_id)
        if not incident.affected_task_ids:
            raise RuntimeError("INCIDENT_AFFECTED_TASKS_REQUIRED")
        for ref in affected_case_refs:
            if ref not in incident.affected_case_refs:
                incident.affected_case_refs.append(ref)
        for ref in evidence_refs:
            if ref not in incident.evidence_refs:
                incident.evidence_refs.append(ref)

        self._pause_tasks(incident.affected_task_ids, mission_id)
        if incident.recovery_task_id is None:
            recovery = Task(
                task_id="TASK-RECOVERY-" + incident.incident_id.split("-", 1)[1],
                mission_id=mission_id,
                node="RUNTIME",
                task_type="SHARED_DEPENDENCY_RECOVERY",
                objective="Recover shared %s dependency %s" % (category, dependency_key),
                required_capabilities=list(self.RECOVERY_CAPABILITIES[category]),
                acceptance_criteria=["shared dependency recovery is independently verified"],
                priority=0,
            )
            self.scheduler.register(recovery)
            incident.recovery_task_id = recovery.task_id
            incident.state = SharedIncidentStatus.RECOVERING
        incident.updated_at = int(time.time())
        self._persist(incident, version)
        self.scheduler.refresh_ready(mission_id)
        return incident

    def resolve(
        self,
        incident_id: str,
        *,
        evaluation_id: str,
        evidence_refs: Sequence[str],
    ) -> SharedDependencyIncident:
        rows = self.truth.query(INCIDENT_ARTIFACT, incident_id=incident_id)
        if not rows:
            raise RuntimeError("SHARED_INCIDENT_NOT_FOUND")
        row = rows[0]
        if row["state"] != SharedIncidentStatus.RECOVERING.value:
            raise RuntimeError("SHARED_INCIDENT_NOT_RECOVERING")
        if not evaluation_id or not evidence_refs:
            raise RuntimeError("SHARED_INCIDENT_RESOLUTION_EVALUATION_AND_EVIDENCE_REQUIRED")
        recovery_rows = self.truth.query("rc7_task", task_id=row["recovery_task_id"])
        if not recovery_rows or recovery_rows[0]["state"] != TaskStatus.PASS.value:
            raise RuntimeError("SHARED_INCIDENT_RECOVERY_TASK_NOT_ACCEPTED")

        incident = SharedDependencyIncident(
            incident_id=row["incident_id"],
            mission_id=row["mission_id"],
            category=row["category"],
            dependency_key=row["dependency_key"],
            affected_task_ids=list(row["affected_task_ids"]),
            affected_case_refs=list(row.get("affected_case_refs", [])),
            evidence_refs=list(dict.fromkeys(list(row.get("evidence_refs", [])) + list(evidence_refs))),
            state=SharedIncidentStatus.RESOLVED,
            recovery_task_id=row["recovery_task_id"],
            resolution_evaluation_id=evaluation_id,
            created_at=int(row.get("created_at", 0)),
            updated_at=int(time.time()),
        )
        self._persist(incident, int(row["artifact_version"]) + 1)
        self._resume_tasks(incident)
        return incident

    def _pause_tasks(self, task_ids: Sequence[str], mission_id: str) -> None:
        for task_id in task_ids:
            rows = self.truth.query("rc7_task", task_id=task_id)
            if not rows:
                raise RuntimeError("AFFECTED_TASK_NOT_FOUND:%s" % task_id)
            row = rows[0]
            if row["mission_id"] != mission_id:
                raise RuntimeError("AFFECTED_TASK_MISSION_MISMATCH")
            task = self.scheduler.task(task_id)
            if task.state in {TaskStatus.READY, TaskStatus.LEASED, TaskStatus.RUNNING}:
                transition_task(task, TaskStatus.BLOCKED)
                append_entity(
                    self.truth,
                    task,
                    release_id=self.release_id,
                    artifact_version=int(row["artifact_version"]) + 1,
                )

    def _resume_tasks(self, incident: SharedDependencyIncident) -> None:
        for task_id in incident.affected_task_ids:
            rows = self.truth.query("rc7_task", task_id=task_id)
            if not rows:
                continue
            row = rows[0]
            if row["state"] != TaskStatus.BLOCKED.value:
                continue
            if self._other_active_incident_affects(task_id, incident.incident_id):
                continue
            task = self.scheduler.task(task_id)
            transition_task(task, TaskStatus.READY)
            append_entity(
                self.truth,
                task,
                release_id=self.release_id,
                artifact_version=int(row["artifact_version"]) + 1,
            )

    def _other_active_incident_affects(self, task_id: str, exclude_incident_id: str) -> bool:
        for row in self.truth.query(INCIDENT_ARTIFACT):
            if row["incident_id"] == exclude_incident_id:
                continue
            if row["state"] != SharedIncidentStatus.RESOLVED.value and task_id in row["affected_task_ids"]:
                return True
        return False

    def _persist(self, incident: SharedDependencyIncident, version: int) -> None:
        receipt = self.truth.append_atomic(
            INCIDENT_EVENT,
            _payload(incident, self.release_id, version),
        )
        if receipt.status != "PERSISTENCE_VERIFIED":
            raise RuntimeError("SHARED_INCIDENT_PERSISTENCE_FAILED")


install_shared_incident_overlay()
