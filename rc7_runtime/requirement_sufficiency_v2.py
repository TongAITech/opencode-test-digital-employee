"""RC7.1 deterministic requirement-analysis accountability gate.

A requirement analysis may legitimately have an empty semantic dimension, but
an empty list must not silently shrink the downstream Test Obligation
inventory.  For real DSH production candidates RC7.1 therefore requires every
semantic dimension (except boundary, which already has a stricter legacy gate)
to be either populated with valid identified facts or explicitly excluded as
NOT_APPLICABLE with rationale and durable evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple


REQUIREMENT_DIMENSIONS = (
    "business_rules",
    "roles",
    "preconditions",
    "normal_paths",
    "negative_paths",
    "boundaries",
    "states",
    "data_constraints",
    "dependencies",
    "side_effects",
)

# Boundary completeness is already a P0 deterministic rule in
# IndependentRequirementSufficiencyGate. Avoid producing a duplicate Gap/task.
LEGACY_STRICT_DIMENSIONS = {"boundaries"}


@dataclass(frozen=True)
class RequirementSufficiencyV2Result:
    passed: bool
    reasons: Tuple[str, ...]
    metrics: Dict[str, Any]


class RequirementSufficiencyV2:
    def evaluate(self, analysis: Mapping[str, Any], *, force: bool = False) -> RequirementSufficiencyV2Result:
        atomic = analysis.get("atomic_statements")
        sources = analysis.get("source_assertions")
        atomic_count = len(atomic) if isinstance(atomic, list) else 0
        source_count = len(sources) if isinstance(sources, list) else 0
        active = bool(force or atomic_count >= 3 or source_count >= 3)
        if not active:
            return RequirementSufficiencyV2Result(
                passed=True,
                reasons=(),
                metrics={
                    "status": "NOT_REQUIRED_FOR_SMALL_ANALYSIS",
                    "active": False,
                    "atomic_count": atomic_count,
                    "source_count": source_count,
                },
            )

        evidence = {
            value for value in analysis.get("evidence_refs", [])
            if isinstance(value, str) and value.strip()
        }
        raw_exclusions = analysis.get("dimension_exclusions", [])
        exclusions: Dict[str, Dict[str, Any]] = {}
        reasons = []
        invalid_exclusions = []
        if not isinstance(raw_exclusions, list):
            reasons.append("REQ_DIMENSION_EXCLUSIONS_INVALID")
            raw_exclusions = []
        for raw in raw_exclusions:
            if not isinstance(raw, dict):
                invalid_exclusions.append("NOT_OBJECT")
                continue
            dimension = str(raw.get("dimension") or "").strip()
            rationale = str(raw.get("reason") or "").strip()
            evidence_ref = raw.get("evidence_ref")
            if (
                dimension not in REQUIREMENT_DIMENSIONS
                or dimension in exclusions
                or not rationale
                or not isinstance(evidence_ref, str)
                or not evidence_ref.strip()
                or evidence_ref not in evidence
            ):
                invalid_exclusions.append(dimension or "UNKNOWN")
                continue
            exclusions[dimension] = dict(raw)
        for dimension in sorted(set(invalid_exclusions)):
            reasons.append("REQ_DIMENSION_EXCLUSION_INVALID:%s" % dimension)

        populated = []
        excluded = []
        unaccounted = []
        invalid_items = []
        for dimension in REQUIREMENT_DIMENSIONS:
            values = analysis.get(dimension)
            if not isinstance(values, list):
                # Base schema gate owns missing/non-list fields.
                continue
            if values:
                seen = set()
                valid = True
                for item in values:
                    if not isinstance(item, dict):
                        valid = False
                        break
                    item_id = item.get("id")
                    if not isinstance(item_id, str) or not item_id.strip() or item_id in seen:
                        valid = False
                        break
                    seen.add(item_id)
                if not valid:
                    invalid_items.append(dimension)
                    reasons.append("REQ_DIMENSION_ITEM_INVALID:%s" % dimension)
                else:
                    populated.append(dimension)
                if dimension in exclusions:
                    reasons.append("REQ_DIMENSION_EXCLUSION_CONFLICT:%s" % dimension)
                continue

            if dimension in LEGACY_STRICT_DIMENSIONS:
                # The legacy independent gate emits REQ_BOUNDARY_RULE_MISSING.
                continue
            if dimension in exclusions:
                excluded.append(dimension)
            else:
                unaccounted.append(dimension)
                reasons.append("REQ_DIMENSION_UNACCOUNTED:%s" % dimension)

        unique_reasons = tuple(dict.fromkeys(reasons))
        metrics = {
            "status": "SUFFICIENT" if not unique_reasons else "NOT_SUFFICIENT",
            "active": True,
            "atomic_count": atomic_count,
            "source_count": source_count,
            "dimension_total": len(REQUIREMENT_DIMENSIONS),
            "populated_dimensions": sorted(populated),
            "excluded_dimensions": sorted(excluded),
            "unaccounted_dimensions": sorted(unaccounted),
            "invalid_item_dimensions": sorted(invalid_items),
            "valid_exclusion_count": len(exclusions),
            "reason_count": len(unique_reasons),
        }
        return RequirementSufficiencyV2Result(
            passed=not unique_reasons,
            reasons=unique_reasons,
            metrics=metrics,
        )
