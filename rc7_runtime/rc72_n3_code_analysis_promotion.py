"""Promote one hash-anchored N3 code-analysis result into canonical candidate truth.

This is a trust-boundary adapter, not code-analysis acceptance.  It promotes
only when the exact raw DSH bytes still match the evidence anchor, immutable
repository/revision/target lineage is intact, the candidate has no unresolved
worker unknowns/gaps, and every symbol/mapping evidence reference is backed by
the candidate evidence set.

The result is a CODE_ANALYSIS_CANDIDATE and stops at OUTPUT_PRODUCED.  An
independent reviewer and deterministic N3 sufficiency gate remain mandatory
before N3 can PASS or N4 can be released.
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
from .rc72_n3_code_analysis_anchor import install_rc72_n3_code_analysis_anchor_overlay
from .rc72_n3_code_analysis_handoff import N3CodeAnalysisDshHandoffService


class N3CodeAnalysisPromotionError(RuntimeError):
    pass


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3CodeAnalysisPromotionError(
            "RC72_N3_CODE_PROMOTION_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class N3CodeAnalysisCandidatePromotionService:
    """Promote one anchored N3 CODE_ANALYSIS candidate to OUTPUT_PRODUCED."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        mission_id: str,
        source_commit: str,
        state_root: str,
    ) -> None:
        install_rc72_n3_code_analysis_anchor_overlay()
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
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    @staticmethod
    def _artifact_id(mission_id: str, task_id: str) -> str:
        return _stable_id("ART-N3-CODE", mission_id, task_id)

    def _anchor(self, release_batch_id: str, target_id: str) -> Dict[str, Any]:
        rows = self.truth.query(
            "rc72_n3_code_analysis_evidence_anchor",
            release_batch_id=release_batch_id,
        )
        exact = [
            row for row in rows
            if row.get("target_id") == target_id
            and row.get("mission_id") == self.mission_id
            and row.get("release_id") == self.release_id
            and row.get("source_commit") == self.source_commit
            and row.get("candidate_schema") == "RC72_N3_CODE_ANALYSIS_CANDIDATE_V1"
        ]
        if len(exact) != 1:
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_EXACT_EVIDENCE_ANCHOR_REQUIRED:%d"
                % len(exact)
            )
        return exact[0]

    def _raw_candidate(
        self,
        anchor: Mapping[str, Any],
        assignment: Mapping[str, Any],
    ) -> Tuple[Dict[str, Any], bytes]:
        raw_ref = _required(anchor.get("raw_output_ref"), "raw_output_ref")
        if not raw_ref.startswith("file://"):
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_RAW_OUTPUT_REF_INVALID"
            )
        path = Path(raw_ref[len("file://"):]).expanduser().resolve()
        try:
            path.relative_to(self.state_root)
        except ValueError as exc:
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_RAW_OUTPUT_OUTSIDE_STATE_ROOT"
            ) from exc
        if not path.is_file():
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_RAW_OUTPUT_MISSING"
            )
        raw = path.read_bytes()
        if _sha256(raw) != anchor.get("raw_output_sha256"):
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_RAW_OUTPUT_HASH_MISMATCH"
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_RAW_OUTPUT_NOT_UTF8"
            ) from exc
        events = tuple(DshHeadlessWorkerLauncher._parse_json_lines(text))
        if not events:
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_RAW_EVENTS_REQUIRED"
            )
        if DshHeadlessWorkerLauncher._session_id(events) != anchor.get("dsh_session_id"):
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_SESSION_ANCHOR_MISMATCH"
            )
        try:
            candidate = N3CodeAnalysisDshHandoffService._strict_top_level_final_json(events)
            normalized = N3CodeAnalysisDshHandoffService._validate_candidate(
                candidate, assignment
            )
        except Exception as exc:
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_CANDIDATE_INVALID:%s" % exc
            ) from exc
        if list(normalized.get("unknowns") or []):
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_UNRESOLVED_ANALYSIS_UNKNOWNS"
            )
        if list(normalized.get("gaps") or []):
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_UNRESOLVED_ANALYSIS_GAPS"
            )
        for field in ("requirement_ids", "changed_files", "changed_symbols"):
            if not list(normalized.get(field) or []):
                raise N3CodeAnalysisPromotionError(
                    "RC72_N3_CODE_PROMOTION_%s_REQUIRED" % field.upper()
                )
        evidence_refs = set(str(ref) for ref in normalized["evidence_refs"])
        for item in normalized["symbol_explanations"]:
            symbol = _required(item.get("symbol"), "symbol_explanation_symbol")
            if symbol not in normalized["changed_symbols"]:
                raise N3CodeAnalysisPromotionError(
                    "RC72_N3_CODE_PROMOTION_SYMBOL_EXPLANATION_NOT_CHANGED:%s"
                    % symbol
                )
            refs = [str(ref) for ref in list(item.get("evidence_refs") or [])]
            if not set(refs).issubset(evidence_refs):
                raise N3CodeAnalysisPromotionError(
                    "RC72_N3_CODE_PROMOTION_SYMBOL_EVIDENCE_NOT_CANONICAL:%s"
                    % symbol
                )
        for item in normalized["reverse_requirement_mappings"]:
            requirement_id = _required(
                item.get("requirement_id"), "reverse_mapping_requirement_id"
            )
            symbol = _required(item.get("symbol"), "reverse_mapping_symbol")
            evidence_ref = _required(
                item.get("evidence_ref"), "reverse_mapping_evidence_ref"
            )
            if requirement_id not in normalized["requirement_ids"]:
                raise N3CodeAnalysisPromotionError(
                    "RC72_N3_CODE_PROMOTION_REVERSE_REQUIREMENT_NOT_CANONICAL:%s"
                    % requirement_id
                )
            if symbol not in normalized["changed_symbols"]:
                raise N3CodeAnalysisPromotionError(
                    "RC72_N3_CODE_PROMOTION_REVERSE_SYMBOL_NOT_CHANGED:%s" % symbol
                )
            if evidence_ref not in evidence_refs:
                raise N3CodeAnalysisPromotionError(
                    "RC72_N3_CODE_PROMOTION_REVERSE_EVIDENCE_NOT_CANONICAL:%s"
                    % evidence_ref
                )
        return normalized, raw

    def _validate_lineage(
        self,
        *,
        release_batch_id: str,
        target_id: str,
        anchor: Mapping[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        attempt = self._one(
            "rc72_n3_code_analysis_attempt", attempt_id=str(anchor["attempt_id"])
        )
        assignment = self._one(
            "rc72_n3_code_analysis_assignment",
            assignment_id=str(anchor["assignment_id"]),
        )
        dispatch = self._one(
            "rc72_n3_code_analysis_dispatch", dispatch_id=str(anchor["dispatch_id"])
        )
        task = self._one("rc7_task", task_id=str(anchor["workitem_id"]))
        expected = {
            "mission_id": self.mission_id,
            "release_batch_id": release_batch_id,
            "target_id": target_id,
            "source_commit": self.source_commit,
            "workitem_id": anchor.get("workitem_id"),
            "assignment_id": anchor.get("assignment_id"),
            "dispatch_id": anchor.get("dispatch_id"),
            "worker_instance_id": anchor.get("worker_instance_id"),
            "application_id": anchor.get("application_id"),
        }
        for name, value in expected.items():
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
                if actual != value:
                    raise N3CodeAnalysisPromotionError(
                        "RC72_N3_CODE_PROMOTION_LINEAGE_MISMATCH:%s:%s"
                        % (row_name, name)
                    )
        for field in (
            "repository_ref", "source_revision", "source_mapping_generation",
            "source_mapping_task_id", "source_mapping_artifact_id",
            "source_mapping_evaluation_id",
        ):
            if attempt.get(field) != assignment.get(field):
                raise N3CodeAnalysisPromotionError(
                    "RC72_N3_CODE_PROMOTION_ANALYSIS_TARGET_MISMATCH:%s" % field
                )
        if (
            task.get("mission_id") != self.mission_id
            or task.get("node") != "CODE_ANALYSIS"
            or task.get("lease_owner") != anchor.get("worker_instance_id")
        ):
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_TASK_LINEAGE_MISMATCH"
            )
        if task.get("state") not in {
            TaskStatus.LEASED.value,
            TaskStatus.RUNNING.value,
            TaskStatus.OUTPUT_PRODUCED.value,
            TaskStatus.EVALUATING.value,
            TaskStatus.PASS.value,
            TaskStatus.REPAIR_REQUIRED.value,
        }:
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_TASK_STATE_INVALID:%s"
                % str(task.get("state") or "UNKNOWN")
            )
        return attempt, assignment, dispatch, task

    def _evidence(
        self,
        *,
        anchor: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> Tuple[Evidence, ...]:
        task_id = str(anchor["workitem_id"])
        attempt_id = str(anchor["attempt_id"])
        target_id = str(anchor["target_id"])
        result: List[Evidence] = [
            Evidence(
                evidence_id=_stable_id(
                    "EVD-N3-CODE-RAW",
                    self.mission_id,
                    task_id,
                    attempt_id,
                    str(anchor["raw_output_sha256"]),
                ),
                mission_id=self.mission_id,
                kind="N3_CODE_ANALYSIS_DSH_RAW_PROOF",
                source_ref="dsh://session/%s" % str(anchor["dsh_session_id"]),
                content_ref=str(anchor["raw_output_ref"]),
                subject_refs=[task_id, attempt_id, target_id],
                content_hash=str(anchor["raw_output_sha256"]),
            )
        ]
        for index, source_ref in enumerate(list(candidate["evidence_refs"])):
            result.append(
                Evidence(
                    evidence_id=_stable_id(
                        "EVD-N3-CODE",
                        self.mission_id,
                        task_id,
                        target_id,
                        str(index),
                        str(source_ref),
                    ),
                    mission_id=self.mission_id,
                    kind="N3_CODE_ANALYSIS_PROOF",
                    source_ref=str(source_ref),
                    content_ref=str(source_ref),
                    subject_refs=[task_id, target_id],
                )
            )
        return tuple(result)

    def _persist_candidate_envelope(
        self,
        *,
        task: Mapping[str, Any],
        anchor: Mapping[str, Any],
        artifact_id: str,
        evidence_ids: List[str],
        candidate: Mapping[str, Any],
    ) -> Tuple[str, str]:
        target_dir = self.state_root / "rc72-code-analysis-candidates"
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = _stable_id(
            "code-analysis-candidate",
            self.mission_id,
            str(task["task_id"]),
            str(anchor["attempt_id"]),
            str(anchor["raw_output_sha256"]),
        ) + ".json"
        target = target_dir / filename
        semantic_payload = {
            "candidate_kind": "CODE_ANALYSIS_CANDIDATE",
            "application_id": candidate["application_id"],
            "target_id": candidate["target_id"],
            "repository_ref": candidate["repository_ref"],
            "source_revision": candidate["source_revision"],
            "requirement_ids": list(candidate["requirement_ids"]),
            "source_revisions": list(candidate["source_revisions"]),
            "changed_files": list(candidate["changed_files"]),
            "changed_symbols": list(candidate["changed_symbols"]),
            "symbol_explanations": list(candidate["symbol_explanations"]),
            "reverse_requirement_mappings": list(
                candidate["reverse_requirement_mappings"]
            ),
            "codegraph_required": bool(candidate["codegraph_required"]),
            "candidate_unknowns": [],
            "candidate_gaps": [],
        }
        envelope = {
            "task_id": str(task["task_id"]),
            "artifact": {
                "artifact_id": artifact_id,
                "artifact_type": "CODE_ANALYSIS_CANDIDATE",
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
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_EXISTING_OUTPUT_IDENTITY_MISMATCH"
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
            "target_id": semantic.get("target_id"),
            "changed_files": list(semantic.get("changed_files") or []),
            "changed_symbols": list(semantic.get("changed_symbols") or []),
            "task_state": str(task["state"]),
        }

    def promote(
        self, *, release_batch_id: str, target_id: str
    ) -> Dict[str, Any]:
        release_batch_id = _required(release_batch_id, "release_batch_id")
        target_id = _required(target_id, "target_id")
        anchor = self._anchor(release_batch_id, target_id)
        _attempt, assignment, _dispatch, task = self._validate_lineage(
            release_batch_id=release_batch_id,
            target_id=target_id,
            anchor=anchor,
        )
        candidate, _raw = self._raw_candidate(anchor, assignment)
        artifact_id = self._artifact_id(self.mission_id, str(task["task_id"]))
        if task.get("state") in {
            TaskStatus.OUTPUT_PRODUCED.value,
            TaskStatus.EVALUATING.value,
            TaskStatus.PASS.value,
            TaskStatus.REPAIR_REQUIRED.value,
        }:
            return self._verify_existing(task=task, artifact_id=artifact_id)

        evidence = self._evidence(anchor=anchor, candidate=candidate)
        evidence_ids = list(dict.fromkeys(item.evidence_id for item in evidence))
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
            artifact_type="CODE_ANALYSIS_CANDIDATE",
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
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_TASK_NOT_PROMOTABLE:%s" % state
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
            raise N3CodeAnalysisPromotionError(
                "RC72_N3_CODE_PROMOTION_MUST_STOP_AT_OUTPUT_PRODUCED"
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
            "application_id": semantic["application_id"],
            "target_id": target_id,
            "task_id": str(task["task_id"]),
            "artifact_id": artifact_id,
            "content_ref": durable.content_ref,
            "content_hash": durable.content_hash,
            "evidence_ids": evidence_ids,
            "evidence_anchor_id": str(anchor["anchor_id"]),
            "changed_files": list(semantic["changed_files"]),
            "changed_symbols": list(semantic["changed_symbols"]),
            "task_state": promoted.state.value,
        }
