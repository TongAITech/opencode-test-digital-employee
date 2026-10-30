"""Independent RC7.2 N3 source-target mapping review.

A promoted SOURCE_TARGET_MAPPING_CANDIDATE is still only worker-proposed source
truth. This adapter assigns a fresh independent DSH reviewer, requires a real
tool call and durable reviewer evidence, then combines reviewer judgement with
a deterministic mapping-integrity gate.

This layer may move the SOURCE_TARGET_DISCOVERY WorkItem to PASS or
REPAIR_REQUIRED. It never creates CODE_ANALYSIS WorkItems, never advances the
N3 MissionNode, never releases N4, and never claims field/BANK_FINAL status.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .models import (
    Evaluation,
    EvaluationResult,
    Evidence,
    Gap,
    GapSeverity,
    MissionStatus,
    TaskStatus,
)
from .rc72_authority import RC72AuthorityRuntime, SOURCE_TARGET_REVIEWER
from .state_machine import transition_mission, transition_task
from .truth_overlay import append_entity


class N3SourceTargetReviewError(RuntimeError):
    pass


_STAGE = "SOURCE_TARGET_DISCOVERY"
_REVIEW_AGENT = "source-target-review"
_REVIEW_PHASE = "ANALYSIS"
_REVIEW_EVIDENCE_KIND = "INDEPENDENT_SOURCE_TARGET_REVIEW_PROOF"


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3SourceTargetReviewError(
            "RC72_N3_SOURCE_REVIEW_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _strings(value: Any, name: str, *, required: bool = False) -> List[str]:
    if not isinstance(value, list):
        raise N3SourceTargetReviewError(
            "RC72_N3_SOURCE_REVIEW_%s_INVALID" % name.upper()
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise N3SourceTargetReviewError(
            "RC72_N3_SOURCE_REVIEW_%s_INVALID" % name.upper()
        )
    out = [item.strip() for item in value]
    if len(set(out)) != len(out):
        raise N3SourceTargetReviewError(
            "RC72_N3_SOURCE_REVIEW_%s_DUPLICATE" % name.upper()
        )
    if required and not out:
        raise N3SourceTargetReviewError(
            "RC72_N3_SOURCE_REVIEW_%s_REQUIRED" % name.upper()
        )
    return out


@dataclass(frozen=True)
class N3SourceTargetReviewResult:
    task_id: str
    artifact_id: str
    application_id: str
    reviewer_worker_id: str
    reviewer_session_id: str
    evaluation_id: str
    evaluation_result: str
    gap_ids: Tuple[str, ...]
    task_state: str
    deterministic_reasons: Tuple[str, ...]


class N3SourceTargetReviewService:
    """Independently review one promoted source-target mapping candidate."""

    def __init__(
        self,
        control: ClosedLoopControlPlane,
        launcher: DshHeadlessWorkerLauncher,
        *,
        allowed_tools: Sequence[str],
    ) -> None:
        self.control = control
        self.launcher = launcher
        tools = [
            str(item).strip() for item in allowed_tools
            if isinstance(item, str) and item.strip()
        ]
        if not tools or len(set(tools)) != len(tools):
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_ALLOWED_TOOLS_INVALID"
            )
        self.allowed_tools = tuple(tools)
        self.reader = CandidatePayloadReader()
        if not isinstance(self.launcher.authority, RC72AuthorityRuntime):
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_RC72_AUTHORITY_REQUIRED"
            )

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.control.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_TRUTH_NOT_UNIQUE:%s:%d"
                % (artifact_type, len(rows))
            )
        return rows[0]

    def _resume(
        self,
        *,
        task_id: str,
        artifact_id: str,
        application_id: str,
    ) -> N3SourceTargetReviewResult:
        task = self.control.scheduler.task(task_id)
        evaluation_id = _required(task.evaluation_id, "evaluation_id")
        row = self._one("rc7_evaluation", evaluation_id=evaluation_id)
        if (
            row.get("mission_id") != self.control.mission_id
            or row.get("node") != _STAGE
            or artifact_id not in list(row.get("artifact_refs") or [])
        ):
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_RESUME_EVALUATION_LINEAGE_MISMATCH"
            )
        dimensions = row.get("dimensions")
        if not isinstance(dimensions, dict) or dimensions.get("rc72_source_target_review") != "V1":
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_RESUME_MARKER_MISSING"
            )
        if dimensions.get("application_id") != application_id:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_RESUME_APPLICATION_MISMATCH"
            )
        return N3SourceTargetReviewResult(
            task_id=task_id,
            artifact_id=artifact_id,
            application_id=application_id,
            reviewer_worker_id=str(dimensions.get("reviewer_worker_id") or ""),
            reviewer_session_id=str(dimensions.get("reviewer_session_id") or ""),
            evaluation_id=evaluation_id,
            evaluation_result=str(row.get("result") or ""),
            gap_ids=tuple(str(item) for item in list(row.get("gap_refs") or [])),
            task_state=task.state.value,
            deterministic_reasons=tuple(
                str(item) for item in list(dimensions.get("deterministic_reasons") or [])
            ),
        )

    def _candidate(
        self, *, task_id: str, artifact_id: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
        task = self.control.scheduler.task(task_id)
        if task.node != _STAGE:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_TASK_NODE_MISMATCH"
            )
        if task.state in {TaskStatus.PASS, TaskStatus.REPAIR_REQUIRED}:
            candidate = self.reader.load(
                self.control.truth,
                artifact_id,
                expected_mission_id=self.control.mission_id,
                expected_task_id=task_id,
            )
            semantic = dict(candidate.semantic_payload)
            application_id = _required(semantic.get("application_id"), "application_id")
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_ALREADY_EVALUATED:%s" % application_id
            )
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_CANDIDATE_REQUIRED:%s" % task.state.value
            )
        if artifact_id not in task.output_artifact_refs:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_ARTIFACT_NOT_TASK_OUTPUT"
            )
        analyzer_worker_id = _required(task.lease_owner, "analyzer_worker_id")
        candidate = self.reader.load(
            self.control.truth,
            artifact_id,
            expected_mission_id=self.control.mission_id,
            expected_task_id=task_id,
        )
        if candidate.artifact_type != "SOURCE_TARGET_MAPPING_CANDIDATE":
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_ARTIFACT_TYPE_INVALID"
            )
        semantic = dict(candidate.semantic_payload)
        if semantic.get("candidate_kind") != "SOURCE_TARGET_MAPPING_CANDIDATE":
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_CANDIDATE_KIND_INVALID"
            )
        application_id = _required(semantic.get("application_id"), "application_id")
        return semantic, {
            "task_id": task_id,
            "artifact_id": artifact_id,
            "content_ref": candidate.content_ref,
            "content_hash": candidate.content_hash,
            "input_refs": list(task.input_artifact_refs),
            "artifact_evidence_refs": list(
                self._one("rc7_artifact", artifact_id=artifact_id).get("evidence_refs") or []
            ),
        }, analyzer_worker_id

    def _mapping_reasons(
        self,
        *,
        semantic: Mapping[str, Any],
        application_id: str,
    ) -> Tuple[List[str], List[str]]:
        reasons: List[str] = []
        unknowns = semantic.get("candidate_unknowns")
        gaps = semantic.get("candidate_gaps")
        if not isinstance(unknowns, list) or unknowns:
            reasons.append("CANDIDATE_UNKNOWNS_NOT_EMPTY")
        if not isinstance(gaps, list) or gaps:
            reasons.append("CANDIDATE_GAPS_NOT_EMPTY")
        targets = semantic.get("targets")
        if not isinstance(targets, list) or not targets:
            reasons.append("SOURCE_TARGET_SET_EMPTY")
            return reasons, []

        target_ids: List[str] = []
        repo_revisions: Dict[str, set] = {}
        for index, raw in enumerate(targets):
            if not isinstance(raw, Mapping):
                reasons.append("TARGET_NOT_OBJECT:%d" % index)
                continue
            target_id = raw.get("target_id")
            repository_ref = raw.get("repository_ref")
            source_revision = raw.get("source_revision")
            source_refs = raw.get("source_evidence_refs")
            evidence_ids = raw.get("canonical_evidence_ids")
            if not isinstance(target_id, str) or not target_id.strip():
                reasons.append("TARGET_ID_MISSING:%d" % index)
                continue
            target_id = target_id.strip()
            target_ids.append(target_id)
            if not isinstance(repository_ref, str) or not repository_ref.strip():
                reasons.append("REPOSITORY_REF_MISSING:%s" % target_id)
                continue
            repository_ref = repository_ref.strip()
            if not repository_ref.startswith("git://"):
                reasons.append("REPOSITORY_REF_NOT_GIT:%s" % target_id)
            if not isinstance(source_revision, str) or not source_revision.strip():
                reasons.append("SOURCE_REVISION_MISSING:%s" % target_id)
                continue
            source_revision = source_revision.strip()
            repo_revisions.setdefault(repository_ref, set()).add(source_revision)
            try:
                normalized_source_refs = _strings(
                    source_refs, "source_evidence_refs", required=True
                )
                normalized_evidence_ids = _strings(
                    evidence_ids, "canonical_evidence_ids", required=True
                )
            except N3SourceTargetReviewError as exc:
                reasons.append("TARGET_EVIDENCE_INVALID:%s:%s" % (target_id, exc))
                continue
            for evidence_id in normalized_evidence_ids:
                rows = self.control.truth.query("rc7_evidence", evidence_id=evidence_id)
                if len(rows) != 1:
                    reasons.append("TARGET_EVIDENCE_NOT_UNIQUE:%s:%s" % (target_id, evidence_id))
                    continue
                row = rows[0]
                if (
                    row.get("mission_id") != self.control.mission_id
                    or row.get("kind") != "N3_SOURCE_TARGET_PROOF"
                    or application_id not in list(row.get("subject_refs") or [])
                    or target_id not in list(row.get("subject_refs") or [])
                ):
                    reasons.append("TARGET_EVIDENCE_LINEAGE_INVALID:%s:%s" % (target_id, evidence_id))
                    continue
                source_ref = str(row.get("source_ref") or "")
                if source_ref not in normalized_source_refs:
                    reasons.append("TARGET_EVIDENCE_SOURCE_MISMATCH:%s:%s" % (target_id, evidence_id))

        if len(target_ids) != len(set(target_ids)):
            reasons.append("TARGET_ID_DUPLICATE")
        for repository_ref, revisions in sorted(repo_revisions.items()):
            if len(revisions) > 1:
                reasons.append("AMBIGUOUS_REPOSITORY_REVISION:%s" % repository_ref)
        return list(dict.fromkeys(reasons)), list(dict.fromkeys(target_ids))

    def _review_prompt(
        self,
        *,
        application_id: str,
        analyzer_worker_id: str,
        task_id: str,
        artifact_id: str,
        semantic: Mapping[str, Any],
        target_ids: Sequence[str],
    ) -> str:
        contract = {
            "application_id": application_id,
            "task_id": task_id,
            "artifact_id": artifact_id,
            "analyzer_worker_id": analyzer_worker_id,
            "allowed_tools": list(self.allowed_tools),
            "required_target_ids": list(target_ids),
            "candidate": dict(semantic),
        }
        schema = {
            "decision": "PASS or GAPS",
            "reviewed_target_ids": list(target_ids),
            "gap_ids": ["specific reviewer gap ids when decision=GAPS"],
            "summary": "independent rationale",
        }
        return (
            "You are an independent RC7.2 source-target mapping reviewer. You are not the discovery worker. "
            "Call at least one allowed real tool and independently validate the application-to-repository/source-revision mapping. "
            "Verify every target id, repository locator, exact revision and source evidence. Challenge ambiguous repository mappings, stale or guessed revisions, and evidence that does not identify the exact target. "
            "Do not create CODE_ANALYSIS work, do not modify the candidate, and do not claim N3 PASS/N4/field/BANK_FINAL. "
            "Return one strict JSON object with exactly decision,reviewed_target_ids,gap_ids,summary.\n"
            "REVIEW_CONTRACT=" + json.dumps(contract, ensure_ascii=False, sort_keys=True) + "\n"
            "RETURN_SCHEMA=" + json.dumps(schema, ensure_ascii=False, sort_keys=True)
        )

    @staticmethod
    def _normalize_review(
        output: Any,
        *,
        expected_target_ids: Sequence[str],
    ) -> Dict[str, Any]:
        if not isinstance(output, Mapping):
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_OUTPUT_NOT_OBJECT"
            )
        if set(output.keys()) != {"decision", "reviewed_target_ids", "gap_ids", "summary"}:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_OUTPUT_CONTRACT_INVALID"
            )
        decision = output.get("decision")
        if not isinstance(decision, str) or decision.upper() not in {"PASS", "GAPS"}:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_DECISION_INVALID"
            )
        reviewed = _strings(
            output.get("reviewed_target_ids"), "reviewed_target_ids", required=True
        )
        expected = list(dict.fromkeys(str(item) for item in expected_target_ids))
        if set(reviewed) != set(expected) or len(reviewed) != len(expected):
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_TARGET_COVERAGE_MISMATCH"
            )
        gap_ids = _strings(output.get("gap_ids"), "gap_ids")
        summary = _required(output.get("summary"), "summary")
        decision = decision.upper()
        if decision == "PASS" and gap_ids:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_PASS_WITH_GAPS_FORBIDDEN"
            )
        if decision == "GAPS" and not gap_ids:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_GAPS_DECISION_REQUIRES_GAP_IDS"
            )
        return {
            "decision": decision,
            "reviewed_target_ids": reviewed,
            "gap_ids": gap_ids,
            "summary": summary,
        }

    def _reviewer_evidence(
        self,
        *,
        task_id: str,
        artifact_id: str,
        application_id: str,
        reviewer: Any,
    ) -> Tuple[str, ...]:
        evidence_ids: List[str] = []
        for ref in list(reviewer.evidence_refs or []):
            if not isinstance(ref, str) or not ref.strip():
                continue
            evidence_id = _stable_id(
                "EVD-N3-SOURCE-REVIEW",
                self.control.mission_id,
                artifact_id,
                reviewer.worker_instance_id,
                ref,
            )
            evidence = Evidence(
                evidence_id=evidence_id,
                mission_id=self.control.mission_id,
                kind=_REVIEW_EVIDENCE_KIND,
                source_ref="dsh://worker/%s" % reviewer.worker_instance_id,
                content_ref=ref,
                subject_refs=[task_id, artifact_id, application_id],
            )
            append_entity(
                self.control.truth,
                evidence,
                release_id=self.control.release_id,
                artifact_version=1,
            )
            evidence_ids.append(evidence_id)
        if not evidence_ids:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_REVIEWER_EVIDENCE_MISSING"
            )
        return tuple(evidence_ids)

    def _gaps(
        self,
        *,
        task_id: str,
        artifact_id: str,
        application_id: str,
        reviewer_worker_id: str,
        reviewer_gap_ids: Sequence[str],
        deterministic_reasons: Sequence[str],
        evidence_refs: Sequence[str],
    ) -> Tuple[Gap, ...]:
        reasons = ["REVIEWER_GAP:%s" % item for item in reviewer_gap_ids]
        reasons.extend("DETERMINISTIC:%s" % item for item in deterministic_reasons)
        out: List[Gap] = []
        for reason in list(dict.fromkeys(reasons)):
            gap_id = _stable_id(
                "GAP-N3-SOURCE-MAP",
                self.control.mission_id,
                task_id,
                artifact_id,
                reviewer_worker_id,
                reason,
            )
            severity = (
                GapSeverity.CRITICAL
                if "AMBIGUOUS" in reason or "REVISION" in reason
                else GapSeverity.HIGH
            )
            out.append(Gap(
                gap_id=gap_id,
                mission_id=self.control.mission_id,
                source_node=_STAGE,
                category="SOURCE_TARGET_MAPPING_GAP",
                severity=severity,
                target_node=_STAGE,
                description="Source-target mapping review failed: %s" % reason,
                subject_refs=[task_id, artifact_id, application_id],
                evidence_refs=list(dict.fromkeys(evidence_refs)),
                acceptance_criteria=[
                    "repair %s with fresh source discovery evidence and rerun independent review"
                    % reason
                ],
            ))
        return tuple(out)

    def _persist_evaluation(
        self,
        *,
        task_id: str,
        artifact_id: str,
        application_id: str,
        reviewer_worker_id: str,
        reviewer_session_id: str,
        review: Mapping[str, Any],
        deterministic_reasons: Sequence[str],
        reviewer_evidence_ids: Sequence[str],
        artifact_evidence_refs: Sequence[str],
    ) -> Tuple[Evaluation, Tuple[Gap, ...], TaskStatus]:
        reviewer_gap_ids = list(review.get("gap_ids") or [])
        result = (
            EvaluationResult.PASS
            if review.get("decision") == "PASS" and not deterministic_reasons
            else EvaluationResult.REPAIR_REQUIRED
        )
        evidence_refs = list(dict.fromkeys(
            list(artifact_evidence_refs) + list(reviewer_evidence_ids)
        ))
        gaps = self._gaps(
            task_id=task_id,
            artifact_id=artifact_id,
            application_id=application_id,
            reviewer_worker_id=reviewer_worker_id,
            reviewer_gap_ids=reviewer_gap_ids,
            deterministic_reasons=deterministic_reasons,
            evidence_refs=evidence_refs,
        ) if result == EvaluationResult.REPAIR_REQUIRED else tuple()
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-N3-SOURCE",
                self.control.mission_id,
                artifact_id,
                reviewer_worker_id,
                str(review.get("decision")),
                ",".join(sorted(str(item) for item in deterministic_reasons)),
                ",".join(sorted(reviewer_gap_ids)),
            ),
            mission_id=self.control.mission_id,
            node=_STAGE,
            artifact_refs=[artifact_id],
            result=result,
            evaluator_ref="dsh:%s+deterministic-source-target-gate" % reviewer_worker_id,
            dimensions={
                "rc72_source_target_review": "V1",
                "application_id": application_id,
                "reviewer_worker_id": reviewer_worker_id,
                "reviewer_session_id": reviewer_session_id,
                "reviewer_decision": str(review.get("decision")),
                "reviewed_target_ids": list(review.get("reviewed_target_ids") or []),
                "review_summary": str(review.get("summary") or ""),
                "deterministic_reasons": list(deterministic_reasons),
                "mapping_gate": "PASS" if result == EvaluationResult.PASS else "REPAIR_REQUIRED",
            },
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=evidence_refs,
        )

        task = self.control.scheduler.task(task_id)
        append_entity(
            self.control.truth,
            evaluation,
            release_id=self.control.release_id,
            artifact_version=1,
        )
        transition_task(task, TaskStatus.EVALUATING)
        for gap in gaps:
            append_entity(
                self.control.truth,
                gap,
                release_id=self.control.release_id,
                artifact_version=1,
            )
            if gap.gap_id not in task.gap_refs:
                task.gap_refs.append(gap.gap_id)
        target_state = (
            TaskStatus.PASS if result == EvaluationResult.PASS
            else TaskStatus.REPAIR_REQUIRED
        )
        transition_task(
            task,
            target_state,
            evaluation_id=evaluation.evaluation_id,
        )
        self.control.scheduler.persist_evaluated_task(task)
        if result == EvaluationResult.REPAIR_REQUIRED:
            mission = self.control._mission()
            if mission.state == MissionStatus.RUNNING:
                transition_mission(mission, MissionStatus.REPAIRING)
                self.control._persist_mission(mission)
        self.control._sync_mission(self.control._mission())
        return evaluation, gaps, target_state

    def review_and_apply(
        self,
        *,
        task_id: str,
        artifact_id: str,
    ) -> N3SourceTargetReviewResult:
        task = self.control.scheduler.task(task_id)
        if task.state in {TaskStatus.PASS, TaskStatus.REPAIR_REQUIRED} and task.evaluation_id:
            durable = self.reader.load(
                self.control.truth,
                artifact_id,
                expected_mission_id=self.control.mission_id,
                expected_task_id=task_id,
            )
            application_id = _required(
                durable.semantic_payload.get("application_id"), "application_id"
            )
            return self._resume(
                task_id=task_id,
                artifact_id=artifact_id,
                application_id=application_id,
            )

        semantic, candidate_meta, analyzer_worker_id = self._candidate(
            task_id=task_id,
            artifact_id=artifact_id,
        )
        application_id = _required(semantic.get("application_id"), "application_id")
        deterministic_reasons, target_ids = self._mapping_reasons(
            semantic=semantic,
            application_id=application_id,
        )
        if not target_ids:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_TARGET_IDS_REQUIRED"
            )

        analyzer_attempts = self.control.truth.query(
            "rc72_n3_source_target_attempt", workitem_id=task_id
        )
        if len(analyzer_attempts) != 1:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_ANALYZER_ATTEMPT_NOT_UNIQUE:%d"
                % len(analyzer_attempts)
            )
        analyzer_session_id = _required(
            analyzer_attempts[0].get("dsh_session_id"), "analyzer_session_id"
        )

        assignment = self.launcher.assign(
            agent_id=_REVIEW_AGENT,
            role=SOURCE_TARGET_REVIEWER,
            phase=_REVIEW_PHASE,
            mission_id=self.control.mission_id,
            attempt_id=_stable_id(
                "ATT-N3-SOURCE-REVIEW",
                self.control.mission_id,
                artifact_id,
                str(candidate_meta["content_hash"]),
            ),
            scope=artifact_id,
            input_refs=tuple(
                [str(candidate_meta["content_ref"])]
                + list(candidate_meta.get("input_refs") or [])
            ),
            allowed_artifact_types=(),
            allowed_tools=self.allowed_tools,
            parent_worker_id=getattr(
                self.launcher, "coordinator_instance_id", None
            ),
        )
        if assignment.worker_instance_id == analyzer_worker_id:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_REVIEWER_NOT_INDEPENDENT"
            )

        reviewer, output = self.launcher.execute(
            assignment,
            self._review_prompt(
                application_id=application_id,
                analyzer_worker_id=analyzer_worker_id,
                task_id=task_id,
                artifact_id=artifact_id,
                semantic=semantic,
                target_ids=target_ids,
            ),
        )
        if reviewer.worker_instance_id == analyzer_worker_id:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_REVIEWER_NOT_INDEPENDENT"
            )
        reviewer_session_id = _required(
            reviewer.dsh_session_id, "reviewer_session_id"
        )
        if reviewer_session_id == analyzer_session_id:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_SESSION_NOT_INDEPENDENT"
            )
        if not reviewer.tool_calls:
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_REAL_TOOL_CALL_MISSING"
            )
        observed_tools = {
            str(item.get("tool_name") or "") for item in reviewer.tool_calls
        }
        if not observed_tools or not observed_tools.issubset(set(self.allowed_tools)):
            raise N3SourceTargetReviewError(
                "RC72_N3_SOURCE_REVIEW_UNAUTHORIZED_TOOL_OBSERVED"
            )

        review = self._normalize_review(
            output,
            expected_target_ids=target_ids,
        )
        reviewer_evidence_ids = self._reviewer_evidence(
            task_id=task_id,
            artifact_id=artifact_id,
            application_id=application_id,
            reviewer=reviewer,
        )
        evaluation, gaps, target_state = self._persist_evaluation(
            task_id=task_id,
            artifact_id=artifact_id,
            application_id=application_id,
            reviewer_worker_id=reviewer.worker_instance_id,
            reviewer_session_id=reviewer_session_id,
            review=review,
            deterministic_reasons=deterministic_reasons,
            reviewer_evidence_ids=reviewer_evidence_ids,
            artifact_evidence_refs=list(
                candidate_meta.get("artifact_evidence_refs") or []
            ),
        )
        return N3SourceTargetReviewResult(
            task_id=task_id,
            artifact_id=artifact_id,
            application_id=application_id,
            reviewer_worker_id=reviewer.worker_instance_id,
            reviewer_session_id=reviewer_session_id,
            evaluation_id=evaluation.evaluation_id,
            evaluation_result=evaluation.result.value,
            gap_ids=tuple(gap.gap_id for gap in gaps),
            task_state=target_state.value,
            deterministic_reasons=tuple(deterministic_reasons),
        )
