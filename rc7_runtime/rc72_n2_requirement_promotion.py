"""Promote one hash-anchored N2 DSH candidate into canonical RC7 candidate truth.

This is a trust-boundary adapter, not a Requirement acceptance gate.  It only
promotes a candidate when the exact raw DSH bytes still match the immediate
R1 evidence anchor, re-parses the strict traceable contract, materializes
canonical Evidence for every real source locator, persists a normalized runtime
candidate envelope, and submits it as the leased WorkItem's WorkerOutput.

The result stops at OUTPUT_PRODUCED.  Independent DSH review plus deterministic
Requirement sufficiency remain mandatory before the WorkItem can PASS.
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
from .rc72_n2_candidate_guard import (
    N2TraceableRequirementDshHandoffService,
    install_rc72_n2_candidate_guard_overlay,
)


class N2RequirementPromotionError(RuntimeError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N2RequirementPromotionError(
            "RC72_N2_PROMOTION_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class N2RequirementCandidatePromotionService:
    """Promote one anchored Requirement candidate to canonical OUTPUT_PRODUCED."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        mission_id: str,
        source_commit: str,
        state_root: str,
    ) -> None:
        install_rc72_n2_candidate_guard_overlay()
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.mission_id = _required(mission_id, "mission_id")
        self.source_commit = _required(source_commit, "source_commit")
        self.state_root = Path(_required(state_root, "state_root")).expanduser().resolve()
        self.control = ClosedLoopControlPlane(
            truth, self.release_id, self.mission_id
        )
        self.reader = CandidatePayloadReader()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    @staticmethod
    def _artifact_id(mission_id: str, task_id: str) -> str:
        # Deliberately identical to DshTaskWorkerBridge.expected_output for a
        # non-PRODUCE REQUIREMENT_ANALYSIS WorkItem, preserving inherited RC7
        # CandidatePayloadReader / evaluator compatibility.
        return _stable_id("ART-TASK", mission_id, task_id)

    def _anchor(
        self, release_batch_id: str, requirement_id: str
    ) -> Dict[str, Any]:
        rows = self.truth.query(
            "rc72_n2_dsh_evidence_anchor",
            release_batch_id=release_batch_id,
        )
        exact = [
            row for row in rows
            if row.get("requirement_id") == requirement_id
            and row.get("mission_id") == self.mission_id
            and row.get("release_id") == self.release_id
            and row.get("source_commit") == self.source_commit
            and row.get("candidate_schema")
            == "RC72_N2_REQUIREMENT_CANDIDATE_V1_TRACEABLE"
        ]
        if len(exact) != 1:
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_EXACT_EVIDENCE_ANCHOR_REQUIRED:%d"
                % len(exact)
            )
        return exact[0]

    def _raw_candidate(
        self, anchor: Mapping[str, Any], requirement_id: str
    ) -> Tuple[Dict[str, Any], bytes]:
        raw_ref = _required(anchor.get("raw_output_ref"), "raw_output_ref")
        if not raw_ref.startswith("file://"):
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_RAW_OUTPUT_REF_INVALID"
            )
        path = Path(raw_ref[len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.state_root)
        except ValueError as exc:
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_RAW_OUTPUT_OUTSIDE_STATE_ROOT"
            ) from exc
        if not path.is_file():
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_RAW_OUTPUT_MISSING"
            )
        raw = path.read_bytes()
        if _sha256(raw) != anchor.get("raw_output_sha256"):
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_RAW_OUTPUT_HASH_MISMATCH"
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_RAW_OUTPUT_NOT_UTF8"
            ) from exc
        events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(text))
        if not events:
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_RAW_EVENTS_REQUIRED"
            )
        if DshHeadlessWorkerLauncher._session_id(events) != anchor.get(
            "dsh_session_id"
        ):
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_SESSION_ANCHOR_MISMATCH"
            )
        candidate = DshHeadlessWorkerLauncher._final_json(events)
        try:
            normalized = N2TraceableRequirementDshHandoffService._validate_candidate(
                candidate, requirement_id
            )
        except Exception as exc:
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_TRACEABLE_CANDIDATE_INVALID:%s" % exc
            ) from exc
        return normalized, raw

    def _validate_lineage(
        self,
        *,
        release_batch_id: str,
        requirement_id: str,
        anchor: Mapping[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        attempt = self._one(
            "rc72_n2_requirement_attempt",
            attempt_id=str(anchor["attempt_id"]),
        )
        assignment = self._one(
            "rc72_n2_requirement_assignment",
            assignment_id=str(anchor["assignment_id"]),
        )
        dispatch = self._one(
            "rc72_n2_requirement_dispatch",
            dispatch_id=str(anchor["dispatch_id"]),
        )
        task = self._one("rc7_task", task_id=str(anchor["workitem_id"]))
        identity = (
            ("mission_id", self.mission_id),
            ("release_batch_id", release_batch_id),
            ("requirement_id", requirement_id),
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
                # dispatch deliberately has no worker/assignment identity.
                if name in {"worker_instance_id", "assignment_id"} and row_name == "dispatch":
                    continue
                if name == "assignment_id" and row_name == "assignment":
                    actual = row.get("assignment_id")
                elif name == "dispatch_id" and row_name == "dispatch":
                    actual = row.get("dispatch_id")
                else:
                    actual = row.get(name)
                if actual != expected:
                    raise N2RequirementPromotionError(
                        "RC72_N2_PROMOTION_LINEAGE_MISMATCH:%s:%s"
                        % (row_name, name)
                    )
        if (
            task.get("mission_id") != self.mission_id
            or task.get("node") != "REQUIREMENT_ANALYSIS"
            or task.get("lease_owner") != anchor.get("worker_instance_id")
        ):
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_TASK_LINEAGE_MISMATCH"
            )
        if task.get("state") not in {
            TaskStatus.LEASED.value,
            TaskStatus.RUNNING.value,
            TaskStatus.OUTPUT_PRODUCED.value,
            TaskStatus.EVALUATING.value,
            TaskStatus.PASS.value,
            TaskStatus.REPAIR_REQUIRED.value,
        }:
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_TASK_STATE_INVALID:%s"
                % str(task.get("state") or "UNKNOWN")
            )
        return attempt, assignment, dispatch, task

    def _evidence(
        self,
        *,
        requirement_id: str,
        anchor: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> Tuple[Evidence, ...]:
        task_id = str(anchor["workitem_id"])
        attempt_id = str(anchor["attempt_id"])
        result: List[Evidence] = [
            Evidence(
                evidence_id=_stable_id(
                    "EVD-N2-RAW",
                    self.mission_id,
                    task_id,
                    attempt_id,
                    str(anchor["raw_output_sha256"]),
                ),
                mission_id=self.mission_id,
                kind="N2_REQUIREMENT_DSH_RAW_PROOF",
                source_ref="dsh://session/%s" % str(anchor["dsh_session_id"]),
                content_ref=str(anchor["raw_output_ref"]),
                subject_refs=[task_id, attempt_id, requirement_id],
                content_hash=str(anchor["raw_output_sha256"]),
            )
        ]
        source_refs = list(candidate["facts"]["source_refs"])
        for index, source_ref in enumerate(source_refs):
            result.append(
                Evidence(
                    evidence_id=_stable_id(
                        "EVD-N2-SOURCE",
                        self.mission_id,
                        task_id,
                        requirement_id,
                        str(index),
                        source_ref,
                    ),
                    mission_id=self.mission_id,
                    kind="N2_REQUIREMENT_SOURCE_PROOF",
                    # Both aliases intentionally preserve the exact worker
                    # locator so DshRequirementEvaluator can bind trace_links
                    # to canonical Evidence ids without inventing new aliases.
                    source_ref=source_ref,
                    content_ref=source_ref,
                    subject_refs=[task_id, requirement_id],
                )
            )
        return tuple(result)

    def _semantic_payload(
        self,
        candidate: Mapping[str, Any],
    ) -> Dict[str, Any]:
        facts = candidate["facts"]
        analysis = dict(facts["analysis"])
        payload = dict(analysis)
        payload.update(
            {
                "requirement_id": facts["requirement_id"],
                "sst_ids": list(facts["sst_ids"]),
                "source_refs": list(facts["source_refs"]),
                "candidate_unknowns": list(candidate.get("unknowns") or []),
                "candidate_gaps": list(candidate.get("gaps") or []),
                # Force the RC7.1 denominator-accountability gate even when a
                # Requirement happens to be small.
                "sufficiency_v2_required": True,
            }
        )
        return payload

    def _persist_candidate_envelope(
        self,
        *,
        task: Mapping[str, Any],
        anchor: Mapping[str, Any],
        artifact_id: str,
        evidence_ids: List[str],
        semantic_payload: Mapping[str, Any],
    ) -> Tuple[str, str]:
        target_dir = self.state_root / "rc7-worker-candidates"
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = _stable_id(
            "candidate",
            self.mission_id,
            str(task["task_id"]),
            str(anchor["attempt_id"]),
            str(anchor["worker_instance_id"]),
        ) + ".json"
        target = target_dir / filename
        envelope = {
            "task_id": str(task["task_id"]),
            "artifact": {
                "artifact_id": artifact_id,
                "artifact_type": "REQUIREMENT_ANALYSIS_OUTPUT",
                "content_ref": str(anchor["raw_output_ref"]),
                "parent_refs": list(task.get("input_artifact_refs") or []),
                "evidence_refs": list(evidence_ids),
            },
            "semantic_payload": dict(semantic_payload),
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
        serialized = json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        ) + "\n"
        raw = serialized.encode("utf-8")
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
        self,
        *,
        task: Mapping[str, Any],
        artifact_id: str,
    ) -> Dict[str, Any]:
        refs = list(task.get("output_artifact_refs") or [])
        if refs != [artifact_id]:
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_EXISTING_OUTPUT_IDENTITY_MISMATCH"
            )
        payload = self.reader.load(
            self.truth,
            artifact_id,
            expected_mission_id=self.mission_id,
            expected_task_id=str(task["task_id"]),
        )
        return {
            "status": "RESUMED",
            "task_id": str(task["task_id"]),
            "artifact_id": artifact_id,
            "content_ref": payload.content_ref,
            "content_hash": payload.content_hash,
            "task_state": str(task["state"]),
        }

    def promote(
        self, *, release_batch_id: str, requirement_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        requirement_id = _required(requirement_id, "requirement_id")
        anchor = self._anchor(release_batch_id, requirement_id)
        candidate, _raw = self._raw_candidate(anchor, requirement_id)
        _attempt, _assignment, _dispatch, task = self._validate_lineage(
            release_batch_id=release_batch_id,
            requirement_id=requirement_id,
            anchor=anchor,
        )
        artifact_id = self._artifact_id(
            self.mission_id, str(task["task_id"])
        )

        if task.get("state") in {
            TaskStatus.OUTPUT_PRODUCED.value,
            TaskStatus.EVALUATING.value,
            TaskStatus.PASS.value,
            TaskStatus.REPAIR_REQUIRED.value,
        }:
            return self._verify_existing(task=task, artifact_id=artifact_id)

        evidence = self._evidence(
            requirement_id=requirement_id,
            anchor=anchor,
            candidate=candidate,
        )
        evidence_ids = list(dict.fromkeys(item.evidence_id for item in evidence))
        semantic_payload = self._semantic_payload(candidate)
        content_ref, content_hash = self._persist_candidate_envelope(
            task=task,
            anchor=anchor,
            artifact_id=artifact_id,
            evidence_ids=evidence_ids,
            semantic_payload=semantic_payload,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            mission_id=self.mission_id,
            artifact_type="REQUIREMENT_ANALYSIS_OUTPUT",
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
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_TASK_NOT_PROMOTABLE:%s" % state
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
            raise N2RequirementPromotionError(
                "RC72_N2_PROMOTION_MUST_STOP_AT_OUTPUT_PRODUCED"
            )
        # Re-open through the same reader the independent evaluator will use;
        # promotion is not considered complete if the durable envelope cannot
        # survive the evaluator-facing hash/identity checks.
        durable = self.reader.load(
            self.truth,
            artifact_id,
            expected_mission_id=self.mission_id,
            expected_task_id=str(task["task_id"]),
        )
        return {
            "status": "PROMOTED",
            "release_batch_id": release_batch_id,
            "requirement_id": requirement_id,
            "task_id": str(task["task_id"]),
            "artifact_id": artifact_id,
            "content_ref": durable.content_ref,
            "content_hash": durable.content_hash,
            "evidence_ids": evidence_ids,
            "evidence_anchor_id": str(anchor["anchor_id"]),
            "sst_ids": list(candidate["facts"]["sst_ids"]),
            "candidate_unknowns": list(candidate.get("unknowns") or []),
            "candidate_gaps": list(candidate.get("gaps") or []),
            "task_state": promoted.state.value,
        }
