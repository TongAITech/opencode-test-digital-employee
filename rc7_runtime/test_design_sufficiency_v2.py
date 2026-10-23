"""RC7.1 Test Design Sufficiency v2.

Semantic coverage alone is not enough for a large test design: a small number
of broad cases can link every Test Obligation and still provide shallow test
confidence.  This module adds deterministic anti-collapse, risk-depth and
interaction-coverage checks on top of the existing semantic-coverage gate.

The gate intentionally activates stronger density/depth rules only for larger
inventories.  Small unit-test fixtures and legitimately small changes are not
forced to manufacture arbitrary case volume.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from .test_design_loop import TestObligation


# A large design should not average more than four required semantic obligations
# per case. This is an anti-collapse capacity, not a business-domain minimum
# case count. The resulting minimum case floor is derived from the obligation
# inventory and therefore scales with the actual change surface.
DENSITY_ACTIVATION_SUBJECTS = 8
REQUIRED_OBLIGATION_CAPACITY_PER_CASE = 4

# A single very broad case may still be legitimate, but once the inventory is
# large, one case linking more than this many required obligations is treated as
# suspicious concentration and requires a delta-design review.
CONCENTRATION_ACTIVATION_SUBJECTS = 12
MAX_REQUIRED_OBLIGATIONS_PER_CASE = 6

# Repeated obligations of the same semantic kind need multiple distinct cases
# in a large design; otherwise one mega-case can make a category look complete.
KIND_DIVERSITY_ACTIVATION_SUBJECTS = 6
REQUIRED_KIND_OBLIGATION_CAPACITY_PER_CASE = 3

# Critical obligations in the following categories need two independent case
# exercises when the overall inventory is non-trivial.
CRITICAL_DEPTH_KINDS = {
    "BUSINESS_RULE",
    "NEGATIVE_PATH",
    "BOUNDARY",
    "STATE_TRANSITION",
    "ROLE_PERMISSION",
    "DATA_CONDITION",
    "CODE_IMPACT",
    "SIDE_EFFECT",
    "HIGH_RISK_HYPOTHESIS",
}

# Interaction coverage is deliberately kind-level rather than a full Cartesian
# product. It enforces important pair interactions without exploding case count.
INTERACTION_PAIRS = (
    ("BUSINESS_RULE", "BOUNDARY"),
    ("BUSINESS_RULE", "DATA_CONDITION"),
    ("STATE_TRANSITION", "ROLE_PERMISSION"),
    ("NEGATIVE_PATH", "SIDE_EFFECT"),
    ("CODE_IMPACT", "REGRESSION"),
    ("CODE_IMPACT", "HIGH_RISK_HYPOTHESIS"),
)
INTERACTION_MIN_KIND_SUBJECTS = 2


@dataclass(frozen=True)
class SufficiencyV2Result:
    passed: bool
    reasons: Tuple[str, ...]
    metrics: Dict[str, Any]
    delta_requests: Tuple[Dict[str, Any], ...]


def _ceil_div(value: int, capacity: int) -> int:
    return int(math.ceil(float(value) / float(capacity))) if value else 0


class TestDesignSufficiencyV2:
    """Deterministic large-design anti-collapse and depth evaluator."""

    def evaluate(
        self,
        *,
        obligations: Iterable[TestObligation],
        cases: Iterable[Mapping[str, Any]],
    ) -> SufficiencyV2Result:
        required = [item for item in obligations if item.required]
        case_list = [dict(item) for item in cases if isinstance(item, Mapping)]
        subject_by_id = {item.obligation_id: item for item in required}
        required_ids = set(subject_by_id)

        subject_cases: Dict[str, Set[str]] = defaultdict(set)
        layer_subjects: Dict[str, Set[str]] = defaultdict(set)
        layer_cases: Dict[str, Set[str]] = defaultdict(set)
        kind_subjects: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
        kind_cases: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
        case_required_links: Dict[str, Set[str]] = {}
        case_kinds: Dict[str, Set[str]] = {}

        for obligation in required:
            layer = str(obligation.layer).upper()
            kind = str(obligation.kind).upper()
            layer_subjects[layer].add(obligation.obligation_id)
            kind_subjects[(layer, kind)].add(obligation.obligation_id)

        for index, case in enumerate(case_list):
            tc_id = str(case.get("tc_id") or "CASE[%d]" % index)
            layer = str(case.get("layer") or "").upper()
            linked: Set[str] = set()
            links = case.get("coverage_links")
            if isinstance(links, list):
                for link in links:
                    if not isinstance(link, Mapping):
                        continue
                    subject_id = link.get("subject_id")
                    if isinstance(subject_id, str) and subject_id in required_ids:
                        obligation = subject_by_id[subject_id]
                        # The base semantic gate already rejects cross-layer links;
                        # keep this evaluator fail-safe and only count same-layer links.
                        if str(obligation.layer).upper() == layer:
                            linked.add(subject_id)
            case_required_links[tc_id] = linked
            kinds = {str(subject_by_id[sid].kind).upper() for sid in linked}
            case_kinds[tc_id] = kinds
            if linked:
                layer_cases[layer].add(tc_id)
            for sid in linked:
                subject_cases[sid].add(tc_id)
                key = (layer, str(subject_by_id[sid].kind).upper())
                kind_cases[key].add(tc_id)

        reasons: List[str] = []
        delta_requests: List[Dict[str, Any]] = []
        required_count = len(required)
        case_count = len(case_list)

        # Overall anti-collapse density floor.
        minimum_case_count = 0
        if required_count >= DENSITY_ACTIVATION_SUBJECTS:
            minimum_case_count = _ceil_div(required_count, REQUIRED_OBLIGATION_CAPACITY_PER_CASE)
            if case_count < minimum_case_count:
                reason = "CASE_DENSITY_INSUFFICIENT:ALL:required=%d:cases=%d:min=%d" % (
                    required_count,
                    case_count,
                    minimum_case_count,
                )
                reasons.append(reason)
                delta_requests.append(
                    {
                        "layer": "ALL",
                        "obligation_ids": sorted(required_ids),
                        "reason": "CASE_DENSITY_INSUFFICIENT",
                        "required_case_floor": minimum_case_count,
                        "current_case_count": case_count,
                    }
                )

        # Layer-local density catches a design that satisfies the total floor by
        # overproducing cases in one layer while collapsing another layer.
        layer_metrics: Dict[str, Dict[str, Any]] = {}
        for layer in sorted(layer_subjects):
            subjects = layer_subjects[layer]
            actual_cases = len(layer_cases.get(layer, set()))
            minimum = 0
            if len(subjects) >= DENSITY_ACTIVATION_SUBJECTS:
                minimum = _ceil_div(len(subjects), REQUIRED_OBLIGATION_CAPACITY_PER_CASE)
                if actual_cases < minimum:
                    reason = "CASE_DENSITY_INSUFFICIENT:%s:required=%d:cases=%d:min=%d" % (
                        layer,
                        len(subjects),
                        actual_cases,
                        minimum,
                    )
                    reasons.append(reason)
                    delta_requests.append(
                        {
                            "layer": layer,
                            "obligation_ids": sorted(subjects),
                            "reason": "CASE_DENSITY_INSUFFICIENT",
                            "required_case_floor": minimum,
                            "current_case_count": actual_cases,
                        }
                    )
            layer_metrics[layer] = {
                "required_subject_count": len(subjects),
                "case_count": actual_cases,
                "minimum_case_floor": minimum,
            }

        # Concentration: large inventories may not be represented by one case
        # linking an unbounded number of unrelated required obligations.
        overloaded_cases: Dict[str, int] = {}
        if required_count >= CONCENTRATION_ACTIVATION_SUBJECTS:
            for tc_id, linked in sorted(case_required_links.items()):
                if len(linked) > MAX_REQUIRED_OBLIGATIONS_PER_CASE:
                    overloaded_cases[tc_id] = len(linked)
                    reasons.append(
                        "CASE_OBLIGATION_CONCENTRATION_HIGH:%s:links=%d:max=%d" % (
                            tc_id,
                            len(linked),
                            MAX_REQUIRED_OBLIGATIONS_PER_CASE,
                        )
                    )
                    linked_layers = sorted({str(subject_by_id[sid].layer).upper() for sid in linked})
                    delta_requests.append(
                        {
                            "layer": linked_layers[0] if len(linked_layers) == 1 else "ALL",
                            "obligation_ids": sorted(linked),
                            "reason": "CASE_OBLIGATION_CONCENTRATION_HIGH",
                            "source_case_id": tc_id,
                        }
                    )

        # Same-kind diversity for material categories.
        kind_metrics: Dict[str, Dict[str, Any]] = {}
        for (layer, kind), subjects in sorted(kind_subjects.items()):
            distinct_cases = len(kind_cases.get((layer, kind), set()))
            minimum = 0
            if len(subjects) >= KIND_DIVERSITY_ACTIVATION_SUBJECTS:
                minimum = _ceil_div(len(subjects), REQUIRED_KIND_OBLIGATION_CAPACITY_PER_CASE)
                if distinct_cases < minimum:
                    reason = "KIND_DIVERSITY_INSUFFICIENT:%s:%s:required=%d:cases=%d:min=%d" % (
                        layer,
                        kind,
                        len(subjects),
                        distinct_cases,
                        minimum,
                    )
                    reasons.append(reason)
                    delta_requests.append(
                        {
                            "layer": layer,
                            "obligation_ids": sorted(subjects),
                            "reason": "KIND_DIVERSITY_INSUFFICIENT",
                            "kind": kind,
                            "required_case_floor": minimum,
                            "current_case_count": distinct_cases,
                        }
                    )
            kind_metrics["%s:%s" % (layer, kind)] = {
                "required_subject_count": len(subjects),
                "distinct_case_count": distinct_cases,
                "minimum_case_floor": minimum,
            }

        # Critical semantic depth: in a non-trivial design, one critical
        # obligation should have two independent case exercises rather than one
        # all-purpose case claiming the complete risk surface.
        critical_depth_gaps: Dict[str, int] = {}
        if required_count >= DENSITY_ACTIVATION_SUBJECTS:
            for obligation in required:
                kind = str(obligation.kind).upper()
                if str(obligation.risk).upper() != "CRITICAL" or kind not in CRITICAL_DEPTH_KINDS:
                    continue
                depth = len(subject_cases.get(obligation.obligation_id, set()))
                if depth < 2:
                    critical_depth_gaps[obligation.obligation_id] = depth
                    reasons.append(
                        "CRITICAL_OBLIGATION_DEPTH_INSUFFICIENT:%s:cases=%d:min=2" % (
                            obligation.obligation_id,
                            depth,
                        )
                    )
                    delta_requests.append(
                        {
                            "layer": str(obligation.layer).upper(),
                            "obligation_ids": [obligation.obligation_id],
                            "reason": "CRITICAL_OBLIGATION_DEPTH_INSUFFICIENT",
                            "required_case_floor": 2,
                            "current_case_count": depth,
                        }
                    )

        # Risk-relevant kind interaction coverage. Enforce only when each side
        # has at least two obligations in the same layer so small changes are not
        # forced into artificial combinatorial cases.
        missing_interactions: List[str] = []
        for layer in sorted(layer_subjects):
            for left, right in INTERACTION_PAIRS:
                left_subjects = kind_subjects.get((layer, left), set())
                right_subjects = kind_subjects.get((layer, right), set())
                if len(left_subjects) < INTERACTION_MIN_KIND_SUBJECTS or len(right_subjects) < INTERACTION_MIN_KIND_SUBJECTS:
                    continue
                interaction_cases = sorted(
                    tc_id
                    for tc_id in layer_cases.get(layer, set())
                    if left in case_kinds.get(tc_id, set()) and right in case_kinds.get(tc_id, set())
                )
                key = "%s:%sx%s" % (layer, left, right)
                if not interaction_cases:
                    missing_interactions.append(key)
                    reasons.append("INTERACTION_COVERAGE_MISSING:%s" % key)
                    delta_requests.append(
                        {
                            "layer": layer,
                            "obligation_ids": sorted(left_subjects | right_subjects),
                            "reason": "INTERACTION_COVERAGE_MISSING",
                            "interaction": "%sx%s" % (left, right),
                        }
                    )

        unique_reasons = tuple(dict.fromkeys(reasons))
        # Preserve request order for deterministic repair planning while removing
        # exact duplicates that can arise from overlapping density checks.
        deduped_requests: List[Dict[str, Any]] = []
        seen_requests = set()
        for request in delta_requests:
            signature = repr(sorted(request.items(), key=lambda item: item[0]))
            if signature in seen_requests:
                continue
            seen_requests.add(signature)
            deduped_requests.append(request)

        linked_counts = [len(value) for value in case_required_links.values()]
        metrics: Dict[str, Any] = {
            "status": "SUFFICIENT" if not unique_reasons else "NOT_SUFFICIENT",
            "required_subject_count": required_count,
            "case_count": case_count,
            "minimum_case_floor": minimum_case_count,
            "average_required_obligations_per_case": (
                round(float(sum(linked_counts)) / float(case_count), 6) if case_count else 0.0
            ),
            "max_required_obligations_per_case": max(linked_counts) if linked_counts else 0,
            "overloaded_cases": overloaded_cases,
            "critical_depth_gaps": critical_depth_gaps,
            "missing_interactions": missing_interactions,
            "layer_metrics": layer_metrics,
            "kind_metrics": kind_metrics,
            "reason_count": len(unique_reasons),
        }
        return SufficiencyV2Result(
            passed=not unique_reasons,
            reasons=unique_reasons,
            metrics=metrics,
            delta_requests=tuple(deduped_requests),
        )
