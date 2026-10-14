"""RC6 Wave 5 evidence-backed requirement/code intelligence gates.

Gates recompute sufficiency from canonical artifacts and evidence. Caller supplied
percentages, gap counts or boolean claims are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Set, Tuple


class IntelligenceContractError(ValueError):
    pass


@dataclass(frozen=True)
class GateResult:
    passed: bool
    status: str
    reasons: List[str]
    metrics: Dict[str, Any]


REQUIRED_REQ_DIMENSIONS = (
    "business_rules", "roles", "preconditions", "normal_paths", "negative_paths",
    "boundaries", "states", "data_constraints", "dependencies", "side_effects",
)


def _require_str(obj: Dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IntelligenceContractError(f"MISSING_OR_INVALID_{key.upper()}")
    return value.strip()


def _require_list(obj: Dict[str, Any], key: str) -> list:
    value = obj.get(key)
    if not isinstance(value, list):
        raise IntelligenceContractError(f"MISSING_OR_INVALID_{key.upper()}")
    return value


def _unique_ids(items: Iterable[Dict[str, Any]], field: str, code: str) -> Set[str]:
    result: Set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise IntelligenceContractError(code)
        item_id = item.get(field)
        if not isinstance(item_id, str) or not item_id.strip() or item_id in result:
            raise IntelligenceContractError(code)
        result.add(item_id)
    return result


def _validate_review(review: Dict[str, Any], analysis_id: str, analyzer_worker_id: str) -> List[str]:
    reasons: List[str] = []
    if not isinstance(review, dict):
        return ["REVIEW_MISSING"]
    try:
        _require_str(review, "review_id")
        subject = _require_str(review, "subject_analysis_id")
        reviewer = _require_str(review, "reviewer_worker_id")
        reviewed_analyzer = _require_str(review, "analyzer_worker_id")
        decision = _require_str(review, "decision").upper()
        evidence = _require_list(review, "evidence_refs")
        gaps = _require_list(review, "gap_ids")
    except IntelligenceContractError as exc:
        return [f"INVALID_REVIEW:{exc}"]
    if subject != analysis_id:
        reasons.append("REVIEW_SUBJECT_MISMATCH")
    if reviewed_analyzer != analyzer_worker_id:
        reasons.append("REVIEW_ANALYZER_MISMATCH")
    if reviewer == analyzer_worker_id:
        reasons.append("REVIEW_INDEPENDENCE_FAIL")
    if decision not in {"PASS", "GAPS"}:
        reasons.append("REVIEW_DECISION_INVALID")
    if not evidence:
        reasons.append("REVIEW_EVIDENCE_MISSING")
    if decision == "GAPS" or gaps:
        reasons.append("REVIEW_OPEN_GAPS")
    return reasons


class RequirementSufficiencyEvaluator:
    def evaluate(self, artifact: Dict[str, Any], review: Dict[str, Any]) -> GateResult:
        reasons: List[str] = []
        metrics: Dict[str, Any] = {}
        try:
            analysis_id = _require_str(artifact, "analysis_id")
            _require_str(artifact, "release_id")
            _require_str(artifact, "requirement_id")
            analyzer_worker_id = _require_str(artifact, "analyzer_worker_id")
            sources = _require_list(artifact, "source_assertions")
            atomic = _require_list(artifact, "atomic_statements")
            links = _require_list(artifact, "trace_links")
            evidence_refs = _require_list(artifact, "evidence_refs")
            for dim in REQUIRED_REQ_DIMENSIONS:
                _require_list(artifact, dim)
            source_ids = _unique_ids(sources, "id", "INVALID_SOURCE_ASSERTION_IDS")
            atomic_ids = _unique_ids(atomic, "id", "INVALID_ATOMIC_STATEMENT_IDS")
        except IntelligenceContractError as exc:
            return GateResult(False, "INVALID_ARTIFACT_SCHEMA", [str(exc)], {})

        if not sources or not atomic:
            reasons.append("REQ_EMPTY_SOURCE_OR_ATOMIC")
        if not evidence_refs:
            reasons.append("REQ_EVIDENCE_MISSING")

        mapped_source: Set[str] = set()
        mapped_atomic: Set[str] = set()
        bad_links = 0
        for link in links:
            if not isinstance(link, dict):
                bad_links += 1
                continue
            sid = link.get("source_id")
            aid = link.get("atomic_id")
            eref = link.get("evidence_ref")
            if sid not in source_ids or aid not in atomic_ids or not isinstance(eref, str) or not eref.strip():
                bad_links += 1
                continue
            mapped_source.add(sid)
            mapped_atomic.add(aid)

        orphan_sources = sorted(source_ids - mapped_source)
        unsupported_atomic = sorted(atomic_ids - mapped_atomic)
        untestable = sorted(
            x.get("id") for x in atomic
            if isinstance(x, dict) and x.get("id") in atomic_ids and x.get("testable") is not True
        )
        missing_source_refs = sorted(
            x.get("id") for x in atomic
            if isinstance(x, dict) and x.get("id") in atomic_ids
            and (not isinstance(x.get("source_ref"), str) or not x.get("source_ref").strip())
        )

        metrics.update({
            "source_total": len(source_ids),
            "source_mapped": len(mapped_source),
            "atomic_total": len(atomic_ids),
            "atomic_mapped": len(mapped_atomic),
            "traceability": (len(mapped_source) / len(source_ids)) if source_ids else 0.0,
            "orphan_source_ids": orphan_sources,
            "unsupported_atomic_ids": unsupported_atomic,
            "untestable_atomic_ids": untestable,
            "bad_trace_links": bad_links,
        })
        if orphan_sources:
            reasons.append("REQ_TRACEABILITY_GAP")
        if unsupported_atomic or missing_source_refs:
            reasons.append("REQ_UNSUPPORTED_ASSERTION")
        if untestable:
            reasons.append("REQ_TESTABILITY_GAP")
        if bad_links:
            reasons.append("REQ_INVALID_TRACE_LINK")

        reasons.extend(_validate_review(review, analysis_id, analyzer_worker_id))
        return GateResult(not reasons, "SUFFICIENT" if not reasons else "NOT_SUFFICIENT_CONTENT", reasons, metrics)


class CodeSufficiencyEvaluator:
    def evaluate(self, artifact: Dict[str, Any], review: Dict[str, Any], *, target_id: str) -> GateResult:
        reasons: List[str] = []
        metrics: Dict[str, Any] = {}
        try:
            analysis_id = _require_str(artifact, "analysis_id")
            _require_str(artifact, "release_id")
            analyzer_worker_id = _require_str(artifact, "analyzer_worker_id")
            requirements = _require_list(artifact, "requirement_ids")
            source_revisions = artifact.get("source_revisions")
            if not isinstance(source_revisions, dict) or not source_revisions:
                raise IntelligenceContractError("MISSING_OR_INVALID_SOURCE_REVISIONS")
            changed_files = _require_list(artifact, "changed_files")
            changed_symbols = _require_list(artifact, "changed_symbols")
            explanations = _require_list(artifact, "symbol_explanations")
            reverse = _require_list(artifact, "reverse_requirement_mappings")
            tool_calls = _require_list(artifact, "tool_calls")
            evidence_refs = _require_list(artifact, "evidence_refs")
            symbol_ids = _unique_ids(changed_symbols, "id", "INVALID_CHANGED_SYMBOL_IDS")
        except IntelligenceContractError as exc:
            return GateResult(False, "INVALID_ARTIFACT_SCHEMA", [str(exc)], {})

        requirement_ids = {x for x in requirements if isinstance(x, str) and x.strip()}
        if len(requirement_ids) != len(requirements):
            reasons.append("CODE_INVALID_REQUIREMENT_IDS")
        if not evidence_refs:
            reasons.append("CODE_EVIDENCE_MISSING")
        if not changed_files or not changed_symbols:
            reasons.append("CODE_CHANGESET_EMPTY")
        if any(not isinstance(v, str) or not v.strip() for v in source_revisions.values()):
            reasons.append("CODE_SOURCE_REVISION_MISSING")

        explained: Set[str] = set()
        bad_explanations = 0
        for item in explanations:
            if not isinstance(item, dict):
                bad_explanations += 1
                continue
            sid = item.get("symbol_id")
            erefs = item.get("evidence_refs")
            if sid not in symbol_ids or not isinstance(erefs, list) or not erefs or not all(isinstance(x, str) and x.strip() for x in erefs):
                bad_explanations += 1
                continue
            explained.add(sid)
        unexplained = sorted(symbol_ids - explained)

        mapped_requirements: Set[str] = set()
        bad_reverse = 0
        for item in reverse:
            if not isinstance(item, dict):
                bad_reverse += 1
                continue
            rid = item.get("requirement_id")
            sid = item.get("symbol_id")
            eref = item.get("evidence_ref")
            if rid not in requirement_ids or sid not in symbol_ids or not isinstance(eref, str) or not eref.strip():
                bad_reverse += 1
                continue
            mapped_requirements.add(rid)
        unmapped_requirements = sorted(requirement_ids - mapped_requirements)

        codegraph_required = artifact.get("codegraph_required") is not False
        codegraph_calls = [
            c for c in tool_calls
            if isinstance(c, dict) and c.get("tool_id") == "codegraph"
            and isinstance(c.get("call_ref"), str) and c.get("call_ref").strip()
            and isinstance(c.get("evidence_ref"), str) and c.get("evidence_ref").strip()
            and c.get("target_id") == target_id
        ]
        git_calls = [
            c for c in tool_calls
            if isinstance(c, dict) and c.get("tool_id") == "git"
            and isinstance(c.get("call_ref"), str) and c.get("call_ref").strip()
            and isinstance(c.get("evidence_ref"), str) and c.get("evidence_ref").strip()
            and c.get("target_id") == target_id
        ]

        metrics.update({
            "changed_symbol_total": len(symbol_ids),
            "explained_symbol_total": len(explained),
            "unexplained_symbol_ids": unexplained,
            "requirement_total": len(requirement_ids),
            "reverse_mapped_requirement_total": len(mapped_requirements),
            "unmapped_requirement_ids": unmapped_requirements,
            "codegraph_evidence_calls": len(codegraph_calls),
            "git_evidence_calls": len(git_calls),
        })
        if unexplained or bad_explanations:
            reasons.append("CODE_UNEXPLAINED_CHANGE")
        if unmapped_requirements or bad_reverse:
            reasons.append("CODE_REVERSE_MAPPING_GAP")
        if codegraph_required and not codegraph_calls:
            reasons.append("CODEGRAPH_REAL_TOOL_EVIDENCE_MISSING")
        if not git_calls:
            reasons.append("GIT_REAL_TOOL_EVIDENCE_MISSING")

        reasons.extend(_validate_review(review, analysis_id, analyzer_worker_id))
        return GateResult(not reasons, "SUFFICIENT" if not reasons else "NOT_SUFFICIENT_CONTENT", reasons, metrics)
