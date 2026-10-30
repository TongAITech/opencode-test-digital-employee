"""RC7.2 governed MissionNode -> durable WorkItem dispatch bridge.

This is the first autonomous-dispatch slice after governed Field Mission
bootstrap. It does not launch a worker. It binds canonical N1 to the existing
RC7 durable Task authority and persists an explicit dsh-agent-teams dispatch
contract for a later fresh-worker assignment adapter.

There is no second WorkItem/Attempt store: rc7_task remains WorkItem truth,
execution_attempt remains Attempt truth, and worker/session identities remain
disposable execution identities rather than Mission state.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Mapping

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError, Mission, Task
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_field_mission_start import install_rc72_field_mission_start_overlay
from .rc72_state_machine import RC72StateMachine
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_mission_node_dispatch"
_EVENT = "RC72_MISSION_NODE_DISPATCH_UPSERTED"
_BUCKET = "rc72_mission_node_dispatches"

_SUBSTRATE = "DSH_AGENT_TEAMS"
_WORKER_POLICY = "FRESH_SESSION_REQUIRED"
_STATUS = "READY_FOR_ASSIGNMENT"
_TASK_TYPE = "RC72_NODE_WORK"

# The first atom intentionally supports only N1. Later nodes must be added with
# their own stage/gate semantics instead of being guessed from a node name.
_N1_STAGE = "REALITY_RECON"
_N1_ROLE = "REALITY_RECON_WORKER"
_N1_CAPABILITIES = ("reality_recon", "field_evidence")


class MissionNodeDispatchError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MissionNodeDispatchError("RC72_DISPATCH_%s_REQUIRED" % name.upper())
    return value.strip()


def _string_list(value: Any, name: str, *, allow_empty: bool = True) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError("RC72_DISPATCH_%s_INVALID" % name.upper())
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("RC72_DISPATCH_%s_INVALID" % name.upper())
    if len(set(value)) != len(value):
        raise _contracts.DomainValidationError("RC72_DISPATCH_%s_DUPLICATE" % name.upper())
    if not allow_empty and not value:
        raise _contracts.DomainValidationError("RC72_DISPATCH_%s_REQUIRED" % name.upper())
    return list(value)


def validate_rc72_mission_node_dispatch(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "dispatch_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "field_start_receipt_id", "mission_node_id",
        "node_type", "stage", "workitem_id", "team_role",
        "execution_substrate", "worker_policy", "status",
    ):
        out[name] = _contracts._require_str(out, name)

    if out["node_type"] != AutonomousMissionNode.N1_REALITY.value:
        raise _contracts.DomainValidationError("RC72_DISPATCH_NODE_NOT_SUPPORTED")
    if out["stage"] != _N1_STAGE:
        raise _contracts.DomainValidationError("RC72_DISPATCH_STAGE_INVALID")
    if out["execution_substrate"] != _SUBSTRATE:
        raise _contracts.DomainValidationError("RC72_DISPATCH_SUBSTRATE_INVALID")
    if out["worker_policy"] != _WORKER_POLICY:
        raise _contracts.DomainValidationError("RC72_DISPATCH_WORKER_POLICY_INVALID")
    if out["status"] != _STATUS:
        raise _contracts.DomainValidationError("RC72_DISPATCH_STATUS_INVALID")

    out["required_capabilities"] = _string_list(
        out.get("required_capabilities"), "required_capabilities", allow_empty=False
    )
    out["input_refs"] = _string_list(
        out.get("input_refs"), "input_refs", allow_empty=False
    )

    # Planning truth must not masquerade as execution truth.
    for forbidden in (
        "worker_id", "session_id", "attempt_id", "lease_id",
        "execution_result", "q7_pass", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_DISPATCH_EXECUTION_CLAIM_FORBIDDEN:%s" % forbidden
            )

    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_DISPATCH_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_DISPATCH_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_mission_node_dispatch_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_field_mission_start_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_mission_node_dispatch
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


class N1AutonomousDispatchService:
    """Materialize exactly one governed N1 WorkItem + AgentTeams dispatch."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_mission_node_dispatch_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")

    @staticmethod
    def _dispatch_id(
        mission_id: str, release_batch_id: str, source_commit: str
    ) -> str:
        raw = "\x1f".join(
            (
                mission_id,
                release_batch_id,
                AutonomousMissionNode.N1_REALITY.value,
                source_commit,
            )
        )
        return "N1DISP-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _workitem_id(mission_id: str, release_batch_id: str) -> str:
        raw = "\x1f".join(
            (mission_id, release_batch_id, AutonomousMissionNode.N1_REALITY.value)
        )
        return "WI-N1-%s" % hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise MissionNodeDispatchError(
                "RC72_DISPATCH_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _preflight(self, release_batch_id: str) -> tuple:
        batch = self._one(
            "rc72_release_batch", release_batch_id=release_batch_id
        )
        mission_id = _required(batch.get("mission_id"), "mission_id")
        release_id = _required(batch.get("release_id"), "release_id")
        node = self._one(
            "rc72_mission_node",
            mission_id=mission_id,
            node_type=AutonomousMissionNode.N1_REALITY.value,
        )
        if node.get("scope_ref") != "release-batch://%s" % release_batch_id:
            raise MissionNodeDispatchError(
                "RC72_DISPATCH_NODE_SCOPE_MISMATCH"
            )
        if node.get("state") not in {
            MissionNodeState.READY.value,
            MissionNodeState.RUNNING.value,
        }:
            raise MissionNodeDispatchError(
                "RC72_DISPATCH_N1_STATE_INVALID:%s"
                % str(node.get("state") or "UNKNOWN")
            )

        starts = self.truth.query(
            "rc72_field_mission_start_receipt",
            release_batch_id=release_batch_id,
        )
        exact = [
            row
            for row in starts
            if row.get("mission_id") == mission_id
            and row.get("release_id") == release_id
            and row.get("source_commit") == self.source_commit
            and row.get("status") == "BOOTSTRAPPED"
            and row.get("n1_mission_node_id") == node.get("mission_node_id")
        ]
        if len(exact) != 1:
            raise MissionNodeDispatchError(
                "RC72_DISPATCH_EXACT_FIELD_START_REQUIRED:%d" % len(exact)
            )

        # Do not merge RC7.2 node dispatch into a pre-existing legacy graph.
        workitem_id = self._workitem_id(mission_id, release_batch_id)
        existing_tasks = self.truth.query("rc7_task", mission_id=mission_id)
        foreign = [
            row
            for row in existing_tasks
            if row.get("task_id") != workitem_id
        ]
        if foreign:
            raise MissionNodeDispatchError(
                "RC72_DISPATCH_LEGACY_TASK_GRAPH_CONFLICT"
            )

        mission_rows = self.truth.query("rc7_mission", mission_id=mission_id)
        if len(mission_rows) > 1:
            raise MissionNodeDispatchError(
                "RC72_DISPATCH_RC7_MISSION_NOT_UNIQUE"
            )
        if mission_rows and mission_rows[0].get("release_id") != release_id:
            raise MissionNodeDispatchError(
                "RC72_DISPATCH_RC7_MISSION_RELEASE_MISMATCH"
            )
        return batch, node, exact[0], mission_rows[0] if mission_rows else None

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "release_id": payload.get("release_id"),
            "mission_id": payload.get("mission_id"),
            "release_batch_id": payload.get("release_batch_id"),
            "source_commit": payload.get("source_commit"),
            "field_start_receipt_id": payload.get("field_start_receipt_id"),
            "mission_node_id": payload.get("mission_node_id"),
            "node_type": payload.get("node_type"),
            "stage": payload.get("stage"),
            "workitem_id": payload.get("workitem_id"),
            "team_role": payload.get("team_role"),
            "execution_substrate": payload.get("execution_substrate"),
            "worker_policy": payload.get("worker_policy"),
            "required_capabilities": list(
                payload.get("required_capabilities") or []
            ),
            "input_refs": list(payload.get("input_refs") or []),
            "status": payload.get("status"),
        }

    def dispatch(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(
            release_batch_id, "release_batch_id"
        )
        batch, node, start, existing_mission = self._preflight(
            release_batch_id
        )
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        node_id = str(node["mission_node_id"])
        workitem_id = self._workitem_id(mission_id, release_batch_id)
        dispatch_id = self._dispatch_id(
            mission_id, release_batch_id, self.source_commit
        )

        existing_dispatch = self.truth.query(
            _ARTIFACT, dispatch_id=dispatch_id
        )
        if len(existing_dispatch) > 1:
            raise MissionNodeDispatchError(
                "RC72_DISPATCH_NOT_UNIQUE"
            )

        expected_payload = {
            "dispatch_id": dispatch_id,
            "release_id": release_id,
            "mission_id": mission_id,
            "release_batch_id": release_batch_id,
            "source_commit": self.source_commit,
            "field_start_receipt_id": str(start["start_receipt_id"]),
            "mission_node_id": node_id,
            "node_type": AutonomousMissionNode.N1_REALITY.value,
            "stage": _N1_STAGE,
            "workitem_id": workitem_id,
            "team_role": _N1_ROLE,
            "execution_substrate": _SUBSTRATE,
            "worker_policy": _WORKER_POLICY,
            "required_capabilities": list(_N1_CAPABILITIES),
            # These are canonical RC7.2 lineage refs consumed by the assignment
            # adapter. They are deliberately NOT copied into rc7_task
            # input_artifact_refs: TaskScheduler accepts only rc7_artifact ids
            # or its frozen governed external-input schemes.
            "input_refs": [
                "release-batch://%s" % release_batch_id,
                "mission-node://%s" % node_id,
                "field-start://%s" % str(start["start_receipt_id"]),
            ],
            "status": _STATUS,
        }
        if existing_dispatch:
            if self._signature(existing_dispatch[0]) != self._signature(
                expected_payload
            ):
                raise MissionNodeDispatchError(
                    "RC72_DISPATCH_IDENTITY_CONFLICT"
                )
            task_rows = self.truth.query(
                "rc7_task", task_id=workitem_id
            )
            if len(task_rows) != 1:
                raise MissionNodeDispatchError(
                    "RC72_DISPATCH_WORKITEM_NOT_UNIQUE:%d"
                    % len(task_rows)
                )
            if node.get("state") != MissionNodeState.RUNNING.value:
                raise MissionNodeDispatchError(
                    "RC72_DISPATCH_EXISTING_RECEIPT_NODE_NOT_RUNNING"
                )
            return {
                "status": "RESUMED",
                "dispatch_id": dispatch_id,
                "workitem_id": workitem_id,
                "mission_id": mission_id,
                "release_id": release_id,
                "release_batch_id": release_batch_id,
                "mission_node_id": node_id,
                "node_state": MissionNodeState.RUNNING.value,
                "workitem_state": str(task_rows[0].get("state") or "UNKNOWN"),
                "execution_substrate": _SUBSTRATE,
                "worker_policy": _WORKER_POLICY,
            }

        if existing_mission is None:
            control = ClosedLoopControlPlane.bootstrap(
                self.truth,
                Mission(
                    mission_id=mission_id,
                    release_id=release_id,
                    goal=(
                        "Complete ReleaseBatch %s through canonical N1-N10 "
                        "with evidence-backed gates" % release_batch_id
                    ),
                ),
            )
        else:
            control = ClosedLoopControlPlane(
                self.truth, release_id, mission_id
            )

        task_rows = self.truth.query("rc7_task", task_id=workitem_id)
        if task_rows:
            raise MissionNodeDispatchError(
                "RC72_DISPATCH_WORKITEM_EXISTS_WITHOUT_RECEIPT"
            )
        task = Task(
            task_id=workitem_id,
            mission_id=mission_id,
            node=_N1_STAGE,
            task_type=_TASK_TYPE,
            objective=(
                "Establish evidence-backed ReleaseBatch reality/readiness "
                "truth for %s" % release_batch_id
            ),
            required_capabilities=list(_N1_CAPABILITIES),
            # RC7.2 lineage lives in the dispatch receipt until the assignment
            # adapter projects it into the worker ContextEnvelope. Keeping this
            # empty preserves TaskScheduler's frozen input-validity contract.
            input_artifact_refs=[],
            acceptance_criteria=[
                "real environment/deployment/capability facts are evidence-backed",
                "unknown or unavailable prerequisites remain explicit gaps, never PASS",
                "output is sufficient for an independent N1 NodeGate decision",
            ],
            priority=0,
        )
        control.register_task(task)

        persisted_task = self.truth.query(
            "rc7_task", task_id=workitem_id
        )
        if (
            len(persisted_task) != 1
            or persisted_task[0].get("state") != "READY"
        ):
            observed = (
                persisted_task[0].get("state")
                if len(persisted_task) == 1
                else "NOT_UNIQUE:%d" % len(persisted_task)
            )
            raise MissionNodeDispatchError(
                "RC72_DISPATCH_WORKITEM_NOT_READY:%s" % observed
            )

        # N1 becomes RUNNING because durable, scheduler-ready work now exists;
        # no worker execution is claimed until AgentTeams consumes this dispatch.
        RC72StateMachine(
            self.truth, release_id=release_id
        ).transition_state(
            node_id,
            MissionNodeState.RUNNING,
            reason="governed N1 WorkItem dispatch materialized",
        )

        now = _now()
        payload = dict(expected_payload)
        payload.update(
            {
                "created_at": now,
                "updated_at": now,
                "artifact_version": 1,
            }
        )
        self.truth.append_atomic(_EVENT, payload)
        rows = self.truth.query(_ARTIFACT, dispatch_id=dispatch_id)
        if len(rows) != 1:
            raise MissionNodeDispatchError(
                "RC72_DISPATCH_PERSISTENCE_FAILED"
            )

        return {
            "status": "DISPATCHED",
            "dispatch_id": dispatch_id,
            "workitem_id": workitem_id,
            "mission_id": mission_id,
            "release_id": release_id,
            "release_batch_id": release_batch_id,
            "mission_node_id": node_id,
            "node_state": MissionNodeState.RUNNING.value,
            "workitem_state": "READY",
            "execution_substrate": _SUBSTRATE,
            "worker_policy": _WORKER_POLICY,
            "team_role": _N1_ROLE,
        }


install_rc72_mission_node_dispatch_overlay()
