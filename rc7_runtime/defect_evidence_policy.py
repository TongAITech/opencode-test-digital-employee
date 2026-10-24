"""Deterministic N9 defect evidence policies for RC7.1.

This layer does not create defects from test failures. It operates only after
PRODUCT ownership and reproduction have already been proven by Runtime.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple


class DefectEvidencePolicyError(RuntimeError):
    pass


def _required(value: object, code: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DefectEvidencePolicyError(code)
    return text


def _tuple(values: Sequence[str]) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(str(x).strip() for x in values if str(x).strip()))


def _stable(prefix: str, value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "%s-%s" % (prefix, hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24])


@dataclass(frozen=True)
class DefectSignature:
    signature_id: str
    product_area: str
    requirement_refs: Tuple[str, ...]
    affected_application: str
    surface_ref: str
    failure_signature_id: str
    business_error_code: Optional[str]
    root_stack_frame: Optional[str]
    suspected_symbols: Tuple[str, ...]
    codegraph_root: Optional[str]
    business_symptom: str
    final_state_mismatch: Optional[str]
    root_cause_statement: Optional[str]
    evidence_refs: Tuple[str, ...]


@dataclass(frozen=True)
class DuplicateDecision:
    disposition: str
    confidence: float
    matched_defect_id: Optional[str]
    matched_fields: Tuple[str, ...]
    reason: str

    @property
    def auto_merge_allowed(self) -> bool:
        return self.disposition == "DUPLICATE"


@dataclass(frozen=True)
class SeverityFactors:
    business_impact: int
    blast_radius: int
    data_integrity: int
    security_compliance: int
    transaction_criticality: int
    workaround_unavailable: int
    reproducibility: int
    evidence_refs: Tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "business_impact",
            "blast_radius",
            "data_integrity",
            "security_compliance",
            "transaction_criticality",
            "workaround_unavailable",
            "reproducibility",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0 or value > 4:
                raise DefectEvidencePolicyError("SEVERITY_FACTOR_INVALID:%s" % name)
        if not self.evidence_refs:
            raise DefectEvidencePolicyError("SEVERITY_EVIDENCE_REQUIRED")


@dataclass(frozen=True)
class SeverityDecision:
    severity: str
    score: int
    reasons: Tuple[str, ...]
    evidence_refs: Tuple[str, ...]


@dataclass(frozen=True)
class RCAEvidenceChain:
    symptom_evidence_refs: Tuple[str, ...]
    affected_application: str = ""
    service_or_endpoint: str = ""
    module_or_symbol: str = ""
    code_change_refs: Tuple[str, ...] = ()
    codegraph_refs: Tuple[str, ...] = ()
    git_refs: Tuple[str, ...] = ()
    requirement_refs: Tuple[str, ...] = ()
    evidence_refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RCAAssessment:
    level: str
    level_number: int
    filing_minimum_met: bool
    evidence_refs: Tuple[str, ...]
    reason: str


class DefectEvidencePolicy:
    @staticmethod
    def build_signature(
        *,
        product_area: str,
        requirement_refs: Sequence[str],
        affected_application: str,
        surface_ref: str,
        failure_signature_id: str,
        business_symptom: str,
        evidence_refs: Sequence[str],
        business_error_code: Optional[str] = None,
        root_stack_frame: Optional[str] = None,
        suspected_symbols: Sequence[str] = (),
        codegraph_root: Optional[str] = None,
        final_state_mismatch: Optional[str] = None,
        root_cause_statement: Optional[str] = None,
    ) -> DefectSignature:
        evidence = _tuple(evidence_refs)
        if not evidence:
            raise DefectEvidencePolicyError("DEFECT_SIGNATURE_EVIDENCE_REQUIRED")
        payload = {
            "product_area": _required(product_area, "DEFECT_SIGNATURE_PRODUCT_AREA_REQUIRED"),
            "requirement_refs": sorted(_tuple(requirement_refs)),
            "affected_application": _required(
                affected_application, "DEFECT_SIGNATURE_APPLICATION_REQUIRED"
            ),
            "surface_ref": str(surface_ref or "").strip(),
            "failure_signature_id": _required(
                failure_signature_id, "DEFECT_FAILURE_SIGNATURE_REQUIRED"
            ),
            "business_error_code": str(business_error_code or "").strip() or None,
            "root_stack_frame": str(root_stack_frame or "").strip() or None,
            "suspected_symbols": sorted(_tuple(suspected_symbols)),
            "codegraph_root": str(codegraph_root or "").strip() or None,
            "business_symptom": _required(
                business_symptom, "DEFECT_BUSINESS_SYMPTOM_REQUIRED"
            ),
            "final_state_mismatch": str(final_state_mismatch or "").strip() or None,
            "root_cause_statement": str(root_cause_statement or "").strip() or None,
        }
        return DefectSignature(
            signature_id=_stable("DEFSIG", payload),
            requirement_refs=tuple(payload["requirement_refs"]),
            suspected_symbols=tuple(payload["suspected_symbols"]),
            evidence_refs=evidence,
            **{k: v for k, v in payload.items() if k not in {"requirement_refs", "suspected_symbols"}},
        )

    @staticmethod
    def compare(
        candidate: DefectSignature,
        existing_defect_id: str,
        existing: DefectSignature,
    ) -> DuplicateDecision:
        existing_defect_id = _required(existing_defect_id, "DUPLICATE_TARGET_DEFECT_REQUIRED")
        matched = []
        strong = 0

        def exact(name: str, left: object, right: object, *, strong_anchor: bool = False) -> bool:
            nonlocal strong
            if left and right and left == right:
                matched.append(name)
                if strong_anchor:
                    strong += 1
                return True
            return False

        same_app = exact("affected_application", candidate.affected_application, existing.affected_application)
        same_surface = exact("surface_ref", candidate.surface_ref, existing.surface_ref)
        exact("failure_signature_id", candidate.failure_signature_id, existing.failure_signature_id, strong_anchor=True)
        exact("business_error_code", candidate.business_error_code, existing.business_error_code, strong_anchor=True)
        exact("root_stack_frame", candidate.root_stack_frame, existing.root_stack_frame, strong_anchor=True)
        exact("codegraph_root", candidate.codegraph_root, existing.codegraph_root, strong_anchor=True)
        symptom_match = exact("business_symptom", candidate.business_symptom, existing.business_symptom)
        state_match = exact("final_state_mismatch", candidate.final_state_mismatch, existing.final_state_mismatch)

        if set(candidate.suspected_symbols).intersection(existing.suspected_symbols):
            matched.append("suspected_symbols")
            strong += 1
        requirement_overlap = bool(set(candidate.requirement_refs).intersection(existing.requirement_refs))
        if requirement_overlap:
            matched.append("requirement_refs")

        context_match = same_app and (same_surface or requirement_overlap)
        outcome_match = symptom_match or state_match
        if strong >= 2 and context_match and outcome_match:
            return DuplicateDecision(
                disposition="DUPLICATE",
                confidence=0.95,
                matched_defect_id=existing_defect_id,
                matched_fields=tuple(matched),
                reason="MULTI_EVIDENCE_ROOT_CAUSE_COMPATIBLE",
            )
        if strong >= 1 and same_app and (same_surface or outcome_match or requirement_overlap):
            return DuplicateDecision(
                disposition="POSSIBLE_DUPLICATE",
                confidence=0.65,
                matched_defect_id=existing_defect_id,
                matched_fields=tuple(matched),
                reason="PARTIAL_STRONG_EVIDENCE_REQUIRES_REVIEW",
            )
        return DuplicateDecision(
            disposition="DISTINCT",
            confidence=0.0,
            matched_defect_id=None,
            matched_fields=tuple(matched),
            reason="INSUFFICIENT_ROOT_CAUSE_COMPATIBILITY",
        )

    @staticmethod
    def derive_severity(factors: SeverityFactors) -> SeverityDecision:
        score = (
            factors.business_impact
            + factors.blast_radius
            + factors.data_integrity
            + factors.security_compliance
            + factors.transaction_criticality
            + factors.workaround_unavailable
            + factors.reproducibility
        )
        reasons = []
        if factors.security_compliance >= 4:
            reasons.append("CRITICAL_SECURITY_OR_COMPLIANCE")
        if factors.data_integrity >= 4:
            reasons.append("CRITICAL_DATA_INTEGRITY")
        if factors.transaction_criticality >= 4 and factors.business_impact >= 3:
            reasons.append("CRITICAL_TRANSACTION_IMPACT")
        if reasons or score >= 22:
            severity = "CRITICAL"
        elif factors.security_compliance >= 3 or factors.data_integrity >= 3 or score >= 15:
            severity = "HIGH"
        elif score >= 8:
            severity = "MEDIUM"
        else:
            severity = "LOW"
        if not reasons:
            reasons.append("POLICY_SCORE_%d" % score)
        return SeverityDecision(
            severity=severity,
            score=score,
            reasons=tuple(reasons),
            evidence_refs=factors.evidence_refs,
        )

    @staticmethod
    def assess_rca(chain: RCAEvidenceChain) -> RCAAssessment:
        evidence = _tuple(chain.evidence_refs + chain.symptom_evidence_refs)
        if not chain.symptom_evidence_refs:
            raise DefectEvidencePolicyError("RCA_SYMPTOM_EVIDENCE_REQUIRED")
        level = 0
        reason = "SYMPTOM_ONLY"
        if str(chain.affected_application or "").strip():
            level, reason = 1, "AFFECTED_APPLICATION_IDENTIFIED"
        if str(chain.service_or_endpoint or "").strip():
            level, reason = 2, "SERVICE_OR_ENDPOINT_IDENTIFIED"
        if str(chain.module_or_symbol or "").strip():
            level, reason = 3, "MODULE_OR_SYMBOL_IDENTIFIED"
        if chain.code_change_refs and chain.codegraph_refs and chain.git_refs:
            level, reason = 4, "CODE_CHANGE_GRAPH_AND_GIT_CHAIN_IDENTIFIED"
        return RCAAssessment(
            level="RCA-L%d" % level,
            level_number=level,
            filing_minimum_met=level >= 2,
            evidence_refs=evidence,
            reason=reason,
        )
