"""RC6 Wave 7 semantic coverage and oracle closure.

Coverage is computed over explicit subjects, never by Case count or by the
presence of broad dimensions. Oracle requirements are derived from layer,
risk, and action semantics; callers cannot self-declare sufficiency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Set, Tuple


class CoverageContractError(ValueError):
    pass


LAYERS = {f"L{i}" for i in range(1, 8)}
RISKS = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
SUBJECT_KINDS = {
    "REQUIREMENT_ASSERTION",
    "BUSINESS_RULE",
    "POSITIVE_PATH",
    "NEGATIVE_PATH",
    "BOUNDARY",
    "STATE_TRANSITION",
    "ROLE_PERMISSION",
    "DATA_CONDITION",
    "CODE_IMPACT",
    "SIDE_EFFECT",
    "REGRESSION",
    "HIGH_RISK_HYPOTHESIS",
}

LAYER_ORACLES = {
    "L1": {"UNIT_ASSERTION"},
    "L2": {"COMPONENT_STATE"},
    "L3": {"API_RESPONSE", "BUSINESS_RULE"},
    "L4": {"UI_STATE"},
    "L5": {"CROSS_SYSTEM_CONSISTENCY"},
    "L6": {"PERFORMANCE_THRESHOLD"},
    "L7": {"SECURITY_CONTROL"},
}


@dataclass(frozen=True)
class CoverageSubject:
    subject_id: str
    kind: str
    layer: str
    risk: str
    required: bool
    evidence_refs: tuple


@dataclass(frozen=True)
class ClosureResult:
    passed: bool
    status: str
    metrics: Dict[str, Any]
    uncovered_subject_ids: tuple
    critical_high_gap_ids: tuple
    oracle_gap_case_ids: tuple


@dataclass(frozen=True)
class DeltaDesignRequest:
    layer: str
    subject_ids: tuple
    subject_refs: tuple
    reason: str


class CoverageSubjectRegistry:
    def __init__(self, raw_subjects: Iterable[Dict[str, Any]]):
        self.subjects: Dict[str, CoverageSubject] = {}
        for raw in raw_subjects:
            subject = self._validate(raw)
            if subject.subject_id in self.subjects:
                raise CoverageContractError("DUPLICATE_COVERAGE_SUBJECT")
            self.subjects[subject.subject_id] = subject
        if not self.subjects:
            raise CoverageContractError("COVERAGE_SUBJECTS_EMPTY")

    @staticmethod
    def _validate(raw: Dict[str, Any]) -> CoverageSubject:
        if not isinstance(raw, dict):
            raise CoverageContractError("INVALID_COVERAGE_SUBJECT")
        sid = raw.get("subject_id")
        kind = str(raw.get("kind", "")).upper()
        layer = str(raw.get("layer", "")).upper()
        risk = str(raw.get("risk", "")).upper()
        required = raw.get("required")
        refs = raw.get("evidence_refs")
        if not isinstance(sid, str) or not sid.strip():
            raise CoverageContractError("COVERAGE_SUBJECT_ID_REQUIRED")
        if kind not in SUBJECT_KINDS:
            raise CoverageContractError("INVALID_COVERAGE_SUBJECT_KIND")
        if layer not in LAYERS:
            raise CoverageContractError("INVALID_COVERAGE_SUBJECT_LAYER")
        if risk not in RISKS:
            raise CoverageContractError("INVALID_COVERAGE_SUBJECT_RISK")
        if not isinstance(required, bool):
            raise CoverageContractError("COVERAGE_SUBJECT_REQUIRED_FLAG_MISSING")
        if not isinstance(refs, list) or not refs or not all(isinstance(x, str) and x.strip() for x in refs):
            raise CoverageContractError("COVERAGE_SUBJECT_EVIDENCE_REQUIRED")
        return CoverageSubject(sid.strip(), kind, layer, risk, required, tuple(refs))

    def required(self) -> List[CoverageSubject]:
        return [self.subjects[k] for k in sorted(self.subjects) if self.subjects[k].required]


class OraclePolicy:
    @staticmethod
    def required_oracles(case: Dict[str, Any]) -> Set[str]:
        layer = str(case.get("layer", "")).upper()
        if layer not in LAYERS:
            raise CoverageContractError("INVALID_CASE_LAYER")
        required = set(LAYER_ORACLES[layer])
        action = case.get("action_semantics")
        if not isinstance(action, dict):
            raise CoverageContractError("ACTION_SEMANTICS_REQUIRED")
        if action.get("state_changing") is True:
            required.add("PERSISTENCE")
        if action.get("negative") is True:
            required.add("NEGATIVE_SIDE_EFFECT")
        if action.get("authorization_sensitive") is True:
            required.add("AUTHORIZATION")
        risk = str(case.get("risk", "")).upper()
        if risk not in RISKS:
            raise CoverageContractError("CASE_RISK_REQUIRED")
        if risk in {"CRITICAL", "HIGH"}:
            required.add("EVIDENCE_CORRELATION")
        return required

    @staticmethod
    def provided_oracles(case: Dict[str, Any]) -> Set[str]:
        oracle = case.get("oracle")
        if isinstance(oracle, dict):
            entries = oracle.get("checks")
        else:
            entries = oracle
        if not isinstance(entries, list):
            return set()
        result: Set[str] = set()
        for item in entries:
            if not isinstance(item, dict):
                continue
            typ = item.get("type")
            evidence_ref = item.get("evidence_ref")
            if isinstance(typ, str) and typ.strip() and isinstance(evidence_ref, str) and evidence_ref.strip():
                result.add(typ.upper())
        return result


class DesignClosureEvaluator:
    def evaluate(self, registry: CoverageSubjectRegistry, cases: Iterable[Dict[str, Any]]) -> ClosureResult:
        case_list = list(cases)
        covered: Dict[str, Set[str]] = {s.subject_id: set() for s in registry.required()}
        oracle_gaps: List[str] = []
        invalid_links: List[str] = []

        seen_case_ids: Set[str] = set()
        for case in case_list:
            if not isinstance(case, dict):
                raise CoverageContractError("INVALID_CASE")
            tc_id = case.get("tc_id")
            if not isinstance(tc_id, str) or not tc_id.strip() or tc_id in seen_case_ids:
                raise CoverageContractError("INVALID_OR_DUPLICATE_CASE_ID")
            seen_case_ids.add(tc_id)
            layer = str(case.get("layer", "")).upper()
            if layer not in LAYERS:
                raise CoverageContractError("INVALID_CASE_LAYER")
            status = str(case.get("status", "")).upper()
            if status not in {"CANDIDATE", "TEST_READY"}:
                raise CoverageContractError("CASE_NOT_REVIEWABLE")

            links = case.get("coverage_links")
            if not isinstance(links, list):
                raise CoverageContractError("CASE_COVERAGE_LINKS_REQUIRED")
            for link in links:
                if not isinstance(link, dict):
                    invalid_links.append(tc_id)
                    continue
                sid = link.get("subject_id")
                eref = link.get("evidence_ref")
                subject = registry.subjects.get(sid)
                if subject is None or subject.layer != layer or not isinstance(eref, str) or not eref.strip():
                    invalid_links.append(f"{tc_id}:{sid}")
                    continue
                if subject.required:
                    covered[sid].add(tc_id)

            required_oracles = OraclePolicy.required_oracles(case)
            provided_oracles = OraclePolicy.provided_oracles(case)
            if not required_oracles.issubset(provided_oracles):
                oracle_gaps.append(tc_id)

        uncovered = sorted(sid for sid, tcids in covered.items() if not tcids)
        critical_high = sorted(
            sid for sid in uncovered if registry.subjects[sid].risk in {"CRITICAL", "HIGH"}
        )
        required_count = len(covered)
        metrics = {
            "required_subject_count": required_count,
            "covered_subject_count": required_count - len(uncovered),
            "semantic_coverage": ((required_count - len(uncovered)) / required_count) if required_count else 1.0,
            "case_count": len(case_list),
            "invalid_coverage_links": sorted(set(invalid_links)),
            "oracle_gap_count": len(set(oracle_gaps)),
            "critical_high_gap_count": len(critical_high),
        }
        passed = not uncovered and not invalid_links and not oracle_gaps
        status = "SUFFICIENT" if passed else "NOT_SUFFICIENT"
        return ClosureResult(
            passed=passed,
            status=status,
            metrics=metrics,
            uncovered_subject_ids=tuple(uncovered),
            critical_high_gap_ids=tuple(critical_high),
            oracle_gap_case_ids=tuple(sorted(set(oracle_gaps))),
        )


class DeltaDesignPlanner:
    def plan(self, registry: CoverageSubjectRegistry, result: ClosureResult) -> List[DeltaDesignRequest]:
        by_layer: Dict[str, List[str]] = {}
        for sid in result.uncovered_subject_ids:
            subject = registry.subjects[sid]
            by_layer.setdefault(subject.layer, []).append(sid)
        requests: List[DeltaDesignRequest] = []
        for layer in sorted(by_layer):
            ids = tuple(sorted(by_layer[layer]))
            refs = tuple(f"coverage-subject://{sid}" for sid in ids)
            requests.append(
                DeltaDesignRequest(
                    layer=layer,
                    subject_ids=ids,
                    subject_refs=refs,
                    reason="SEMANTIC_COVERAGE_GAP",
                )
            )
        return requests


class CaseFreezeGate:
    def freeze(self, cases: Iterable[Dict[str, Any]], result: ClosureResult) -> List[Dict[str, Any]]:
        if not result.passed:
            raise CoverageContractError("DESIGN_CLOSURE_NOT_SUFFICIENT")
        frozen: List[Dict[str, Any]] = []
        for case in cases:
            row = dict(case)
            if str(row.get("status", "")).upper() not in {"CANDIDATE", "TEST_READY"}:
                raise CoverageContractError("CASE_NOT_FREEZABLE")
            row["status"] = "FROZEN"
            frozen.append(row)
        return frozen
