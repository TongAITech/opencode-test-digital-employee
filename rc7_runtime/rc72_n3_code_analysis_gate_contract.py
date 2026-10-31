"""RC7.2 N3 analyzer -> deterministic code-gate compatibility contract.

The first N3 CODE_ANALYSIS bridge intentionally kept a small, analyzer-friendly
raw candidate shape.  The mature deterministic Code gate predates RC7.2 and
expects a richer canonical schema: structured changed-symbol identities,
repository->revision mapping and an impact-surface inventory.

This overlay closes that integration boundary without weakening either side:

* raw DSH output keeps the frozen V1 top-level keys, so raw evidence/attempt
  lineage remains replayable;
* each symbol explanation may carry evidence-backed impact surfaces,
  exclusions and dimension exclusions;
* promotion deterministically normalizes the raw V1 candidate into the
  canonical schema consumed by DshCodeEvaluator/CodeAnalysisClosedLoop;
* no missing impact fact is invented.  Missing impact inventory stays empty and
  CodeSufficiencyV2 therefore fails closed once real Git/CodeGraph proof is
  present;
* the public promotion receipt keeps the historical list-of-symbol-id shape so
  existing callers do not confuse an internal schema normalization with an API
  break.

This module is an RC7.2 construction overlay.  It makes no N3 NodeGate, N4,
Q7, Field or BANK_FINAL claim.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .code_sufficiency_v2 import IMPACT_KIND_DIMENSION, REQUIRED_IMPACT_DIMENSIONS
from .rc72_n3_code_analysis_handoff import (
    N3CodeAnalysisDshHandoffService,
    N3CodeAnalysisHandoffError,
)
from .rc72_n3_code_analysis_promotion import N3CodeAnalysisCandidatePromotionService


_INSTALLED = False
_ORIGINAL_VALIDATE = N3CodeAnalysisDshHandoffService._validate_candidate
_ORIGINAL_PROMPT = N3CodeAnalysisDshHandoffService._prompt
_ORIGINAL_PROMOTE = N3CodeAnalysisCandidatePromotionService.promote


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_%s_REQUIRED" % name.upper()
        )
    return value.strip()


def _list(value: Any, name: str) -> List[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_%s_INVALID" % name.upper()
        )
    return list(value)


def _string_list(value: Any, name: str, *, required: bool = False) -> List[str]:
    values = _list(value, name)
    out: List[str] = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_GATE_%s_INVALID" % name.upper()
            )
        out.append(item.strip())
    if required and not out:
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_%s_REQUIRED" % name.upper()
        )
    if len(out) != len(set(out)):
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_%s_DUPLICATE" % name.upper()
        )
    return out


def _normalize_surface(
    raw: Any,
    *,
    symbol_id: str,
    changed_files: Sequence[str],
    index: int,
) -> Dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_IMPACT_SURFACE_INVALID:%s:%d" % (symbol_id, index)
        )
    surface_id = _required(raw.get("id"), "impact_surface_id")
    kind = _required(raw.get("kind"), "impact_surface_kind").upper()
    if kind not in IMPACT_KIND_DIMENSION:
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_IMPACT_KIND_INVALID:%s" % kind
        )
    source_symbol_id = _required(
        raw.get("source_symbol_id"), "impact_surface_source_symbol_id"
    )
    if source_symbol_id != symbol_id:
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_IMPACT_SYMBOL_MISMATCH:%s" % surface_id
        )
    source_file = raw.get("source_file")
    if source_file is not None:
        source_file = _required(source_file, "impact_surface_source_file")
        if source_file not in changed_files:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_GATE_IMPACT_FILE_NOT_CHANGED:%s" % source_file
            )
    reason = raw.get("reason")
    if reason is not None:
        reason = _required(reason, "impact_surface_reason")
    result: Dict[str, Any] = {
        "id": surface_id,
        "kind": kind,
        "source_symbol_id": source_symbol_id,
    }
    if source_file is not None:
        result["source_file"] = source_file
    if reason is not None:
        result["reason"] = reason
    return result


def _normalize_exclusion(
    raw: Any,
    *,
    symbol_id: str,
    changed_files: Sequence[str],
    index: int,
) -> Dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_IMPACT_EXCLUSION_INVALID:%s:%d" % (symbol_id, index)
        )
    target_type = _required(raw.get("target_type"), "impact_exclusion_target_type").upper()
    if target_type not in {"SYMBOL", "FILE"}:
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_IMPACT_EXCLUSION_TARGET_TYPE_INVALID:%s"
            % target_type
        )
    target_ref = _required(raw.get("target_ref"), "impact_exclusion_target_ref")
    if target_type == "SYMBOL" and target_ref != symbol_id:
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_IMPACT_EXCLUSION_SYMBOL_MISMATCH:%s" % target_ref
        )
    if target_type == "FILE" and target_ref not in changed_files:
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_IMPACT_EXCLUSION_FILE_NOT_CHANGED:%s" % target_ref
        )
    reason = _required(raw.get("reason"), "impact_exclusion_reason")
    basis = _string_list(
        raw.get("basis_symbol_ids"), "impact_exclusion_basis_symbol_ids", required=True
    )
    if symbol_id not in basis:
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_IMPACT_EXCLUSION_BASIS_MISSING:%s" % symbol_id
        )
    return {
        "target_type": target_type,
        "target_ref": target_ref,
        "reason": reason,
        "basis_symbol_ids": basis,
    }


def _normalize_dimension_exclusion(
    raw: Any,
    *,
    symbol_id: str,
    index: int,
) -> Dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_DIMENSION_EXCLUSION_INVALID:%s:%d"
            % (symbol_id, index)
        )
    dimension = _required(
        raw.get("dimension"), "impact_dimension_exclusion_dimension"
    ).upper()
    if dimension not in REQUIRED_IMPACT_DIMENSIONS:
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_DIMENSION_INVALID:%s" % dimension
        )
    reason = _required(raw.get("reason"), "impact_dimension_exclusion_reason")
    basis = _string_list(
        raw.get("basis_symbol_ids"),
        "impact_dimension_exclusion_basis_symbol_ids",
        required=True,
    )
    if symbol_id not in basis:
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_DIMENSION_BASIS_MISSING:%s:%s"
            % (dimension, symbol_id)
        )
    return {
        "dimension": dimension,
        "reason": reason,
        "basis_symbol_ids": basis,
    }


def _validate_candidate_v2(
    candidate: Mapping[str, Any], assignment: Mapping[str, Any]
) -> Dict[str, Any]:
    """Validate V1 envelope and normalize optional gate-detail extensions.

    Legacy V1 candidates with no impact details remain replayable, but they are
    normalized with empty impact collections.  They cannot PASS the real v2
    impact gate once runtime tool proof activates it.
    """
    normalized = dict(_ORIGINAL_VALIDATE(candidate, assignment))
    changed_files = [str(item) for item in normalized.get("changed_files") or []]
    changed_symbols = [str(item) for item in normalized.get("changed_symbols") or []]
    explanations = normalized.get("symbol_explanations")
    if not isinstance(explanations, list):
        raise N3CodeAnalysisHandoffError(
            "RC72_N3_CODE_GATE_SYMBOL_EXPLANATIONS_INVALID"
        )

    seen_surfaces = set()
    seen_dimension_exclusions = set()
    enriched: List[Dict[str, Any]] = []
    for index, raw in enumerate(explanations):
        if not isinstance(raw, Mapping):
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_GATE_SYMBOL_EXPLANATION_INVALID:%d" % index
            )
        symbol_id = _required(raw.get("symbol"), "symbol_explanation_symbol")
        if symbol_id not in changed_symbols:
            raise N3CodeAnalysisHandoffError(
                "RC72_N3_CODE_GATE_SYMBOL_NOT_CHANGED:%s" % symbol_id
            )
        item = dict(raw)
        surfaces = [
            _normalize_surface(
                value,
                symbol_id=symbol_id,
                changed_files=changed_files,
                index=surface_index,
            )
            for surface_index, value in enumerate(
                _list(raw.get("impact_surfaces"), "impact_surfaces")
            )
        ]
        for surface in surfaces:
            if surface["id"] in seen_surfaces:
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_GATE_IMPACT_SURFACE_DUPLICATE:%s" % surface["id"]
                )
            seen_surfaces.add(surface["id"])
        exclusions = [
            _normalize_exclusion(
                value,
                symbol_id=symbol_id,
                changed_files=changed_files,
                index=exclusion_index,
            )
            for exclusion_index, value in enumerate(
                _list(raw.get("impact_exclusions"), "impact_exclusions")
            )
        ]
        dimension_exclusions = [
            _normalize_dimension_exclusion(
                value,
                symbol_id=symbol_id,
                index=dimension_index,
            )
            for dimension_index, value in enumerate(
                _list(
                    raw.get("impact_dimension_exclusions"),
                    "impact_dimension_exclusions",
                )
            )
        ]
        for exclusion in dimension_exclusions:
            key = (exclusion["dimension"], tuple(exclusion["basis_symbol_ids"]))
            if key in seen_dimension_exclusions:
                raise N3CodeAnalysisHandoffError(
                    "RC72_N3_CODE_GATE_DIMENSION_EXCLUSION_DUPLICATE:%s"
                    % exclusion["dimension"]
                )
            seen_dimension_exclusions.add(key)
        item["impact_surfaces"] = surfaces
        item["impact_exclusions"] = exclusions
        item["impact_dimension_exclusions"] = dimension_exclusions
        enriched.append(item)
    normalized["symbol_explanations"] = enriched
    return normalized


def _impact_shape(symbol: str, source_file: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "explanation": "evidence-backed explanation of changed behavior and downstream impact",
        "evidence_refs": ["real git/codegraph call ref"],
        "impact_surfaces": [
            {
                "id": "stable impact id",
                "kind": "CALLER | CALLEE | API | DATABASE | CONFIG | MESSAGE | EXCEPTION | TRANSACTION | SIDE_EFFECT | STATE | SECURITY | PERFORMANCE | FILE",
                "source_symbol_id": symbol,
                "source_file": source_file,
                "reason": "observed impact relationship",
            }
        ],
        "impact_exclusions": [
            {
                "target_type": "SYMBOL | FILE",
                "target_ref": symbol,
                "reason": "evidence-backed reason the target has no additional impact surface",
                "basis_symbol_ids": [symbol],
            }
        ],
        "impact_dimension_exclusions": [
            {
                "dimension": "CALL_GRAPH | INTERFACE | DATA | CONFIG | EVENT | ERROR | TRANSACTION | SIDE_EFFECT | SECURITY | PERFORMANCE",
                "reason": "evidence-backed NOT_APPLICABLE reason",
                "basis_symbol_ids": [symbol],
            }
        ],
    }


def _prompt_v2(self: N3CodeAnalysisDshHandoffService, assignment: Mapping[str, Any]) -> str:
    base = _ORIGINAL_PROMPT(self, assignment)
    extension = {
        "contract": "RC72_N3_REAL_CODE_GATE_EXTENSION_V2",
        "required_symbol_explanation_extension": _impact_shape(
            "exact changed symbol id", "exact changed file path"
        ),
        "rules": [
            "Every changed symbol must have exactly one symbol_explanations item.",
            "Use real git/codegraph observations; never invent an impact surface merely to satisfy a dimension.",
            "For every applicable impact dimension emit one or more evidence-backed impact_surfaces.",
            "For every non-applicable mandatory impact dimension emit an explicit impact_dimension_exclusions entry with a concrete reason and basis_symbol_ids.",
            "Every changed file must be represented by an impact surface source_file or an explicit FILE impact_exclusion.",
            "Mandatory dimensions are CALL_GRAPH, INTERFACE, DATA, CONFIG, EVENT, ERROR, TRANSACTION, SIDE_EFFECT, SECURITY, PERFORMANCE.",
            "If evidence is insufficient, put the uncertainty in gaps/unknowns instead of fabricating coverage; promotion will fail closed.",
        ],
    }
    return base + " GateExtension=" + json.dumps(extension, ensure_ascii=False, sort_keys=True)


def _flatten_candidate(candidate: Mapping[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    surfaces: List[Dict[str, Any]] = []
    exclusions: List[Dict[str, Any]] = []
    dimension_exclusions: List[Dict[str, Any]] = []
    for item in list(candidate.get("symbol_explanations") or []):
        if not isinstance(item, Mapping):
            continue
        surfaces.extend(dict(value) for value in list(item.get("impact_surfaces") or []))
        exclusions.extend(dict(value) for value in list(item.get("impact_exclusions") or []))
        dimension_exclusions.extend(
            dict(value) for value in list(item.get("impact_dimension_exclusions") or [])
        )
    return {
        "impact_surfaces": surfaces,
        "impact_exclusions": exclusions,
        "impact_dimension_exclusions": dimension_exclusions,
    }


def _persist_candidate_envelope_v2(
    self: N3CodeAnalysisCandidatePromotionService,
    *,
    task: Mapping[str, Any],
    anchor: Mapping[str, Any],
    artifact_id: str,
    evidence_ids: List[str],
    candidate: Mapping[str, Any],
):
    target_dir = self.state_root / "rc72-code-analysis-candidates"
    target_dir.mkdir(parents=True, exist_ok=True)
    raw_identity = "\x1f".join(
        (
            self.mission_id,
            str(task["task_id"]),
            str(anchor["attempt_id"]),
            str(anchor["raw_output_sha256"]),
        )
    ).encode("utf-8")
    filename = "code-analysis-candidate-%s.json" % hashlib.sha256(raw_identity).hexdigest()[:20]
    target = target_dir / filename

    changed_symbols = [
        {"id": str(symbol)} for symbol in list(candidate.get("changed_symbols") or [])
    ]
    explanations = []
    for raw in list(candidate.get("symbol_explanations") or []):
        item = dict(raw)
        explanations.append(
            {
                "symbol_id": str(item.get("symbol") or ""),
                "explanation": str(item.get("explanation") or ""),
                "evidence_refs": list(item.get("evidence_refs") or []),
            }
        )
    reverse = []
    for raw in list(candidate.get("reverse_requirement_mappings") or []):
        item = dict(raw)
        reverse.append(
            {
                "requirement_id": str(item.get("requirement_id") or ""),
                "symbol_id": str(item.get("symbol") or ""),
                "evidence_ref": str(item.get("evidence_ref") or ""),
            }
        )
    impact = _flatten_candidate(candidate)
    semantic_payload = {
        "candidate_kind": "CODE_ANALYSIS_CANDIDATE",
        "gate_contract": "RC72_N3_REAL_CODE_GATE_EXTENSION_V2",
        "application_id": candidate["application_id"],
        "target_id": candidate["target_id"],
        "repository_ref": candidate["repository_ref"],
        "source_revision": candidate["source_revision"],
        "requirement_ids": list(candidate["requirement_ids"]),
        "source_revisions": {
            str(candidate["repository_ref"]): str(candidate["source_revision"])
        },
        "changed_files": list(candidate["changed_files"]),
        "changed_symbols": changed_symbols,
        "symbol_explanations": explanations,
        "reverse_requirement_mappings": reverse,
        "impact_surfaces": impact["impact_surfaces"],
        "impact_exclusions": impact["impact_exclusions"],
        "impact_dimension_exclusions": impact["impact_dimension_exclusions"],
        "codegraph_required": bool(candidate["codegraph_required"]),
        "sufficiency_v2_required": True,
        "candidate_unknowns": [],
        "candidate_gaps": [],
    }
    envelope = {
        "task_id": str(task["task_id"]),
        "artifact": {
            "artifact_id": artifact_id,
            "artifact_type": "CODE_ANALYSIS_CANDIDATE",
            "content_ref": str(anchor["raw_output_ref"]),
            "parent_refs": list(task.get("input_artifact_refs") or []),
            "evidence_refs": list(evidence_ids),
        },
        "semantic_payload": semantic_payload,
        "runtime_lineage": {
            "attempt_id": anchor["attempt_id"],
            "assignment_id": anchor["assignment_id"],
            "dispatch_id": anchor["dispatch_id"],
            "dsh_session_id": anchor["dsh_session_id"],
            "raw_output_sha256": anchor["raw_output_sha256"],
            "evidence_anchor_id": anchor["anchor_id"],
            "source_commit": anchor["source_commit"],
        },
    }
    raw = (
        json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")
    content_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    fd, temp_name = tempfile.mkstemp(
        prefix=filename + ".", suffix=".tmp", dir=str(target_dir)
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return "file://" + str(Path(target).resolve()), content_hash


def _promote_compat(self: N3CodeAnalysisCandidatePromotionService, *args: Any, **kwargs: Any):
    result = dict(_ORIGINAL_PROMOTE(self, *args, **kwargs))
    symbols = result.get("changed_symbols")
    if isinstance(symbols, list) and symbols and all(isinstance(item, Mapping) for item in symbols):
        result["changed_symbols"] = [str(item.get("id") or "") for item in symbols]
    return result


def install_rc72_n3_code_analysis_gate_contract() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    N3CodeAnalysisDshHandoffService._validate_candidate = staticmethod(
        _validate_candidate_v2
    )
    N3CodeAnalysisDshHandoffService._prompt = _prompt_v2
    N3CodeAnalysisCandidatePromotionService._persist_candidate_envelope = (
        _persist_candidate_envelope_v2
    )
    N3CodeAnalysisCandidatePromotionService.promote = _promote_compat
    _INSTALLED = True


__all__ = ["install_rc72_n3_code_analysis_gate_contract"]
