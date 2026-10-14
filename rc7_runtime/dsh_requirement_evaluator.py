"""Independent DSH Requirement reviewer connected to the RC7 deterministic gate.

The producer DSH worker stops at OUTPUT_PRODUCED. This component reloads the
runtime-hashed candidate, launches a fresh reviewer Worker/session under a
separate signed lease, converts only reviewer evidence into canonical RC7
Evidence, and finally invokes RequirementClosedLoop. The reviewer itself never
owns PASS authority; the deterministic gate creates the canonical Evaluation.

Before review, semantic trace links are bound to evidence that actually exists
in R1 for the candidate Artifact. A nonempty worker string is not evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher, WorkerInvocation

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .models import Evidence, TaskStatus
from .requirement_loop import RequirementClosedLoop, RequirementLoopResult
from .truth_overlay import append_entity


class DshRequirementEvaluatorError(RuntimeError):
    pass


_RUNTIME_STATUS_TOOL = "mcp__pfc_aitest_rc6__runtime_status"


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class DshRequirementEvaluation:
    task_id: str
    artifact_id: str
    analyzer_worker_id: str
    reviewer_worker_id: str
    reviewer_session_id: str
    reviewer_evidence_ids: Tuple[str, ...]
    analysis: Dict[str, object]
    review: Dict[str, object]
    loop_result: RequirementLoopResult


class DshRequirementEvaluator:
    def __init__(
        self,
        launcher: DshHeadlessWorkerLauncher,
        *,
        allowed_tools: Sequence[str] = (_RUNTIME_STATUS_TOOL,),
    ) -> None:
        self.launcher = launcher
        self.allowed_tools = tuple(allowed_tools)
        if not self.allowed_tools:
            raise ValueError("REQUIREMENT_REVIEWER_REAL_TOOL_REQUIRED")
        self.reader = CandidatePayloadReader()
        self.loop = RequirementClosedLoop()

    def evaluate(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        artifact_id: str,
    ) -> DshRequirementEvaluation:
        task = control.scheduler.task(task_id)
        if task.node != "REQUIREMENT_ANALYSIS":
            raise DshRequirementEvaluatorError("REQUIREMENT_EVALUATOR_TASK_NODE_MISMATCH")
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise DshRequirementEvaluatorError("REQUIREMENT_EVALUATOR_CANDIDATE_REQUIRED")
        analyzer_worker_id = str(task.lease_owner or "")
        if not analyzer_worker_id:
            raise DshRequirementEvaluatorError("REQUIREMENT_ANALYZER_IDENTITY_MISSING")
        if artifact_id not in task.output_artifact_refs:
            raise DshRequirementEvaluatorError("REQUIREMENT_ARTIFACT_NOT_TASK_OUTPUT")

        candidate = self.reader.load(
            control.truth,
            artifact_id,
            expected_mission_id=control.mission_id,
            expected_task_id=task_id,
        )
        analysis = dict(candidate.semantic_payload)
        analysis["analysis_id"] = _stable_id(
            "REQ-AN",
            control.mission_id,
            artifact_id,
            candidate.content_hash,
        )
        analysis["release_id"] = control.release_id
        analysis["analyzer_worker_id"] = analyzer_worker_id
        artifact_row = control.truth.query("rc7_artifact", artifact_id=artifact_id)[0]
        self._bind_analysis_evidence(control, artifact_row, analysis)

        assignment = self.launcher.assign(
            agent_id="rc7-requirement-sufficiency",
            role="REQUIREMENT_REVIEWER",
            phase="ANALYSIS",
            mission_id=control.mission_id,
            attempt_id=_stable_id("ATT-REQ-REVIEW", control.mission_id, artifact_id, candidate.content_hash),
            scope=artifact_id,
            input_refs=tuple([candidate.content_ref] + list(task.input_artifact_refs)),
            allowed_artifact_types=("requirement_review", "analysis_gap"),
            allowed_tools=self.allowed_tools,
            parent_worker_id=getattr(self.launcher, "coordinator_instance_id", None),
        )
        if assignment.worker_instance_id == analyzer_worker_id:
            raise DshRequirementEvaluatorError("REQUIREMENT_REVIEWER_NOT_INDEPENDENT")

        reviewer, output = self.launcher.execute(
            assignment,
            self._review_prompt(
                task_id=task_id,
                artifact_id=artifact_id,
                analyzer_worker_id=analyzer_worker_id,
                analysis=analysis,
            ),
        )
        if reviewer.worker_instance_id == analyzer_worker_id:
            raise DshRequirementEvaluatorError("REQUIREMENT_REVIEWER_NOT_INDEPENDENT")
        if not reviewer.dsh_session_id:
            raise DshRequirementEvaluatorError("REQUIREMENT_REVIEWER_SESSION_MISSING")
        if not reviewer.tool_calls:
            raise DshRequirementEvaluatorError("REQUIREMENT_REVIEWER_REAL_TOOL_CALL_MISSING")

        review_evidence_ids = self._persist_reviewer_evidence(
            control,
            task_id=task_id,
            artifact_id=artifact_id,
            reviewer=reviewer,
        )
        review = self._normalize_review(
            output,
            analysis_id=str(analysis["analysis_id"]),
            analyzer_worker_id=analyzer_worker_id,
            reviewer_worker_id=reviewer.worker_instance_id,
            evidence_ids=review_evidence_ids,
        )
        result = self.loop.evaluate(
            mission_id=control.mission_id,
            artifact_ref=artifact_id,
            analysis=analysis,
            review=review,
            evaluator_ref="dsh:%s+deterministic-requirement-gate" % reviewer.worker_instance_id,
        )
        return DshRequirementEvaluation(
            task_id=task_id,
            artifact_id=artifact_id,
            analyzer_worker_id=analyzer_worker_id,
            reviewer_worker_id=reviewer.worker_instance_id,
            reviewer_session_id=str(reviewer.dsh_session_id),
            reviewer_evidence_ids=tuple(review_evidence_ids),
            analysis=analysis,
            review=review,
            loop_result=result,
        )

    def evaluate_and_apply(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        artifact_id: str,
    ) -> DshRequirementEvaluation:
        evaluated = self.evaluate(control, task_id, artifact_id)
        control.accept_evaluation(
            task_id,
            evaluation=evaluated.loop_result.evaluation,
            gaps=evaluated.loop_result.gaps,
        )
        return evaluated

    @staticmethod
    def _bind_analysis_evidence(
        control: ClosedLoopControlPlane,
        artifact_row: Dict[str, object],
        analysis: Dict[str, object],
    ) -> None:
        artifact_evidence_ids = artifact_row.get("evidence_refs", [])
        if not isinstance(artifact_evidence_ids, list) or not artifact_evidence_ids:
            raise DshRequirementEvaluatorError("REQUIREMENT_ARTIFACT_EVIDENCE_MISSING")

        canonical_ids = []
        aliases = {}
        ambiguous = set()
        for evidence_id in artifact_evidence_ids:
            if not isinstance(evidence_id, str) or not evidence_id:
                raise DshRequirementEvaluatorError("REQUIREMENT_ARTIFACT_EVIDENCE_ID_INVALID")
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1:
                raise DshRequirementEvaluatorError("REQUIREMENT_ARTIFACT_EVIDENCE_NOT_DURABLE:%s" % evidence_id)
            row = rows[0]
            if row.get("mission_id") != control.mission_id:
                raise DshRequirementEvaluatorError("REQUIREMENT_ARTIFACT_EVIDENCE_MISSION_MISMATCH")
            canonical_ids.append(evidence_id)
            for alias in (evidence_id, row.get("content_ref"), row.get("source_ref")):
                if not isinstance(alias, str) or not alias:
                    continue
                existing = aliases.get(alias)
                if existing is not None and existing != evidence_id:
                    ambiguous.add(alias)
                else:
                    aliases[alias] = evidence_id
        for alias in ambiguous:
            aliases.pop(alias, None)

        links = analysis.get("trace_links")
        if not isinstance(links, list):
            raise DshRequirementEvaluatorError("REQUIREMENT_TRACE_LINKS_REQUIRED")
        normalized_links = []
        for link in links:
            if not isinstance(link, dict):
                raise DshRequirementEvaluatorError("REQUIREMENT_TRACE_LINK_INVALID")
            evidence_ref = link.get("evidence_ref")
            if not isinstance(evidence_ref, str) or not evidence_ref:
                raise DshRequirementEvaluatorError("REQUIREMENT_TRACE_EVIDENCE_REF_REQUIRED")
            canonical = aliases.get(evidence_ref)
            if canonical is None:
                raise DshRequirementEvaluatorError(
                    "REQUIREMENT_TRACE_EVIDENCE_NOT_DURABLE:%s" % evidence_ref
                )
            normalized = dict(link)
            normalized["evidence_ref"] = canonical
            normalized_links.append(normalized)

        analysis["trace_links"] = normalized_links
        analysis["evidence_refs"] = list(dict.fromkeys(canonical_ids))

    def _persist_reviewer_evidence(
        self,
        control: ClosedLoopControlPlane,
        *,
        task_id: str,
        artifact_id: str,
        reviewer: WorkerInvocation,
    ) -> Tuple[str, ...]:
        evidence_ids = []
        for ref in reviewer.evidence_refs:
            if not isinstance(ref, str) or not ref.strip():
                continue
            evidence_id = _stable_id(
                "EVD-REQ-REVIEW",
                control.mission_id,
                artifact_id,
                reviewer.worker_instance_id,
                ref,
            )
            evidence = Evidence(
                evidence_id=evidence_id,
                mission_id=control.mission_id,
                kind="INDEPENDENT_REQUIREMENT_REVIEW_PROOF",
                source_ref="dsh://worker/%s" % reviewer.worker_instance_id,
                content_ref=ref,
                subject_refs=[task_id, artifact_id],
            )
            append_entity(control.truth, evidence, release_id=control.release_id, artifact_version=1)
            evidence_ids.append(evidence_id)
        if not evidence_ids:
            raise DshRequirementEvaluatorError("REQUIREMENT_REVIEWER_EVIDENCE_MISSING")
        return tuple(evidence_ids)

    @staticmethod
    def _normalize_review(
        output: Dict[str, object],
        *,
        analysis_id: str,
        analyzer_worker_id: str,
        reviewer_worker_id: str,
        evidence_ids: Sequence[str],
    ) -> Dict[str, object]:
        if not isinstance(output, dict):
            raise DshRequirementEvaluatorError("REQUIREMENT_REVIEW_OUTPUT_NOT_OBJECT")
        decision = output.get("decision")
        if not isinstance(decision, str) or decision.upper() not in {"PASS", "GAPS"}:
            raise DshRequirementEvaluatorError("REQUIREMENT_REVIEW_DECISION_INVALID")
        gap_ids = output.get("gap_ids", [])
        if not isinstance(gap_ids, list) or not all(isinstance(value, str) and value for value in gap_ids):
            raise DshRequirementEvaluatorError("REQUIREMENT_REVIEW_GAP_IDS_INVALID")
        return {
            "id": _stable_id("REQ-REVIEW", analysis_id, reviewer_worker_id),
            "review_id": _stable_id("REQ-REVIEW", analysis_id, reviewer_worker_id),
            "subject_analysis_id": analysis_id,
            "reviewer_worker_id": reviewer_worker_id,
            "analyzer_worker_id": analyzer_worker_id,
            "decision": decision.upper(),
            "gap_ids": list(dict.fromkeys(gap_ids)),
            "evidence_refs": list(evidence_ids),
            "summary": str(output.get("summary") or ""),
        }

    def _review_prompt(
        self,
        *,
        task_id: str,
        artifact_id: str,
        analyzer_worker_id: str,
        analysis: Dict[str, object],
    ) -> str:
        contract = {
            "task_id": task_id,
            "artifact_id": artifact_id,
            "analyzer_worker_id": analyzer_worker_id,
            "allowed_tools": list(self.allowed_tools),
            "analysis": analysis,
        }
        schema = {
            "decision": "PASS or GAPS",
            "gap_ids": ["specific gap id/reason"],
            "summary": "review rationale",
        }
        return (
            "You are an independent RC7 Requirement Sufficiency Reviewer. You are not the analyzer. "
            "You MUST call at least one allowed real tool. Review the supplied analysis independently. "
            "Check source/atomic traceability, testability, business rules, roles, preconditions, "
            "normal and negative paths, boundaries, states, data constraints, dependencies and side effects. "
            "Do not modify the analysis and do not emit a canonical Evaluation or Task state. "
            "If any material gap exists return decision=GAPS and enumerate gap_ids; otherwise PASS. "
            "Return exactly one JSON object.\n"
            "REVIEW_CONTRACT=" + json.dumps(contract, ensure_ascii=False, sort_keys=True) + "\n"
            "RETURN_SCHEMA=" + json.dumps(schema, ensure_ascii=False, sort_keys=True)
        )
