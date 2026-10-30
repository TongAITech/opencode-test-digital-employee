"""RC7.2 N3 CODE_ANALYSIS WorkItem -> fresh AgentTeams assignment.

Assignment adopts accepted source mapping identity (application/target/repository/
revision) as immutable input truth and leases each per-target WorkItem to one
deterministic fresh worker.  It stops before DSH, Git/CodeGraph, Attempt,
output/evaluation, N3 Gate, N4 release, field/Q7/BANK_FINAL truth.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Mapping

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_n3_code_analysis_dispatch import install_rc72_n3_code_analysis_dispatch_overlay
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n3_code_analysis_assignment"
_EVENT = "RC72_N3_CODE_ANALYSIS_ASSIGNMENT_UPSERTED"
_BUCKET = "rc72_n3_code_analysis_assignments"
_NODE_TYPE = AutonomousMissionNode.N3_CODE_ANALYSIS.value
_NEXT_NODE_TYPE = AutonomousMissionNode.N4_TEST_DESIGN.value
_STAGE = "CODE_ANALYSIS"
_TASK_TYPE = "RC72_NODE_WORK"
_TEAM_ROLE = "CODE_ANALYSIS_WORKER"
_AGENT_ID = "code-analysis"
_SUBSTRATE = "DSH_AGENT_TEAMS"
_WORKER_POLICY = "FRESH_SESSION_REQUIRED"
_STATUS = "LEASED_FOR_HANDOFF"
_GENERATION = 1
_CAPABILITIES = ("code_reasoning", "code_reality")


class N3CodeAnalysisAssignmentError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3CodeAnalysisAssignmentError(
            "RC72_N3_CODE_ASSIGNMENT_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _strings(value: Any, name: str, *, required: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_ASSIGNMENT_%s_INVALID" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_ASSIGNMENT_%s_INVALID" % name.upper()
        )
    out = [item.strip() for item in value]
    if len(set(out)) != len(out):
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_ASSIGNMENT_%s_DUPLICATE" % name.upper()
        )
    if required and not out:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_ASSIGNMENT_%s_REQUIRED" % name.upper()
        )
    return out


def validate_rc72_n3_code_analysis_assignment(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "assignment_id", "dispatch_id", "release_id", "mission_id",
        "release_batch_id", "source_commit", "mission_node_id", "node_type",
        "stage", "application_id", "target_id", "repository_ref",
        "source_revision", "source_mapping_task_id", "source_mapping_artifact_id",
        "source_mapping_evaluation_id", "workitem_id", "team_role", "agent_id",
        "execution_substrate", "worker_policy", "worker_instance_id",
        "task_state", "status",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["node_type"] != _NODE_TYPE or out["stage"] != _STAGE:
        raise _contracts.DomainValidationError("RC72_N3_CODE_ASSIGNMENT_NODE_INVALID")
    if out["team_role"] != _TEAM_ROLE or out["agent_id"] != _AGENT_ID:
        raise _contracts.DomainValidationError("RC72_N3_CODE_ASSIGNMENT_ROLE_INVALID")
    if out["execution_substrate"] != _SUBSTRATE or out["worker_policy"] != _WORKER_POLICY:
        raise _contracts.DomainValidationError("RC72_N3_CODE_ASSIGNMENT_SUBSTRATE_INVALID")
    if out["task_state"] != "LEASED" or out["status"] != _STATUS:
        raise _contracts.DomainValidationError("RC72_N3_CODE_ASSIGNMENT_STATE_INVALID")
    if not out["repository_ref"].startswith("git://"):
        raise _contracts.DomainValidationError("RC72_N3_CODE_ASSIGNMENT_REPOSITORY_REF_INVALID")
    generation = out.get("assignment_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation != _GENERATION:
        raise _contracts.DomainValidationError("RC72_N3_CODE_ASSIGNMENT_GENERATION_INVALID")
    out["assignment_generation"] = generation
    mapping_generation = out.get("source_mapping_generation")
    if isinstance(mapping_generation, bool) or not isinstance(mapping_generation, int) or mapping_generation < 1:
        raise _contracts.DomainValidationError("RC72_N3_CODE_ASSIGNMENT_MAPPING_GENERATION_INVALID")
    out["source_mapping_generation"] = mapping_generation
    out["required_capabilities"] = _strings(
        out.get("required_capabilities"), "required_capabilities", required=True
    )
    if tuple(out["required_capabilities"]) != _CAPABILITIES:
        raise _contracts.DomainValidationError("RC72_N3_CODE_ASSIGNMENT_CAPABILITIES_INVALID")
    for name in (
        "input_refs", "source_evidence_refs", "canonical_evidence_ids",
        "source_mapping_evidence_refs",
    ):
        out[name] = _strings(out.get(name), name, required=True)
    recovered = out.get("recovered_orphan_lease", False)
    if not isinstance(recovered, bool):
        raise _contracts.DomainValidationError("RC72_N3_CODE_ASSIGNMENT_RECOVERY_FLAG_INVALID")
    out["recovered_orphan_lease"] = recovered
    for forbidden in (
        "session_id", "dsh_session_id", "lease_id", "attempt_id",
        "git_result", "codegraph_result", "graph_evidence", "changed_files",
        "changed_symbols", "output_refs", "evidence_refs", "evaluation_result",
        "code_analysis_result", "node_delivery_id", "node_gate", "node_pass",
        "n4_started", "q7_pass", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N3_CODE_ASSIGNMENT_EXECUTION_CLAIM_FORBIDDEN:%s" % forbidden
            )
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N3_CODE_ASSIGNMENT_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N3_CODE_ASSIGNMENT_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n3_code_analysis_assignment_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_n3_code_analysis_dispatch_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n3_code_analysis_assignment
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "assignment_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "assignment_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class N3CodeAnalysisAssignmentService:
    """Lease the exact accepted per-target code WorkItem set to fresh workers."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n3_code_analysis_assignment_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")

    @staticmethod
    def _assignment_id(dispatch_id: str, workitem_id: str) -> str:
        raw = "\x1f".join((dispatch_id, workitem_id, "GEN1"))
        return "N3CODEASN-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _worker_id(assignment_id: str) -> str:
        raw = "\x1f".join((assignment_id, "FRESH_CODE_ANALYSIS_WORKER"))
        return "RC72N3CODEFW-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _input_refs(dispatch: Mapping[str, Any]) -> List[str]:
        refs = [
            "application://%s" % str(dispatch["application_id"]),
            "source-target://%s" % str(dispatch["target_id"]),
            str(dispatch["repository_ref"]),
            "git-revision://%s" % str(dispatch["source_revision"]),
            "artifact://%s" % str(dispatch["source_mapping_artifact_id"]),
            "evaluation://%s" % str(dispatch["source_mapping_evaluation_id"]),
        ]
        refs.extend(str(ref) for ref in list(dispatch.get("canonical_evidence_ids") or []))
        return list(dict.fromkeys(refs))

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "dispatch_id", "release_id", "mission_id", "release_batch_id",
            "source_commit", "mission_node_id", "node_type", "stage",
            "application_id", "target_id", "repository_ref", "source_revision",
            "source_mapping_generation", "source_mapping_task_id",
            "source_mapping_artifact_id", "source_mapping_evaluation_id",
            "workitem_id", "team_role", "agent_id", "execution_substrate",
            "worker_policy", "worker_instance_id", "assignment_generation",
            "task_state", "status",
        )
        out = {key: payload.get(key) for key in keys}
        for key in (
            "required_capabilities", "input_refs", "source_evidence_refs",
            "canonical_evidence_ids", "source_mapping_evidence_refs",
        ):
            out[key] = list(payload.get(key) or [])
        return out

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N3CodeAnalysisAssignmentError(
                "RC72_N3_CODE_ASSIGNMENT_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def assign_all(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE_TYPE
        )
        n4 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE_TYPE
        )
        if node.get("state") != MissionNodeState.RUNNING.value:
            raise N3CodeAnalysisAssignmentError("RC72_N3_CODE_ASSIGNMENT_N3_NOT_RUNNING")
        if n4.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N3CodeAnalysisAssignmentError("RC72_N3_CODE_ASSIGNMENT_N4_ALREADY_RELEASED")

        rows = self.truth.query(
            "rc72_n3_code_analysis_dispatch", release_batch_id=release_batch_id
        )
        dispatches = [
            row for row in rows
            if row.get("source_commit") == self.source_commit
            and row.get("node_type") == _NODE_TYPE
            and row.get("stage") == _STAGE
            and row.get("status") == "READY_FOR_ASSIGNMENT"
        ]
        if not dispatches or len(dispatches) != len(rows):
            raise N3CodeAnalysisAssignmentError(
                "RC72_N3_CODE_ASSIGNMENT_EXACT_DISPATCH_SET_REQUIRED"
            )
        identities = [
            (str(row.get("application_id")), str(row.get("target_id")))
            for row in dispatches
        ]
        if len(identities) != len(set(identities)):
            raise N3CodeAnalysisAssignmentError(
                "RC72_N3_CODE_ASSIGNMENT_DISPATCH_TARGET_DUPLICATE"
            )

        plans = []
        for dispatch in sorted(
            dispatches,
            key=lambda row: (str(row["application_id"]), str(row["target_id"])),
        ):
            workitem_id = str(dispatch["workitem_id"])
            task = self._one("rc7_task", task_id=workitem_id)
            if (
                task.get("mission_id") != mission_id
                or task.get("node") != _STAGE
                or task.get("task_type") != _TASK_TYPE
                or list(task.get("required_capabilities") or []) != list(_CAPABILITIES)
                or list(dispatch.get("required_capabilities") or []) != list(_CAPABILITIES)
                or list(task.get("input_artifact_refs") or [])
                != [str(dispatch["source_mapping_artifact_id"])]
                or list(task.get("dependency_task_ids") or [])
                != [str(dispatch["source_mapping_task_id"])]
            ):
                raise N3CodeAnalysisAssignmentError(
                    "RC72_N3_CODE_ASSIGNMENT_WORKITEM_LINEAGE_MISMATCH:%s" % workitem_id
                )
            assignment_id = self._assignment_id(str(dispatch["dispatch_id"]), workitem_id)
            worker_id = self._worker_id(assignment_id)
            expected = {
                "assignment_id": assignment_id,
                "dispatch_id": str(dispatch["dispatch_id"]),
                "release_id": release_id,
                "mission_id": mission_id,
                "release_batch_id": release_batch_id,
                "source_commit": self.source_commit,
                "mission_node_id": str(node["mission_node_id"]),
                "node_type": _NODE_TYPE,
                "stage": _STAGE,
                "application_id": str(dispatch["application_id"]),
                "target_id": str(dispatch["target_id"]),
                "repository_ref": str(dispatch["repository_ref"]),
                "source_revision": str(dispatch["source_revision"]),
                "source_mapping_generation": int(dispatch["source_mapping_generation"]),
                "source_mapping_task_id": str(dispatch["source_mapping_task_id"]),
                "source_mapping_artifact_id": str(dispatch["source_mapping_artifact_id"]),
                "source_mapping_evaluation_id": str(dispatch["source_mapping_evaluation_id"]),
                "workitem_id": workitem_id,
                "team_role": _TEAM_ROLE,
                "agent_id": _AGENT_ID,
                "execution_substrate": _SUBSTRATE,
                "worker_policy": _WORKER_POLICY,
                "worker_instance_id": worker_id,
                "assignment_generation": _GENERATION,
                "required_capabilities": list(_CAPABILITIES),
                "input_refs": self._input_refs(dispatch),
                "source_evidence_refs": list(dispatch["source_evidence_refs"]),
                "canonical_evidence_ids": list(dispatch["canonical_evidence_ids"]),
                "source_mapping_evidence_refs": list(dispatch["source_mapping_evidence_refs"]),
                "task_state": "LEASED",
                "status": _STATUS,
            }
            existing = self.truth.query(_ARTIFACT, assignment_id=assignment_id)
            if len(existing) > 1:
                raise N3CodeAnalysisAssignmentError(
                    "RC72_N3_CODE_ASSIGNMENT_NOT_UNIQUE"
                )
            state = str(task.get("state") or "UNKNOWN")
            lease_owner = task.get("lease_owner")
            if existing:
                if self._signature(existing[0]) != self._signature(expected):
                    raise N3CodeAnalysisAssignmentError(
                        "RC72_N3_CODE_ASSIGNMENT_IDENTITY_CONFLICT"
                    )
                if lease_owner != worker_id:
                    raise N3CodeAnalysisAssignmentError(
                        "RC72_N3_CODE_ASSIGNMENT_RECEIPT_LEASE_MISMATCH"
                    )
                mode = "RESUMED"
            elif state == "LEASED":
                if lease_owner != worker_id:
                    raise N3CodeAnalysisAssignmentError(
                        "RC72_N3_CODE_ASSIGNMENT_COMPETING_LEASE_OWNER:%s" % workitem_id
                    )
                mode = "RECOVER_ORPHAN"
            elif state == "READY" and not lease_owner:
                mode = "NEW"
            else:
                raise N3CodeAnalysisAssignmentError(
                    "RC72_N3_CODE_ASSIGNMENT_WORKITEM_NOT_ASSIGNABLE:%s:%s"
                    % (workitem_id, state)
                )
            plans.append((dispatch, task, expected, mode))

        if all(item[3] == "RESUMED" for item in plans):
            return {
                "status": "RESUMED",
                "release_batch_id": release_batch_id,
                "mission_id": mission_id,
                "assignments": [item[2] for item in plans],
            }
        if any(item[3] == "RESUMED" for item in plans):
            raise N3CodeAnalysisAssignmentError(
                "RC72_N3_CODE_ASSIGNMENT_PARTIAL_RECEIPT_SET"
            )

        control = ClosedLoopControlPlane(self.truth, release_id, mission_id)
        new_ids = {str(item[1]["task_id"]) for item in plans if item[3] == "NEW"}
        ready = list(control.scheduler.ready_tasks(mission_id))
        foreign = [task.task_id for task in ready if task.task_id not in new_ids]
        if foreign:
            raise N3CodeAnalysisAssignmentError(
                "RC72_N3_CODE_ASSIGNMENT_FOREIGN_READY_TASK_CONFLICT:%s"
                % ",".join(sorted(foreign))
            )
        if {task.task_id for task in ready} != new_ids:
            raise N3CodeAnalysisAssignmentError(
                "RC72_N3_CODE_ASSIGNMENT_READY_SET_MISMATCH"
            )
        by_task = {str(item[1]["task_id"]): item for item in plans}
        for task in ready:
            _dispatch, _task, expected, _mode = by_task[task.task_id]
            leased = control.lease_next(
                worker_ref=str(expected["worker_instance_id"]),
                capabilities=list(_CAPABILITIES),
            )
            if leased is None or leased.task_id != task.task_id:
                raise N3CodeAnalysisAssignmentError(
                    "RC72_N3_CODE_ASSIGNMENT_LEASE_IDENTITY_MISMATCH:%s" % task.task_id
                )
        now = _now()
        for _dispatch, _task, expected, mode in plans:
            if mode == "RESUMED":
                continue
            payload = dict(expected)
            payload["recovered_orphan_lease"] = mode == "RECOVER_ORPHAN"
            payload.update({"created_at": now, "updated_at": now, "artifact_version": 1})
            self.truth.append_atomic(_EVENT, payload)
        return {
            "status": "ASSIGNED",
            "release_batch_id": release_batch_id,
            "mission_id": mission_id,
            "assignments": [item[2] for item in plans],
        }


install_rc72_n3_code_analysis_assignment_overlay()
