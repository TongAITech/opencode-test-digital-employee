from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aitest_runtime.durable_core import canonical_sha256

from .contracts import (
    COVERAGE_DIMENSIONS,
    DECISION_SCOPE_KINDS,
    EVIDENCE_CONFIDENCE_STATES,
    EvidenceConfidence,
    R37EvaluationInput,
    RemainingRiskItem,
    RISK_CATEGORIES,
    WorkSetReceipt,
)
from .errors import R37Error


@dataclass(frozen=True)
class EvaluationResult:
    decision: Any
    remaining_risks: tuple[RemainingRiskItem, ...]
    coverage_summary: Mapping[str, Any]
    evidence_status: str


def _as_bool(value: Any) -> bool:
    return bool(value)


def _item_id(item: Mapping[str, Any], fallback: str) -> str:
    value = item.get("risk_item_id") or item.get("id") or item.get("ref_id")
    return str(value) if value else fallback


def _dimension_from_sources(evaluation: R37EvaluationInput, dimension: str) -> dict[str, Any]:
    if dimension == "requirement":
        obligations = evaluation.coverage_snapshot_ref.get("obligations") or ()
        denominator = int(evaluation.coverage_snapshot_ref.get("denominator_count", len(obligations)))
        mapped = sum(1 for item in obligations if str(item.get("mapping_state", "")).upper() == "MAPPED")
        partial = sum(1 for item in obligations if str(item.get("mapping_state", "")).upper() == "PARTIAL")
        unmapped = sum(1 for item in obligations if str(item.get("mapping_state", "")).upper() == "UNMAPPED")
        uncovered = sum(
            1 for item in obligations
            if any(str(gap.get("kind", gap)).upper() in {"UNCOVERED", "REQUIREMENT_CODE_GAP", "SOURCE_INCOMPLETE"} for gap in item.get("coverage_gaps", ()))
        )
        return {
            "applicable": denominator > 0 or bool(obligations), "denominator_count": denominator,
            "covered_count": max(0, mapped - partial), "mapped_count": mapped, "partial_count": partial,
            "unmapped_count": unmapped, "uncovered_count": uncovered, "blocked_count": 0,
            "covered_refs": [], "gap_refs": [], "source_refs": [dict(evaluation.coverage_snapshot_ref)],
        }
    if dimension == "change":
        reconciliation = evaluation.reconciliation_ref
        changes = reconciliation.get("change_obligations") or ()
        items = reconciliation.get("items") or ()
        denominator = int(reconciliation.get("change_denominator_count", len(changes)))
        if not denominator:
            denominator = sum(1 for item in items if item.get("change_obligation_id") or item.get("semantic") == "CHANGE_ONLY")
        unresolved = sum(
            1 for item in changes
            if str(item.get("impact_resolution", "")).upper() in {"PARTIAL", "UNMAPPED"}
        )
        unresolved += sum(1 for item in items if str(item.get("semantic", "")) == "CHANGE_ONLY" and item.get("gap_kinds"))
        return {
            "applicable": denominator > 0 or bool(changes) or bool(items), "denominator_count": denominator,
            "covered_count": max(0, denominator - unresolved), "mapped_count": max(0, denominator - unresolved),
            "partial_count": 0, "unmapped_count": unresolved, "uncovered_count": unresolved, "blocked_count": 0,
            "covered_refs": [], "gap_refs": [], "source_refs": [dict(evaluation.reconciliation_ref)],
        }
    if dimension == "risk":
        refs = evaluation.risk_vector_refs or evaluation.standard_case_refs
        return {
            "applicable": bool(refs), "denominator_count": len(refs), "covered_count": 0, "mapped_count": 0,
            "partial_count": 0, "unmapped_count": 0, "uncovered_count": len(refs), "blocked_count": 0,
            "covered_refs": [], "gap_refs": [], "source_refs": [dict(item) for item in refs],
        }
    refs = evaluation.journey_refs
    verified = sum(
        1 for item in refs
        if str(item.get("result", item.get("status", ""))).upper() == "PASS"
        and str(item.get("runtime_execution", "")).upper() == "REAL"
        and str(item.get("evidence_class", "")).upper() == "FIELD_EVIDENCE"
    )
    return {
        "applicable": bool(refs), "denominator_count": len(refs), "covered_count": verified,
        "mapped_count": verified, "partial_count": 0, "unmapped_count": 0,
        "uncovered_count": max(0, len(refs) - verified), "blocked_count": 0,
        "covered_refs": [], "gap_refs": [], "source_refs": [dict(item) for item in refs],
    }


def normalize_coverage(evaluation: R37EvaluationInput) -> dict[str, Any]:
    supplied = dict(evaluation.coverage_summary.get("dimensions") or {})
    dimensions: dict[str, Any] = {}
    for dimension in COVERAGE_DIMENSIONS:
        dimensions[dimension] = dict(supplied.get(dimension) or _dimension_from_sources(evaluation, dimension))
        dimensions[dimension].setdefault("applicable", False)
        dimensions[dimension].setdefault("denominator_count", 0)
        dimensions[dimension].setdefault("covered_count", 0)
        dimensions[dimension].setdefault("mapped_count", 0)
        dimensions[dimension].setdefault("partial_count", 0)
        dimensions[dimension].setdefault("unmapped_count", 0)
        dimensions[dimension].setdefault("uncovered_count", 0)
        dimensions[dimension].setdefault("blocked_count", 0)
        dimensions[dimension].setdefault("covered_refs", [])
        dimensions[dimension].setdefault("gap_refs", [])
        dimensions[dimension].setdefault("source_refs", [])
    return {"dimensions": dimensions, "summary_digest": canonical_sha256({"dimensions": dimensions})}


def _required_source_blockers(evaluation: R37EvaluationInput) -> list[str]:
    blockers: list[str] = []
    if evaluation.blocked_critical_work:
        blockers.append("BLOCKED_CRITICAL_WORK")
    if evaluation.r2_runtime_projection_ref is None:
        blockers.append("R2_RUNTIME_PROJECTION_MISSING")
    if evaluation.workset_request is None or evaluation.workset_receipt is None:
        blockers.append("BOUNDED_WORKSET_RECEIPT_MISSING")
    elif evaluation.workset_request.workset_id != evaluation.workset_receipt.workset_id:
        blockers.append("WORKSET_REQUEST_RECEIPT_MISMATCH")
    elif (
        evaluation.workset_request.session_ref != evaluation.session_ref
        or evaluation.workset_receipt.session_ref != evaluation.session_ref
    ):
        blockers.append("WORKSET_SESSION_MISMATCH")
    elif (
        evaluation.workset_request.as_of_seq != evaluation.as_of_seq
        or dict(evaluation.workset_request.source_cursors) != dict(evaluation.source_cursors)
    ):
        blockers.append("WORKSET_CURSOR_MISMATCH")
    if not evaluation.session_ref:
        blockers.append("EPHEMERAL_SESSION_REF_MISSING")
    if evaluation.workset_receipt is not None:
        if evaluation.workset_receipt.truncation != "NONE":
            blockers.append("WORKSET_TRUNCATED")
        for source, status in evaluation.workset_receipt.source_statuses.items():
            if status != "COLLECTED" and any(token in source.upper() for token in ("R1", "R2", "R3", "EVIDENCE", "CRITICAL")):
                blockers.append(f"SOURCE_{status}_{source}")
    return blockers


def _overall_evidence_status(confidences: tuple[EvidenceConfidence, ...]) -> str:
    if not confidences:
        return "NOT_EVALUATED"
    states = {item.status for item in confidences}
    for state in ("BLOCKED", "UNAVAILABLE", "CONFLICTED", "INSUFFICIENT", "PARTIAL"):
        if state in states:
            return state
    return "SUFFICIENT" if states == {"SUFFICIENT"} else "NOT_EVALUATED"


def _risk(
    evaluation: R37EvaluationInput,
    risk_item_id: str,
    category: str,
    reason_code: str,
    summary: str,
    *,
    critical: bool,
    status: str = "OPEN",
    gap_refs: tuple[Any, ...] = (),
    evidence_refs: tuple[Any, ...] = (),
    defect_refs: tuple[Any, ...] = (),
    acceptance_ref: Mapping[str, Any] | None = None,
    field_validation_required: bool = False,
) -> RemainingRiskItem:
    if category not in RISK_CATEGORIES:
        raise R37Error("R3_7_SCHEMA_INVALID", f"unsupported generated risk category: {category}")
    sources = (evaluation.coverage_snapshot_ref, evaluation.reconciliation_ref)
    return RemainingRiskItem(
        risk_item_id=risk_item_id, scope=evaluation.scope, category=category, severity_or_risk_band="CRITICAL" if critical else "MEDIUM",
        status=status, critical=critical, reason_code=reason_code, risk_summary=summary,
        source_refs=sources, coverage_gap_refs=gap_refs, evidence_refs=evidence_refs, defect_refs=defect_refs,
        acceptance_ref=acceptance_ref, field_validation_required=field_validation_required,
        origin_lineage=evaluation.origin_lineage,
    )


def _input_risks(evaluation: R37EvaluationInput) -> list[RemainingRiskItem]:
    return [item if isinstance(item, RemainingRiskItem) else RemainingRiskItem.from_dict(item) for item in evaluation.remaining_risk]


def _risk_acceptance_covers(risk_acceptance_ref: Mapping[str, Any] | None, risks: list[RemainingRiskItem]) -> bool:
    """Validate the explicit acceptance boundary without making it canonical truth."""
    if not risk_acceptance_ref:
        return False
    has_actor_or_policy = any(
        key in risk_acceptance_ref for key in ("actor_ref", "authorized_by", "policy_ref", "authorization_ref")
    )
    has_scope = any(key in risk_acceptance_ref for key in ("scope", "scope_ref")) or all(
        key in risk_acceptance_ref for key in ("project_id", "environment_id", "version_scope")
    )
    has_review_or_expiry = any(
        key in risk_acceptance_ref for key in ("review_by", "expiry", "expires_at", "expiry_at")
    )
    accepted_refs = next(
        (
            risk_acceptance_ref.get(key)
            for key in ("accepted_risk_refs", "accepted_risk_item_refs", "risk_refs")
            if risk_acceptance_ref.get(key)
        ),
        (),
    )
    if not isinstance(accepted_refs, (list, tuple)) or not accepted_refs:
        return False
    known_risk_ids = {item.risk_item_id for item in risks}
    accepted_ids = {
        str(item.get("ref_id") or item.get("risk_item_id") or item.get("id"))
        if isinstance(item, Mapping) else str(item)
        for item in accepted_refs
    }
    return has_actor_or_policy and has_scope and has_review_or_expiry and bool(known_risk_ids & accepted_ids)


def evaluate_test_sufficiency(evaluation: R37EvaluationInput | Mapping[str, Any]) -> EvaluationResult:
    if isinstance(evaluation, Mapping):
        evaluation = R37EvaluationInput.from_dict(evaluation)
    if not isinstance(evaluation, R37EvaluationInput):
        raise R37Error("R3_7_SCHEMA_INVALID", "evaluation must be R37EvaluationInput or object")

    coverage = normalize_coverage(evaluation)
    risks: list[RemainingRiskItem] = _input_risks(evaluation)
    seen = {item.risk_item_id for item in risks}

    def add(item: RemainingRiskItem) -> None:
        if item.risk_item_id not in seen:
            risks.append(item)
            seen.add(item.risk_item_id)

    for dimension, summary in coverage["dimensions"].items():
        if not summary.get("applicable"):
            continue
        if dimension == "risk" and (evaluation.risk_vector_refs or evaluation.standard_case_refs):
            required_links = (
                ("standard_case_refs", evaluation.standard_case_refs),
                ("case_review_refs", evaluation.case_review_refs),
                ("readiness_refs", evaluation.readiness_refs),
                ("attempt_refs", evaluation.attempt_refs),
                ("result_refs", evaluation.result_refs),
            )
            missing_links = [name for name, refs in required_links if not refs]
            if missing_links:
                summary["covered_count"] = 0
                summary["uncovered_count"] = max(1, int(summary.get("uncovered_count", 0)))
                summary["gap_refs"] = list(summary.get("gap_refs") or ()) + [
                    {"ref_id": f"r3.7:risk-link:{name}", "kind": "R3_7_LINK_GAP", "digest": canonical_sha256({"missing": name})}
                    for name in missing_links
                ]
                add(_risk(
                    evaluation, "risk:risk-coverage:governance-links", "CRITICAL_RISK_UNTESTED", "RISK_LINK_GAP",
                    f"risk coverage is missing governed links: {', '.join(missing_links)}", critical=True,
                    gap_refs=tuple(summary["gap_refs"]),
                ))
        denominator = int(summary.get("denominator_count", 0))
        covered = int(summary.get("covered_count", 0))
        unmapped = int(summary.get("unmapped_count", 0))
        uncovered = int(summary.get("uncovered_count", 0))
        blocked = int(summary.get("blocked_count", 0))
        if unmapped:
            category = "CHANGE_UNMAPPED" if dimension == "change" else "REQUIREMENT_UNMAPPED" if dimension == "requirement" else "JOURNEY_GAP" if dimension == "journey" else "CRITICAL_RISK_UNTESTED"
            add(_risk(evaluation, f"risk:{dimension}:unmapped", category, "UNMAPPED_OBLIGATION", f"{dimension} coverage has {unmapped} unmapped obligations", critical=True, gap_refs=tuple(summary.get("gap_refs") or ())))
        if uncovered or covered < denominator:
            category = "CHANGE_ONLY_UNCOVERED" if dimension == "change" else "REQUIREMENT_UNCOVERED" if dimension == "requirement" else "JOURNEY_GAP" if dimension == "journey" else "CRITICAL_RISK_UNTESTED"
            add(_risk(evaluation, f"risk:{dimension}:uncovered", category, "UNCOVERED_OBLIGATION", f"{dimension} coverage is {covered}/{denominator}", critical=True, gap_refs=tuple(summary.get("gap_refs") or ())))
        if blocked:
            add(_risk(evaluation, f"risk:{dimension}:blocked", "BLOCKED_CRITICAL_WORK", "BLOCKED_COVERAGE", f"{dimension} coverage has blocked critical work", critical=True, status="BLOCKED"))

    for index, item in enumerate(evaluation.uncovered_obligations):
        category = str(item.get("category") or item.get("reason_code") or "REQUIREMENT_UNCOVERED")
        if category not in RISK_CATEGORIES:
            category = "REQUIREMENT_UNCOVERED"
        add(_risk(
            evaluation, _item_id(item, f"risk:uncovered:{index}"), category, str(item.get("reason_code") or "UNCOVERED_OBLIGATION"),
            str(item.get("risk_summary") or item.get("text") or "uncovered or unmapped obligation"),
            critical=bool(item.get("critical", True)), gap_refs=tuple(item.get("gap_refs") or ()),
        ))

    for index, item in enumerate(evaluation.blocked_critical_work):
        add(_risk(
            evaluation, _item_id(item, f"risk:blocked:{index}"), "BLOCKED_CRITICAL_WORK", str(item.get("reason_code") or "BLOCKED_CRITICAL_WORK"),
            str(item.get("risk_summary") or item.get("reason") or "blocked critical work"), critical=True, status="BLOCKED",
        ))

    evidence_status = _overall_evidence_status(evaluation.evidence_confidences)
    if evidence_status in {"INSUFFICIENT", "CONFLICTED"}:
        category = "EVIDENCE_CONFLICTED" if evidence_status == "CONFLICTED" else "EVIDENCE_INSUFFICIENT"
        add(_risk(evaluation, "risk:evidence:confidence", category, f"EVIDENCE_{evidence_status}", f"evidence confidence is {evidence_status}", critical=True, evidence_refs=tuple(evaluation.r1_evidence_refs)))
    elif evidence_status in {"BLOCKED", "UNAVAILABLE"}:
        add(_risk(evaluation, "risk:evidence:blocked", "SOURCE_UNAVAILABLE", f"EVIDENCE_{evidence_status}", f"required evidence is {evidence_status}", critical=True, status="BLOCKED", evidence_refs=tuple(evaluation.r1_evidence_refs)))
    elif evidence_status == "NOT_EVALUATED":
        add(_risk(evaluation, "risk:evidence:not-evaluated", "ORACLE_OR_RESULT_GAP", "EVIDENCE_NOT_EVALUATED", "evidence confidence was not evaluated", critical=True, evidence_refs=tuple(evaluation.r1_evidence_refs)))

    for index, item in enumerate(evaluation.defect_truth):
        outcome = str(item.get("outcome", item.get("status", ""))).upper()
        contradiction = bool(item.get("unresolved_contradiction_refs") or item.get("contradiction_refs"))
        if outcome in {"CONFIRMED_DEFECT", "INCONCLUSIVE", "BLOCKED"} or contradiction:
            category = "CONFIRMED_DEFECT" if outcome == "CONFIRMED_DEFECT" else "INCONCLUSIVE_DEFECT"
            add(_risk(
                evaluation, _item_id(item, f"risk:defect:{index}"), category, "DEFECT_TRUTH_REMAINS", str(item.get("decision_basis") or "defect truth remains a risk"),
                critical=bool(item.get("critical", True)), status="BLOCKED" if outcome == "BLOCKED" else "OPEN",
                defect_refs=(item.get("assessment_ref") or item.get("ref_id") or f"defect:{index}",),
            ))
        if str(item.get("rca_status", "")).upper() in {"PARTIAL", "UNRESOLVED"}:
            add(_risk(evaluation, f"risk:rca:{index}", "INCONCLUSIVE_DEFECT", "RCA_UNRESOLVED", "defect RCA remains partial or unresolved", critical=bool(item.get("critical", True)), defect_refs=(item.get("ref_id") or f"defect:{index}",)))

    field_evidence = any(item.evidence_class == "FIELD_EVIDENCE" and item.status == "SUFFICIENT" for item in evaluation.evidence_confidences)
    real_field_journey = any(
        str(item.get("runtime_execution", "")).upper() == "REAL"
        and str(item.get("evidence_class", "")).upper() == "FIELD_EVIDENCE"
        and str(item.get("result", item.get("status", ""))).upper() == "PASS"
        for item in evaluation.journey_refs
    )
    field_pending = not (field_evidence and real_field_journey)
    if field_pending:
        add(_risk(evaluation, "risk:field-validation", "FIELD_VALIDATION_PENDING", "FIELD_VALIDATION_PENDING", "real field evidence and journey validation remain open", critical=False, status="PENDING_FIELD_VALIDATION", field_validation_required=True))

    hard_blockers = _required_source_blockers(evaluation)
    hard_blockers.extend(item.risk_item_id for item in risks if item.status == "BLOCKED" and item.critical)
    if hard_blockers:
        decision_value = "BLOCKED"
    else:
        acceptance_valid = _risk_acceptance_covers(evaluation.risk_acceptance_ref, risks)
        actionable_risks = [
            item for item in risks
            if item.status in {"OPEN", "BLOCKED"} or (item.status == "PENDING_FIELD_VALIDATION" and evaluation.decision_scope_kind in {"FIELD", "MIXED"})
        ]
        if acceptance_valid and actionable_risks:
            decision_value = "RISK_ACCEPTED"
        else:
            critical_risks = [item for item in actionable_risks if item.critical]
            dimensions_ok = all(
                not summary.get("applicable")
                or (
                    int(summary.get("unmapped_count", 0)) == 0
                    and int(summary.get("uncovered_count", 0)) == 0
                    and int(summary.get("blocked_count", 0)) == 0
                    and int(summary.get("covered_count", 0)) >= int(summary.get("denominator_count", 0))
                )
                for summary in coverage["dimensions"].values()
            )
            evidence_ok = evidence_status == "SUFFICIENT"
            field_ok = evaluation.decision_scope_kind == "ENGINEERING" or (field_evidence and real_field_journey)
            decision_value = "SUFFICIENT" if dimensions_ok and evidence_ok and field_ok and not critical_risks else "NOT_SUFFICIENT"

    risk_refs = [
        {"ref_id": item.risk_item_id, "kind": "R3_7_REMAINING_RISK", "digest": item.risk_digest or ""}
        for item in risks
    ]
    receipt_ref = {
        "ref_id": f"workset:{evaluation.workset_receipt.workset_id}" if evaluation.workset_receipt else "workset:missing",
        "kind": "R3_E1_WORKSET_RECEIPT",
        "digest": evaluation.workset_receipt.receipt_digest if evaluation.workset_receipt else "missing",
    }
    field_state = {
        **dict(evaluation.field_validation_state), "status": "OPEN" if field_pending else "SATISFIED",
        "mandatory": True, "real_field_evidence": field_evidence, "real_field_journey": real_field_journey,
    }
    basis = {
        "policy_version": evaluation.policy_version,
        "actor_ref": dict(evaluation.actor_ref),
        "coverage_rules": {key: dict(value) for key, value in coverage["dimensions"].items()},
        "risk_rules": {"remaining_risk_count": len(risks), "critical_count": sum(1 for item in risks if item.critical)},
        "blocked_critical_work": list(hard_blockers) + [item.risk_item_id for item in risks if item.status == "BLOCKED"],
        "evidence_confidence": {"overall": evidence_status, "states": [item.status for item in evaluation.evidence_confidences]},
        "defect_truth": [dict(item) for item in evaluation.defect_truth],
        "remaining_risk": {"item_refs": risk_refs},
        "field_validation_rules": field_state,
        "plan_and_automation_non_factors": ["PLAN_COMPLETE_NOT_SUFFICIENCY", "AUTOMATION_PASS_RATE_NOT_SUFFICIENCY", "CASE_COUNT_NOT_SUFFICIENCY", "TASK_COUNT_NOT_SUFFICIENCY", "AUTOMATION_COUNT_NOT_SUFFICIENCY"],
        "operational_metrics": dict(evaluation.operational_metrics),
        "hard_blockers": hard_blockers,
    }
    decision_id = f"decision:{evaluation.scope['project_id']}:{evaluation.scope['version_scope']}:{evaluation.as_of_seq}"
    summary = f"{decision_value}: coverage, evidence confidence, blocked work, defect truth and remaining risk evaluated at cursor {evaluation.as_of_seq}; plan and automation metrics were not decision inputs"
    from .contracts import TestSufficiencyDecision
    decision = TestSufficiencyDecision(
        decision_id=decision_id, scope=evaluation.scope, decision_scope_kind=evaluation.decision_scope_kind, decision=decision_value,
        basis=basis, coverage_snapshot=evaluation.coverage_snapshot_ref, coverage_summary=coverage,
        evidence_confidence_refs=tuple(item.to_reference() for item in evaluation.evidence_confidences), remaining_risk={
            "item_refs": risk_refs, "open_count": sum(1 for item in risks if item.status == "OPEN"),
            "blocked_critical_count": sum(1 for item in risks if item.status == "BLOCKED" and item.critical),
            "accepted_count": sum(1 for item in risks if item.status == "ACCEPTED"),
            "pending_field_validation_count": sum(1 for item in risks if item.status == "PENDING_FIELD_VALIDATION"),
            "digest": canonical_sha256(risk_refs),
        }, evidence_refs=tuple(evaluation.r1_evidence_refs), defect_assessment_refs=tuple(evaluation.defect_assessment_refs),
        rca_refs=tuple(evaluation.rca_refs), journey_verification_refs=tuple(evaluation.journey_refs),
        r1_r2_projection_ref=evaluation.r2_runtime_projection_ref, evaluation_receipt_ref=receipt_ref,
        session_ref=evaluation.session_ref or "missing-session", field_validation_state=field_state,
        risk_acceptance_ref=evaluation.risk_acceptance_ref, decision_summary=summary,
        source_provenance=(evaluation.coverage_snapshot_ref, evaluation.reconciliation_ref), origin_lineage=evaluation.origin_lineage,
    )
    return EvaluationResult(decision, tuple(risks), coverage, evidence_status)
