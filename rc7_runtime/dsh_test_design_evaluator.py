"""Independent DSH Test Design reviewer plus deterministic semantic-closure gate.

The design worker may propose obligations, cases and evidence aliases, but never
owns PASS authority. This adapter reloads the runtime-hashed candidate, binds
all semantic evidence aliases to durable R1 Evidence, checks producer DSH tool
reality from R1, launches a fresh reviewer Worker/session, and finally lets the
existing deterministic TestDesignClosedLoop decide acceptance.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple

from rc6_runtime.agent_runtime import DshHeadlessWorkerLauncher, WorkerInvocation

from .candidate_payload import CandidatePayloadReader
from .closed_loop_control import ClosedLoopControlPlane
from .dsh_proof import DshR1ProofReader
from .models import Evaluation, EvaluationResult, Evidence, Gap, GapSeverity, TaskStatus
from .test_design_loop import TestDesignClosedLoop, TestDesignLoopResult, TestObligation
from .truth_overlay import append_entity


class DshTestDesignEvaluatorError(RuntimeError):
    pass


_RUNTIME_STATUS_TOOL = "mcp__pfc_aitest_rc6__runtime_status"


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return "%s-%s" % (prefix, hashlib.sha256(raw).hexdigest()[:20])


def _tool_category(tool_name: str) -> str:
    name = str(tool_name or "").strip().lower().replace("-", "_")
    if "read_text" in name or name in {"filesystem", "file_read", "read_file"}:
        return "source_read"
    if "codegraph" in name:
        return "codegraph"
    if name == "git" or name.startswith("git_") or "__git_" in name or "_git_" in name:
        return "git"
    return "other"


@dataclass(frozen=True)
class DshTestDesignEvaluation:
    task_id: str
    artifact_id: str
    designer_worker_id: str
    reviewer_worker_id: str
    reviewer_session_id: str
    reviewer_evidence_ids: Tuple[str, ...]
    obligations: Tuple[TestObligation, ...]
    cases: Tuple[Dict[str, object], ...]
    review: Dict[str, object]
    loop_result: TestDesignLoopResult


class DshTestDesignEvaluator:
    def __init__(
        self,
        launcher: DshHeadlessWorkerLauncher,
        *,
        reviewer_allowed_tools: Sequence[str] = (_RUNTIME_STATUS_TOOL, "read_text", "codegraph_query"),
    ) -> None:
        self.launcher = launcher
        self.reviewer_allowed_tools = tuple(reviewer_allowed_tools)
        if not self.reviewer_allowed_tools:
            raise ValueError("TEST_DESIGN_REVIEWER_REAL_TOOL_REQUIRED")
        self.reader = CandidatePayloadReader()
        self.proofs = DshR1ProofReader()
        self.loop = TestDesignClosedLoop()

    def evaluate(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        artifact_id: str,
    ) -> DshTestDesignEvaluation:
        task = control.scheduler.task(task_id)
        if task.node != "TEST_DESIGN":
            raise DshTestDesignEvaluatorError("TEST_DESIGN_EVALUATOR_TASK_NODE_MISMATCH")
        if task.state != TaskStatus.OUTPUT_PRODUCED:
            raise DshTestDesignEvaluatorError("TEST_DESIGN_EVALUATOR_CANDIDATE_REQUIRED")
        designer_worker_id = str(task.lease_owner or "")
        if not designer_worker_id:
            raise DshTestDesignEvaluatorError("TEST_DESIGN_WORKER_IDENTITY_MISSING")
        if artifact_id not in task.output_artifact_refs:
            raise DshTestDesignEvaluatorError("TEST_DESIGN_ARTIFACT_NOT_TASK_OUTPUT")

        candidate = self.reader.load(
            control.truth,
            artifact_id,
            expected_mission_id=control.mission_id,
            expected_task_id=task_id,
        )
        payload = dict(candidate.semantic_payload)
        artifact_row = control.truth.query("rc7_artifact", artifact_id=artifact_id)[0]
        aliases, canonical_evidence = self._candidate_evidence_aliases(control, artifact_row)
        obligations = self._obligations(payload.get("obligations"), aliases)
        cases = self._cases(payload.get("cases"), aliases)

        producer_categories = {
            _tool_category(proof.tool_name)
            for proof in self.proofs.tool_calls(
                control.truth,
                mission_id=control.mission_id,
                worker_instance_id=designer_worker_id,
            )
        }
        producer_gaps: List[str] = []
        if "source_read" not in producer_categories:
            producer_gaps.append("DESIGNER_REAL_SOURCE_READ_MISSING")
        if any(item.kind.upper() == "CODE_IMPACT" for item in obligations) and "codegraph" not in producer_categories:
            producer_gaps.append("DESIGNER_CODEGRAPH_PROOF_MISSING")

        assignment = self.launcher.assign(
            agent_id="rc7-test-design-sufficiency",
            role="RC7_TEST_DESIGN_REVIEWER",
            phase="DESIGN_REVIEW",
            mission_id=control.mission_id,
            attempt_id=_stable_id("ATT-TD-REVIEW", control.mission_id, artifact_id, candidate.content_hash),
            scope=artifact_id,
            input_refs=tuple([candidate.content_ref] + list(task.input_artifact_refs)),
            allowed_artifact_types=("rc7_test_design_review", "analysis_gap"),
            allowed_tools=self.reviewer_allowed_tools,
            parent_worker_id=getattr(self.launcher, "coordinator_instance_id", None),
        )
        if assignment.worker_instance_id == designer_worker_id:
            raise DshTestDesignEvaluatorError("TEST_DESIGN_REVIEWER_NOT_INDEPENDENT")
        reviewer, output = self.launcher.execute(
            assignment,
            self._review_prompt(
                task_id=task_id,
                artifact_id=artifact_id,
                designer_worker_id=designer_worker_id,
                obligations=obligations,
                cases=cases,
            ),
        )
        if reviewer.worker_instance_id == designer_worker_id:
            raise DshTestDesignEvaluatorError("TEST_DESIGN_REVIEWER_NOT_INDEPENDENT")
        if not reviewer.dsh_session_id:
            raise DshTestDesignEvaluatorError("TEST_DESIGN_REVIEWER_SESSION_MISSING")
        if not reviewer.tool_calls:
            raise DshTestDesignEvaluatorError("TEST_DESIGN_REVIEWER_REAL_TOOL_CALL_MISSING")

        reviewer_evidence_ids = self._persist_reviewer_evidence(
            control,
            task_id=task_id,
            artifact_id=artifact_id,
            reviewer=reviewer,
        )
        review = self._normalize_review(
            output,
            reviewer=reviewer,
            designer_worker_id=designer_worker_id,
            reviewer_evidence_ids=reviewer_evidence_ids,
            requires_codegraph=any(item.kind.upper() == "CODE_IMPACT" for item in obligations),
        )

        base = self.loop.evaluate(
            mission_id=control.mission_id,
            artifact_ref=artifact_id,
            obligations=obligations,
            cases=cases,
            evaluator_ref="dsh:%s+deterministic-test-design-gate" % reviewer.worker_instance_id,
        )
        result = self._merge_reviewer_and_runtime_gaps(
            control,
            artifact_id=artifact_id,
            base=base,
            producer_gaps=producer_gaps,
            review=review,
            evidence_refs=list(dict.fromkeys(canonical_evidence + list(reviewer_evidence_ids))),
        )
        return DshTestDesignEvaluation(
            task_id=task_id,
            artifact_id=artifact_id,
            designer_worker_id=designer_worker_id,
            reviewer_worker_id=reviewer.worker_instance_id,
            reviewer_session_id=str(reviewer.dsh_session_id),
            reviewer_evidence_ids=tuple(reviewer_evidence_ids),
            obligations=tuple(obligations),
            cases=tuple(cases),
            review=review,
            loop_result=result,
        )

    def evaluate_and_apply(
        self,
        control: ClosedLoopControlPlane,
        task_id: str,
        artifact_id: str,
    ) -> DshTestDesignEvaluation:
        evaluated = self.evaluate(control, task_id, artifact_id)
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
            raise DshTestDesignEvaluatorError("TEST_DESIGN_ARTIFACT_EVIDENCE_MISSING")
        aliases: Dict[str, str] = {}
        canonical: List[str] = []
        ambiguous = set()
        for evidence_id in refs:
            if not isinstance(evidence_id, str) or not evidence_id:
                continue
            rows = control.truth.query("rc7_evidence", evidence_id=evidence_id)
            if len(rows) != 1:
                continue
            row = rows[0]
            if row.get("mission_id") != control.mission_id:
                raise DshTestDesignEvaluatorError("TEST_DESIGN_EVIDENCE_MISSION_MISMATCH")
            canonical_id = str(row.get("evidence_id") or "")
            if not canonical_id:
                continue
            canonical.append(canonical_id)
            for alias in (canonical_id, row.get("content_ref"), row.get("source_ref")):
                if not isinstance(alias, str) or not alias:
                    continue
                prior = aliases.get(alias)
                if prior is not None and prior != canonical_id:
                    ambiguous.add(alias)
                else:
                    aliases[alias] = canonical_id
        for alias in ambiguous:
            aliases.pop(alias, None)
        if not canonical:
            raise DshTestDesignEvaluatorError("TEST_DESIGN_ARTIFACT_HAS_NO_DURABLE_EVIDENCE")
        return aliases, canonical

    @staticmethod
    def _obligations(raw: object, aliases: Mapping[str, str]) -> List[TestObligation]:
        if not isinstance(raw, list) or not raw:
            raise DshTestDesignEvaluatorError("TEST_DESIGN_OBLIGATIONS_REQUIRED")
        result = []
        for item in raw:
            if not isinstance(item, dict):
                raise DshTestDesignEvaluatorError("TEST_DESIGN_OBLIGATION_INVALID")
            refs = item.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                raise DshTestDesignEvaluatorError("TEST_DESIGN_OBLIGATION_EVIDENCE_REQUIRED")
            canonical = []
            for ref in refs:
                if not isinstance(ref, str) or ref not in aliases:
                    raise DshTestDesignEvaluatorError("TEST_DESIGN_OBLIGATION_EVIDENCE_NOT_DURABLE:%s" % ref)
                canonical.append(aliases[ref])
            result.append(
                TestObligation(
                    obligation_id=str(item.get("obligation_id") or ""),
                    kind=str(item.get("kind") or ""),
                    layer=str(item.get("layer") or ""),
                    risk=str(item.get("risk") or ""),
                    evidence_refs=tuple(dict.fromkeys(canonical)),
                    required=item.get("required", True) is True,
                )
            )
        return result

    @staticmethod
    def _cases(raw: object, aliases: Mapping[str, str]) -> List[Dict[str, object]]:
        if not isinstance(raw, list) or not raw:
            raise DshTestDesignEvaluatorError("TEST_DESIGN_CASES_REQUIRED")
        result: List[Dict[str, object]] = []
        for item in raw:
            if not isinstance(item, dict):
                raise DshTestDesignEvaluatorError("TEST_DESIGN_CASE_INVALID")
            case = dict(item)
            links = case.get("coverage_links")
            if not isinstance(links, list):
                raise DshTestDesignEvaluatorError("TEST_DESIGN_CASE_COVERAGE_LINKS_REQUIRED")
            normalized_links = []
            for link in links:
                if not isinstance(link, dict):
                    raise DshTestDesignEvaluatorError("TEST_DESIGN_CASE_COVERAGE_LINK_INVALID")
                ref = link.get("evidence_ref")
                if not isinstance(ref, str) or ref not in aliases:
                    raise DshTestDesignEvaluatorError("TEST_DESIGN_COVERAGE_EVIDENCE_NOT_DURABLE:%s" % ref)
                row = dict(link)
                row["evidence_ref"] = aliases[ref]
                normalized_links.append(row)
            case["coverage_links"] = normalized_links
            oracle = case.get("oracle")
            if isinstance(oracle, dict):
                checks = oracle.get("checks")
                if isinstance(checks, list):
                    normalized_checks = []
                    for check in checks:
                        if not isinstance(check, dict):
                            raise DshTestDesignEvaluatorError("TEST_DESIGN_ORACLE_CHECK_INVALID")
                        ref = check.get("evidence_ref")
                        if not isinstance(ref, str) or ref not in aliases:
                            raise DshTestDesignEvaluatorError("TEST_DESIGN_ORACLE_EVIDENCE_NOT_DURABLE:%s" % ref)
                        row = dict(check)
                        row["evidence_ref"] = aliases[ref]
                        normalized_checks.append(row)
                    oracle_row = dict(oracle)
                    oracle_row["checks"] = normalized_checks
                    case["oracle"] = oracle_row
            result.append(case)
        return result

    @staticmethod
    def _persist_reviewer_evidence(
        control: ClosedLoopControlPlane,
        *,
        task_id: str,
        artifact_id: str,
        reviewer: WorkerInvocation,
    ) -> Tuple[str, ...]:
        refs: List[str] = list(reviewer.evidence_refs)
        for call in reviewer.tool_calls:
            if isinstance(call, dict):
                value = call.get("call_ref")
                if isinstance(value, str) and value:
                    refs.append(value)
        evidence_ids = []
        for ref in refs:
            if not isinstance(ref, str) or not ref:
                continue
            evidence_id = _stable_id(
                "EVD-TD-REVIEW",
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
                        kind="INDEPENDENT_TEST_DESIGN_REVIEW_PROOF",
                        source_ref="dsh://worker/%s" % reviewer.worker_instance_id,
                        content_ref=ref,
                        subject_refs=[task_id, artifact_id],
                    ),
                    release_id=control.release_id,
                    artifact_version=1,
                )
            evidence_ids.append(evidence_id)
        if not evidence_ids:
            raise DshTestDesignEvaluatorError("TEST_DESIGN_REVIEWER_EVIDENCE_MISSING")
        return tuple(dict.fromkeys(evidence_ids))

    @staticmethod
    def _normalize_review(
        output: Dict[str, object],
        *,
        reviewer: WorkerInvocation,
        designer_worker_id: str,
        reviewer_evidence_ids: Sequence[str],
        requires_codegraph: bool,
    ) -> Dict[str, object]:
        if not isinstance(output, dict):
            raise DshTestDesignEvaluatorError("TEST_DESIGN_REVIEW_OUTPUT_NOT_OBJECT")
        decision = output.get("decision")
        if not isinstance(decision, str) or decision.upper() not in {"PASS", "GAPS"}:
            raise DshTestDesignEvaluatorError("TEST_DESIGN_REVIEW_DECISION_INVALID")
        gap_ids = output.get("gap_ids", [])
        if not isinstance(gap_ids, list) or not all(isinstance(value, str) and value for value in gap_ids):
            raise DshTestDesignEvaluatorError("TEST_DESIGN_REVIEW_GAP_IDS_INVALID")
        categories = {
            _tool_category(str(call.get("tool_name") or ""))
            for call in reviewer.tool_calls
            if isinstance(call, dict)
        }
        enforced = list(gap_ids)
        if "source_read" not in categories:
            enforced.append("REVIEWER_REAL_SOURCE_READ_MISSING")
        if requires_codegraph and "codegraph" not in categories:
            enforced.append("REVIEWER_CODEGRAPH_PROOF_MISSING")
        return {
            "reviewer_worker_id": reviewer.worker_instance_id,
            "designer_worker_id": designer_worker_id,
            "decision": "GAPS" if enforced else decision.upper(),
            "gap_ids": list(dict.fromkeys(enforced)),
            "evidence_refs": list(reviewer_evidence_ids),
            "summary": str(output.get("summary") or ""),
        }

    def _merge_reviewer_and_runtime_gaps(
        self,
        control: ClosedLoopControlPlane,
        *,
        artifact_id: str,
        base: TestDesignLoopResult,
        producer_gaps: Sequence[str],
        review: Mapping[str, object],
        evidence_refs: Sequence[str],
    ) -> TestDesignLoopResult:
        extra_reasons = list(producer_gaps)
        review_gap_ids = review.get("gap_ids", [])
        if isinstance(review_gap_ids, list):
            extra_reasons.extend(str(value) for value in review_gap_ids if isinstance(value, str) and value)
        if not extra_reasons:
            evaluation = Evaluation(
                evaluation_id=base.evaluation.evaluation_id,
                mission_id=base.evaluation.mission_id,
                node=base.evaluation.node,
                artifact_refs=list(base.evaluation.artifact_refs),
                result=base.evaluation.result,
                evaluator_ref=base.evaluation.evaluator_ref,
                dimensions=dict(base.evaluation.dimensions, independent_review="PASS"),
                gap_refs=list(base.evaluation.gap_refs),
                evidence_refs=list(dict.fromkeys(list(base.evaluation.evidence_refs) + list(evidence_refs))),
            )
            return TestDesignLoopResult(
                evaluation=evaluation,
                gaps=base.gaps,
                delta_requests=base.delta_requests,
                semantic_coverage=base.semantic_coverage,
                case_count=base.case_count,
            )

        extra_gaps = []
        for reason in sorted(set(extra_reasons)):
            extra_gaps.append(
                Gap(
                    gap_id=_stable_id("GAP-TD-REVIEW", control.mission_id, artifact_id, reason),
                    mission_id=control.mission_id,
                    source_node="TEST_DESIGN",
                    category="TEST_DESIGN_REVIEW_GAP",
                    severity=GapSeverity.HIGH,
                    target_node="TEST_DESIGN",
                    description=reason,
                    subject_refs=[artifact_id],
                    evidence_refs=list(evidence_refs),
                    acceptance_criteria=["independent Test Design review no longer reports %s" % reason],
                )
            )
        gaps = tuple(list(base.gaps) + extra_gaps)
        dimensions = dict(base.evaluation.dimensions)
        dimensions["independent_review"] = "GAPS"
        dimensions["review_gap_ids"] = sorted(set(extra_reasons))
        evaluation = Evaluation(
            evaluation_id=_stable_id(
                "EVAL-TD-DSH",
                control.mission_id,
                artifact_id,
                base.evaluation.evaluation_id,
                ",".join(sorted(gap.gap_id for gap in gaps)),
            ),
            mission_id=control.mission_id,
            node="TEST_DESIGN",
            artifact_refs=[artifact_id],
            result=EvaluationResult.REPAIR_REQUIRED,
            evaluator_ref=base.evaluation.evaluator_ref,
            dimensions=dimensions,
            gap_refs=[gap.gap_id for gap in gaps],
            evidence_refs=list(dict.fromkeys(list(base.evaluation.evidence_refs) + list(evidence_refs))),
        )
        return TestDesignLoopResult(
            evaluation=evaluation,
            gaps=gaps,
            delta_requests=base.delta_requests,
            semantic_coverage=base.semantic_coverage,
            case_count=base.case_count,
        )

    def _review_prompt(
        self,
        *,
        task_id: str,
        artifact_id: str,
        designer_worker_id: str,
        obligations: Sequence[TestObligation],
        cases: Sequence[Dict[str, object]],
    ) -> str:
        contract = {
            "task_id": task_id,
            "artifact_id": artifact_id,
            "designer_worker_id": designer_worker_id,
            "allowed_tools": list(self.reviewer_allowed_tools),
            "obligations": [
                {
                    "obligation_id": item.obligation_id,
                    "kind": item.kind,
                    "layer": item.layer,
                    "risk": item.risk,
                    "required": item.required,
                    "evidence_refs": list(item.evidence_refs),
                }
                for item in obligations
            ],
            "cases": list(cases),
        }
        schema = {
            "decision": "PASS or GAPS",
            "gap_ids": ["specific missing scenario, boundary, state, permission, data, regression, or oracle gap"],
            "summary": "independent review rationale",
        }
        return (
            "You are an independent RC7 Test Design Sufficiency Reviewer. You are not the designer. "
            "Use real read_text and CodeGraph evidence when relevant. Review semantic obligations, case coverage, "
            "risk, positive/negative/boundary/state/permission/data/regression scenarios and Oracle completeness. "
            "Case count is never a sufficiency criterion. Do not modify the candidate and do not emit a canonical "
            "Evaluation or Task state. Return GAPS for any material missing scenario or unverifiable coverage. "
            "Return exactly one JSON object.\n"
            "REVIEW_CONTRACT=" + json.dumps(contract, ensure_ascii=False, sort_keys=True) + "\n"
            "RETURN_SCHEMA=" + json.dumps(schema, ensure_ascii=False, sort_keys=True)
        )
