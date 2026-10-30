"""Promote one hash-anchored N3 source-target discovery into canonical candidate truth.

This is a trust-boundary adapter, not source-mapping acceptance. It promotes
only when the exact raw DSH bytes still match the N3 evidence anchor, the
application/worker/task lineage is intact, and every proposed target is
source-evidence-backed with no unresolved worker unknowns or gaps.

The result is a SOURCE_TARGET_MAPPING_CANDIDATE and stops at OUTPUT_PRODUCED.
An independent source-mapping reviewer is still mandatory before any mapping
can be accepted or any CODE_ANALYSIS WorkItem can be materialized.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher
from rc6_runtime.truth import TruthRuntime

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .control_plane import WorkerOutput
from .models import Artifact, Evidence, TaskStatus
from .rc72_n3_source_target_anchor import install_rc72_n3_source_target_anchor_overlay
from .rc72_n3_source_target_handoff import N3SourceTargetDshHandoffService


class N3SourceTargetPromotionError(RuntimeError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3SourceTargetPromotionError(
            "RC72_N3_PROMOTION_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class N3SourceTargetCandidatePromotionService:
    """Promote one anchored N3 source mapping candidate to OUTPUT_PRODUCED."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        mission_id: str,
        source_commit: str,
        state_root: str,
    ) -> None:
        install_rc72_n3_source_target_anchor_overlay()
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
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    @staticmethod
    def _artifact_id(mission_id: str, task_id: str) -> str:
        return _stable_id("ART-N3-SOURCE", mission_id, task_id)

    def _anchor(self, release_batch_id: str, application_id: str) -> Dict[str, Any]:
        rows = self.truth.query(
            "rc72_n3_dsh_evidence_anchor", release_batch_id=release_batch_id
        )
        exact = [
            row for row in rows
            if row.get("application_id") == application_id
            and row.get("mission_id") == self.mission_id
            and row.get("release_id") == self.release_id
            and row.get("source_commit") == self.source_commit
            and row.get("candidate_schema") == "RC72_N3_SOURCE_TARGET_CANDIDATE_V1"
        ]
        if len(exact) != 1:
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_EXACT_EVIDENCE_ANCHOR_REQUIRED:%d" % len(exact)
            )
        return exact[0]

    def _raw_candidate(
        self, anchor: Mapping[str, Any], application_id: str
    ) -> Tuple[Dict[str, Any], bytes]:
        raw_ref = _required(anchor.get("raw_output_ref"), "raw_output_ref")
        if not raw_ref.startswith("file://"):
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_RAW_OUTPUT_REF_INVALID"
            )
        path = Path(raw_ref[len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.state_root)
        except ValueError as exc:
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_RAW_OUTPUT_OUTSIDE_STATE_ROOT"
            ) from exc
        if not path.is_file():
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_RAW_OUTPUT_MISSING"
            )
        raw = path.read_bytes()
        if _sha256(raw) != anchor.get("raw_output_sha256"):
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_RAW_OUTPUT_HASH_MISMATCH"
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_RAW_OUTPUT_NOT_UTF8"
            ) from exc
        events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(text))
        if not events:
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_RAW_EVENTS_REQUIRED"
            )
        if DshHeadlessWorkerLauncher._session_id(events) != anchor.get("dsh_session_id"):
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_SESSION_ANCHOR_MISMATCH"
            )
        try:
            candidate = N3SourceTargetDshHandoffService._strict_top_level_final_json(events)
            normalized = N3SourceTargetDshHandoffService._validate_candidate(
                candidate, application_id
            )
        except Exception as exc:
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_CANDIDATE_INVALID:%s" % exc
            ) from exc
        unknowns = list(normalized.get("unknowns") or [])
        gaps = list(normalized.get("gaps") or [])
        targets = list(normalized.get("targets") or [])
        if unknowns:
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_UNRESOLVED_DISCOVERY_UNKNOWNS"
            )
        if gaps:
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_UNRESOLVED_DISCOVERY_GAPS"
            )
        if not targets:
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_SOURCE_TARGET_REQUIRED"
            )
        return normalized, raw

    def _validate_lineage(
        self,
        *,
        release_batch_id: str,
        application_id: str,
        anchor: Mapping[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        attempt = self._one(
            "rc72_n3_source_target_attempt", attempt_id=str(anchor["attempt_id"])
        )
        assignment = self._one(
            "rc72_n3_source_target_assignment",
            assignment_id=str(anchor["assignment_id"]),
        )
        dispatch = self._one(
            "rc72_n3_source_target_dispatch", dispatch_id=str(anchor["dispatch_id"])
        )
        task = self._one("rc7_task", task_id=str(anchor["workitem_id"]))
        identity = (
            ("mission_id", self.mission_id),
            ("release_batch_id", release_batch_id),
            ("application_id", application_id),
            ("source_commit", self.source_commit),
            ("workitem_id", anchor.get("workitem_id")),
            ("assignment_id", anchor.get("assignment_id")),
            ("dispatch_id", anchor.get("dispatch_id")),
            ("worker_instance_id", anchor.get("worker_instance_id")),
        )
        for name, expected in identity:
            for row_name, row in (
                ("attempt", attempt),
                ("assignment", assignment),
                ("dispatch", dispatch),
            ):
                if name in {"worker_instance_id", "assignment_id"} and row_name == "dispatch":
                    continue
                if name == "assignment_id" and row_name == "assignment":
                    actual = row.get("assignment_id")
                elif name == "dispatch_id" and row_name == "dispatch":
                    actual = row.get("dispatch_id")
                else:
                    actual = row.get(name)
                if actual != expected:
                    raise N3SourceTargetPromotionError(
                        "RC72_N3_PROMOTION_LINEAGE_MISMATCH:%s:%s"
                        % (row_name, name)
                    )
        if (
            task.get("mission_id") != self.mission_id
            or task.get("node") != "SOURCE_TARGET_DISCOVERY"
            or task.get("lease_owner") != anchor.get("worker_instance_id")
        ):
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_TASK_LINEAGE_MISMATCH"
            )
        if task.get("state") not in {
            TaskStatus.LEASED.value,
            TaskStatus.RUNNING.value,
            TaskStatus.OUTPUT_PRODUCED.value,
            TaskStatus.EVALUATING.value,
            TaskStatus.PASS.value,
            TaskStatus.REPAIR_REQUIRED.value,
        }:
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_TASK_STATE_INVALID:%s"
                % str(task.get("state") or "UNKNOWN")
            )
        return attempt, assignment, dispatch, task

    def _evidence(
        self,
        *,
        application_id: str,
        anchor: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> Tuple[Tuple[Evidence, ...], List[Dict[str, Any]]]:
        task_id = str(anchor["workitem_id"])
        attempt_id = str(anchor["attempt_id"])
        result: List[Evidence] = [
            Evidence(
                evidence_id=_stable_id(
                    "EVD-N3-SOURCE-RAW",
                    self.mission_id,
                    task_id,
                    attempt_id,
                    str(anchor["raw_output_sha256"]),
                ),
                mission_id=self.mission_id,
                kind="N3_SOURCE_TARGET_DSH_RAW_PROOF",
                source_ref="dsh://session/%s" % str(anchor["dsh_session_id"]),
                content_ref=str(anchor["raw_output_ref"]),
                subject_refs=[task_id, attempt_id, application_id],
                content_hash=str(anchor["raw_output_sha256"]),
            )
        ]
        normalized_targets: List[Dict[str, Any]] = []
        for target_index, raw_target in enumerate(list(candidate["targets"])):
            target = dict(raw_target)
            target_id = str(target["target_id"])
            canonical_evidence_ids: List[str] = []
            for evidence_index, source_ref in enumerate(list(target["evidence_refs"])):
                evidence_id = _stable_id(
                    "EVD-N3-SOURCE",
                    self.mission_id,
                    task_id,
                    application_id,
                    target_id,
                    str(target_index),
                    str(evidence_index),
                    str(source_ref),
                )
                canonical_evidence_ids.append(evidence_id)
                result.append(
                    Evidence(
                        evidence_id=evidence_id,
                        mission_id=self.mission_id,
                        kind="N3_SOURCE_TARGET_PROOF",
                        source_ref=str(source_ref),
                        content_ref=str(source_ref),
                        subject_refs=[task_id, application_id, target_id],
                    )
                )
            normalized_targets.append(
                {
                    "target_id": target_id,
                    "repository_ref": str(target["repository_ref"]),
                    "source_revision": str(target["source_revision"]),
                    "source_evidence_refs": list(target["evidence_refs"]),
                    "canonical_evidence_ids": canonical_evidence_ids,
                }
            )
        return tuple(result), normalized_targets

    def _persist_candidate_envelope(
        self,
        *,
        task: Mapping[str, Any],
        anchor: Mapping[str, Any],
        artifact_id: str,
        evidence_ids: List[str],
        application_id: str,
        targets: List[Dict[str, Any]],
    ) -> Tuple[str, str]:
        target_dir = self.state_root / "rc72-source-mapping-candidates"
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = _stable_id(
            "source-mapping-candidate",
            self.mission_id,
            str(task["task_id"]),
            str(anchor["attempt_id"]),
            str(anchor["raw_output_sha256"]),
        ) + ".json"
        target = target_dir / filename
        semantic_payload = {
            "candidate_kind": "SOURCE_TARGET_MAPPING_CANDIDATE",
            "application_id": application_id,
            "targets": list(targets),
            "candidate_unknowns": [],
            "candidate_gaps": [],
        }
        envelope = {
            "task_id": str(task["task_id"]),
            "artifact": {
                "artifact_id": artifact_id,
                "artifact_type": "SOURCE_TARGET_MAPPING_CANDIDATE",
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
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_EXISTING_OUTPUT_IDENTITY_MISMATCH"
            )
        durable = self.reader.load(
            self.truth,
            artifact_id,
            expected_mission_id=self.mission_id,
            expected_task_id=str(task["task_id"]),
        )
        semantic = dict(durable.semantic_payload)
        return {
            "status": "RESUMED",
            "task_id": str(task["task_id"]),
            "artifact_id": artifact_id,
            "content_ref": durable.content_ref,
            "content_hash": durable.content_hash,
            "application_id": semantic.get("application_id"),
            "targets": list(semantic.get("targets") or []),
            "task_state": str(task["state"]),
        }

    def promote(
        self, *, release_batch_id: str, application_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        application_id = _required(application_id, "application_id")
        anchor = self._anchor(release_batch_id, application_id)
        candidate, _raw = self._raw_candidate(anchor, application_id)
        _attempt, _assignment, _dispatch, task = self._validate_lineage(
            release_batch_id=release_batch_id,
            application_id=application_id,
            anchor=anchor,
        )
        artifact_id = self._artifact_id(self.mission_id, str(task["task_id"]))
        if task.get("state") in {
            TaskStatus.OUTPUT_PRODUCED.value,
            TaskStatus.EVALUATING.value,
            TaskStatus.PASS.value,
            TaskStatus.REPAIR_REQUIRED.value,
        }:
            return self._verify_existing(task=task, artifact_id=artifact_id)

        evidence, normalized_targets = self._evidence(
            application_id=application_id,
            anchor=anchor,
            candidate=candidate,
        )
        evidence_ids = list(dict.fromkeys(item.evidence_id for item in evidence))
        content_ref, content_hash = self._persist_candidate_envelope(
            task=task,
            anchor=anchor,
            artifact_id=artifact_id,
            evidence_ids=evidence_ids,
            application_id=application_id,
            targets=normalized_targets,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=self.mission_id,
            artifact_type="SOURCE_TARGET_MAPPING_CANDIDATE",
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
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_TASK_NOT_PROMOTABLE:%s" % state
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
            raise N3SourceTargetPromotionError(
                "RC72_N3_PROMOTION_MUST_STOP_AT_OUTPUT_PRODUCED"
            )
        durable = self.reader.load(
            self.truth,
            artifact_id,
            expected_mission_id=self.mission_id,
            expected_task_id=str(task["task_id"]),
        )
        return {
            "status": "PROMOTED",
            "release_batch_id": release_batch_id,
            "application_id": application_id,
            "task_id": str(task["task_id"]),
            "artifact_id": artifact_id,
            "content_ref": durable.content_ref,
            "content_hash": durable.content_hash,
            "evidence_ids": evidence_ids,
            "evidence_anchor_id": str(anchor["anchor_id"]),
            "targets": normalized_targets,
            "task_state": promoted.state.value,
        }
