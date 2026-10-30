"""RC7.2 N1 governed handoff -> evidence anchor -> Delivery -> Gate bridge.

The worker Attempt remains execution truth only.  This module adds the missing
anti-tamper and admission boundary:

1. wrap the existing real DSH handoff and immediately anchor the raw JSONL bytes
   (SHA-256) in canonical R1;
2. replay only that anchored JSONL to create canonical RC7 Artifact/Evidence and
   an RC7.2 NodeDelivery;
3. apply a deterministic runtime-owned NodeGate; only a PASS gate can close the
   WorkItem, PASS N1 and release N2.

No path in this module may claim Q7 PASS, field_verified or BANK_FINAL.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .models import Artifact, ContractError, Evaluation, EvaluationResult, Evidence, TaskStatus
from .rc72_domain import AutonomousMissionNode, MissionNodeState, NodeDelivery, NodeGate, NodeGateDecision
from .rc72_mission_node_handoff import N1DshHandoffService, install_rc72_mission_node_handoff_overlay
from .rc72_state_machine import RC72StateMachine
from .rc72_truth import install_rc72_truth_overlay
from .truth_overlay import install_rc7_truth_overlay


_NODE = AutonomousMissionNode.N1_REALITY
_NEXT_NODE = AutonomousMissionNode.N2_REQUIREMENT
_STAGE = "REALITY_RECON"
_ARTIFACT_TYPE = "N1_REALITY_CANDIDATE"

_ANCHOR_ARTIFACT = "rc72_n1_dsh_evidence_anchor"
_ANCHOR_EVENT = "RC72_N1_DSH_EVIDENCE_ANCHOR_UPSERTED"
_ANCHOR_BUCKET = "rc72_n1_dsh_evidence_anchors"

_REVIEWER_WORKER_ID = "rc72-runtime-n1-gate"
_REVIEWER_SESSION_ID = "runtime://rc72/n1-gate/v1"

_CRITERIA = (
    "N1_ATTEMPT_CANONICAL",
    "N1_RAW_EVIDENCE_IMMUTABLE",
    "N1_DSH_SESSION_MATCH",
    "N1_AUTHORIZED_TOOL_CALL_OBSERVED",
    "N1_STATUS_CANDIDATE",
    "N1_FACTS_OBJECT_REQUIRED",
    "N1_RELEASE_ID_MATCH",
    "N1_RELEASE_BATCH_ID_MATCH",
    "N1_SOURCE_COMMIT_MATCH",
    "N1_DEPLOYMENT_RECORDS_REQUIRED",
    "N1_ENVIRONMENT_CHECKS_REQUIRED",
    "N1_CAPABILITY_CHECKS_REQUIRED",
    "N1_UNKNOWNS_EMPTY",
    "N1_GAPS_EMPTY",
    "N1_CANONICAL_EVIDENCE_REQUIRED",
)


class N1CompletionError(ContractError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N1CompletionError("RC72_N1_%s_REQUIRED" % name.upper())
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:24])


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _uniq(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _gap_strings(values: Any) -> List[str]:
    if not isinstance(values, list):
        return ["INVALID_GAP_SHAPE"]
    out = []
    for value in values:
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
        else:
            out.append(repr(value))
    return out


def validate_rc72_n1_dsh_evidence_anchor(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "anchor_id",
        "release_id",
        "mission_id",
        "release_batch_id",
        "source_commit",
        "attempt_id",
        "mission_node_id",
        "workitem_id",
        "worker_instance_id",
        "dsh_session_id",
        "candidate_output_ref",
        "raw_output_ref",
        "raw_output_sha256",
    ):
        out[name] = _contracts._require_str(out, name)
    if not out["dsh_session_id"].startswith("session-"):
        raise _contracts.DomainValidationError("RC72_N1_ANCHOR_DSH_SESSION_INVALID")
    if not out["raw_output_ref"].startswith("file://"):
        raise _contracts.DomainValidationError("RC72_N1_ANCHOR_RAW_OUTPUT_REF_INVALID")
    if not out["raw_output_sha256"].startswith("sha256:") or len(out["raw_output_sha256"]) != 71:
        raise _contracts.DomainValidationError("RC72_N1_ANCHOR_SHA256_INVALID")
    value = out.get("created_at")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _contracts.DomainValidationError("RC72_N1_ANCHOR_CREATED_AT_INVALID")
    for forbidden in (
        "node_gate",
        "node_gate_id",
        "node_pass",
        "q7_pass",
        "field_verified",
        "bank_final",
    ):
        if forbidden in out:
            raise _contracts.DomainValidationError(
                "RC72_N1_ANCHOR_BUSINESS_CLAIM_FORBIDDEN:%s" % forbidden
            )
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("RC72_N1_ANCHOR_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ANCHOR_ARTIFACT
    return out


def install_rc72_n1_completion_overlay() -> None:
    install_rc7_truth_overlay()
    install_rc72_truth_overlay()
    install_rc72_mission_node_handoff_overlay()
    _contracts.VALIDATORS[_ANCHOR_ARTIFACT] = validate_rc72_n1_dsh_evidence_anchor
    _truth.BUCKETS[_ANCHOR_ARTIFACT] = _ANCHOR_BUCKET
    _truth.IDENTITY_FIELDS[_ANCHOR_ARTIFACT] = "anchor_id"
    _truth.EVENT_TYPES[_ANCHOR_EVENT] = (_ANCHOR_ARTIFACT, "anchor_id")


def _ensure_anchor_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _ANCHOR_BUCKET):
        setattr(projection, _ANCHOR_BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ANCHOR_ARTIFACT, {})


def _attempt_raw_file(attempt: Mapping[str, Any]) -> Tuple[str, Path]:
    file_refs = [
        ref
        for ref in attempt.get("runtime_evidence_refs", [])
        if isinstance(ref, str) and ref.startswith("file://")
    ]
    if len(file_refs) != 1:
        raise N1CompletionError(
            "RC72_N1_RAW_DSH_EVIDENCE_REQUIRED:%d" % len(file_refs)
        )
    content_ref = file_refs[0]
    path = Path(content_ref[len("file://"):])
    if not path.is_file():
        raise N1CompletionError("RC72_N1_RAW_DSH_EVIDENCE_NOT_FOUND")
    return content_ref, path


def _parse_raw_candidate(
    attempt: Mapping[str, Any],
    *,
    expected_sha256: Optional[str] = None,
) -> Tuple[Dict[str, Any], str, str, Tuple[Dict[str, Any], ...]]:
    content_ref, path = _attempt_raw_file(attempt)
    raw = path.read_bytes()
    if not raw:
        raise N1CompletionError("RC72_N1_RAW_DSH_EVIDENCE_EMPTY")
    observed_hash = _sha256(raw)
    if expected_sha256 is not None and observed_hash != expected_sha256:
        raise N1CompletionError("RC72_N1_RAW_DSH_EVIDENCE_HASH_MISMATCH")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise N1CompletionError("RC72_N1_RAW_DSH_EVIDENCE_NOT_UTF8") from exc

    events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(text))
    if not events:
        raise N1CompletionError("RC72_N1_RAW_DSH_EVENTS_REQUIRED")
    session_id = DshHeadlessWorkerLauncher._session_id(events)
    if session_id != attempt.get("dsh_session_id"):
        raise N1CompletionError("RC72_N1_DSH_SESSION_EVIDENCE_MISMATCH")

    parsed_calls = tuple(DshHeadlessWorkerLauncher._tool_calls(events))
    observed = [
        {
            "call_ref": str(item.get("call_ref") or ""),
            "tool_name": str(item.get("tool_name") or ""),
        }
        for item in attempt.get("observed_tool_calls", [])
    ]
    if list(parsed_calls) != observed:
        raise N1CompletionError("RC72_N1_TOOL_CALL_EVIDENCE_MISMATCH")

    candidate = DshHeadlessWorkerLauncher._final_json(events)
    if not isinstance(candidate, dict) or not candidate:
        raise N1CompletionError("RC72_N1_CANDIDATE_JSON_REQUIRED")
    for key in ("status", "facts", "unknowns", "gaps"):
        if key not in candidate:
            raise N1CompletionError("RC72_N1_CANDIDATE_FIELD_REQUIRED:%s" % key)
    if not isinstance(candidate.get("unknowns"), list):
        raise N1CompletionError("RC72_N1_CANDIDATE_UNKNOWNS_INVALID")
    if not isinstance(candidate.get("gaps"), list):
        raise N1CompletionError("RC72_N1_CANDIDATE_GAPS_INVALID")
    return candidate, content_ref, observed_hash, parsed_calls


class N1EvidenceAnchorService:
    """Anchor the exact raw DSH handoff bytes immediately after Attempt admission."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n1_completion_overlay()
        _ensure_anchor_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")

    @staticmethod
    def _anchor_id(attempt_id: str) -> str:
        return _stable_id("N1ANCH", attempt_id, "DSH_RAW_OUTPUT")

    def _attempt(self, release_batch_id: str) -> Dict[str, Any]:
        rows = self.truth.query(
            "rc72_mission_node_worker_attempt",
            release_batch_id=release_batch_id,
        )
        exact = [
            row
            for row in rows
            if row.get("source_commit") == self.source_commit
            and row.get("node_type") == _NODE.value
            and row.get("stage") == _STAGE
            and row.get("state") == "WORKER_COMPLETED_PENDING_DELIVERY"
            and row.get("handoff_status") == "DSH_SESSION_OBSERVED"
            and row.get("process_outcome") == "SUCCEEDED"
        ]
        if len(exact) != 1:
            raise N1CompletionError(
                "RC72_N1_EXACT_HANDOFF_ATTEMPT_REQUIRED:%d" % len(exact)
            )
        return exact[0]

    def anchor(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        attempt = self._attempt(release_batch_id)
        _candidate, content_ref, raw_hash, _calls = _parse_raw_candidate(attempt)
        anchor_id = self._anchor_id(str(attempt["attempt_id"]))
        existing = self.truth.query(_ANCHOR_ARTIFACT, anchor_id=anchor_id)
        expected = {
            "release_id": attempt.get("release_id"),
            "mission_id": attempt.get("mission_id"),
            "release_batch_id": attempt.get("release_batch_id"),
            "source_commit": self.source_commit,
            "attempt_id": attempt.get("attempt_id"),
            "mission_node_id": attempt.get("mission_node_id"),
            "workitem_id": attempt.get("workitem_id"),
            "worker_instance_id": attempt.get("worker_instance_id"),
            "dsh_session_id": attempt.get("dsh_session_id"),
            "candidate_output_ref": attempt.get("candidate_output_ref"),
            "raw_output_ref": content_ref,
            "raw_output_sha256": raw_hash,
        }
        if existing:
            if len(existing) != 1:
                raise N1CompletionError("RC72_N1_EVIDENCE_ANCHOR_NOT_UNIQUE")
            for key, value in expected.items():
                if existing[0].get(key) != value:
                    raise N1CompletionError("RC72_N1_EVIDENCE_ANCHOR_CONFLICT")
            return dict(existing[0])

        payload = dict(expected)
        payload.update(
            {
                "anchor_id": anchor_id,
                "created_at": int(attempt.get("updated_at") or attempt.get("created_at") or 0),
                "artifact_version": 1,
            }
        )
        self.truth.append_atomic(_ANCHOR_EVENT, payload)
        rows = self.truth.query(_ANCHOR_ARTIFACT, anchor_id=anchor_id)
        if len(rows) != 1:
            raise N1CompletionError("RC72_N1_EVIDENCE_ANCHOR_PERSISTENCE_FAILED")
        return rows[0]


class N1GovernedHandoffService:
    """Preferred RC7.2 N1 handoff path: real DSH Attempt plus immediate hash anchor."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        source_commit: str,
        launcher: DshHeadlessWorkerLauncher,
        allowed_tools: Sequence[str],
    ) -> None:
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")
        self.handoff_service = N1DshHandoffService(
            truth,
            source_commit=self.source_commit,
            launcher=launcher,
            allowed_tools=allowed_tools,
        )
        self.anchor_service = N1EvidenceAnchorService(
            truth, source_commit=self.source_commit
        )

    def handoff(self, *, release_batch_id: str) -> Dict[str, Any]:
        result = self.handoff_service.handoff(release_batch_id=release_batch_id)
        anchor = self.anchor_service.anchor(release_batch_id=release_batch_id)
        out = dict(result)
        out.update(
            {
                "evidence_anchor_id": anchor["anchor_id"],
                "raw_output_sha256": anchor["raw_output_sha256"],
            }
        )
        return out


class N1DeliveryGateService:
    """Promote one anchored N1 DSH handoff into canonical Delivery/Gate truth."""

    def __init__(self, truth: TruthRuntime, *, source_commit: str) -> None:
        install_rc72_n1_completion_overlay()
        _ensure_anchor_bucket(truth)
        self.truth = truth
        self.source_commit = _required(source_commit, "source_commit")

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N1CompletionError(
                "RC72_N1_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows))
            )
        return rows[0]

    def _attempt(self, release_batch_id: str) -> Dict[str, Any]:
        return N1EvidenceAnchorService(
            self.truth, source_commit=self.source_commit
        )._attempt(release_batch_id)

    def _anchor(self, attempt: Mapping[str, Any]) -> Dict[str, Any]:
        anchor_id = N1EvidenceAnchorService._anchor_id(str(attempt["attempt_id"]))
        anchor = self._one(_ANCHOR_ARTIFACT, anchor_id=anchor_id)
        if (
            anchor.get("attempt_id") != attempt.get("attempt_id")
            or anchor.get("source_commit") != self.source_commit
            or anchor.get("mission_id") != attempt.get("mission_id")
            or anchor.get("worker_instance_id") != attempt.get("worker_instance_id")
            or anchor.get("dsh_session_id") != attempt.get("dsh_session_id")
            or anchor.get("candidate_output_ref") != attempt.get("candidate_output_ref")
        ):
            raise N1CompletionError("RC72_N1_EVIDENCE_ANCHOR_LINEAGE_MISMATCH")
        return anchor

    def _raw_candidate(
        self, attempt: Mapping[str, Any], anchor: Mapping[str, Any]
    ) -> Tuple[Dict[str, Any], str, str, Tuple[Dict[str, Any], ...]]:
        return _parse_raw_candidate(
            attempt,
            expected_sha256=_required(anchor.get("raw_output_sha256"), "raw_output_sha256"),
        )

    def _lineage(
        self, attempt: Mapping[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        batch = self._one(
            "rc72_release_batch",
            release_batch_id=str(attempt["release_batch_id"]),
        )
        node = self._one(
            "rc72_mission_node",
            mission_node_id=str(attempt["mission_node_id"]),
        )
        assignment = self._one(
            "rc72_mission_node_worker_assignment",
            assignment_id=str(attempt["assignment_id"]),
        )
        task = self._one("rc7_task", task_id=str(attempt["workitem_id"]))
        expected = (
            batch.get("mission_id") == attempt.get("mission_id")
            and batch.get("release_id") == attempt.get("release_id")
            and node.get("mission_id") == attempt.get("mission_id")
            and node.get("node_type") == _NODE.value
            and assignment.get("mission_id") == attempt.get("mission_id")
            and assignment.get("mission_node_id") == attempt.get("mission_node_id")
            and assignment.get("workitem_id") == attempt.get("workitem_id")
            and assignment.get("worker_instance_id") == attempt.get("worker_instance_id")
            and assignment.get("source_commit") == self.source_commit
            and task.get("mission_id") == attempt.get("mission_id")
            and task.get("node") == _STAGE
            and task.get("lease_owner") == attempt.get("worker_instance_id")
        )
        if not expected:
            raise N1CompletionError("RC72_N1_LINEAGE_MISMATCH")
        return batch, node, assignment, task

    @staticmethod
    def _artifact_id(attempt_id: str) -> str:
        return _stable_id("N1ART", attempt_id, "REALITY_CANDIDATE")

    @staticmethod
    def _evidence_id(attempt_id: str, raw_hash: str) -> str:
        return _stable_id("N1EVD", attempt_id, raw_hash)

    @staticmethod
    def _delivery_id(attempt_id: str, raw_hash: str) -> str:
        return _stable_id("N1DEL", attempt_id, raw_hash)

    @staticmethod
    def _gate_id(delivery_id: str, raw_hash: str) -> str:
        return _stable_id("N1GATE", delivery_id, raw_hash, "RUNTIME_GATE_V1")

    @staticmethod
    def _evaluation_id(delivery_id: str, raw_hash: str) -> str:
        return _stable_id("N1EVAL", delivery_id, raw_hash, "RUNTIME_GATE_V1")

    def _canonical_output(
        self,
        attempt: Mapping[str, Any],
        assignment: Mapping[str, Any],
        *,
        content_ref: str,
        raw_hash: str,
    ) -> Tuple[str, str]:
        mission_id = str(attempt["mission_id"])
        release_id = str(attempt["release_id"])
        workitem_id = str(attempt["workitem_id"])
        worker_id = str(attempt["worker_instance_id"])
        attempt_id = str(attempt["attempt_id"])
        artifact_id = self._artifact_id(attempt_id)
        evidence_id = self._evidence_id(attempt_id, raw_hash)

        control = ClosedLoopControlPlane(self.truth, release_id, mission_id)
        current = control.scheduler.task(workitem_id)
        evidence_rows = self.truth.query("rc7_evidence", evidence_id=evidence_id)
        artifact_rows = self.truth.query("rc7_artifact", artifact_id=artifact_id)

        if current.state == TaskStatus.LEASED:
            current = control.start(workitem_id, worker_ref=worker_id)
        if current.state == TaskStatus.RUNNING:
            if evidence_rows or artifact_rows:
                raise N1CompletionError(
                    "RC72_N1_PARTIAL_WORKER_OUTPUT_REQUIRES_RECOVERY"
                )
            evidence = Evidence(
                evidence_id=evidence_id,
                mission_id=mission_id,
                kind="N1_DSH_HANDOFF_RECORD",
                source_ref="dsh://session/%s" % str(attempt["dsh_session_id"]),
                content_ref=content_ref,
                subject_refs=[attempt_id, workitem_id, str(attempt["mission_node_id"])],
                content_hash=raw_hash,
            )
            artifact = Artifact(
                artifact_id=artifact_id,
                mission_id=mission_id,
                artifact_type=_ARTIFACT_TYPE,
                producer_task_id=workitem_id,
                content_ref=content_ref,
                parent_refs=list(assignment.get("input_refs") or []),
                evidence_refs=[evidence_id],
                content_hash=raw_hash,
            )
            current = control.submit_worker_output(
                WorkerOutput(
                    task_id=workitem_id,
                    worker_ref=worker_id,
                    artifacts=(artifact,),
                    evidence=(evidence,),
                )
            )
            evidence_rows = self.truth.query("rc7_evidence", evidence_id=evidence_id)
            artifact_rows = self.truth.query("rc7_artifact", artifact_id=artifact_id)

        if current.state not in {TaskStatus.OUTPUT_PRODUCED, TaskStatus.PASS}:
            raise N1CompletionError(
                "RC72_N1_WORKITEM_OUTPUT_STATE_INVALID:%s" % current.state.value
            )
        if len(evidence_rows) != 1 or len(artifact_rows) != 1:
            raise N1CompletionError("RC72_N1_CANONICAL_OUTPUT_NOT_UNIQUE")
        artifact = artifact_rows[0]
        evidence = evidence_rows[0]
        if (
            artifact.get("mission_id") != mission_id
            or artifact.get("producer_task_id") != workitem_id
            or artifact.get("content_ref") != content_ref
            or artifact.get("content_hash") != raw_hash
            or evidence.get("mission_id") != mission_id
            or evidence.get("content_ref") != content_ref
            or evidence.get("content_hash") != raw_hash
        ):
            raise N1CompletionError("RC72_N1_CANONICAL_OUTPUT_IDENTITY_MISMATCH")
        if artifact_id not in list(
            self._one("rc7_task", task_id=workitem_id).get("output_artifact_refs") or []
        ):
            raise N1CompletionError("RC72_N1_WORKITEM_OUTPUT_REF_MISSING")
        return artifact_id, evidence_id

    def admit_delivery(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        attempt = self._attempt(release_batch_id)
        anchor = self._anchor(attempt)
        _batch, node, assignment, _task = self._lineage(attempt)
        candidate, content_ref, raw_hash, _calls = self._raw_candidate(attempt, anchor)
        artifact_id, evidence_id = self._canonical_output(
            attempt,
            assignment,
            content_ref=content_ref,
            raw_hash=raw_hash,
        )
        delivery_id = self._delivery_id(str(attempt["attempt_id"]), raw_hash)
        existing = self.truth.query("rc72_node_delivery", delivery_id=delivery_id)
        if existing:
            if len(existing) != 1:
                raise N1CompletionError("RC72_N1_DELIVERY_NOT_UNIQUE")
            return {
                "status": "RESUMED",
                "delivery_id": delivery_id,
                "artifact_id": artifact_id,
                "evidence_id": evidence_id,
                "node_state": self._one(
                    "rc72_mission_node",
                    mission_node_id=str(attempt["mission_node_id"]),
                )["state"],
                "workitem_state": self._one(
                    "rc7_task", task_id=str(attempt["workitem_id"])
                )["state"],
            }

        if node.get("state") != MissionNodeState.RUNNING.value:
            raise N1CompletionError(
                "RC72_N1_DELIVERY_REQUIRES_RUNNING_NODE:%s" % node.get("state")
            )
        known_gaps = _uniq(
            _gap_strings(candidate.get("unknowns")) + _gap_strings(candidate.get("gaps"))
        )
        delivery = NodeDelivery(
            delivery_id=delivery_id,
            mission_id=str(attempt["mission_id"]),
            mission_node_id=str(attempt["mission_node_id"]),
            node_type=_NODE,
            version=1,
            producer_ref=str(attempt["worker_instance_id"]),
            input_refs=_uniq(
                list(assignment.get("input_refs") or [])
                + [
                    "rc72-attempt://%s" % str(attempt["attempt_id"]),
                    "rc72-anchor://%s" % str(anchor["anchor_id"]),
                    str(attempt["candidate_output_ref"]),
                ]
            ),
            artifact_refs=[artifact_id],
            evidence_refs=[evidence_id],
            known_gaps=known_gaps,
            created_by_workitems=[str(attempt["workitem_id"])],
        )
        RC72StateMachine(
            self.truth, release_id=str(attempt["release_id"])
        ).submit_delivery(delivery)
        return {
            "status": "DELIVERY_ADMITTED",
            "delivery_id": delivery_id,
            "artifact_id": artifact_id,
            "evidence_id": evidence_id,
            "raw_hash": raw_hash,
            "node_state": MissionNodeState.REVIEW_PENDING.value,
            "workitem_state": TaskStatus.OUTPUT_PRODUCED.value,
        }

    def _evaluate(
        self,
        attempt: Mapping[str, Any],
        anchor: Mapping[str, Any],
        delivery: Mapping[str, Any],
    ) -> Tuple[List[str], List[str], Dict[str, Any], str]:
        candidate, content_ref, raw_hash, calls = self._raw_candidate(attempt, anchor)
        failed: List[str] = []

        if attempt.get("state") != "WORKER_COMPLETED_PENDING_DELIVERY":
            failed.append("N1_ATTEMPT_CANONICAL")

        artifact_refs = list(delivery.get("artifact_refs") or [])
        evidence_refs = list(delivery.get("evidence_refs") or [])
        if len(artifact_refs) != 1:
            failed.append("N1_RAW_EVIDENCE_IMMUTABLE")
        else:
            rows = self.truth.query("rc7_artifact", artifact_id=artifact_refs[0])
            if len(rows) != 1:
                failed.append("N1_RAW_EVIDENCE_IMMUTABLE")
            else:
                artifact = rows[0]
                if (
                    artifact.get("content_ref") != content_ref
                    or artifact.get("content_hash") != raw_hash
                    or anchor.get("raw_output_sha256") != raw_hash
                ):
                    failed.append("N1_RAW_EVIDENCE_IMMUTABLE")

        if attempt.get("dsh_session_id") != anchor.get("dsh_session_id"):
            failed.append("N1_DSH_SESSION_MATCH")

        authorized = set(attempt.get("authorized_tools") or [])
        if not calls or any(call.get("tool_name") not in authorized for call in calls):
            failed.append("N1_AUTHORIZED_TOOL_CALL_OBSERVED")

        if str(candidate.get("status") or "").upper() != "CANDIDATE":
            failed.append("N1_STATUS_CANDIDATE")

        facts = candidate.get("facts")
        if not isinstance(facts, Mapping) or not facts:
            failed.append("N1_FACTS_OBJECT_REQUIRED")
            facts = {}

        if facts.get("release_id") != attempt.get("release_id"):
            failed.append("N1_RELEASE_ID_MATCH")
        if facts.get("release_batch_id") != attempt.get("release_batch_id"):
            failed.append("N1_RELEASE_BATCH_ID_MATCH")
        if facts.get("source_commit") != self.source_commit:
            failed.append("N1_SOURCE_COMMIT_MATCH")

        for key, code in (
            ("deployment_records", "N1_DEPLOYMENT_RECORDS_REQUIRED"),
            ("environment_checks", "N1_ENVIRONMENT_CHECKS_REQUIRED"),
            ("capability_checks", "N1_CAPABILITY_CHECKS_REQUIRED"),
        ):
            value = facts.get(key)
            if not isinstance(value, list) or not value:
                failed.append(code)

        if not isinstance(candidate.get("unknowns"), list) or candidate.get("unknowns"):
            failed.append("N1_UNKNOWNS_EMPTY")
        if not isinstance(candidate.get("gaps"), list) or candidate.get("gaps"):
            failed.append("N1_GAPS_EMPTY")

        if not evidence_refs:
            failed.append("N1_CANONICAL_EVIDENCE_REQUIRED")
        else:
            for evidence_id in evidence_refs:
                rows = self.truth.query("rc7_evidence", evidence_id=evidence_id)
                if (
                    len(rows) != 1
                    or rows[0].get("mission_id") != attempt.get("mission_id")
                    or rows[0].get("content_hash") != raw_hash
                ):
                    failed.append("N1_CANONICAL_EVIDENCE_REQUIRED")
                    break

        failed = _uniq(failed)
        passed = [code for code in _CRITERIA if code not in failed]
        return passed, failed, candidate, raw_hash

    def _ensure_forward(
        self,
        runtime: RC72StateMachine,
        mission_id: str,
        gate_id: str,
    ) -> str:
        n2 = runtime.node_by_type(mission_id, _NEXT_NODE)
        if n2.get("state") == MissionNodeState.NOT_STARTED.value:
            runtime.forward(_NODE, _NEXT_NODE, source_gate_id=gate_id)
            n2 = runtime.node_by_type(mission_id, _NEXT_NODE)
        if n2.get("state") != MissionNodeState.READY.value:
            raise N1CompletionError(
                "RC72_N1_N2_NOT_READY_AFTER_PASS:%s" % n2.get("state")
            )
        return str(n2["state"])

    def evaluate_and_advance(self, *, release_batch_id: str) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        attempt = self._attempt(release_batch_id)
        anchor = self._anchor(attempt)
        self._lineage(attempt)
        _candidate, _content_ref, raw_hash, _calls = self._raw_candidate(attempt, anchor)
        delivery_id = self._delivery_id(str(attempt["attempt_id"]), raw_hash)
        delivery = self._one("rc72_node_delivery", delivery_id=delivery_id)
        runtime = RC72StateMachine(
            self.truth, release_id=str(attempt["release_id"])
        )
        gate_id = self._gate_id(delivery_id, raw_hash)
        existing_gate = self.truth.query("rc72_node_gate", gate_id=gate_id)
        if existing_gate:
            if len(existing_gate) != 1:
                raise N1CompletionError("RC72_N1_GATE_NOT_UNIQUE")
            decision = str(existing_gate[0]["decision"])
            n2_state = runtime.node_by_type(
                str(attempt["mission_id"]), _NEXT_NODE
            )["state"]
            if decision == NodeGateDecision.PASS.value:
                n2_state = self._ensure_forward(
                    runtime, str(attempt["mission_id"]), gate_id
                )
            return {
                "status": "RESUMED",
                "gate_id": gate_id,
                "decision": decision,
                "n1_state": runtime.node(str(attempt["mission_node_id"]))["state"],
                "n2_state": n2_state,
                "workitem_state": self._one(
                    "rc7_task", task_id=str(attempt["workitem_id"])
                )["state"],
            }

        node = runtime.node(str(attempt["mission_node_id"]))
        if node.get("state") != MissionNodeState.REVIEW_PENDING.value:
            raise N1CompletionError(
                "RC72_N1_GATE_REQUIRES_REVIEW_PENDING:%s" % node.get("state")
            )
        passed, failed, _candidate, raw_hash = self._evaluate(attempt, anchor, delivery)
        decision = (
            NodeGateDecision.PASS
            if not failed
            else NodeGateDecision.NEEDS_REVISION
        )
        evidence_refs = list(delivery.get("evidence_refs") or [])
        artifact_refs = list(delivery.get("artifact_refs") or [])

        if decision == NodeGateDecision.PASS:
            control = ClosedLoopControlPlane(
                self.truth,
                str(attempt["release_id"]),
                str(attempt["mission_id"]),
            )
            task = control.scheduler.task(str(attempt["workitem_id"]))
            evaluation_id = self._evaluation_id(delivery_id, raw_hash)
            if task.state == TaskStatus.OUTPUT_PRODUCED:
                control.accept_evaluation(
                    str(attempt["workitem_id"]),
                    evaluation=Evaluation(
                        evaluation_id=evaluation_id,
                        mission_id=str(attempt["mission_id"]),
                        node=_STAGE,
                        artifact_refs=artifact_refs,
                        result=EvaluationResult.PASS,
                        evaluator_ref=_REVIEWER_WORKER_ID,
                        dimensions={
                            "node_type": _NODE.value,
                            "delivery_id": delivery_id,
                            "criteria": list(_CRITERIA),
                            "passed": list(passed),
                            "failed": [],
                            "deterministic_runtime_gate": True,
                            "field_verified": False,
                        },
                        evidence_refs=evidence_refs,
                    ),
                )
            elif task.state != TaskStatus.PASS:
                raise N1CompletionError(
                    "RC72_N1_WORKITEM_NOT_EVALUATABLE:%s" % task.state.value
                )

        gate = NodeGate(
            gate_id=gate_id,
            mission_id=str(attempt["mission_id"]),
            mission_node_id=str(attempt["mission_node_id"]),
            node_type=_NODE,
            delivery_id=delivery_id,
            decision=decision,
            reviewer_worker_id=_REVIEWER_WORKER_ID,
            reviewer_session_id=_REVIEWER_SESSION_ID,
            criteria=list(_CRITERIA),
            passed=passed,
            failed=failed,
            evidence_refs=evidence_refs,
            return_node=_NODE if failed else None,
            reason=(
                "deterministic N1 reality contract satisfied"
                if not failed
                else "deterministic N1 reality failures: %s" % ",".join(failed)
            ),
        )
        runtime.apply_gate(gate)
        n2_state = runtime.node_by_type(
            str(attempt["mission_id"]), _NEXT_NODE
        )["state"]
        if decision == NodeGateDecision.PASS:
            n2_state = self._ensure_forward(
                runtime, str(attempt["mission_id"]), gate_id
            )
        return {
            "status": "GATED",
            "gate_id": gate_id,
            "decision": decision.value,
            "passed": passed,
            "failed": failed,
            "n1_state": runtime.node(str(attempt["mission_node_id"]))["state"],
            "n2_state": n2_state,
            "workitem_state": self._one(
                "rc7_task", task_id=str(attempt["workitem_id"])
            )["state"],
            "field_verified": False,
            "bank_final": False,
        }

    def complete(self, *, release_batch_id: str) -> Dict[str, Any]:
        delivery = self.admit_delivery(release_batch_id=release_batch_id)
        gate = self.evaluate_and_advance(release_batch_id=release_batch_id)
        return {"delivery": delivery, "gate": gate}


install_rc72_n1_completion_overlay()
