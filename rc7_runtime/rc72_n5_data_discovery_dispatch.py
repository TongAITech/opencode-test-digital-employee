"""RC7.2 N5 exact data-discovery WorkItem dispatch.

Only N5 DataRequirements whose deterministic resolution plan is
DISCOVERY_REQUIRED are schedulable here.  REUSE_VERIFIED requirements are
already resolved and MUST NOT be sent to an agent merely to repeat work.

Each WorkItem is one canonical DataRequirement, preserving Case/Requirement/SST
lineage and exact N4/N3 parent artifacts.  This slice creates no worker/session,
performs no DB query, constructs no data, creates no DataRef/binding/lease,
passes no N5 gate and never releases N6.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Mapping, Sequence

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError, Task
from .rc72_n5_data_inventory import install_rc72_n5_data_inventory_overlay
from .rc72_n5_data_resolution import install_rc72_n5_data_resolution_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n5_data_discovery_dispatch"
_EVENT = "RC72_N5_DATA_DISCOVERY_DISPATCH_UPSERTED"
_BUCKET = "rc72_n5_data_discovery_dispatches"
_STAGE = "TEST_DATA"
_TASK_TYPE = "RC72_NODE_WORK"
_TEAM_ROLE = "DATA_PREPARER"
_SUBSTRATE = "DSH_AGENT_TEAMS"
_WORKER_POLICY = "FRESH_SESSION_REQUIRED"
_STATUS = "READY_FOR_ASSIGNMENT"
_REQUIRED_CAPABILITIES = ("test_data",)
_INSTALLED = False


class N5DataDiscoveryDispatchError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N5DataDiscoveryDispatchError(
            "RC72_N5_DISCOVERY_DISPATCH_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _string_list(value: Any, name: str, *, allow_empty: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_DISPATCH_%s_INVALID" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_DISPATCH_%s_INVALID" % name.upper()
        )
    if len(value) != len(set(value)):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_DISPATCH_%s_DUPLICATE" % name.upper()
        )
    if not allow_empty and not value:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_DISPATCH_%s_REQUIRED" % name.upper()
        )
    return list(value)


def validate_rc72_n5_data_discovery_dispatch(
    payload: Dict[str, Any]
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "dispatch_id",
        "release_id",
        "mission_id",
        "release_batch_id",
        "source_commit",
        "mission_node_id",
        "data_requirement_id",
        "resolution_plan_id",
        "source_case_sha256",
        "requirement_id",
        "sst_id",
        "obligation_id",
        "case_id",
        "workitem_id",
        "stage",
        "team_role",
        "execution_substrate",
        "worker_policy",
        "status",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["stage"] != _STAGE:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_DISPATCH_STAGE_INVALID"
        )
    if out["team_role"] != _TEAM_ROLE:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_DISPATCH_TEAM_ROLE_INVALID"
        )
    if out["execution_substrate"] != _SUBSTRATE:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_DISPATCH_SUBSTRATE_INVALID"
        )
    if out["worker_policy"] != _WORKER_POLICY:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_DISPATCH_WORKER_POLICY_INVALID"
        )
    if out["status"] != _STATUS:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_DISPATCH_STATUS_INVALID"
        )
    if not out["source_case_sha256"].startswith("sha256:"):
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_DISPATCH_CASE_HASH_INVALID"
        )
    for name in (
        "parent_artifact_refs",
        "dependency_workitem_refs",
        "required_capabilities",
        "case_preconditions",
        "case_code_trace",
    ):
        out[name] = _string_list(out.get(name), name)
    for forbidden in (
        "worker_id",
        "worker_instance_id",
        "session_id",
        "dsh_session_id",
        "attempt_id",
        "data_ref",
        "binding_id",
        "verification",
        "verified",
        "reserved",
        "data_lease_id",
        "execution_result",
        "output_refs",
        "node_pass",
        "n5_pass",
        "n6_ready",
        "field_verified",
        "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N5_DISCOVERY_DISPATCH_EXECUTION_CLAIM_FORBIDDEN:%s"
                % forbidden
            )
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N5_DISCOVERY_DISPATCH_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N5_DISCOVERY_DISPATCH_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n5_data_discovery_dispatch_overlay() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    install_rc7_truth_overlay()
    install_rc72_n5_data_inventory_overlay()
    install_rc72_n5_data_resolution_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n5_data_discovery_dispatch
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "dispatch_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "dispatch_id")
    _INSTALLED = True


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class N5DataDiscoveryDispatchService:
    """Create one small discovery WorkItem for each unresolved DataRequirement."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        source_commit: str,
    ) -> None:
        install_rc72_n5_data_discovery_dispatch_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.source_commit = _required(source_commit, "source_commit")

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N5DataDiscoveryDispatchError(
                "RC72_N5_DISCOVERY_DISPATCH_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    @staticmethod
    def _workitem_id(mission_id: str, data_requirement_id: str) -> str:
        return _stable_id(
            "WI-N5-DATA-DISCOVERY", mission_id, data_requirement_id
        )

    def _dispatch_id(
        self,
        *,
        mission_id: str,
        data_requirement_id: str,
        resolution_plan_id: str,
        source_case_sha256: str,
    ) -> str:
        return _stable_id(
            "N5DISP-DATA",
            mission_id,
            data_requirement_id,
            resolution_plan_id,
            source_case_sha256,
            self.source_commit,
        )

    def _parent_tasks(self, mission_id: str, artifact_refs: Sequence[str]) -> List[str]:
        tasks: List[str] = []
        for artifact_id in artifact_refs:
            artifact = self._one("rc7_artifact", artifact_id=artifact_id)
            if artifact.get("mission_id") != mission_id or artifact.get("state") != "VALID":
                raise N5DataDiscoveryDispatchError(
                    "RC72_N5_DISCOVERY_DISPATCH_PARENT_ARTIFACT_INVALID:%s"
                    % artifact_id
                )
            producer = _required(artifact.get("producer_task_id"), "producer_task_id")
            task = self._one("rc7_task", task_id=producer)
            if task.get("mission_id") != mission_id or task.get("state") != "PASS":
                raise N5DataDiscoveryDispatchError(
                    "RC72_N5_DISCOVERY_DISPATCH_PARENT_TASK_NOT_PASS:%s"
                    % producer
                )
            if producer not in tasks:
                tasks.append(producer)
        return tasks

    def _expected_rows(self, *, release_batch_id: str) -> List[Dict[str, Any]]:
        snapshots = self.truth.query(
            "rc72_n5_data_inventory_snapshot", release_batch_id=release_batch_id
        )
        if len(snapshots) != 1:
            raise N5DataDiscoveryDispatchError(
                "RC72_N5_DISCOVERY_DISPATCH_INVENTORY_REQUIRED"
            )
        snapshot = snapshots[0]
        mission_id = _required(snapshot.get("mission_id"), "mission_id")
        if snapshot.get("release_id") != self.release_id:
            raise N5DataDiscoveryDispatchError(
                "RC72_N5_DISCOVERY_DISPATCH_RELEASE_MISMATCH"
            )
        if snapshot.get("source_commit") != self.source_commit:
            raise N5DataDiscoveryDispatchError(
                "RC72_N5_DISCOVERY_DISPATCH_SOURCE_MISMATCH"
            )
        n5 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type="N5_TEST_DATA"
        )
        n6 = self._one(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type="N6_EXECUTABLE_READINESS",
        )
        if n5.get("state") != "RUNNING":
            raise N5DataDiscoveryDispatchError(
                "RC72_N5_DISCOVERY_DISPATCH_N5_RUNNING_REQUIRED:%s"
                % str(n5.get("state") or "UNKNOWN")
            )
        if n6.get("state") != "NOT_STARTED":
            raise N5DataDiscoveryDispatchError(
                "RC72_N5_DISCOVERY_DISPATCH_N6_MUST_REMAIN_LOCKED"
            )

        requirement_ids = list(snapshot.get("data_requirement_ids") or [])
        if not requirement_ids:
            raise N5DataDiscoveryDispatchError(
                "RC72_N5_DISCOVERY_DISPATCH_REQUIREMENT_SET_EMPTY"
            )
        plans = self.truth.query(
            "rc72_n5_data_resolution_plan", release_batch_id=release_batch_id
        )
        if {str(row.get("data_requirement_id")) for row in plans} != set(
            str(item) for item in requirement_ids
        ):
            raise N5DataDiscoveryDispatchError(
                "RC72_N5_DISCOVERY_DISPATCH_PLAN_DENOMINATOR_MISMATCH"
            )
        expected: List[Dict[str, Any]] = []
        for plan in sorted(plans, key=lambda row: str(row["data_requirement_id"])):
            if plan.get("source_commit") != self.source_commit:
                raise N5DataDiscoveryDispatchError(
                    "RC72_N5_DISCOVERY_DISPATCH_PLAN_SOURCE_MISMATCH"
                )
            status = str(plan.get("status") or "")
            if status == "REUSE_VERIFIED":
                continue
            if status != "DISCOVERY_REQUIRED":
                raise N5DataDiscoveryDispatchError(
                    "RC72_N5_DISCOVERY_DISPATCH_PLAN_STATUS_INVALID:%s" % status
                )
            if plan.get("binding_id") not in (None, "") or plan.get("data_ref") not in (
                None,
                "",
            ):
                raise N5DataDiscoveryDispatchError(
                    "RC72_N5_DISCOVERY_DISPATCH_UNRESOLVED_PLAN_GUESSED_DATA_REF"
                )
            data_requirement_id = _required(
                plan.get("data_requirement_id"), "data_requirement_id"
            )
            requirement = self._one(
                "rc72_n5_data_requirement", data_requirement_id=data_requirement_id
            )
            if (
                requirement.get("mission_id") != mission_id
                or requirement.get("release_id") != self.release_id
                or requirement.get("release_batch_id") != release_batch_id
                or requirement.get("source_commit") != self.source_commit
                or requirement.get("source_case_sha256")
                != plan.get("source_case_sha256")
                or requirement.get("status") != "UNRESOLVED"
            ):
                raise N5DataDiscoveryDispatchError(
                    "RC72_N5_DISCOVERY_DISPATCH_REQUIREMENT_LINEAGE_INVALID:%s"
                    % data_requirement_id
                )
            n4_artifact_id = _required(
                requirement.get("source_n4_artifact_id"), "source_n4_artifact_id"
            )
            n3_artifact_refs = list(requirement.get("source_n3_artifact_refs") or [])
            parent_artifacts = [n4_artifact_id] + [
                str(ref) for ref in n3_artifact_refs if str(ref) != n4_artifact_id
            ]
            if not n3_artifact_refs:
                raise N5DataDiscoveryDispatchError(
                    "RC72_N5_DISCOVERY_DISPATCH_N3_PARENT_REQUIRED:%s"
                    % data_requirement_id
                )
            dependency_tasks = self._parent_tasks(mission_id, parent_artifacts)
            workitem_id = self._workitem_id(mission_id, data_requirement_id)
            expected.append(
                {
                    "dispatch_id": self._dispatch_id(
                        mission_id=mission_id,
                        data_requirement_id=data_requirement_id,
                        resolution_plan_id=str(plan["plan_id"]),
                        source_case_sha256=str(requirement["source_case_sha256"]),
                    ),
                    "release_id": self.release_id,
                    "mission_id": mission_id,
                    "release_batch_id": release_batch_id,
                    "source_commit": self.source_commit,
                    "mission_node_id": str(n5["mission_node_id"]),
                    "data_requirement_id": data_requirement_id,
                    "resolution_plan_id": str(plan["plan_id"]),
                    "source_case_sha256": str(requirement["source_case_sha256"]),
                    "requirement_id": str(requirement["requirement_id"]),
                    "sst_id": str(requirement["sst_id"]),
                    "obligation_id": str(requirement["obligation_id"]),
                    "case_id": str(requirement["case_id"]),
                    "workitem_id": workitem_id,
                    "stage": _STAGE,
                    "team_role": _TEAM_ROLE,
                    "execution_substrate": _SUBSTRATE,
                    "worker_policy": _WORKER_POLICY,
                    "parent_artifact_refs": parent_artifacts,
                    "dependency_workitem_refs": dependency_tasks,
                    "required_capabilities": list(_REQUIRED_CAPABILITIES),
                    "case_preconditions": list(
                        requirement.get("case_preconditions") or []
                    ),
                    "case_code_trace": list(requirement.get("case_code_trace") or []),
                    "status": _STATUS,
                }
            )
        ids = [str(row["data_requirement_id"]) for row in expected]
        if len(ids) != len(set(ids)):
            raise N5DataDiscoveryDispatchError(
                "RC72_N5_DISCOVERY_DISPATCH_IDENTITY_SET_INVALID"
            )
        return expected

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        scalar = (
            "release_id",
            "mission_id",
            "release_batch_id",
            "source_commit",
            "mission_node_id",
            "data_requirement_id",
            "resolution_plan_id",
            "source_case_sha256",
            "requirement_id",
            "sst_id",
            "obligation_id",
            "case_id",
            "workitem_id",
            "stage",
            "team_role",
            "execution_substrate",
            "worker_policy",
            "status",
        )
        out = {name: payload.get(name) for name in scalar}
        for name in (
            "parent_artifact_refs",
            "dependency_workitem_refs",
            "required_capabilities",
            "case_preconditions",
            "case_code_trace",
        ):
            out[name] = list(payload.get(name) or [])
        return out

    def dispatch(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        expected_rows = self._expected_rows(release_batch_id=release_batch_id)
        snapshots = self.truth.query(
            "rc72_n5_data_inventory_snapshot", release_batch_id=release_batch_id
        )
        snapshot = snapshots[0]
        mission_id = str(snapshot["mission_id"])
        n5 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type="N5_TEST_DATA"
        )
        n6 = self._one(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type="N6_EXECUTABLE_READINESS",
        )
        existing = self.truth.query(_ARTIFACT, release_batch_id=release_batch_id)
        if existing:
            if len(existing) != len(expected_rows):
                raise N5DataDiscoveryDispatchError(
                    "RC72_N5_DISCOVERY_DISPATCH_EXISTING_SET_INCOMPLETE"
                )
            by_id = {str(row["dispatch_id"]): row for row in existing}
            for expected in expected_rows:
                current = by_id.get(str(expected["dispatch_id"]))
                if current is None or self._signature(current) != self._signature(expected):
                    raise N5DataDiscoveryDispatchError(
                        "RC72_N5_DISCOVERY_DISPATCH_SET_IDENTITY_CONFLICT"
                    )
                task = self._one("rc7_task", task_id=str(expected["workitem_id"]))
                if task.get("state") not in {
                    "READY",
                    "LEASED",
                    "RUNNING",
                    "OUTPUT_PRODUCED",
                    "EVALUATING",
                    "PASS",
                    "REPAIR_REQUIRED",
                }:
                    raise N5DataDiscoveryDispatchError(
                        "RC72_N5_DISCOVERY_DISPATCH_TASK_STATE_INVALID:%s"
                        % str(task.get("state") or "UNKNOWN")
                    )
            if n5.get("state") != "RUNNING" or n6.get("state") != "NOT_STARTED":
                raise N5DataDiscoveryDispatchError(
                    "RC72_N5_DISCOVERY_DISPATCH_REPLAY_NODE_STATE_INVALID"
                )
            return {
                "status": "RESUMED",
                "release_batch_id": release_batch_id,
                "mission_id": mission_id,
                "dispatch_count": len(expected_rows),
                "dispatch_ids": [row["dispatch_id"] for row in expected_rows],
                "workitem_ids": [row["workitem_id"] for row in expected_rows],
                "data_requirement_ids": [
                    row["data_requirement_id"] for row in expected_rows
                ],
                "n5_state": "RUNNING",
                "n6_state": "NOT_STARTED",
            }

        # Zero discovery work is valid only when every DataRequirement already
        # has an exact verified binding.  No dummy worker is created.
        if not expected_rows:
            if n5.get("state") != "RUNNING" or n6.get("state") != "NOT_STARTED":
                raise N5DataDiscoveryDispatchError(
                    "RC72_N5_DISCOVERY_DISPATCH_NOOP_NODE_STATE_INVALID"
                )
            return {
                "status": "NO_DISCOVERY_REQUIRED",
                "release_batch_id": release_batch_id,
                "mission_id": mission_id,
                "dispatch_count": 0,
                "dispatch_ids": [],
                "workitem_ids": [],
                "data_requirement_ids": [],
                "n5_state": "RUNNING",
                "n6_state": "NOT_STARTED",
            }

        control = ClosedLoopControlPlane(self.truth, self.release_id, mission_id)
        for expected in expected_rows:
            workitem_id = str(expected["workitem_id"])
            if self.truth.query("rc7_task", task_id=workitem_id):
                raise N5DataDiscoveryDispatchError(
                    "RC72_N5_DISCOVERY_DISPATCH_WORKITEM_EXISTS_WITHOUT_RECEIPT:%s"
                    % workitem_id
                )
            data_requirement_id = str(expected["data_requirement_id"])
            requirement = self._one(
                "rc72_n5_data_requirement", data_requirement_id=data_requirement_id
            )
            control.register_task(
                Task(
                    task_id=workitem_id,
                    mission_id=mission_id,
                    node=_STAGE,
                    task_type=_TASK_TYPE,
                    objective=(
                        "Discover an existing test DataRef that exactly satisfies DataRequirement %s "
                        "for Requirement %s / SST %s / Case %s. Use deterministic registered data/DB "
                        "tools first; do not invent, guess, substitute, reserve, mutate, or claim verification "
                        "without canonical evidence. If no exact data is proven, return an explicit not-found "
                        "result for later construction routing."
                        % (
                            data_requirement_id,
                            expected["requirement_id"],
                            expected["sst_id"],
                            expected["case_id"],
                        )
                    ),
                    required_capabilities=list(_REQUIRED_CAPABILITIES),
                    dependency_task_ids=list(expected["dependency_workitem_refs"]),
                    input_artifact_refs=list(expected["parent_artifact_refs"]),
                    acceptance_criteria=[
                        "the exact DataRequirement id and source Case SHA-256 are preserved",
                        "Requirement/SST/Obligation/Case lineage is unchanged",
                        "registered deterministic data/DB lookup is used before model reasoning where available",
                        "a found candidate has an exact DataRef and evidence proving all Case preconditions",
                        "verification evidence is canonical R1 evidence, not worker prose",
                        "no exact match produces explicit NOT_FOUND; arbitrary nearest-match substitution is forbidden",
                        "data mutation, reservation, cleanup execution and N5 PASS are outside this WorkItem",
                    ],
                    priority=25,
                )
            )
            task = self._one("rc7_task", task_id=workitem_id)
            if task.get("state") != "READY":
                raise N5DataDiscoveryDispatchError(
                    "RC72_N5_DISCOVERY_DISPATCH_WORKITEM_NOT_READY:%s:%s"
                    % (workitem_id, str(task.get("state") or "UNKNOWN"))
                )
            if requirement.get("source_case_sha256") != expected["source_case_sha256"]:
                raise N5DataDiscoveryDispatchError(
                    "RC72_N5_DISCOVERY_DISPATCH_CASE_CHANGED_DURING_DISPATCH"
                )

        now = _now()
        for expected in expected_rows:
            payload = dict(expected)
            payload.update(
                {"created_at": now, "updated_at": now, "artifact_version": 1}
            )
            self.truth.append_atomic(_EVENT, payload)
        persisted = self.truth.query(_ARTIFACT, release_batch_id=release_batch_id)
        if len(persisted) != len(expected_rows):
            raise N5DataDiscoveryDispatchError(
                "RC72_N5_DISCOVERY_DISPATCH_PERSISTENCE_FAILED"
            )
        current_n6 = self._one(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type="N6_EXECUTABLE_READINESS",
        )
        if current_n6.get("state") != "NOT_STARTED":
            raise N5DataDiscoveryDispatchError(
                "RC72_N5_DISCOVERY_DISPATCH_RELEASED_N6"
            )
        return {
            "status": "DISPATCHED",
            "release_batch_id": release_batch_id,
            "mission_id": mission_id,
            "dispatch_count": len(expected_rows),
            "dispatch_ids": [row["dispatch_id"] for row in expected_rows],
            "workitem_ids": [row["workitem_id"] for row in expected_rows],
            "data_requirement_ids": [
                row["data_requirement_id"] for row in expected_rows
            ],
            "team_role": _TEAM_ROLE,
            "execution_substrate": _SUBSTRATE,
            "worker_policy": _WORKER_POLICY,
            "n5_state": "RUNNING",
            "n6_state": "NOT_STARTED",
        }


install_rc72_n5_data_discovery_dispatch_overlay()

__all__ = [
    "N5DataDiscoveryDispatchError",
    "N5DataDiscoveryDispatchService",
    "install_rc72_n5_data_discovery_dispatch_overlay",
    "validate_rc72_n5_data_discovery_dispatch",
]
