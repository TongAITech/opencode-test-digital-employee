"""RC7.2 governed N3 source-target mapping revision planning + fresh assignment.

Independent source-mapping review may put a SOURCE_TARGET_DISCOVERY WorkItem in
REPAIR_REQUIRED. RC7.2 must never rerun that same WorkItem/worker/session. This
layer therefore creates a new per-application revision WorkItem, leases it to a
fresh deterministic AgentTeams worker, and preserves the previous candidate,
review Evaluation and Gap lineage immutably.

The revision identity is keyed by trigger Evaluation + application. Replaying
the same failed review resumes the same generation/worker; only a later failed
independent review may allocate the next generation. This layer stops at
LEASED_FOR_HANDOFF: no DSH session, mapping output, CODE_ANALYSIS WorkItem,
NodeGate, N4 release, field_verified or BANK_FINAL claim is admitted here.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Mapping, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .closed_loop_control import ClosedLoopControlPlane
from .models import ContractError, Task, TaskStatus
from .rc72_domain import AutonomousMissionNode, MissionNodeState
from .rc72_truth import install_rc72_truth_overlay
from .state_machine import transition_task
from .truth_overlay import append_entity, install_rc7_truth_overlay


_ARTIFACT = "rc72_n3_source_target_revision"
_EVENT = "RC72_N3_SOURCE_TARGET_REVISION_UPSERTED"
_BUCKET = "rc72_n3_source_target_revisions"
_NODE = AutonomousMissionNode.N3_CODE_ANALYSIS
_NEXT_NODE = AutonomousMissionNode.N4_TEST_DESIGN
_STAGE = "SOURCE_TARGET_DISCOVERY"
_TASK_TYPE = "RC72_NODE_WORK"
_TEAM_ROLE = "SOURCE_TARGET_DISCOVERY_WORKER"
_AGENT_ID = "source-target-discovery"
_SUBSTRATE = "DSH_AGENT_TEAMS"
_WORKER_POLICY = "FRESH_SESSION_REQUIRED"
_STATUS = "LEASED_FOR_HANDOFF"
_CAPABILITIES = ("source_target_discovery",)
_REVIEW_MARKER = "V1"
_GAP_CATEGORY = "SOURCE_TARGET_MAPPING_GAP"


class N3SourceTargetRevisionError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3SourceTargetRevisionError(
            "RC72_N3_SOURCE_REVISION_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _strings(value: Any, name: str, *, required: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REVISION_%s_INVALID" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REVISION_%s_INVALID" % name.upper()
        )
    out = [item.strip() for item in value]
    if len(set(out)) != len(out):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REVISION_%s_DUPLICATE" % name.upper()
        )
    if required and not out:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REVISION_%s_REQUIRED" % name.upper()
        )
    return out


def validate_rc72_n3_source_target_revision(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "revision_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "mission_node_id", "application_id",
        "trigger_evaluation_id", "previous_workitem_id", "previous_artifact_id",
        "revision_workitem_id", "revision_worker_instance_id", "team_role",
        "agent_id", "execution_substrate", "worker_policy", "status",
    ):
        out[name] = _contracts._require_str(out, name)
    generation = out.get("revision_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 2:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REVISION_GENERATION_INVALID"
        )
    out["revision_generation"] = generation
    if out["team_role"] != _TEAM_ROLE or out["agent_id"] != _AGENT_ID:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REVISION_ROLE_INVALID"
        )
    if out["execution_substrate"] != _SUBSTRATE or out["worker_policy"] != _WORKER_POLICY:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REVISION_SUBSTRATE_INVALID"
        )
    if out["status"] != _STATUS:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REVISION_STATUS_INVALID"
        )
    out["gap_refs"] = _strings(out.get("gap_refs"), "gap_refs", required=True)
    out["input_artifact_refs"] = _strings(
        out.get("input_artifact_refs"), "input_artifact_refs", required=True
    )
    out["required_capabilities"] = _strings(
        out.get("required_capabilities"), "required_capabilities", required=True
    )
    if tuple(out["required_capabilities"]) != _CAPABILITIES:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REVISION_CAPABILITIES_INVALID"
        )
    recovered = out.get("recovered_orphan_lease", False)
    if not isinstance(recovered, bool):
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REVISION_RECOVERY_FLAG_INVALID"
        )
    out["recovered_orphan_lease"] = recovered
    for forbidden in (
        "repository", "repository_ref", "source_revision", "base_revision",
        "head_revision", "target_id", "session_id", "dsh_session_id",
        "attempt_id", "output_refs", "evidence_refs", "evaluation_result",
        "code_analysis_result", "node_delivery_id", "node_gate", "node_pass",
        "n4_started", "q7_pass", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N3_SOURCE_REVISION_EXECUTION_CLAIM_FORBIDDEN:%s" % forbidden
            )
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N3_SOURCE_REVISION_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N3_SOURCE_REVISION_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n3_source_target_revision_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n3_source_target_revision
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "revision_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "revision_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


class N3SourceTargetRevisionService:
    """Create fresh revision WorkItems only for failed source-mapping reviews."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n3_source_target_revision_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N3SourceTargetRevisionError(
                "RC72_N3_SOURCE_REVISION_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _application_for_workitem(self, workitem_id: str) -> str:
        initial = self.truth.query(
            "rc72_n3_source_target_dispatch", workitem_id=workitem_id
        )
        if len(initial) == 1:
            if initial[0].get("source_commit") != self.source_commit:
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_DISPATCH_SOURCE_COMMIT_MISMATCH"
                )
            return _required(initial[0].get("application_id"), "application_id")
        previous = [
            row for row in self.truth.query(_ARTIFACT)
            if row.get("revision_workitem_id") == workitem_id
        ]
        if len(previous) == 1:
            if previous[0].get("source_commit") != self.source_commit:
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_PREVIOUS_SOURCE_COMMIT_MISMATCH"
                )
            return _required(previous[0].get("application_id"), "application_id")
        raise N3SourceTargetRevisionError(
            "RC72_N3_SOURCE_REVISION_WORKITEM_APPLICATION_NOT_UNIQUE:%s"
            % workitem_id
        )

    def _generation(
        self,
        *,
        release_batch_id: str,
        application_id: str,
        trigger_evaluation_id: str,
    ) -> int:
        rows = [
            row for row in self.truth.query(_ARTIFACT, release_batch_id=release_batch_id)
            if row.get("source_commit") == self.source_commit
            and row.get("application_id") == application_id
        ]
        same_trigger = [
            row for row in rows
            if row.get("trigger_evaluation_id") == trigger_evaluation_id
        ]
        if same_trigger:
            if len(same_trigger) != 1:
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_TRIGGER_RECEIPT_NOT_UNIQUE"
                )
            generation = int(same_trigger[0].get("revision_generation") or 0)
            if generation < 2:
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_EXISTING_GENERATION_INVALID"
                )
            return generation
        if not rows:
            return 2
        highest = max(int(row.get("revision_generation") or 0) for row in rows)
        if highest < 2:
            raise N3SourceTargetRevisionError(
                "RC72_N3_SOURCE_REVISION_EXISTING_GENERATION_INVALID"
            )
        if len([
            row for row in rows
            if int(row.get("revision_generation") or 0) == highest
        ]) != 1:
            raise N3SourceTargetRevisionError(
                "RC72_N3_SOURCE_REVISION_GENERATION_NOT_UNIQUE"
            )
        return highest + 1

    def _context(
        self, release_batch_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        batch = self._one("rc72_release_batch", release_batch_id=release_batch_id)
        mission_id = _required(batch.get("mission_id"), "mission_id")
        release_id = _required(batch.get("release_id"), "release_id")
        applications = list(batch.get("application_ids") or [])
        if (
            not applications
            or not all(isinstance(item, str) and item.strip() for item in applications)
            or len(set(applications)) != len(applications)
        ):
            raise N3SourceTargetRevisionError(
                "RC72_N3_SOURCE_REVISION_CANONICAL_APPLICATIONS_REQUIRED"
            )
        mission = self._one("rc7_mission", mission_id=mission_id)
        if mission.get("release_id") != release_id:
            raise N3SourceTargetRevisionError(
                "RC72_N3_SOURCE_REVISION_MISSION_LINEAGE_MISMATCH"
            )
        node = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE.value
        )
        if node.get("state") != MissionNodeState.RUNNING.value:
            raise N3SourceTargetRevisionError(
                "RC72_N3_SOURCE_REVISION_N3_NOT_RUNNING:%s"
                % str(node.get("state") or "UNKNOWN")
            )
        n4 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
        )
        if n4.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N3SourceTargetRevisionError(
                "RC72_N3_SOURCE_REVISION_N4_ALREADY_RELEASED"
            )
        return batch, node, n4

    def _affected(
        self,
        *,
        batch: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        mission_id = str(batch["mission_id"])
        canonical_apps = set(str(item) for item in list(batch.get("application_ids") or []))
        result: List[Dict[str, Any]] = []
        for row in self.truth.query("rc7_task", mission_id=mission_id):
            if row.get("node") != _STAGE:
                continue
            if row.get("state") not in {
                TaskStatus.REPAIR_REQUIRED.value,
                TaskStatus.STALE.value,
            }:
                continue
            evaluation_id = row.get("evaluation_id")
            if not isinstance(evaluation_id, str) or not evaluation_id.strip():
                continue
            evaluations = self.truth.query(
                "rc7_evaluation", evaluation_id=evaluation_id
            )
            if len(evaluations) != 1:
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_EVALUATION_NOT_UNIQUE:%s"
                    % evaluation_id
                )
            evaluation = evaluations[0]
            dimensions = evaluation.get("dimensions")
            if (
                evaluation.get("mission_id") != mission_id
                or evaluation.get("node") != _STAGE
                or evaluation.get("result") != "REPAIR_REQUIRED"
                or not isinstance(dimensions, dict)
                or dimensions.get("rc72_source_target_review") != _REVIEW_MARKER
            ):
                continue
            application_id = _required(
                dimensions.get("application_id"), "application_id"
            )
            if application_id not in canonical_apps:
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_APPLICATION_OUTSIDE_BATCH:%s"
                    % application_id
                )
            if self._application_for_workitem(str(row["task_id"])) != application_id:
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_APPLICATION_LINEAGE_MISMATCH:%s"
                    % application_id
                )
            artifact_refs = list(row.get("output_artifact_refs") or [])
            if len(artifact_refs) != 1:
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_PREVIOUS_ARTIFACT_NOT_UNIQUE:%s"
                    % application_id
                )
            artifact = self._one(
                "rc7_artifact", artifact_id=str(artifact_refs[0])
            )
            if (
                artifact.get("mission_id") != mission_id
                or artifact.get("producer_task_id") != row.get("task_id")
                or artifact.get("artifact_type_name") != "SOURCE_TARGET_MAPPING_CANDIDATE"
                or artifact.get("state") != "VALID"
                or str(artifact["artifact_id"]) not in list(evaluation.get("artifact_refs") or [])
            ):
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_PREVIOUS_ARTIFACT_LINEAGE_INVALID:%s"
                    % application_id
                )
            gap_refs = list(evaluation.get("gap_refs") or [])
            if not gap_refs:
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_TRIGGER_GAPS_REQUIRED:%s"
                    % application_id
                )
            if not set(gap_refs).issubset(set(row.get("gap_refs") or [])):
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_TASK_GAP_BINDING_MISMATCH:%s"
                    % application_id
                )
            for gap_id in gap_refs:
                gap = self._one("rc7_gap", gap_id=str(gap_id))
                if (
                    gap.get("mission_id") != mission_id
                    or gap.get("source_node") != _STAGE
                    or gap.get("target_node") != _STAGE
                    or gap.get("category") != _GAP_CATEGORY
                    or gap.get("state") != "OPEN"
                ):
                    raise N3SourceTargetRevisionError(
                        "RC72_N3_SOURCE_REVISION_GAP_INVALID:%s" % gap_id
                    )
            result.append({
                "application_id": application_id,
                "trigger_evaluation_id": evaluation_id,
                "previous_workitem_id": str(row["task_id"]),
                "previous_artifact_id": str(artifact["artifact_id"]),
                "gap_refs": sorted(str(item) for item in gap_refs),
                "previous_task": row,
            })
        if not result:
            raise N3SourceTargetRevisionError(
                "RC72_N3_SOURCE_REVISION_AFFECTED_APPLICATION_REQUIRED"
            )
        by_app: Dict[str, Dict[str, Any]] = {}
        for item in result:
            app = str(item["application_id"])
            current = by_app.get(app)
            if current is None:
                by_app[app] = item
                continue
            # At most one active failed review may own the next revision for an
            # application. A later generation is discoverable only after the
            # previous source task has become STALE with its receipt present.
            current_receipt = self.truth.query(
                _ARTIFACT,
                trigger_evaluation_id=str(current["trigger_evaluation_id"]),
            )
            item_receipt = self.truth.query(
                _ARTIFACT,
                trigger_evaluation_id=str(item["trigger_evaluation_id"]),
            )
            if current_receipt and not item_receipt:
                by_app[app] = item
            elif item_receipt and not current_receipt:
                pass
            else:
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_ACTIVE_REVIEW_NOT_UNIQUE:%s" % app
                )
        return [by_app[app] for app in sorted(by_app)]

    def _expected(
        self,
        *,
        batch: Mapping[str, Any],
        node: Mapping[str, Any],
        affected: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        release_batch_id = str(batch["release_batch_id"])
        mission_id = str(batch["mission_id"])
        out: List[Dict[str, Any]] = []
        for item in affected:
            application_id = str(item["application_id"])
            trigger_evaluation_id = str(item["trigger_evaluation_id"])
            generation = self._generation(
                release_batch_id=release_batch_id,
                application_id=application_id,
                trigger_evaluation_id=trigger_evaluation_id,
            )
            revision_id = _stable_id(
                "N3SRCREV",
                mission_id,
                trigger_evaluation_id,
                application_id,
                "GEN%d" % generation,
            )
            workitem_id = _stable_id(
                "WI-N3-SOURCE-REV", revision_id, "WORKITEM"
            )
            worker_id = _stable_id(
                "RC72N3SRCREVFW", revision_id, "FRESH_WORKER"
            )
            previous_task = item["previous_task"]
            input_refs: List[str] = []
            for ref in (
                list(previous_task.get("input_artifact_refs") or [])
                + [str(item["previous_artifact_id"])]
            ):
                if ref not in input_refs:
                    input_refs.append(str(ref))
            out.append({
                "revision_id": revision_id,
                "release_id": str(batch["release_id"]),
                "mission_id": mission_id,
                "release_batch_id": release_batch_id,
                "source_commit": self.source_commit,
                "mission_node_id": str(node["mission_node_id"]),
                "application_id": application_id,
                "trigger_evaluation_id": trigger_evaluation_id,
                "revision_generation": generation,
                "previous_workitem_id": str(item["previous_workitem_id"]),
                "previous_artifact_id": str(item["previous_artifact_id"]),
                "revision_workitem_id": workitem_id,
                "revision_worker_instance_id": worker_id,
                "team_role": _TEAM_ROLE,
                "agent_id": _AGENT_ID,
                "execution_substrate": _SUBSTRATE,
                "worker_policy": _WORKER_POLICY,
                "gap_refs": list(item["gap_refs"]),
                "input_artifact_refs": input_refs,
                "required_capabilities": list(_CAPABILITIES),
                "status": _STATUS,
            })
        return out

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "revision_id", "release_id", "mission_id", "release_batch_id",
            "source_commit", "mission_node_id", "application_id",
            "trigger_evaluation_id", "revision_generation",
            "previous_workitem_id", "previous_artifact_id",
            "revision_workitem_id", "revision_worker_instance_id", "team_role",
            "agent_id", "execution_substrate", "worker_policy", "status",
        )
        result = {key: payload.get(key) for key in keys}
        for key in ("gap_refs", "input_artifact_refs", "required_capabilities"):
            result[key] = list(payload.get(key) or [])
        return result

    def _persist_source_stale(
        self, *, previous_task_id: str, release_id: str
    ) -> None:
        row = self._one("rc7_task", task_id=previous_task_id)
        if row.get("state") == TaskStatus.STALE.value:
            return
        if row.get("state") != TaskStatus.REPAIR_REQUIRED.value:
            raise N3SourceTargetRevisionError(
                "RC72_N3_SOURCE_REVISION_SOURCE_TASK_NOT_REPAIR_REQUIRED:%s:%s"
                % (previous_task_id, str(row.get("state") or "UNKNOWN"))
            )
        task = ClosedLoopControlPlane(
            self.truth, release_id, str(row["mission_id"])
        ).scheduler.task(previous_task_id)
        transition_task(task, TaskStatus.STALE)
        append_entity(
            self.truth,
            task,
            release_id=release_id,
            artifact_version=int(row.get("artifact_version") or 1) + 1,
        )

    def _persist_receipt(
        self, expected: Mapping[str, Any], *, recovered: bool
    ) -> None:
        payload = dict(expected)
        now = _now()
        payload.update({
            "recovered_orphan_lease": recovered,
            "created_at": now,
            "updated_at": now,
            "artifact_version": 1,
        })
        self.truth.append_atomic(_EVENT, payload)

    def plan_and_assign(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch, node, _n4 = self._context(release_batch_id)
        release_id = str(batch["release_id"])
        mission_id = str(batch["mission_id"])
        affected = self._affected(batch=batch)
        expected = self._expected(batch=batch, node=node, affected=affected)

        plans: List[Dict[str, Any]] = []
        for item in expected:
            receipts = self.truth.query(_ARTIFACT, revision_id=str(item["revision_id"]))
            if len(receipts) > 1:
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_RECEIPT_NOT_UNIQUE"
                )
            task_rows = self.truth.query(
                "rc7_task", task_id=str(item["revision_workitem_id"])
            )
            if receipts:
                if self._signature(receipts[0]) != self._signature(item):
                    raise N3SourceTargetRevisionError(
                        "RC72_N3_SOURCE_REVISION_RECEIPT_CONFLICT"
                    )
                if len(task_rows) != 1:
                    raise N3SourceTargetRevisionError(
                        "RC72_N3_SOURCE_REVISION_RECEIPT_TASK_NOT_UNIQUE"
                    )
                task = task_rows[0]
                if (
                    task.get("lease_owner") != item["revision_worker_instance_id"]
                    or task.get("state") not in {
                        TaskStatus.LEASED.value,
                        TaskStatus.RUNNING.value,
                        TaskStatus.OUTPUT_PRODUCED.value,
                        TaskStatus.EVALUATING.value,
                        TaskStatus.PASS.value,
                        TaskStatus.REPAIR_REQUIRED.value,
                        TaskStatus.STALE.value,
                    }
                ):
                    raise N3SourceTargetRevisionError(
                        "RC72_N3_SOURCE_REVISION_RECEIPT_LEASE_MISMATCH"
                    )
                mode = "RESUMED"
            elif task_rows:
                if len(task_rows) != 1:
                    raise N3SourceTargetRevisionError(
                        "RC72_N3_SOURCE_REVISION_ORPHAN_TASK_NOT_UNIQUE"
                    )
                task = task_rows[0]
                if (
                    task.get("state") != TaskStatus.LEASED.value
                    or task.get("lease_owner") != item["revision_worker_instance_id"]
                ):
                    raise N3SourceTargetRevisionError(
                        "RC72_N3_SOURCE_REVISION_ORPHAN_LEASE_INVALID"
                    )
                mode = "RECOVER_ORPHAN"
            else:
                mode = "NEW"
            plans.append({"expected": item, "mode": mode})

        if all(plan["mode"] == "RESUMED" for plan in plans):
            return {
                "status": "RESUMED",
                "release_batch_id": release_batch_id,
                "mission_id": mission_id,
                "mission_node_id": str(node["mission_node_id"]),
                "node_state": MissionNodeState.RUNNING.value,
                "n4_state": MissionNodeState.NOT_STARTED.value,
                "revisions": [plan["expected"] for plan in plans],
            }
        if any(plan["mode"] == "RESUMED" for plan in plans):
            raise N3SourceTargetRevisionError(
                "RC72_N3_SOURCE_REVISION_PARTIAL_RECEIPT_SET"
            )

        control = ClosedLoopControlPlane(self.truth, release_id, mission_id)
        for plan in plans:
            if plan["mode"] != "NEW":
                continue
            item = plan["expected"]
            control.register_task(Task(
                task_id=str(item["revision_workitem_id"]),
                mission_id=mission_id,
                node=_STAGE,
                task_type=_TASK_TYPE,
                objective=(
                    "Re-discover evidence-backed source repository and exact source revision(s) for application %s after independent mapping review gaps; never reuse or trust the previous mapping without fresh tool evidence"
                    % item["application_id"]
                ),
                required_capabilities=list(_CAPABILITIES),
                input_artifact_refs=list(item["input_artifact_refs"]),
                gap_refs=list(item["gap_refs"]),
                acceptance_criteria=[
                    "use a fresh AgentTeams worker and a fresh DSH session",
                    "re-check application -> repository/source revision with real tool evidence",
                    "do not guess repository identity or source revision",
                    "return explicit unknown/gap when mapping remains ambiguous",
                    "independent source-target review remains mandatory before acceptance",
                ],
                priority=0,
            ))

        new_ids = {
            str(plan["expected"]["revision_workitem_id"])
            for plan in plans if plan["mode"] == "NEW"
        }
        ready = list(control.scheduler.ready_tasks(mission_id))
        foreign = [task.task_id for task in ready if task.task_id not in new_ids]
        if foreign:
            raise N3SourceTargetRevisionError(
                "RC72_N3_SOURCE_REVISION_FOREIGN_READY_TASK_CONFLICT:%s"
                % ",".join(sorted(foreign))
            )
        if {task.task_id for task in ready} != new_ids:
            raise N3SourceTargetRevisionError(
                "RC72_N3_SOURCE_REVISION_READY_SET_MISMATCH"
            )

        by_task = {
            str(plan["expected"]["revision_workitem_id"]): plan
            for plan in plans
        }
        for ready_task in ready:
            plan = by_task[ready_task.task_id]
            item = plan["expected"]
            leased = control.lease_next(
                worker_ref=str(item["revision_worker_instance_id"]),
                capabilities=list(item["required_capabilities"]),
            )
            if leased is None or leased.task_id != ready_task.task_id:
                observed = "NONE" if leased is None else leased.task_id
                raise N3SourceTargetRevisionError(
                    "RC72_N3_SOURCE_REVISION_LEASE_IDENTITY_MISMATCH:%s:%s"
                    % (ready_task.task_id, observed)
                )

        for plan in plans:
            item = plan["expected"]
            self._persist_source_stale(
                previous_task_id=str(item["previous_workitem_id"]),
                release_id=release_id,
            )
            if plan["mode"] == "NEW":
                self._persist_receipt(item, recovered=False)
            elif plan["mode"] == "RECOVER_ORPHAN":
                self._persist_receipt(item, recovered=True)

        return {
            "status": "ASSIGNED",
            "release_batch_id": release_batch_id,
            "mission_id": mission_id,
            "mission_node_id": str(node["mission_node_id"]),
            "node_state": MissionNodeState.RUNNING.value,
            "n4_state": MissionNodeState.NOT_STARTED.value,
            "revisions": [plan["expected"] for plan in plans],
        }


install_rc72_n3_source_target_revision_overlay()
