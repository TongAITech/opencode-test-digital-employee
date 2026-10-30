"""RC7.2 N3 accepted source mapping -> CODE_ANALYSIS durable dispatch.

Consumes only the latest independently accepted source-target mapping for every
canonical ReleaseBatch application and creates one durable CODE_ANALYSIS
WorkItem per target.  This boundary never assigns a worker, launches DSH, runs
Git/CodeGraph, creates an Attempt/output, closes N3, releases N4, or claims
field/Q7/BANK_FINAL truth.
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
from .rc72_n3_source_target_revision import install_rc72_n3_source_target_revision_overlay
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_n3_code_analysis_dispatch"
_EVENT = "RC72_N3_CODE_ANALYSIS_DISPATCH_UPSERTED"
_BUCKET = "rc72_n3_code_analysis_dispatches"
_NODE = AutonomousMissionNode.N3_CODE_ANALYSIS
_NEXT_NODE = AutonomousMissionNode.N4_TEST_DESIGN
_SOURCE_STAGE = "SOURCE_TARGET_DISCOVERY"
_STAGE = "CODE_ANALYSIS"
_TASK_TYPE = "RC72_NODE_WORK"
_TEAM_ROLE = "CODE_ANALYSIS_WORKER"
_SUBSTRATE = "DSH_AGENT_TEAMS"
_WORKER_POLICY = "FRESH_SESSION_REQUIRED"
_STATUS = "READY_FOR_ASSIGNMENT"
_CAPABILITIES = ("code_reasoning", "code_reality")
_REVIEW_MARKER = "V1"
_GAP_CATEGORY = "SOURCE_TARGET_MAPPING_GAP"
_RESOLVED_GAP_STATES = {"RESOLVED", "WAIVED", "DUPLICATE", "SUPERSEDED"}


class N3CodeAnalysisDispatchError(ContractError):
    pass


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3CodeAnalysisDispatchError(
            "RC72_N3_CODE_DISPATCH_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _strings(value: Any, name: str, *, required: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise N3CodeAnalysisDispatchError(
            "RC72_N3_CODE_DISPATCH_%s_INVALID" % name.upper()
        )
    out: List[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_%s_INVALID" % name.upper()
            )
        out.append(item.strip())
    if len(set(out)) != len(out):
        raise N3CodeAnalysisDispatchError(
            "RC72_N3_CODE_DISPATCH_%s_DUPLICATE" % name.upper()
        )
    if required and not out:
        raise N3CodeAnalysisDispatchError(
            "RC72_N3_CODE_DISPATCH_%s_REQUIRED" % name.upper()
        )
    return out


def validate_rc72_n3_code_analysis_dispatch(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "dispatch_id", "release_id", "mission_id", "release_batch_id",
        "source_commit", "mission_node_id", "node_type", "stage",
        "application_id", "target_id", "repository_ref", "source_revision",
        "workitem_id", "team_role", "execution_substrate", "worker_policy",
        "source_mapping_task_id", "source_mapping_artifact_id",
        "source_mapping_evaluation_id", "status",
    ):
        out[name] = _contracts._require_str(out, name)
    if out["node_type"] != _NODE.value:
        raise _contracts.DomainValidationError("RC72_N3_CODE_DISPATCH_NODE_INVALID")
    if out["stage"] != _STAGE:
        raise _contracts.DomainValidationError("RC72_N3_CODE_DISPATCH_STAGE_INVALID")
    if out["team_role"] != _TEAM_ROLE:
        raise _contracts.DomainValidationError("RC72_N3_CODE_DISPATCH_TEAM_ROLE_INVALID")
    if out["execution_substrate"] != _SUBSTRATE:
        raise _contracts.DomainValidationError("RC72_N3_CODE_DISPATCH_SUBSTRATE_INVALID")
    if out["worker_policy"] != _WORKER_POLICY:
        raise _contracts.DomainValidationError("RC72_N3_CODE_DISPATCH_WORKER_POLICY_INVALID")
    if out["status"] != _STATUS:
        raise _contracts.DomainValidationError("RC72_N3_CODE_DISPATCH_STATUS_INVALID")
    if not out["repository_ref"].startswith("git://"):
        raise _contracts.DomainValidationError("RC72_N3_CODE_DISPATCH_REPOSITORY_REF_INVALID")
    for name in (
        "source_evidence_refs", "canonical_evidence_ids",
        "source_mapping_evidence_refs", "required_capabilities",
    ):
        try:
            out[name] = _strings(out.get(name), name, required=True)
        except N3CodeAnalysisDispatchError as exc:
            raise _contracts.DomainValidationError(str(exc)) from exc
    if tuple(out["required_capabilities"]) != _CAPABILITIES:
        raise _contracts.DomainValidationError("RC72_N3_CODE_DISPATCH_CAPABILITIES_INVALID")
    generation = out.get("source_mapping_generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_DISPATCH_MAPPING_GENERATION_INVALID"
        )
    out["source_mapping_generation"] = generation
    for forbidden in (
        "worker_id", "worker_instance_id", "lease_id", "session_id",
        "dsh_session_id", "attempt_id", "execution_attempt_id",
        "changed_files", "changed_symbols", "git_result", "codegraph_result",
        "graph_evidence", "code_analysis_result", "output_refs",
        "evaluation_result", "node_delivery_id", "node_gate", "node_pass",
        "n4_started", "q7_pass", "field_verified", "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N3_CODE_DISPATCH_EXECUTION_CLAIM_FORBIDDEN:%s" % forbidden
            )
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError(
                "RC72_N3_CODE_DISPATCH_%s_INVALID" % name.upper()
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError(
            "RC72_N3_CODE_DISPATCH_ARTIFACT_VERSION_INVALID"
        )
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_n3_code_analysis_dispatch_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_n3_source_target_revision_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = validate_rc72_n3_code_analysis_dispatch
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


class N3CodeAnalysisDispatchService:
    """Materialize CODE_ANALYSIS WorkItems from latest accepted mappings."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n3_code_analysis_dispatch_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.reader = CandidatePayloadReader()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

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
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_CANONICAL_APPLICATIONS_REQUIRED"
            )
        mission = self._one("rc7_mission", mission_id=mission_id)
        if mission.get("release_id") != release_id:
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_MISSION_LINEAGE_MISMATCH"
            )
        n3 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE.value
        )
        if n3.get("scope_ref") != "release-batch://%s" % release_batch_id:
            raise N3CodeAnalysisDispatchError("RC72_N3_CODE_DISPATCH_N3_SCOPE_MISMATCH")
        if n3.get("state") != MissionNodeState.RUNNING.value:
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_N3_NOT_RUNNING:%s"
                % str(n3.get("state") or "UNKNOWN")
            )
        n4 = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
        )
        if n4.get("state") != MissionNodeState.NOT_STARTED.value:
            raise N3CodeAnalysisDispatchError("RC72_N3_CODE_DISPATCH_N4_ALREADY_RELEASED")
        return batch, n3, n4

    def _latest_mapping_task(
        self,
        *,
        release_batch_id: str,
        application_id: str,
        mission_id: str,
    ) -> Tuple[Dict[str, Any], int]:
        initial = [
            row for row in self.truth.query(
                "rc72_n3_source_target_dispatch", release_batch_id=release_batch_id
            )
            if row.get("mission_id") == mission_id
            and row.get("application_id") == application_id
            and row.get("source_commit") == self.source_commit
        ]
        if len(initial) != 1:
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_SOURCE_DISPATCH_NOT_UNIQUE:%s:%d"
                % (application_id, len(initial))
            )
        revisions = [
            row for row in self.truth.query(
                "rc72_n3_source_target_revision", release_batch_id=release_batch_id
            )
            if row.get("mission_id") == mission_id
            and row.get("application_id") == application_id
            and row.get("source_commit") == self.source_commit
        ]
        if revisions:
            highest = max(int(row.get("revision_generation") or 0) for row in revisions)
            latest = [
                row for row in revisions
                if int(row.get("revision_generation") or 0) == highest
            ]
            if highest < 2 or len(latest) != 1:
                raise N3CodeAnalysisDispatchError(
                    "RC72_N3_CODE_DISPATCH_LATEST_MAPPING_REVISION_NOT_UNIQUE:%s"
                    % application_id
                )
            task_id = _required(latest[0].get("revision_workitem_id"), "revision_workitem_id")
            generation = highest
        else:
            task_id = _required(initial[0].get("workitem_id"), "workitem_id")
            generation = 1
        task = self._one("rc7_task", task_id=task_id)
        if (
            task.get("mission_id") != mission_id
            or task.get("node") != _SOURCE_STAGE
            or task.get("state") != "PASS"
        ):
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_LATEST_MAPPING_NOT_PASS:%s:%s"
                % (application_id, str(task.get("state") or "UNKNOWN"))
            )
        return task, generation

    def _accepted_mapping(
        self,
        *,
        release_batch_id: str,
        application_id: str,
        mission_id: str,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], int, List[Dict[str, Any]]]:
        task, generation = self._latest_mapping_task(
            release_batch_id=release_batch_id,
            application_id=application_id,
            mission_id=mission_id,
        )
        artifact_refs = list(task.get("output_artifact_refs") or [])
        if len(artifact_refs) != 1:
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_MAPPING_ARTIFACT_NOT_UNIQUE:%s" % application_id
            )
        artifact_id = str(artifact_refs[0])
        artifact = self._one("rc7_artifact", artifact_id=artifact_id)
        if (
            artifact.get("mission_id") != mission_id
            or artifact.get("producer_task_id") != task.get("task_id")
            or artifact.get("artifact_type_name") != "SOURCE_TARGET_MAPPING_CANDIDATE"
            or artifact.get("state") != "VALID"
        ):
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_MAPPING_ARTIFACT_LINEAGE_INVALID:%s"
                % application_id
            )
        evaluation_id = _required(task.get("evaluation_id"), "evaluation_id")
        evaluation = self._one("rc7_evaluation", evaluation_id=evaluation_id)
        dimensions = evaluation.get("dimensions")
        if (
            evaluation.get("mission_id") != mission_id
            or evaluation.get("node") != _SOURCE_STAGE
            or evaluation.get("result") != "PASS"
            or artifact_id not in list(evaluation.get("artifact_refs") or [])
            or not isinstance(dimensions, dict)
            or dimensions.get("rc72_source_target_review") != _REVIEW_MARKER
            or dimensions.get("mapping_gate") != "PASS"
            or dimensions.get("application_id") != application_id
        ):
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_MAPPING_EVALUATION_INVALID:%s"
                % application_id
            )
        durable = self.reader.load(
            self.truth,
            artifact_id,
            expected_mission_id=mission_id,
            expected_task_id=str(task["task_id"]),
        )
        semantic = dict(durable.semantic_payload)
        if (
            durable.artifact_type != "SOURCE_TARGET_MAPPING_CANDIDATE"
            or semantic.get("candidate_kind") != "SOURCE_TARGET_MAPPING_CANDIDATE"
            or semantic.get("application_id") != application_id
            or semantic.get("candidate_unknowns") != []
            or semantic.get("candidate_gaps") != []
        ):
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_MAPPING_SEMANTIC_INVALID:%s" % application_id
            )
        raw_targets = semantic.get("targets")
        if not isinstance(raw_targets, list) or not raw_targets:
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_TARGETS_REQUIRED:%s" % application_id
            )
        normalized: List[Dict[str, Any]] = []
        for raw in raw_targets:
            if not isinstance(raw, Mapping):
                raise N3CodeAnalysisDispatchError(
                    "RC72_N3_CODE_DISPATCH_TARGET_INVALID:%s" % application_id
                )
            target_id = _required(raw.get("target_id"), "target_id")
            repository_ref = _required(raw.get("repository_ref"), "repository_ref")
            source_revision = _required(raw.get("source_revision"), "source_revision")
            if not repository_ref.startswith("git://"):
                raise N3CodeAnalysisDispatchError(
                    "RC72_N3_CODE_DISPATCH_REPOSITORY_REF_INVALID:%s" % target_id
                )
            source_refs = _strings(raw.get("source_evidence_refs"), "source_evidence_refs", required=True)
            evidence_ids = _strings(raw.get("canonical_evidence_ids"), "canonical_evidence_ids", required=True)
            for evidence_id in evidence_ids:
                evidence = self._one("rc7_evidence", evidence_id=evidence_id)
                if (
                    evidence.get("mission_id") != mission_id
                    or evidence.get("kind") != "N3_SOURCE_TARGET_PROOF"
                    or application_id not in list(evidence.get("subject_refs") or [])
                    or target_id not in list(evidence.get("subject_refs") or [])
                    or str(evidence.get("source_ref") or "") not in source_refs
                ):
                    raise N3CodeAnalysisDispatchError(
                        "RC72_N3_CODE_DISPATCH_TARGET_EVIDENCE_INVALID:%s:%s"
                        % (target_id, evidence_id)
                    )
            normalized.append({
                "target_id": target_id,
                "repository_ref": repository_ref,
                "source_revision": source_revision,
                "source_evidence_refs": source_refs,
                "canonical_evidence_ids": evidence_ids,
            })
        target_ids = [row["target_id"] for row in normalized]
        if len(target_ids) != len(set(target_ids)):
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_TARGET_ID_DUPLICATE:%s" % application_id
            )
        reviewed = dimensions.get("reviewed_target_ids")
        if (
            not isinstance(reviewed, list)
            or len(reviewed) != len(target_ids)
            or set(str(item) for item in reviewed) != set(target_ids)
        ):
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_REVIEW_TARGET_COVERAGE_MISMATCH:%s"
                % application_id
            )
        unresolved = [
            row for row in self.truth.query("rc7_gap", mission_id=mission_id)
            if row.get("category") == _GAP_CATEGORY
            and application_id in list(row.get("subject_refs") or [])
            and row.get("state") not in _RESOLVED_GAP_STATES
        ]
        if unresolved:
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_UNRESOLVED_MAPPING_GAP:%s:%s"
                % (
                    application_id,
                    ",".join(sorted(str(row.get("gap_id")) for row in unresolved)),
                )
            )
        return task, artifact, evaluation, generation, normalized

    @staticmethod
    def _workitem_id(
        mission_id: str,
        release_batch_id: str,
        application_id: str,
        target_id: str,
        mapping_artifact_id: str,
    ) -> str:
        return _stable_id(
            "WI-N3-CODE", mission_id, release_batch_id, application_id,
            target_id, mapping_artifact_id,
        )

    @staticmethod
    def _dispatch_id(
        mission_id: str,
        release_batch_id: str,
        application_id: str,
        target_id: str,
        mapping_evaluation_id: str,
        source_commit: str,
    ) -> str:
        return _stable_id(
            "N3DISP-CODE", mission_id, release_batch_id, application_id,
            target_id, mapping_evaluation_id, source_commit,
        )

    @staticmethod
    def _signature(payload: Mapping[str, Any]) -> Dict[str, Any]:
        keys = (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "mission_node_id", "node_type", "stage", "application_id",
            "target_id", "repository_ref", "source_revision",
            "source_mapping_generation", "workitem_id", "team_role",
            "execution_substrate", "worker_policy", "source_mapping_task_id",
            "source_mapping_artifact_id", "source_mapping_evaluation_id", "status",
        )
        out = {key: payload.get(key) for key in keys}
        for key in (
            "source_evidence_refs", "canonical_evidence_ids",
            "source_mapping_evidence_refs", "required_capabilities",
        ):
            out[key] = list(payload.get(key) or [])
        return out

    def _expected_rows(
        self,
        *,
        release_batch_id: str,
        batch: Mapping[str, Any],
        n3: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        rows: List[Dict[str, Any]] = []
        for application_id in sorted(str(item) for item in list(batch.get("application_ids") or [])):
            task, artifact, evaluation, generation, targets = self._accepted_mapping(
                release_batch_id=release_batch_id,
                application_id=application_id,
                mission_id=mission_id,
            )
            for target in sorted(targets, key=lambda item: str(item["target_id"])):
                workitem_id = self._workitem_id(
                    mission_id,
                    release_batch_id,
                    application_id,
                    str(target["target_id"]),
                    str(artifact["artifact_id"]),
                )
                rows.append({
                    "dispatch_id": self._dispatch_id(
                        mission_id,
                        release_batch_id,
                        application_id,
                        str(target["target_id"]),
                        str(evaluation["evaluation_id"]),
                        self.source_commit,
                    ),
                    "release_id": release_id,
                    "mission_id": mission_id,
                    "release_batch_id": release_batch_id,
                    "source_commit": self.source_commit,
                    "mission_node_id": str(n3["mission_node_id"]),
                    "node_type": _NODE.value,
                    "stage": _STAGE,
                    "application_id": application_id,
                    "target_id": str(target["target_id"]),
                    "repository_ref": str(target["repository_ref"]),
                    "source_revision": str(target["source_revision"]),
                    "source_evidence_refs": list(target["source_evidence_refs"]),
                    "canonical_evidence_ids": list(target["canonical_evidence_ids"]),
                    "source_mapping_generation": generation,
                    "source_mapping_task_id": str(task["task_id"]),
                    "source_mapping_artifact_id": str(artifact["artifact_id"]),
                    "source_mapping_evaluation_id": str(evaluation["evaluation_id"]),
                    "source_mapping_evidence_refs": list(evaluation.get("evidence_refs") or []),
                    "workitem_id": workitem_id,
                    "team_role": _TEAM_ROLE,
                    "execution_substrate": _SUBSTRATE,
                    "worker_policy": _WORKER_POLICY,
                    "required_capabilities": list(_CAPABILITIES),
                    "status": _STATUS,
                })
        if not rows:
            raise N3CodeAnalysisDispatchError("RC72_N3_CODE_DISPATCH_TARGET_SET_EMPTY")
        identities = [(row["application_id"], row["target_id"]) for row in rows]
        if len(identities) != len(set(identities)):
            raise N3CodeAnalysisDispatchError("RC72_N3_CODE_DISPATCH_TARGET_SET_DUPLICATE")
        return rows

    def dispatch(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        batch, n3, n4 = self._context(release_batch_id)
        expected_rows = self._expected_rows(
            release_batch_id=release_batch_id, batch=batch, n3=n3
        )
        mission_id = str(batch["mission_id"])
        release_id = str(batch["release_id"])
        existing = self.truth.query(_ARTIFACT, release_batch_id=release_batch_id)
        if existing:
            if len(existing) != len(expected_rows):
                raise N3CodeAnalysisDispatchError(
                    "RC72_N3_CODE_DISPATCH_SET_CONFLICT:%d!=%d"
                    % (len(existing), len(expected_rows))
                )
            by_id = {str(row["dispatch_id"]): row for row in existing}
            for expected in expected_rows:
                current = by_id.get(str(expected["dispatch_id"]))
                if current is None or self._signature(current) != self._signature(expected):
                    raise N3CodeAnalysisDispatchError(
                        "RC72_N3_CODE_DISPATCH_SET_IDENTITY_CONFLICT"
                    )
                task = self._one("rc7_task", task_id=str(expected["workitem_id"]))
                if (
                    task.get("mission_id") != mission_id
                    or task.get("node") != _STAGE
                    or list(task.get("required_capabilities") or []) != list(_CAPABILITIES)
                    or task.get("state") not in {
                        "READY", "LEASED", "RUNNING", "OUTPUT_PRODUCED",
                        "EVALUATING", "PASS", "REPAIR_REQUIRED",
                    }
                ):
                    raise N3CodeAnalysisDispatchError(
                        "RC72_N3_CODE_DISPATCH_RECEIPT_TASK_INVALID:%s"
                        % expected["workitem_id"]
                    )
            if n3.get("state") != MissionNodeState.RUNNING.value:
                raise N3CodeAnalysisDispatchError(
                    "RC72_N3_CODE_DISPATCH_RECEIPT_N3_NOT_RUNNING"
                )
            if n4.get("state") != MissionNodeState.NOT_STARTED.value:
                raise N3CodeAnalysisDispatchError(
                    "RC72_N3_CODE_DISPATCH_RECEIPT_N4_RELEASED"
                )
            return self._result("RESUMED", release_batch_id, n3, expected_rows)

        # Check the complete set for conflicts before registering any WorkItem.
        for expected in expected_rows:
            if self.truth.query("rc7_task", task_id=str(expected["workitem_id"])):
                raise N3CodeAnalysisDispatchError(
                    "RC72_N3_CODE_DISPATCH_WORKITEM_EXISTS_WITHOUT_RECEIPT:%s"
                    % expected["workitem_id"]
                )
        control = ClosedLoopControlPlane(self.truth, release_id, mission_id)
        for expected in expected_rows:
            control.register_task(Task(
                task_id=str(expected["workitem_id"]),
                mission_id=mission_id,
                node=_STAGE,
                task_type=_TASK_TYPE,
                objective=(
                    "Analyze accepted source target %s for application %s at exact "
                    "repository %s revision %s with evidence-backed Git change "
                    "analysis and mandatory CodeGraph impact analysis when applicable"
                    % (
                        expected["target_id"], expected["application_id"],
                        expected["repository_ref"], expected["source_revision"],
                    )
                ),
                required_capabilities=list(_CAPABILITIES),
                dependency_task_ids=[str(expected["source_mapping_task_id"])],
                input_artifact_refs=[str(expected["source_mapping_artifact_id"])],
                acceptance_criteria=[
                    "repository_ref and source_revision exactly match accepted source mapping",
                    "real Git tool evidence proves the analyzed change set and revision",
                    "Java changes require real CodeGraph query evidence and structured graph_evidence",
                    "changed files/symbols and downstream impact surfaces are evidence-backed",
                    "requirement reverse mapping is explicit; unresolved code gaps prevent PASS",
                    "independent code reviewer and deterministic code sufficiency gate are required",
                ],
                priority=20,
            ))
            task = self._one("rc7_task", task_id=str(expected["workitem_id"]))
            if task.get("state") != "READY":
                raise N3CodeAnalysisDispatchError(
                    "RC72_N3_CODE_DISPATCH_WORKITEM_NOT_READY:%s:%s"
                    % (expected["workitem_id"], str(task.get("state") or "UNKNOWN"))
                )
        now = _now()
        for expected in expected_rows:
            payload = dict(expected)
            payload.update({"created_at": now, "updated_at": now, "artifact_version": 1})
            self.truth.append_atomic(_EVENT, payload)
        persisted = self.truth.query(_ARTIFACT, release_batch_id=release_batch_id)
        if len(persisted) != len(expected_rows):
            raise N3CodeAnalysisDispatchError("RC72_N3_CODE_DISPATCH_PERSISTENCE_FAILED")
        n3_after = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NODE.value
        )
        n4_after = self._one(
            "rc72_mission_node", mission_id=mission_id, node_type=_NEXT_NODE.value
        )
        if (
            n3_after.get("state") != MissionNodeState.RUNNING.value
            or n4_after.get("state") != MissionNodeState.NOT_STARTED.value
        ):
            raise N3CodeAnalysisDispatchError(
                "RC72_N3_CODE_DISPATCH_NODE_STATE_SIDE_EFFECT_FORBIDDEN"
            )
        return self._result("DISPATCHED", release_batch_id, n3_after, expected_rows)

    @staticmethod
    def _result(
        status: str,
        release_batch_id: str,
        n3: Mapping[str, Any],
        rows: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "status": status,
            "release_batch_id": release_batch_id,
            "mission_id": str(rows[0]["mission_id"]),
            "mission_node_id": str(n3["mission_node_id"]),
            "node_state": str(n3["state"]),
            "dispatch_ids": [str(row["dispatch_id"]) for row in rows],
            "workitem_ids": [str(row["workitem_id"]) for row in rows],
            "targets": [
                {
                    "application_id": str(row["application_id"]),
                    "target_id": str(row["target_id"]),
                    "repository_ref": str(row["repository_ref"]),
                    "source_revision": str(row["source_revision"]),
                    "source_mapping_generation": int(row["source_mapping_generation"]),
                }
                for row in rows
            ],
            "execution_substrate": _SUBSTRATE,
            "worker_policy": _WORKER_POLICY,
            "team_role": _TEAM_ROLE,
            "required_capabilities": list(_CAPABILITIES),
        }


install_rc72_n3_code_analysis_dispatch_overlay()
