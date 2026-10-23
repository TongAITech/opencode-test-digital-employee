"""RC7.1 deterministic Code Impact Sufficiency v2.

A real CodeGraph call is necessary but not sufficient: the analysis must turn
runtime graph/source evidence into an auditable downstream impact inventory.
Every changed symbol/file must be represented by at least one structured impact
surface or an evidence-backed exclusion, and each relevant impact dimension
must be populated or explicitly marked NOT_APPLICABLE with durable evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Set, Tuple


IMPACT_KIND_DIMENSION = {
    "CALLER": "CALL_GRAPH",
    "CALLEE": "CALL_GRAPH",
    "API": "INTERFACE",
    "DATABASE": "DATA",
    "CONFIG": "CONFIG",
    "MESSAGE": "EVENT",
    "EXCEPTION": "ERROR",
    "TRANSACTION": "TRANSACTION",
    "SIDE_EFFECT": "SIDE_EFFECT",
    "STATE": "SIDE_EFFECT",
    "SECURITY": "SECURITY",
    "PERFORMANCE": "PERFORMANCE",
    "FILE": "FILE_LEVEL",
}

REQUIRED_IMPACT_DIMENSIONS = (
    "CALL_GRAPH",
    "INTERFACE",
    "DATA",
    "CONFIG",
    "EVENT",
    "ERROR",
    "TRANSACTION",
    "SIDE_EFFECT",
    "SECURITY",
    "PERFORMANCE",
)


@dataclass(frozen=True)
class CodeSufficiencyV2Result:
    passed: bool
    reasons: Tuple[str, ...]
    metrics: Dict[str, Any]


def _identified_ids(values: object) -> Set[str]:
    result: Set[str] = set()
    if not isinstance(values, list):
        return result
    for item in values:
        if isinstance(item, dict):
            value = item.get("id")
            if isinstance(value, str) and value.strip():
                result.add(value.strip())
    return result


class CodeSufficiencyV2:
    def evaluate(self, analysis: Mapping[str, Any], *, force: bool = False) -> CodeSufficiencyV2Result:
        symbol_ids = _identified_ids(analysis.get("changed_symbols"))
        changed_files = {
            value.strip()
            for value in analysis.get("changed_files", [])
            if isinstance(value, str) and value.strip()
        } if isinstance(analysis.get("changed_files"), list) else set()

        active = bool(force or len(symbol_ids) >= 2 or len(changed_files) >= 2)
        if not active:
            return CodeSufficiencyV2Result(
                passed=True,
                reasons=(),
                metrics={
                    "status": "NOT_REQUIRED_FOR_SMALL_ANALYSIS",
                    "active": False,
                    "changed_symbol_count": len(symbol_ids),
                    "changed_file_count": len(changed_files),
                },
            )

        evidence = {
            value for value in analysis.get("evidence_refs", [])
            if isinstance(value, str) and value.strip()
        }
        reasons = []
        raw_surfaces = analysis.get("impact_surfaces", [])
        if not isinstance(raw_surfaces, list):
            reasons.append("CODE_IMPACT_SURFACES_INVALID")
            raw_surfaces = []

        surface_ids = set()
        surface_symbol_ids: Set[str] = set()
        surface_files: Set[str] = set()
        dimensions: Set[str] = set()
        invalid_surface_ids = []
        kind_counts: Dict[str, int] = {}
        for index, raw in enumerate(raw_surfaces):
            label = "SURFACE[%d]" % index
            if not isinstance(raw, dict):
                invalid_surface_ids.append(label)
                continue
            surface_id = raw.get("id")
            kind = str(raw.get("kind") or "").strip().upper()
            evidence_ref = raw.get("evidence_ref")
            source_symbol_id = raw.get("source_symbol_id")
            source_file = raw.get("source_file")
            valid_identity = isinstance(surface_id, str) and bool(surface_id.strip()) and surface_id not in surface_ids
            valid_kind = kind in IMPACT_KIND_DIMENSION
            valid_evidence = isinstance(evidence_ref, str) and evidence_ref in evidence
            valid_symbol = (
                source_symbol_id is None
                or (isinstance(source_symbol_id, str) and source_symbol_id in symbol_ids)
            )
            valid_file = (
                source_file is None
                or (isinstance(source_file, str) and source_file in changed_files)
            )
            if not (valid_identity and valid_kind and valid_evidence and valid_symbol and valid_file):
                invalid_surface_ids.append(str(surface_id or label))
                continue
            surface_id = surface_id.strip()
            surface_ids.add(surface_id)
            dimensions.add(IMPACT_KIND_DIMENSION[kind])
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
            if isinstance(source_symbol_id, str):
                surface_symbol_ids.add(source_symbol_id)
            if isinstance(source_file, str):
                surface_files.add(source_file)

        for surface_id in sorted(set(invalid_surface_ids)):
            reasons.append("CODE_IMPACT_SURFACE_INVALID:%s" % surface_id)

        raw_exclusions = analysis.get("impact_exclusions", [])
        if not isinstance(raw_exclusions, list):
            reasons.append("CODE_IMPACT_EXCLUSIONS_INVALID")
            raw_exclusions = []
        excluded_symbols: Set[str] = set()
        excluded_files: Set[str] = set()
        invalid_exclusions = []
        for index, raw in enumerate(raw_exclusions):
            label = "EXCLUSION[%d]" % index
            if not isinstance(raw, dict):
                invalid_exclusions.append(label)
                continue
            target_type = str(raw.get("target_type") or "").strip().upper()
            target_ref = raw.get("target_ref")
            reason = str(raw.get("reason") or "").strip()
            evidence_ref = raw.get("evidence_ref")
            valid_evidence = isinstance(evidence_ref, str) and evidence_ref in evidence
            if target_type == "SYMBOL":
                valid_target = isinstance(target_ref, str) and target_ref in symbol_ids
            elif target_type == "FILE":
                valid_target = isinstance(target_ref, str) and target_ref in changed_files
            else:
                valid_target = False
            if not (valid_target and reason and valid_evidence):
                invalid_exclusions.append(str(target_ref or label))
                continue
            if target_type == "SYMBOL":
                excluded_symbols.add(str(target_ref))
            else:
                excluded_files.add(str(target_ref))
        for target in sorted(set(invalid_exclusions)):
            reasons.append("CODE_IMPACT_EXCLUSION_INVALID:%s" % target)

        raw_dimension_exclusions = analysis.get("impact_dimension_exclusions", [])
        if not isinstance(raw_dimension_exclusions, list):
            reasons.append("CODE_IMPACT_DIMENSION_EXCLUSIONS_INVALID")
            raw_dimension_exclusions = []
        excluded_dimensions: Set[str] = set()
        invalid_dimension_exclusions = []
        for index, raw in enumerate(raw_dimension_exclusions):
            label = "DIMENSION_EXCLUSION[%d]" % index
            if not isinstance(raw, dict):
                invalid_dimension_exclusions.append(label)
                continue
            dimension = str(raw.get("dimension") or "").strip().upper()
            reason = str(raw.get("reason") or "").strip()
            evidence_ref = raw.get("evidence_ref")
            if (
                dimension not in REQUIRED_IMPACT_DIMENSIONS
                or dimension in excluded_dimensions
                or not reason
                or not isinstance(evidence_ref, str)
                or evidence_ref not in evidence
            ):
                invalid_dimension_exclusions.append(dimension or label)
                continue
            excluded_dimensions.add(dimension)
        for dimension in sorted(set(invalid_dimension_exclusions)):
            reasons.append("CODE_IMPACT_DIMENSION_EXCLUSION_INVALID:%s" % dimension)

        uncovered_symbols = sorted(symbol_ids - surface_symbol_ids - excluded_symbols)
        uncovered_files = sorted(changed_files - surface_files - excluded_files)
        for symbol_id in uncovered_symbols:
            reasons.append("CODE_IMPACT_SYMBOL_UNACCOUNTED:%s" % symbol_id)
        for path in uncovered_files:
            reasons.append("CODE_IMPACT_FILE_UNACCOUNTED:%s" % path)

        unaccounted_dimensions = sorted(
            dimension
            for dimension in REQUIRED_IMPACT_DIMENSIONS
            if dimension not in dimensions and dimension not in excluded_dimensions
        )
        for dimension in unaccounted_dimensions:
            reasons.append("CODE_IMPACT_DIMENSION_UNACCOUNTED:%s" % dimension)

        # A populated dimension and an exclusion for the same dimension is an
        # internal contradiction. Force a repair instead of choosing one side.
        conflicts = sorted(dimensions & excluded_dimensions)
        for dimension in conflicts:
            reasons.append("CODE_IMPACT_DIMENSION_CONFLICT:%s" % dimension)

        unique_reasons = tuple(dict.fromkeys(reasons))
        metrics = {
            "status": "SUFFICIENT" if not unique_reasons else "NOT_SUFFICIENT",
            "active": True,
            "changed_symbol_count": len(symbol_ids),
            "changed_file_count": len(changed_files),
            "impact_surface_count": len(surface_ids),
            "impact_surface_kind_counts": kind_counts,
            "covered_symbol_count": len(surface_symbol_ids),
            "excluded_symbol_count": len(excluded_symbols),
            "uncovered_symbol_ids": uncovered_symbols,
            "covered_file_count": len(surface_files),
            "excluded_file_count": len(excluded_files),
            "uncovered_files": uncovered_files,
            "populated_dimensions": sorted(dimensions),
            "excluded_dimensions": sorted(excluded_dimensions),
            "unaccounted_dimensions": unaccounted_dimensions,
            "dimension_conflicts": conflicts,
            "reason_count": len(unique_reasons),
        }
        return CodeSufficiencyV2Result(
            passed=not unique_reasons,
            reasons=unique_reasons,
            metrics=metrics,
        )
