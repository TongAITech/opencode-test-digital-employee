"""Promote one hash-anchored RC7.2 N5 discovery proposal into candidate truth.

Promotion is a trust-boundary adapter only. It replays the exact raw DSH bytes
named by the N5 evidence anchor, verifies the hash/session/tool/assignment
lineage, and persists a durable DATA_DISCOVERY_CANDIDATE envelope plus raw DSH
evidence.

The candidate is not a verified DataRef. This layer deliberately stops the
WorkItem at OUTPUT_PRODUCED and never registers a data resource, creates a
DataRequirement binding, acquires a DataLease, passes N5, or releases N6.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .models import Artifact, Evidence, TaskStatus
from .rc72_n5_data_discovery_anchor import install_rc72_n5_data_discovery_anchor_overlay
from .rc72_n5_data_discovery_handoff import N5DataDiscoveryDshHandoffService


class N5DataDiscoveryPromotionError(RuntimeError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N5DataDiscoveryPromotionError(
            "RC72_N5_DISCOVERY_PROMOTION_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class N5DataDiscoveryCandidatePromotionService:
    """Promote one anchored DataRequirement discovery result to OUTPUT_PRODUCED."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        mission_id: str,
        source_commit: str,
        state_root: str,
    ) -> None:
        install_rc72_n5_data_discovery_anchor_overlay()
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.mission_id = _required(mission_id, "mission_id")
        self.source_commit = _required(source_commit, "source_commit")
        self.state_root = Path(_required(state_root, "state_root")).expanduser().resolve()
        self.control = ClosedLoopControlPlane(truth, self.release_id, self.mission_id)
        self.reader = CandidatePayloadReader()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    @staticmethod
    def _artifact_id(mission_id: str, task_id: str) -> str:
        return _stable_id("ART-N5-DATA", mission_id, task_id)

    def _anchor(self, release_batch_id: str, data_requirement_id: str) -> Dict[str, Any]:
        exact = [
            row for row in self.truth.query(
                "rc72_n5_data_discovery_evidence_anchor",
                release_batch_id=release_batch_id,
            )
            if row.get("data_requirement_id") == data_requirement_id
            and row.get("mission_id") == self.mission_id
            and row.get("release_id") == self.release_id
            and row.get("source_commit") == self.source_commit
            and row.get("candidate_schema") == "RC72_N5_DATA_DISCOVERY_CANDIDATE_V1"
        ]
        if len(exact) != 1:
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_EXACT_EVIDENCE_ANCHOR_REQUIRED:%d"
                % len(exact)
            )
        return exact[0]

    def _validate_lineage(
        self,
        *,
        release_batch_id: str,
        data_requirement_id: str,
        anchor: Mapping[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        attempt = self._one(
            "rc72_n5_data_discovery_attempt", attempt_id=str(anchor["attempt_id"])
        )
        assignment = self._one(
            "rc72_n5_data_discovery_assignment",
            assignment_id=str(anchor["assignment_id"]),
        )
        dispatch = self._one(
            "rc72_n5_data_discovery_dispatch", dispatch_id=str(anchor["dispatch_id"])
        )
        requirement = self._one(
            "rc72_n5_data_requirement", data_requirement_id=data_requirement_id
        )
        task = self._one("rc7_task", task_id=str(anchor["workitem_id"]))

        expected = {
            "release_id": self.release_id,
            "mission_id": self.mission_id,
            "release_batch_id": release_batch_id,
            "source_commit": self.source_commit,
            "data_requirement_id": data_requirement_id,
            "resolution_plan_id": anchor.get("resolution_plan_id"),
            "source_case_sha256": anchor.get("source_case_sha256"),
            "requirement_id": anchor.get("requirement_id"),
            "sst_id": anchor.get("sst_id"),
            "obligation_id": anchor.get("obligation_id"),
            "case_id": anchor.get("case_id"),
            "mission_node_id": anchor.get("mission_node_id"),
            "workitem_id": anchor.get("workitem_id"),
            "dispatch_id": anchor.get("dispatch_id"),
        }
        for field, value in expected.items():
            for label, row in (
                ("attempt", attempt),
                ("assignment", assignment),
                ("dispatch", dispatch),
            ):
                if row.get(field) != value:
                    raise N5DataDiscoveryPromotionError(
                        "RC72_N5_DISCOVERY_PROMOTION_LINEAGE_MISMATCH:%s:%s"
                        % (label, field)
                    )
        for field in (
            "release_id", "mission_id", "release_batch_id", "source_commit",
            "data_requirement_id", "source_case_sha256", "requirement_id",
            "sst_id", "obligation_id", "case_id", "mission_node_id",
        ):
            if requirement.get(field) != expected[field]:
                raise N5DataDiscoveryPromotionError(
                    "RC72_N5_DISCOVERY_PROMOTION_REQUIREMENT_LINEAGE_MISMATCH:%s"
                    % field
                )
        if requirement.get("status") != "UNRESOLVED":
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_REQUIREMENT_ALREADY_RESOLVED"
            )
        if (
            task.get("mission_id") != self.mission_id
            or task.get("node") != "TEST_DATA"
            or task.get("lease_owner") != anchor.get("worker_instance_id")
        ):
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_TASK_LINEAGE_MISMATCH"
            )
        if task.get("state") not in {
            TaskStatus.LEASED.value,
            TaskStatus.RUNNING.value,
            TaskStatus.OUTPUT_PRODUCED.value,
            TaskStatus.EVALUATING.value,
            TaskStatus.PASS.value,
            TaskStatus.REPAIR_REQUIRED.value,
        }:
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_TASK_STATE_INVALID:%s"
                % str(task.get("state") or "UNKNOWN")
            )
        if self.truth.query("rc72_n5_data_binding", data_requirement_id=data_requirement_id):
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_BINDING_ALREADY_EXISTS"
            )
        return attempt, assignment, dispatch, requirement, task

    def _raw_candidate(
        self,
        anchor: Mapping[str, Any],
        *,
        data_requirement_id: str,
    ) -> Tuple[Dict[str, Any], bytes]:
        raw_ref = _required(anchor.get("raw_output_ref"), "raw_output_ref")
        if not raw_ref.startswith("file://"):
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_RAW_OUTPUT_REF_INVALID"
            )
        path = Path(raw_ref[len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.state_root)
        except ValueError as exc:
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_RAW_OUTPUT_OUTSIDE_STATE_ROOT"
            ) from exc
        if not path.is_file():
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_RAW_OUTPUT_MISSING"
            )
        raw = path.read_bytes()
        if _sha256(raw) != anchor.get("raw_output_sha256"):
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_RAW_OUTPUT_HASH_MISMATCH"
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_RAW_OUTPUT_NOT_UTF8"
            ) from exc
        events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(text))
        if not events:
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_RAW_EVENTS_REQUIRED"
            )
        if DshHeadlessWorkerLauncher._session_id(events) != anchor.get("dsh_session_id"):
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_SESSION_ANCHOR_MISMATCH"
            )
        attempt = self._one(
            "rc72_n5_data_discovery_attempt", attempt_id=str(anchor["attempt_id"])
        )
        parsed_calls = tuple(DshHeadlessWorkerLauncher._tool_calls(events))
        observed_calls = tuple(
            {
                "call_ref": str(item.get("call_ref") or ""),
                "tool_name": str(item.get("tool_name") or ""),
            }
            for item in list(attempt.get("observed_tool_calls") or [])
        )
        if parsed_calls != observed_calls:
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_TOOL_CALL_EVIDENCE_MISMATCH"
            )
        finals = [
            event for event in events
            if str(event.get("type") or event.get("event") or event.get("kind") or "").lower()
            == "final"
        ]
        if len(finals) != 1 or not isinstance(finals[0].get("text"), str):
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_FINAL_EVENT_NOT_UNIQUE"
            )
        try:
            candidate = json.loads(str(finals[0]["text"]))
        except json.JSONDecodeError as exc:
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_FINAL_JSON_INVALID"
            ) from exc
        assignment = self._one(
            "rc72_n5_data_discovery_assignment",
            assignment_id=str(anchor["assignment_id"]),
        )
        try:
            normalized = N5DataDiscoveryDshHandoffService._validate_candidate(
                candidate, assignment
            )
        except Exception as exc:
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_CANDIDATE_INVALID:%s" % exc
            ) from exc
        if normalized.get("data_requirement_id") != data_requirement_id:
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_CANDIDATE_REQUIREMENT_MISMATCH"
            )
        return normalized, raw

    def _evidence(self, *, anchor: Mapping[str, Any]) -> Tuple[Evidence, ...]:
        task_id = str(anchor["workitem_id"])
        attempt_id = str(anchor["attempt_id"])
        data_requirement_id = str(anchor["data_requirement_id"])
        return (
            Evidence(
                evidence_id=_stable_id(
                    "EVD-N5-DATA-RAW",
                    self.mission_id,
                    task_id,
                    attempt_id,
                    str(anchor["raw_output_sha256"]),
                ),
                mission_id=self.mission_id,
                kind="N5_DATA_DISCOVERY_DSH_RAW_PROOF",
                source_ref="dsh://session/%s" % str(anchor["dsh_session_id"]),
                content_ref=str(anchor["raw_output_ref"]),
                subject_refs=[task_id, attempt_id, data_requirement_id],
                content_hash=str(anchor["raw_output_sha256"]),
            ),
        )

    def _persist_candidate_envelope(
        self,
        *,
        task: Mapping[str, Any],
        anchor: Mapping[str, Any],
        artifact_id: str,
        evidence_ids: Sequence[str],
        candidate: Mapping[str, Any],
    ) -> Tuple[str, str]:
        target_dir = self.state_root / "rc72-data-discovery-candidates"
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = _stable_id(
            "data-discovery-candidate",
            self.mission_id,
            str(task["task_id"]),
            str(anchor["attempt_id"]),
            str(anchor["raw_output_sha256"]),
        ) + ".json"
        target = target_dir / filename
        semantic_payload = {
            "candidate_kind": "DATA_DISCOVERY_CANDIDATE",
            "release_batch_id": candidate["release_batch_id"],
            "data_requirement_id": candidate["data_requirement_id"],
            "resolution_plan_id": candidate["resolution_plan_id"],
            "case_id": candidate["case_id"],
            "strategy": candidate["strategy"],
            "observations": list(candidate["observations"]),
            "verification_plan": list(candidate["verification_plan"]),
            "candidate_unknowns": list(candidate.get("unknowns") or []),
            "candidate_gaps": list(candidate.get("gaps") or []),
        }
        envelope = {
            "task_id": str(task["task_id"]),
            "artifact": {
                "artifact_id": artifact_id,
                "artifact_type": "DATA_DISCOVERY_CANDIDATE",
                "content_ref": str(anchor["raw_output_ref"]),
                "parent_refs": list(task.get("input_artifact_refs") or []),
                "evidence_refs": list(evidence_ids),
            },
            "semantic_payload": semantic_payload,
            "runtime_lineage": {
                "attempt_id": anchor["attempt_id"],
                "assignment_id": anchor["assignment_id"],
                "dispatch_id": anchor["dispatch_id"],
                "dsh_session_id": anchor["dsh_session_id"],
                "raw_output_sha256": anchor["raw_output_sha256"],
                "evidence_anchor_id": anchor["anchor_id"],
                "source_commit": anchor["source_commit"],
            },
        }
        raw = (
            json.dumps(
                envelope,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                separators=(",", ": "),
            )
            + "\n"
        ).encode("utf-8")
        content_hash = _sha256(raw)
        fd, temp_name = tempfile.mkstemp(
            prefix=filename + ".", suffix=".tmp", dir=str(target_dir)
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return "file://" + str(target.resolve()), content_hash

    def _verify_existing(
        self, *, task: Mapping[str, Any], artifact_id: str
    ) -> Dict[str, Any]:
        refs = list(task.get("output_artifact_refs") or [])
        if refs != [artifact_id]:
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_EXISTING_OUTPUT_IDENTITY_MISMATCH"
            )
        durable = self.reader.load(
            self.truth,
            artifact_id,
            expected_mission_id=self.mission_id,
            expected_task_id=str(task["task_id"]),
        )
        semantic = dict(durable.semantic_payload)
        if semantic.get("candidate_kind") != "DATA_DISCOVERY_CANDIDATE":
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_EXISTING_KIND_MISMATCH"
            )
        return {
            "status": "RESUMED",
            "release_batch_id": semantic.get("release_batch_id"),
            "data_requirement_id": semantic.get("data_requirement_id"),
            "resolution_plan_id": semantic.get("resolution_plan_id"),
            "case_id": semantic.get("case_id"),
            "strategy": semantic.get("strategy"),
            "task_id": str(task["task_id"]),
            "artifact_id": artifact_id,
            "content_ref": durable.content_ref,
            "content_hash": durable.content_hash,
            "observation_count": len(list(semantic.get("observations") or [])),
            "verification_plan": list(semantic.get("verification_plan") or []),
            "candidate_unknowns": list(semantic.get("candidate_unknowns") or []),
            "candidate_gaps": list(semantic.get("candidate_gaps") or []),
            "task_state": str(task["state"]),
        }

    def promote(
        self, *, release_batch_id: str, data_requirement_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        data_requirement_id = _required(data_requirement_id, "data_requirement_id")
        anchor = self._anchor(release_batch_id, data_requirement_id)
        _attempt, _assignment, _dispatch, _requirement, task = self._validate_lineage(
            release_batch_id=release_batch_id,
            data_requirement_id=data_requirement_id,
            anchor=anchor,
        )
        candidate, _raw = self._raw_candidate(
            anchor, data_requirement_id=data_requirement_id
        )
        artifact_id = self._artifact_id(self.mission_id, str(task["task_id"]))
        if task.get("state") in {
            TaskStatus.OUTPUT_PRODUCED.value,
            TaskStatus.EVALUATING.value,
            TaskStatus.PASS.value,
            TaskStatus.REPAIR_REQUIRED.value,
        }:
            return self._verify_existing(task=task, artifact_id=artifact_id)

        evidence = self._evidence(anchor=anchor)
        evidence_ids = [item.evidence_id for item in evidence]
        content_ref, content_hash = self._persist_candidate_envelope(
            task=task,
            anchor=anchor,
            artifact_id=artifact_id,
            evidence_ids=evidence_ids,
            candidate=candidate,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=self.mission_id,
            artifact_type="DATA_DISCOVERY_CANDIDATE",
            producer_task_id=str(task["task_id"]),
            content_ref=content_ref,
            parent_refs=list(task.get("input_artifact_refs") or []),
            evidence_refs=evidence_ids,
            content_hash=content_hash,
        )
        worker_id = str(anchor["worker_instance_id"])
        state = str(task["state"])
        if state == TaskStatus.LEASED.value:
            self.control.start(str(task["task_id"]), worker_ref=worker_id)
        elif state != TaskStatus.RUNNING.value:
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_TASK_NOT_PROMOTABLE:%s" % state
            )
        promoted = self.control.submit_worker_output(
            WorkerOutput(
                task_id=str(task["task_id"]),
                worker_ref=worker_id,
                artifacts=(artifact,),
                evidence=evidence,
            )
        )
        if promoted.state != TaskStatus.OUTPUT_PRODUCED:
            raise N5DataDiscoveryPromotionError(
                "RC72_N5_DISCOVERY_PROMOTION_MUST_STOP_AT_OUTPUT_PRODUCED"
            )
        durable = self.reader.load(
            self.truth,
            artifact_id,
            expected_mission_id=self.mission_id,
            expected_task_id=str(task["task_id"]),
        )
        semantic = dict(durable.semantic_payload)
        return {
            "status": "PROMOTED",
            "release_batch_id": release_batch_id,
            "data_requirement_id": data_requirement_id,
            "resolution_plan_id": semantic["resolution_plan_id"],
            "case_id": semantic["case_id"],
            "strategy": semantic["strategy"],
            "task_id": str(task["task_id"]),
            "artifact_id": artifact_id,
            "content_ref": durable.content_ref,
            "content_hash": durable.content_hash,
            "evidence_ids": evidence_ids,
            "evidence_anchor_id": str(anchor["anchor_id"]),
            "observation_count": len(list(semantic["observations"])),
            "verification_plan": list(semantic["verification_plan"]),
            "candidate_unknowns": list(semantic["candidate_unknowns"]),
            "candidate_gaps": list(semantic["candidate_gaps"]),
            "task_state": promoted.state.value,
        }


__all__ = [
    "N5DataDiscoveryCandidatePromotionService",
    "N5DataDiscoveryPromotionError",
]
