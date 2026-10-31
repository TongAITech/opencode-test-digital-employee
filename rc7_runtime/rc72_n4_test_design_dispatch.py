"""RC7.2 N4 Test Design dispatch at Requirement x SST granularity.

N4 is deliberately not a ReleaseBatch-sized prompt.  Once N2 and N3 have
formal PASS NodeGates, this bridge materializes one durable TEST_DESIGN WorkItem
for each canonical Requirement x SST pair.  Each WorkItem receives only:

* that Requirement's active N2 candidate artifact; and
* the active N3 code candidate artifacts whose reverse lineage includes that
  Requirement.

This keeps the parent-derived obligation denominator complete without mixing
unrelated SSTs or applications.  It only dispatches design work; it does not
create TestObligations/Cases, launch workers, evaluate design sufficiency, PASS
N4, release N5, or make field/BANK_FINAL claims.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError, Task
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_n4_parent_truth import N4ParentTruthService, install_rc72_n4_parent_inventory_contract
from .rc72_state_machine import RC72StateMachine
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n4_test_design_dispatch"
_EVENT = "RC72_N4_TEST_DESIGN_DISPATCH_UPSERTED"
_BUCKET = "rc72_n4_test_design_dispatches"
_NODE = AutonomousMissionNode.N4_TEST_DESIGN
_NEXT_NODE = AutonomousMissionNode.N5_TEST_DATA
_STAGE = "TEST_DESIGN"
_TASK_TYPE = "RC72_NODE_WORK"
_TEAM_ROLE = "TEST_DESIGN_WORKER"
_SUBSTRATE = "DSH_AGENT_TEAMS"
_WORKER_POLICY = "FRESH_SESSION_REQUIRED"
_STATUS = "READY_FOR_ASSIGNMENT"
_CAPABILITIES = ("test_design", "codegraph")


class N4TestDesignDispatchError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N4TestDesignDispatchError("RC72_N4_DISPATCH_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _string_list(value: Any, name: str, *, allow_empty: bool = True) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError("RC72_N4_DISPATCH_%s_INVALID" % name.upper())
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("RC72_N4_DISPATCH_%s_INVALID" % name.upper())
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError("RC72_N4_DISPATCH_%s_DUPLICATE" % name.upper())
    if not allow_empty and not value:
        raise _contracts.DomainValidationError("RC72_N4_DISPATCH_%s_REQUIRED" % name.upper())
    return list(value)


def validate_rc72_n4_test_design_dispatch(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "dispatch_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "mission_node_id", "node_type", "stage",
        "requirement_id", "sst_id", "workitem_id", "team_role",
        "execution_substrate", "worker_policy", "parent_snapshot_id",
        "source_n2_delivery_id", "source_n2_gate_id", "source_n3_delivery_id",
        "source_n3_gate_id", "status",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["node_type"] != _NODE.value:
        raise _contracts.DomainValidationError("RC72_N4_DISPATCH_NODE_INVALID")
    if out["stage"] != _STAGE:
        raise _contracts.DomainValidationError("RC72_N4_DISPATCH_STAGE_INVALID")
    if out["team_role"] != _TEAM_ROLE:
        raise _contracts.DomainValidationError("RC72_N4_DISPATCH_TEAM_ROLE_INVALID")
    if out["execution_substrate"] != _SUBSTRATE:
        raise _contracts.DomainValidationError("RC72_N4_DISPATCH_SUBSTRATE_INVALID")
    if out["worker_policy"] != _WORKER_POLICY:
        raise _contracts.DomainValidationError("RC72_N4_DISPATCH_WORKER_POLICY_INVALID")
    if out["status"] != _STATUS:
        raise _contracts.DomainValidationError("RC72_N4_DISPATCH_STATUS_INVALID")
    for name in (
        "parent_artifact_refs", "dependency_workitem_refs", "required_capabilities",
        "parent_obligation_source_refs",
    ):
        out[name] = _string_list(out.get(name), name, allow_empty=False)
    for forbidden in (
        "worker_id", "worker_instance_id", "session_id", "dsh_session_id",
        "attempt_id", "execution_attempt_id", "execution_result", "output_refs",
        "delivery_id", "node_gate", "node_pass", "n4_pass", "n5_ready",
        "q7_pass", "field_verified", "bank_final", "test_cases", "obligations",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N4_DISPATCH_EXECUTION_CLAIM_FORBIDDEN:%s" % forbidden
            )
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N4_DISPATCH_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N4_DISPATCH_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n4_test_design_dispatch_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_n4_parent_inventory_contract()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n4_test_design_dispatch
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "dispatch_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "dispatch_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class N4TestDesignDispatchService:
    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n4_test_design_dispatch_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.reader = CandidatePayloadReader()
        self.parent_truth = N4ParentTruthService(truth)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N4TestDesignDispatchError(
                "RC72_N4_DISPATCH_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _artifact_for_requirement(
        self, *, mission_id: str, artifact_refs: Sequence[str], requirement_id: str
    ) -> str:
        matched: List[str] = []
        for artifact_id in artifact_refs:
            row = self._one("rc7_artifact", artifact_id=artifact_id)
            if row.get("artifact_type_name") != "REQUIREMENT_ANALYSIS_OUTPUT":
                continue
            payload = self.reader.load(
                self.truth,
                artifact_id,
                expected_mission_id=mission_id,
            ).semantic_payload
            if payload.get("requirement_id") == requirement_id:
                matched.append(artifact_id)
        if len(matched) != 1:
            raise N4TestDesignDispatchError(
                "RC72_N4_DISPATCH_REQUIREMENT_ARTIFACT_NOT_UNIQUE:%s:%d"
                % (requirement_id, len(matched))
            )
        return matched[0]

    def _dependency_tasks(self, mission_id: str, artifact_refs: Sequence[str]) -> List[str]:
        tasks: List[str] = []
        for artifact_id in artifact_refs:
            artifact = self._one("rc7_artifact", artifact_id=artifact_id)
            if artifact.get("mission_id") != mission_id or artifact.get("state") != "VALID":
                raise N4TestDesignDispatchError(
                    "RC72_N4_DISPATCH_PARENT_ARTIFACT_INVALID:%s" % artifact_id
                )
            producer = _required(artifact.get("producer_task_id"), "producer_task_id")
            task = self._one("rc7_task", task_id=producer)
            if task.get("mission_id") != mission_id or task.get("state") != "PASS":
                raise N4TestDesignDispatchError(
                    "RC72_N4_DISPATCH_PARENT_TASK_NOT_PASS:%s" % producer
                )
            if producer not in tasks:
                tasks.append(producer)
        return tasks

    @staticmethod
    def _workitem_id(
        mission_id: str, release_batch_id: str, requirement_id: str, sst_id: str
    ) -> str:
        return _stable_id(
            "WI-N4-DESIGN", mission_id, release_batch_id, requirement_id, sst_id
        )

    def _dispatch_id(
        self,
        *,
        mission_id: str,
        release_batch_id: str,
        requirement_id: str,
        sst_id: str,
        parent_snapshot_id: str,
    ) -> str:
        return _stable_id(
            "N4DISP-DESIGN",
            mission_id,
            release_batch_id,
            requirement_id,
            sst_id,
            parent_snapshot_id,
            self.source_commit,
        )

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        scalar = (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "mission_node_id", "node_type", "stage", "requirement_id", "sst_id",
            "workitem_id", "team_role", "execution_substrate", "worker_policy",
            "parent_snapshot_id", "source_n2_delivery_id", "source_n2_gate_id",
            "source_n3_delivery_id", "source_n3_gate_id", "status",
        )
        out = {name: payload.get(name) for name in scalar}
        for name in (
            "parent_artifact_refs", "dependency_workitem_refs",
            "required_capabilities", "parent_obligation_source_refs",
        ):
            out[name] = list(payload.get(name) or [])
        return out

    def _expected_rows(self, snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
        mission_id = str(snapshot["mission_id"])
        batch = self._one(
            "rc72_release_batch", release_batch_id=str(snapshot["release_batch_id"])
        )
        release_id = _required(batch.get("release_id"), "release_id")
        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE.value
        )
        source_rows = list(snapshot.get("obligation_sources") or [])
        expected: List[Dict[str, Any]] = []
        n2_refs = [
            artifact_id
            for artifact_id in list(snapshot["parent_artifact_refs"])
            if self._one("rc7_artifact", artifact_id=artifact_id).get("artifact_type_name")
            == "REQUIREMENT_ANALYSIS_OUTPUT"
        ]
        for requirement_id in list(batch.get("requirement_ids") or []):
            sst_ids = list(snapshot["requirement_sst_map"].get(requirement_id) or [])
            if not sst_ids:
                raise N4TestDesignDispatchError(
                    "RC72_N4_DISPATCH_SST_SET_EMPTY:%s" % requirement_id
                )
            requirement_artifact = self._artifact_for_requirement(
                mission_id=mission_id,
                artifact_refs=n2_refs,
                requirement_id=requirement_id,
            )
            code_artifacts = sorted(
                artifact_id
                for artifact_id, requirement_ids in dict(snapshot["code_requirement_map"]).items()
                if requirement_id in list(requirement_ids or [])
            )
            if not code_artifacts:
                raise N4TestDesignDispatchError(
                    "RC72_N4_DISPATCH_CODE_ARTIFACT_REQUIRED:%s" % requirement_id
                )
            parent_artifacts = [requirement_artifact] + code_artifacts
            dependencies = self._dependency_tasks(mission_id, parent_artifacts)
            source_refs = sorted(
                "%s:%s:%s" % (
                    str(row.get("kind")),
                    str(row.get("source_id")),
                    str(row.get("parent_artifact_id")),
                )
                for row in source_rows
                if row.get("parent_artifact_id") in set(parent_artifacts)
            )
            if not source_refs:
                raise N4TestDesignDispatchError(
                    "RC72_N4_DISPATCH_PARENT_DENOMINATOR_EMPTY:%s" % requirement_id
                )
            for sst_id in sst_ids:
                sst_id = _required(sst_id, "sst_id")
                workitem_id = self._workitem_id(
                    mission_id,
                    str(snapshot["release_batch_id"]),
                    requirement_id,
                    sst_id,
                )
                expected.append({
                    "dispatch_id": self._dispatch_id(
                        mission_id=mission_id,
                        release_batch_id=str(snapshot["release_batch_id"]),
                        requirement_id=requirement_id,
                        sst_id=sst_id,
                        parent_snapshot_id=str(snapshot["snapshot_id"]),
                    ),
                    "release_id": release_id,
                    "mission_id": mission_id,
                    "release_batch_id": str(snapshot["release_batch_id"]),
                    "source_commit": self.source_commit,
                    "mission_node_id": str(node["mission_node_id"]),
                    "node_type": _NODE.value,
                    "stage": _STAGE,
                    "requirement_id": requirement_id,
                    "sst_id": sst_id,
                    "workitem_id": workitem_id,
                    "team_role": _TEAM_ROLE,
                    "execution_substrate": _SUBSTRATE,
                    "worker_policy": _WORKER_POLICY,
                    "parent_snapshot_id": str(snapshot["snapshot_id"]),
                    "source_n2_delivery_id": str(snapshot["n2_delivery_id"]),
                    "source_n2_gate_id": str(snapshot["n2_gate_id"]),
                    "source_n3_delivery_id": str(snapshot["n3_delivery_id"]),
                    "source_n3_gate_id": str(snapshot["n3_gate_id"]),
                    "parent_artifact_refs": list(parent_artifacts),
                    "dependency_workitem_refs": list(dependencies),
                    "parent_obligation_source_refs": list(source_refs),
                    "required_capabilities": list(_CAPABILITIES),
                    "status": _STATUS,
                })
        identities = [(row["requirement_id"], row["sst_id"]) for row in expected]
        if not expected or len(identities) != len(set(identities)):
            raise N4TestDesignDispatchError("RC72_N4_DISPATCH_IDENTITY_SET_INVALID")
        return expected

    def dispatch(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        snapshot = self.parent_truth.resolve(release_batch_id=release_batch_id)
        mission_id = str(snapshot["mission_id"])
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        release_id = str(batch["release_id"])
        n4 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE.value
        )
        n5 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
        )
        if n4.get("state") not in {MissionNodeState.READY.value, MissionNodeState.RUNNING.value}:
            raise N4TestDesignDispatchError(
                "RC72_N4_DISPATCH_N4_STATE_INVALID:%s" % str(n4.get("state"))
            )
        if n5.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N4TestDesignDispatchError("RC72_N4_DISPATCH_N5_ALREADY_RELEASED")
        expected_rows = self._expected_rows(snapshot)

        existing = self.truth.query(_ARTIFACT, release_batch_id=release_batch_id)
        if existing:
            if len(existing) != len(expected_rows):
                raise N4TestDesignDispatchError(
                    "RC72_N4_DISPATCH_SET_CONFLICT:%d!=%d"
                    % (len(existing), len(expected_rows))
                )
            by_id = {str(row["dispatch_id"]): row for row in existing}
            for expected in expected_rows:
                current = by_id.get(str(expected["dispatch_id"]))
                if current is None or self._signature(current) != self._signature(expected):
                    raise N4TestDesignDispatchError(
                        "RC72_N4_DISPATCH_SET_IDENTITY_CONFLICT"
                    )
                task = self._one("rc7_task", task_id=str(expected["workitem_id"]))
                if task.get("state") not in {
                    "READY", "LEASED", "RUNNING", "OUTPUT_PRODUCED",
                    "EVALUATING", "PASS", "REPAIR_REQUIRED",
                }:
                    raise N4TestDesignDispatchError(
                        "RC72_N4_DISPATCH_TASK_STATE_INVALID:%s"
                        % str(task.get("state") or "UNKNOWN")
                    )
            if n4.get("state") != MissionNodeState.RUNNING.value:
                raise N4TestDesignDispatchError(
                    "RC72_N4_DISPATCH_RECEIPTS_REQUIRE_RUNNING_NODE"
                )
            return {
                "status": "RESUMED",
                "release_batch_id": release_batch_id,
                "mission_id": mission_id,
                "mission_node_id": str(n4["mission_node_id"]),
                "node_state": MissionNodeState.RUNNING.value,
                "parent_snapshot_id": str(snapshot["snapshot_id"]),
                "dispatch_ids": [row["dispatch_id"] for row in expected_rows],
                "workitem_ids": [row["workitem_id"] for row in expected_rows],
                "design_scopes": [
                    {"requirement_id": row["requirement_id"], "sst_id": row["sst_id"]}
                    for row in expected_rows
                ],
                "execution_substrate": _SUBSTRATE,
                "worker_policy": _WORKER_POLICY,
            }

        if n4.get("state") != MissionNodeState.READY.value:
            raise N4TestDesignDispatchError(
                "RC72_N4_DISPATCH_RUNNING_WITHOUT_RECEIPTS"
            )

        control = ClosedLoopControlPlane(self.truth, release_id, mission_id)
        for expected in expected_rows:
            workitem_id = str(expected["workitem_id"])
            if self.truth.query("rc7_task", task_id=workitem_id):
                raise N4TestDesignDispatchError(
                    "RC72_N4_DISPATCH_WORKITEM_EXISTS_WITHOUT_RECEIPT:%s" % workitem_id
                )
            requirement_id = str(expected["requirement_id"])
            sst_id = str(expected["sst_id"])
            control.register_task(Task(
                task_id=workitem_id,
                mission_id=mission_id,
                node=_STAGE,
                task_type=_TASK_TYPE,
                objective=(
                    "Design the complete evidence-backed TestObligation and TestCase set for "
                    "Requirement %s / SST %s from the exact PASS N2/N3 parent denominator; "
                    "do not shrink scope to happy path or self-authored coverage"
                    % (requirement_id, sst_id)
                ),
                required_capabilities=list(_CAPABILITIES),
                dependency_task_ids=list(expected["dependency_workitem_refs"]),
                input_artifact_refs=list(expected["parent_artifact_refs"]),
                acceptance_criteria=[
                    "every parent-derived obligation source is covered by an obligation or evidence-backed N/A/exclusion",
                    "Requirement and SST identity are explicit on every obligation and executable case",
                    "positive, negative, boundary, state, role/permission, data, change-impact, regression and integration risks are covered where applicable",
                    "L1-L7 applicability is explicit and evidence-backed; non-applicable levels have a concrete reason",
                    "every executable case has preconditions, data requirements, ordered steps, expected results, oracle refs, evidence requirements and code trace",
                    "TBD, guess during execution, find data later, placeholder oracle and evidence-free happy path are forbidden",
                    "unknowns and design gaps remain explicit and prevent PASS",
                ],
                priority=20,
            ))
            task = self._one("rc7_task", task_id=workitem_id)
            if task.get("state") != "READY":
                raise N4TestDesignDispatchError(
                    "RC72_N4_DISPATCH_WORKITEM_NOT_READY:%s:%s"
                    % (workitem_id, str(task.get("state") or "UNKNOWN"))
                )

        RC72StateMachine(self.truth, release_id=release_id).transition_state(
            str(n4["mission_node_id"]),
            MissionNodeState.RUNNING,
            reason="canonical N4 Requirement x SST design WorkItems materialized",
        )
        now = _now()
        for expected in expected_rows:
            payload = dict(expected)
            payload.update({"created_at": now, "updated_at": now, "artifact_version": 1})
            self.truth.append_atomic(_EVENT, payload)
        persisted = self.truth.query(_ARTIFACT, release_batch_id=release_batch_id)
        if len(persisted) != len(expected_rows):
            raise N4TestDesignDispatchError("RC72_N4_DISPATCH_PERSISTENCE_FAILED")
        return {
            "status": "DISPATCHED",
            "release_batch_id": release_batch_id,
            "mission_id": mission_id,
            "mission_node_id": str(n4["mission_node_id"]),
            "node_state": MissionNodeState.RUNNING.value,
            "parent_snapshot_id": str(snapshot["snapshot_id"]),
            "dispatch_ids": [row["dispatch_id"] for row in expected_rows],
            "workitem_ids": [row["workitem_id"] for row in expected_rows],
            "design_scopes": [
                {"requirement_id": row["requirement_id"], "sst_id": row["sst_id"]}
                for row in expected_rows
            ],
            "execution_substrate": _SUBSTRATE,
            "worker_policy": _WORKER_POLICY,
            "team_role": _TEAM_ROLE,
        }


install_rc72_n4_test_design_dispatch_overlay()

__all__ = [
    "N4TestDesignDispatchError",
    "N4TestDesignDispatchService",
    "install_rc72_n4_test_design_dispatch_overlay",
    "validate_rc72_n4_test_design_dispatch",
]
