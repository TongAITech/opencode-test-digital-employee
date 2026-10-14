"""Independent DSH Code reviewer connected to the RC7 deterministic Code gate.

The Code worker may propose semantic `tool_calls`, but they are never accepted
as proof. The evaluator reconstructs Git/CodeGraph calls from R1
WORKER_TOOL_CALLED events for the exact analyzer identity, persists canonical
RC7 Evidence for those real calls, binds semantic evidence references to R1,
launches a fresh independent Code reviewer, and only then invokes the inherited
evidence-backed CodeSufficiencyEvaluator through CodeAnalysisClosedLoop.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher, WorkerInvocation

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .code_loop import CodeAnalysisClosedLoop, CodeLoopResult
from .dsh_proof import DshR1ProofReader, code_tool_category
from .models import Evidence, TaskStatus
from .truth_overlay import append_entity


class DshCodeEvaluatorError(RuntimeError):
    pass


_RUNTIME_STATUS_TOOL = "mcp__pfc_aitest_rc6__runtime_status"


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


@dataclass(frozen=True)
class DshCodeEvaluation:
    task_id: str
    artifact_id: str
    target_id: str
    analyzer_worker_id: str
    reviewer_worker_id: str
    reviewer_session_id: str
    analyzer_tool_evidence_ids: Tuple[str, ...]
    reviewer_evidence_ids: Tuple[str, ...]
    analysis: Dict[str, object]
    review: Dict[str, object]
    loop_result: CodeLoopResult


class DshCodeEvaluator:
    def __init__(
        self,
        launcher: DshHeadlessWorkerLauncher,
        *,
        reviewer_allowed_tools: Sequence[str] = (_RUNTIME_STATUS_TOOL, "git", "codegraph"),
    ) -> None:
        self.launcher = launcher
        self.reviewer_allowed_tools = tuple(reviewer_allowed_tools)
        if not self.reviewer_allowed_tools:
            raise ValueError("CODE_REVIEWER_REAL_TOOL_REQUIRED")
        self.reader = CandidatePayloadReader()
        self.proofs = DshR1ProofReader()
        self.loop = CodeAnalysisClosedLoop()

    def evaluate(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        artifact_id: str,
        *,
        target_id: str,
    ) -> DshCodeEvaluation:
        task = control.scheduler.task(task_id)
        if task.node != "CODE_ANALYSIS":
            raise DshCodeEvaluatorError("CODE_EVALUATOR_TASK_NODE_MISMATCH")
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise DshCodeEvaluatorError("CODE_EVALUATOR_CANDIDATE_REQUIRED")
        if not isinstance(target_id, str) or not target_id.strip():
            raise DshCodeEvaluatorError("CODE_TARGET_ID_REQUIRED")
        target_id = target_id.strip()
        analyzer_worker_id = str(task.lease_owner or "")
        if not analyzer_worker_id:
            raise DshCodeEvaluatorError("CODE_ANALYZER_IDENTITY_MISSING")
        if artifact_id not in task.output_artifact_refs:
            raise DshCodeEvaluatorError("CODE_ARTIFACT_NOT_TASK_OUTPUT")

        candidate = self.reader.load(
            control.truth,
            artifact_id,
            expected_mission_id=control.mission_id,
            expected_task_id=task_id,
        )
        analysis = dict(candidate.semantic_payload)
        analysis["analysis_id"] = _stable_id(
            "CODE-AN",
            control.mission_id,
            artifact_id,
            target_id,
            candidate.content_hash,
        )
        analysis["release_id"] = control.release_id
        analysis["analyzer_worker_id"] = analyzer_worker_id

        artifact_row = control.truth.query("rc7_artifact", artifact_id=artifact_id)[0]
        aliases, canonical_evidence = self._candidate_evidence_aliases(control, artifact_row)
        tool_evidence_ids, normalized_tool_calls = self._bind_real_analyzer_tool_calls(
            control,
            analyzer_worker_id=analyzer_worker_id,
            task_id=task_id,
            artifact_id=artifact_id,
            target_id=target_id,
        )
        for evidence_id in tool_evidence_ids:
            row = control.truth.query("rc7_evidence", evidence_id=evidence_id)[0]
            canonical_evidence.append(evidence_id)
            for alias in (evidence_id, row.get("content_ref"), row.get("source_ref")):
                if isinstance(alias, str) and alias:
                    aliases.setdefault(alias, evidence_id)

        self._normalize_semantic_evidence(analysis, aliases)
        analysis["evidence_refs"] = list(dict.fromkeys(canonical_evidence))
        # Never trust model-authored tool_calls. Only R1 runtime proof survives.
        analysis["tool_calls"] = normalized_tool_calls

        assignment = self.launcher.assign(
            agent_id="rc7-code-sufficiency",
            role="CODE_REVIEWER",
            phase="ANALYSIS",
            mission_id=control.mission_id,
            attempt_id=_stable_id("ATT-CODE-REVIEW", control.mission_id, artifact_id, target_id, candidate.content_hash),
            scope=artifact_id,
            input_refs=tuple([candidate.content_ref] + list(task.input_artifact_refs)),
            allowed_artifact_types=("code_review", "analysis_gap"),
            allowed_tools=self.reviewer_allowed_tools,
            parent_worker_id=getattr(self.launcher, "coordinator_instance_id", None),
        )
        if assignment.worker_instance_id == analyzer_worker_id:
            raise DshCodeEvaluatorError("CODE_REVIEWER_NOT_INDEPENDENT")
        reviewer, output = self.launcher.execute(
            assignment,
            self._review_prompt(
                task_id=task_id,
                artifact_id=artifact_id,
                target_id=target_id,
                analyzer_worker_id=analyzer_worker_id,
                analysis=analysis,
            ),
        )
        if reviewer.worker_instance_id == analyzer_worker_id:
            raise DshCodeEvaluatorError("CODE_REVIEWER_NOT_INDEPENDENT")
        if not reviewer.dsh_session_id:
            raise DshCodeEvaluatorError("CODE_REVIEWER_SESSION_MISSING")
        if not reviewer.tool_calls:
            raise DshCodeEvaluatorError("CODE_REVIEWER_REAL_TOOL_CALL_MISSING")

        reviewer_evidence_ids = self._persist_reviewer_evidence(
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
            evidence_ids=reviewer_evidence_ids,
            reviewer=reviewer,
            codegraph_required=analysis.get("codegraph_required") is not False,
        )
        result = self.loop.evaluate(
            mission_id=control.mission_id,
            artifact_ref=artifact_id,
            target_id=target_id,
            analysis=analysis,
            review=review,
            evaluator_ref="dsh:%s+deterministic-code-gate" % reviewer.worker_instance_id,
        )
        return DshCodeEvaluation(
            task_id=task_id,
            artifact_id=artifact_id,
            target_id=target_id,
            analyzer_worker_id=analyzer_worker_id,
            reviewer_worker_id=reviewer.worker_instance_id,
            reviewer_session_id=str(reviewer.dsh_session_id),
            analyzer_tool_evidence_ids=tuple(tool_evidence_ids),
            reviewer_evidence_ids=tuple(reviewer_evidence_ids),
            analysis=analysis,
            review=review,
            loop_result=result,
        )

    def evaluate_and_apply(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        artifact_id: str,
        *,
        target_id: str,
    ) -> DshCodeEvaluation:
        evaluated = self.evaluate(
            control,
            task_id,
            artifact_id,
            target_id=target_id,
        )
        control.accept_evaluation(
            task_id,
            evaluation=evaluated.loop_result.evaluation,
            gaps=evaluated.loop_result.gaps,
        )
        return evaluated

    @staticmethod
    def _candidate_evidence_aliases(
        control: ClosedLoopControlPlane,
        artifact_row: Mapping[str, object],
    ) -> Tuple[Dict[str, str], List[str]]:
        refs = artifact_row.get("evidence_refs", [])
        if not isinstance(refs, list) or not refs:
            raise DshCodeEvaluatorError("CODE_ARTIFACT_EVIDENCE_MISSING")
        aliases: Dict[str, str] = {}
        canonical: List[str] = []
        ambiguous = set()
        for evidence_id in refs:
            if not isinstance(evidence_id, str) or not evidence_id:
                continue
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if not rows:
                continue
            if len(rows) != 1:
                raise DshCodeEvaluatorError("CODE_ARTIFACT_EVIDENCE_NOT_UNIQUE:%s" % evidence_id)
            row = rows[0]
            if row.get("mission_id") != control.mission_id:
                raise DshCodeEvaluatorError("CODE_ARTIFACT_EVIDENCE_MISSION_MISMATCH")
            canonical_id = str(row.get("evidence_id") or "")
            if not canonical_id:
                continue
            canonical.append(canonical_id)
            for alias in (canonical_id, row.get("content_ref"), row.get("source_ref")):
                if not isinstance(alias, str) or not alias:
                    continue
                existing = aliases.get(alias)
                if existing is not None and existing != canonical_id:
                    ambiguous.add(alias)
                else:
                    aliases[alias] = canonical_id
        for alias in ambiguous:
            aliases.pop(alias, None)
        if not canonical:
            raise DshCodeEvaluatorError("CODE_ARTIFACT_HAS_NO_DURABLE_EVIDENCE")
        return aliases, canonical

    def _bind_real_analyzer_tool_calls(
        self,
        control: ClosedLoopControlPlane,
        *,
        analyzer_worker_id: str,
        task_id: str,
        artifact_id: str,
        target_id: str,
    ) -> Tuple[Tuple[str, ...], List[Dict[str, str]]]:
        grouped = self.proofs.code_tool_calls(
            control.truth,
            mission_id=control.mission_id,
            worker_instance_id=analyzer_worker_id,
        )
        evidence_ids: List[str] = []
        normalized: List[Dict[str, str]] = []
        for category in ("git", "codegraph"):
            for proof in grouped[category]:
                evidence_id = _stable_id(
                    "EVD-CODE-TOOL",
                    control.mission_id,
                    analyzer_worker_id,
                    proof.event_id,
                    proof.call_ref,
                )
                if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
                    append_entity(
                        control.truth,
                        Evidence(
                            evidence_id=evidence_id,
                            mission_id=control.mission_id,
                            kind="DSH_%s_TOOL_CALL_PROOF" % category.upper(),
                            source_ref="r1-event://%s" % proof.event_id,
                            content_ref=proof.call_ref,
                            subject_refs=[task_id, artifact_id, target_id],
                        ),
                        release_id=control.release_id,
                        artifact_version=1,
                    )
                evidence_ids.append(evidence_id)
                normalized.append(
                    {
                        "tool_id": category,
                        "call_ref": proof.call_ref,
                        "evidence_ref": evidence_id,
                        "target_id": target_id,
                    }
                )
        return tuple(dict.fromkeys(evidence_ids)), normalized

    @staticmethod
    def _normalize_semantic_evidence(analysis: Dict[str, object], aliases: Mapping[str, str]) -> None:
        explanations = analysis.get("symbol_explanations")
        if not isinstance(explanations, list):
            raise DshCodeEvaluatorError("CODE_SYMBOL_EXPLANATIONS_REQUIRED")
        normalized_explanations = []
        for item in explanations:
            if not isinstance(item, dict):
                raise DshCodeEvaluatorError("CODE_SYMBOL_EXPLANATION_INVALID")
            refs = item.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                raise DshCodeEvaluatorError("CODE_SYMBOL_EXPLANATION_EVIDENCE_REQUIRED")
            canonical = []
            for ref in refs:
                if not isinstance(ref, str) or ref not in aliases:
                    raise DshCodeEvaluatorError("CODE_SYMBOL_EVIDENCE_NOT_DURABLE:%s" % ref)
                canonical.append(aliases[ref])
            normalized = dict(item)
            normalized["evidence_refs"] = list(dict.fromkeys(canonical))
            normalized_explanations.append(normalized)
        analysis["symbol_explanations"] = normalized_explanations

        reverse = analysis.get("reverse_requirement_mappings")
        if not isinstance(reverse, list):
            raise DshCodeEvaluatorError("CODE_REVERSE_MAPPINGS_REQUIRED")
        normalized_reverse = []
        for item in reverse:
            if not isinstance(item, dict):
                raise DshCodeEvaluatorError("CODE_REVERSE_MAPPING_INVALID")
            ref = item.get("evidence_ref")
            if not isinstance(ref, str) or ref not in aliases:
                raise DshCodeEvaluatorError("CODE_REVERSE_EVIDENCE_NOT_DURABLE:%s" % ref)
            normalized = dict(item)
            normalized["evidence_ref"] = aliases[ref]
            normalized_reverse.append(normalized)
        analysis["reverse_requirement_mappings"] = normalized_reverse

    def _persist_reviewer_evidence(
        self,
        control: ClosedLoopControlPlane,
        *,
        task_id: str,
        artifact_id: str,
        reviewer: WorkerInvocation,
    ) -> Tuple[str, ...]:
        evidence_ids: List[str] = []
        refs = list(reviewer.evidence_refs)
        for call in reviewer.tool_calls:
            if isinstance(call, dict):
                ref = call.get("call_ref")
                if isinstance(ref, str) and ref:
                    refs.append(ref)
        for ref in refs:
            if not isinstance(ref, str) or not ref:
                continue
            evidence_id = _stable_id(
                "EVD-CODE-REVIEW",
                control.mission_id,
                artifact_id,
                reviewer.worker_instance_id,
                ref,
            )
            if not control.truth.query("rc7_evidence", evidence_id=evidence_id):
                append_entity(
                    control.truth,
                    Evidence(
                        evidence_id=evidence_id,
                        mission_id=control.mission_id,
                        kind="INDEPENDENT_CODE_REVIEW_PROOF",
                        source_ref="dsh://worker/%s" % reviewer.worker_instance_id,
                        content_ref=ref,
                        subject_refs=[task_id, artifact_id],
                    ),
                    release_id=control.release_id,
                    artifact_version=1,
                )
            evidence_ids.append(evidence_id)
        if not evidence_ids:
            raise DshCodeEvaluatorError("CODE_REVIEWER_EVIDENCE_MISSING")
        return tuple(dict.fromkeys(evidence_ids))

    @staticmethod
    def _normalize_review(
        output: Dict[str, object],
        *,
        analysis_id: str,
        analyzer_worker_id: str,
        reviewer_worker_id: str,
        evidence_ids: Sequence[str],
        reviewer: WorkerInvocation,
        codegraph_required: bool,
    ) -> Dict[str, object]:
        if not isinstance(output, dict):
            raise DshCodeEvaluatorError("CODE_REVIEW_OUTPUT_NOT_OBJECT")
        decision = output.get("decision")
        if not isinstance(decision, str) or decision.upper() not in {"PASS", "GAPS"}:
            raise DshCodeEvaluatorError("CODE_REVIEW_DECISION_INVALID")
        gap_ids = output.get("gap_ids", [])
        if not isinstance(gap_ids, list) or not all(isinstance(value, str) and value for value in gap_ids):
            raise DshCodeEvaluatorError("CODE_REVIEW_GAP_IDS_INVALID")

        real_categories = {
            code_tool_category(str(call.get("tool_name") or ""))
            for call in reviewer.tool_calls
            if isinstance(call, dict)
        }
        enforced_gaps = list(gap_ids)
        if "git" not in real_categories:
            enforced_gaps.append("REVIEW_GIT_REAL_TOOL_EVIDENCE_MISSING")
        if codegraph_required and "codegraph" not in real_categories:
            enforced_gaps.append("REVIEW_CODEGRAPH_REAL_TOOL_EVIDENCE_MISSING")
        final_decision = "GAPS" if enforced_gaps else decision.upper()
        return {
            "id": _stable_id("CODE-REVIEW", analysis_id, reviewer_worker_id),
            "review_id": _stable_id("CODE-REVIEW", analysis_id, reviewer_worker_id),
            "subject_analysis_id": analysis_id,
            "reviewer_worker_id": reviewer_worker_id,
            "analyzer_worker_id": analyzer_worker_id,
            "decision": final_decision,
            "gap_ids": list(dict.fromkeys(enforced_gaps)),
            "evidence_refs": list(evidence_ids),
            "summary": str(output.get("summary") or ""),
        }

    def _review_prompt(
        self,
        *,
        task_id: str,
        artifact_id: str,
        target_id: str,
        analyzer_worker_id: str,
        analysis: Dict[str, object],
    ) -> str:
        contract = {
            "task_id": task_id,
            "artifact_id": artifact_id,
            "target_id": target_id,
            "analyzer_worker_id": analyzer_worker_id,
            "allowed_tools": list(self.reviewer_allowed_tools),
            "analysis": analysis,
        }
        schema = {
            "decision": "PASS or GAPS",
            "gap_ids": ["specific code analysis gap"],
            "summary": "independent review rationale",
        }
        return (
            "You are an independent RC7 Code Sufficiency Reviewer. You are not the analyzer. "
            "Use real Git and CodeGraph tools when available and inspect the supplied candidate independently. "
            "Check source revisions, changed files/symbols, symbol explanations, reverse requirement mappings, "
            "and whether the impact analysis is deep enough for downstream test design. Do not modify the "
            "candidate and do not emit a canonical Evaluation or Task state. Return GAPS for any material "
            "uncertainty. Return exactly one JSON object.\n"
            "REVIEW_CONTRACT=" + json.dumps(contract, ensure_ascii=False, sort_keys=True) + "\n"
            "RETURN_SCHEMA=" + json.dumps(schema, ensure_ascii=False, sort_keys=True)
        )
