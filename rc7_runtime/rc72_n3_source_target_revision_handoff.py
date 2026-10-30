"""RC7.2 N3 source-target revision receipt -> fresh DSH Attempt bridge.

The generation-2+ revision planner owns fresh WorkItem/worker identity. This
adapter reuses the production N3 source-discovery handoff contract while
substituting a governed revision receipt for the initial assignment lineage.
All session/tool/raw-evidence checks remain owned by the existing handoff.

A separate immutable revision-attempt link binds the resulting Attempt back to
trigger Evaluation and prior candidate lineage. This layer still does not
promote source truth, close review gaps, create CODE_ANALYSIS work, advance N3,
release N4, or claim field/BANK_FINAL status.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Mapping, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .models import ContractError, TaskStatus
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_n3_source_target_handoff import (
    N3SourceTargetDshHandoffService,
    N3SourceTargetHandoffError,
    install_rc72_n3_source_target_handoff_overlay,
)
from .rc72_n3_source_target_revision import (
    install_rc72_n3_source_target_revision_overlay,
)
from .truth_overlay import install_rc7_truth_overlay


_LINK_ARTIFACT = "rc72_n3_source_target_revision_attempt_link"
_LINK_EVENT = "RC72_N3_SOURCE_TARGET_REVISION_ATTEMPT_LINK_UPSERTED"
_LINK_BUCKET = "rc72_n3_source_target_revision_attempt_links"
_STAGE = "SOURCE_TARGET_DISCOVERY"
_NODE_TYPE = AutonomousMissionNode.N3_CODE_ANALYSIS.value
_NEXT_NODE = AutonomousMissionNode.N4_TEST_DESIGN.value
_STATUS = "LEASED_FOR_HANDOFF"
_TEAM_ROLE = "SOURCE_TARGET_DISCOVERY_WORKER"
_AGENT_ID = "source-target-discovery"
_LINK_STATUS = "REVISION_DSH_SESSION_OBSERVED"


class N3SourceTargetRevisionHandoffError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3SourceTargetRevisionHandoffError(
            "RC72_N3_SOURCE_REV_HANDOFF_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def validate_rc72_n3_source_target_revision_attempt_link(
    payload: Dict[str, Any]
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "link_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "mission_node_id", "application_id", "revision_id",
        "trigger_evaluation_id", "previous_workitem_id", "previous_artifact_id",
        "revision_workitem_id", "revision_worker_instance_id", "root_dispatch_id",
        "attempt_id", "dsh_session_id", "status",
    ):
        out[name] = _contracts._require_str(out, name)
    generation = out.get("revision_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 2:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REV_HANDOFF_GENERATION_INVALID"
        )
    out["revision_generation"] = generation
    if out["status"] != _LINK_STATUS:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REV_HANDOFF_STATUS_INVALID"
        )
    if not out["dsh_session_id"].startswith("session-"):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REV_HANDOFF_SESSION_INVALID"
        )
    for forbidden in (
        "repository", "repository_ref", "source_revision", "base_revision",
        "head_revision", "targets", "source_mapping_accepted", "evaluation_result",
        "code_analysis_result", "node_delivery_id", "node_gate", "node_pass",
        "n4_started", "q7_pass", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N3_SOURCE_REV_HANDOFF_TRUTH_CLAIM_FORBIDDEN:%s" % forbidden
            )
    value = out.get("created_at")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REV_HANDOFF_CREATED_AT_INVALID"
        )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REV_HANDOFF_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _LINK_ARTIFACT
    return out


def install_rc72_n3_source_target_revision_handoff_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_n3_source_target_handoff_overlay()
    install_rc72_n3_source_target_revision_overlay()
    _contracts.VALIDATORS[_LINK_ARTIFACT] = (
        validate_rc72_n3_source_target_revision_attempt_link
    )
    _truth.BUCKETS[_LINK_ARTIFACT] = _LINK_BUCKET
    _truth.IDENTITY_FIELDS[_LINK_ARTIFACT] = "link_id"
    _truth.EVENT_TYPES[_LINK_EVENT] = (_LINK_ARTIFACT, "link_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _LINK_BUCKET):
        setattr(projection, _LINK_BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_LINK_ARTIFACT, {})


class N3SourceTargetRevisionDshHandoffService(N3SourceTargetDshHandoffService):
    """Execute the latest governed source-mapping revision in fresh DSH."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        launcher: DshHeadlessWorkerLauncher,
        allowed_tools: Sequence[str],
    ) -> None:
        install_rc72_n3_source_target_revision_handoff_overlay()
        _ensure_bucket(truth)
        super().__init__(
            truth,
            source_commit=source_commit,
            launcher=launcher,
            allowed_tools=allowed_tools,
        )
        install_rc72_n3_source_target_revision_handoff_overlay()
        _ensure_bucket(truth)

    def _one_linked(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N3SourceTargetRevisionHandoffError(
                "RC72_N3_SOURCE_REV_HANDOFF_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _latest_revision(
        self, release_batch_id: str, application_id: str
    ) -> Dict[str, Any]:
        rows = [
            row for row in self.truth.query(
                "rc72_n3_source_target_revision",
                release_batch_id=release_batch_id,
            )
            if row.get("source_commit") == self.source_commit
            and row.get("application_id") == application_id
            and row.get("status") == _STATUS
        ]
        if not rows:
            raise N3SourceTargetRevisionHandoffError(
                "RC72_N3_SOURCE_REV_HANDOFF_REVISION_REQUIRED"
            )
        highest = max(int(row.get("revision_generation") or 0) for row in rows)
        exact = [
            row for row in rows
            if int(row.get("revision_generation") or 0) == highest
        ]
        if highest < 2 or len(exact) != 1:
            raise N3SourceTargetRevisionHandoffError(
                "RC72_N3_SOURCE_REV_HANDOFF_LATEST_REVISION_NOT_UNIQUE"
            )
        return exact[0]

    def _preflight(
        self, release_batch_id: str, application_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        revision = self._latest_revision(release_batch_id, application_id)
        mission_id = _required(revision.get("mission_id"), "mission_id")
        release_id = _required(revision.get("release_id"), "release_id")
        node_id = _required(revision.get("mission_node_id"), "mission_node_id")
        workitem_id = _required(
            revision.get("revision_workitem_id"), "revision_workitem_id"
        )
        worker_id = _required(
            revision.get("revision_worker_instance_id"),
            "revision_worker_instance_id",
        )
        generation = int(revision.get("revision_generation") or 0)

        batch = self._one_linked(
            "rc72_release_batch", release_batch_id=release_batch_id
        )
        if (
            batch.get("mission_id") != mission_id
            or batch.get("release_id") != release_id
            or application_id not in list(batch.get("application_ids") or [])
        ):
            raise N3SourceTargetRevisionHandoffError(
                "RC72_N3_SOURCE_REV_HANDOFF_RELEASE_BATCH_LINEAGE_MISMATCH"
            )
        node = self._one_linked("rc72_mission_node", mission_node_id=node_id)
        if (
            node.get("mission_id") != mission_id
            or node.get("node_type") != _NODE_TYPE
            or node.get("state") != MissionNodeState.RUNNING.value
        ):
            raise N3SourceTargetRevisionHandoffError(
                "RC72_N3_SOURCE_REV_HANDOFF_N3_NOT_RUNNING"
            )
        n4 = self._one_linked(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE
        )
        if n4.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N3SourceTargetRevisionHandoffError(
                "RC72_N3_SOURCE_REV_HANDOFF_N4_ALREADY_RELEASED"
            )

        trigger = self._one_linked(
            "rc7_evaluation",
            evaluation_id=str(revision["trigger_evaluation_id"]),
        )
        dimensions = trigger.get("dimensions")
        if (
            trigger.get("mission_id") != mission_id
            or trigger.get("node") != _STAGE
            or trigger.get("result") != "REPAIR_REQUIRED"
            or not isinstance(dimensions, dict)
            or dimensions.get("rc72_source_target_review") != "V1"
            or dimensions.get("application_id") != application_id
            or str(revision["previous_artifact_id"]) not in list(trigger.get("artifact_refs") or [])
            or set(revision.get("gap_refs") or []) != set(trigger.get("gap_refs") or [])
        ):
            raise N3SourceTargetRevisionHandoffError(
                "RC72_N3_SOURCE_REV_HANDOFF_TRIGGER_EVALUATION_INVALID"
            )
        previous_task = self._one_linked(
            "rc7_task", task_id=str(revision["previous_workitem_id"])
        )
        if previous_task.get("state") != TaskStatus.STALE.value:
            raise N3SourceTargetRevisionHandoffError(
                "RC72_N3_SOURCE_REV_HANDOFF_PREVIOUS_TASK_NOT_STALE"
            )
        task = self._one_linked("rc7_task", task_id=workitem_id)
        if (
            task.get("mission_id") != mission_id
            or task.get("node") != _STAGE
            or task.get("state") != TaskStatus.LEASED.value
            or task.get("lease_owner") != worker_id
            or list(task.get("required_capabilities") or [])
            != list(revision.get("required_capabilities") or [])
        ):
            raise N3SourceTargetRevisionHandoffError(
                "RC72_N3_SOURCE_REV_HANDOFF_REVISION_WORKITEM_LEASE_MISMATCH"
            )

        dispatches = [
            row for row in self.truth.query(
                "rc72_n3_source_target_dispatch",
                release_batch_id=release_batch_id,
            )
            if row.get("source_commit") == self.source_commit
            and row.get("application_id") == application_id
        ]
        if len(dispatches) != 1:
            raise N3SourceTargetRevisionHandoffError(
                "RC72_N3_SOURCE_REV_HANDOFF_ROOT_DISPATCH_NOT_UNIQUE:%d"
                % len(dispatches)
            )
        dispatch = dispatches[0]
        input_refs = list(revision.get("input_artifact_refs") or [])
        input_refs.extend(
            "gap://%s" % str(gap_id)
            for gap_id in list(revision.get("gap_refs") or [])
        )
        assignment = {
            "assignment_id": str(revision["revision_id"]),
            "dispatch_id": str(dispatch["dispatch_id"]),
            "release_id": release_id,
            "mission_id": mission_id,
            "release_batch_id": release_batch_id,
            "source_commit": self.source_commit,
            "mission_node_id": node_id,
            "node_type": _NODE_TYPE,
            "stage": _STAGE,
            "application_id": application_id,
            "workitem_id": workitem_id,
            "team_role": _TEAM_ROLE,
            "agent_id": _AGENT_ID,
            "worker_instance_id": worker_id,
            "assignment_generation": generation,
            "input_refs": list(dict.fromkeys(input_refs)),
            "status": _STATUS,
        }
        return assignment, dispatch, task

    def _prompt(self, assignment: Mapping[str, Any]) -> str:
        base = super()._prompt(assignment)
        revision = self._one_linked(
            "rc72_n3_source_target_revision",
            revision_id=str(assignment["assignment_id"]),
        )
        extension = {
            "revision_id": revision["revision_id"],
            "revision_generation": revision["revision_generation"],
            "trigger_evaluation_id": revision["trigger_evaluation_id"],
            "previous_artifact_id": revision["previous_artifact_id"],
            "gap_refs": list(revision.get("gap_refs") or []),
            "rule": (
                "This is a fresh revision. Re-discover the mapping using fresh real tool evidence; "
                "do not copy the previous candidate merely because it is an input. Explicitly retain "
                "unknowns/gaps when the failed review cannot be resolved."
            ),
        }
        import json
        return base + "\nRC72_N3_SOURCE_REVISION=" + json.dumps(
            extension, ensure_ascii=False, sort_keys=True
        )

    def _persist_link(
        self,
        *,
        revision: Mapping[str, Any],
        attempt: Mapping[str, Any],
        root_dispatch_id: str,
    ) -> Dict[str, Any]:
        link_id = _stable_id(
            "N3SRCREVLINK",
            str(revision["revision_id"]),
            str(attempt["attempt_id"]),
        )
        expected = {
            "link_id": link_id,
            "release_id": str(revision["release_id"]),
            "mission_id": str(revision["mission_id"]),
            "release_batch_id": str(revision["release_batch_id"]),
            "source_commit": self.source_commit,
            "mission_node_id": str(revision["mission_node_id"]),
            "application_id": str(revision["application_id"]),
            "revision_id": str(revision["revision_id"]),
            "revision_generation": int(revision["revision_generation"]),
            "trigger_evaluation_id": str(revision["trigger_evaluation_id"]),
            "previous_workitem_id": str(revision["previous_workitem_id"]),
            "previous_artifact_id": str(revision["previous_artifact_id"]),
            "revision_workitem_id": str(revision["revision_workitem_id"]),
            "revision_worker_instance_id": str(revision["revision_worker_instance_id"]),
            "root_dispatch_id": root_dispatch_id,
            "attempt_id": str(attempt["attempt_id"]),
            "dsh_session_id": str(attempt["dsh_session_id"]),
            "status": _LINK_STATUS,
        }
        existing = self.truth.query(_LINK_ARTIFACT, link_id=link_id)
        if existing:
            if len(existing) != 1:
                raise N3SourceTargetRevisionHandoffError(
                    "RC72_N3_SOURCE_REV_HANDOFF_LINK_NOT_UNIQUE"
                )
            for key, value in expected.items():
                if existing[0].get(key) != value:
                    raise N3SourceTargetRevisionHandoffError(
                        "RC72_N3_SOURCE_REV_HANDOFF_LINK_CONFLICT:%s" % key
                    )
            return existing[0]
        payload = dict(expected)
        payload.update({"created_at": int(time.time()), "artifact_version": 1})
        self.truth.append_atomic(_LINK_EVENT, payload)
        return self._one_linked(_LINK_ARTIFACT, link_id=link_id)

    def handoff_revision(
        self, *, release_batch_id: str, application_id: str
    ) -> Dict[str, Any]:
        revision = self._latest_revision(release_batch_id, application_id)
        result = super().handoff(
            release_batch_id=release_batch_id,
            application_id=application_id,
        )
        attempt = self._one_linked(
            "rc72_n3_source_target_attempt",
            attempt_id=str(result["attempt_id"]),
        )
        if (
            attempt.get("assignment_id") != revision.get("revision_id")
            or attempt.get("workitem_id") != revision.get("revision_workitem_id")
            or attempt.get("worker_instance_id") != revision.get("revision_worker_instance_id")
        ):
            raise N3SourceTargetRevisionHandoffError(
                "RC72_N3_SOURCE_REV_HANDOFF_ATTEMPT_REVISION_LINEAGE_MISMATCH"
            )
        link = self._persist_link(
            revision=revision,
            attempt=attempt,
            root_dispatch_id=str(attempt["dispatch_id"]),
        )
        out = dict(result)
        out.update({
            "revision_id": str(revision["revision_id"]),
            "revision_generation": int(revision["revision_generation"]),
            "revision_attempt_link_id": str(link["link_id"]),
        })
        return out


install_rc72_n3_source_target_revision_handoff_overlay()
