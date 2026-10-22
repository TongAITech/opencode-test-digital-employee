"""Semantic handoff helpers for RC8 code analysis.

The structural engine produces immutable evidence once. This module creates a
compact request for DSH and promotes that same structural result only after the
semantic output passes the evidence allowlist contract. CodeGraph is not rerun
just to consume semantic output.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .code_analysis import CodeAnalysisResult, validate_semantic_analysis


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _compact(value: Any, *, max_chars: int = 12000) -> Any:
    """Keep request context bounded without inventing summaries.

    Large tool payloads are represented by a literal prefix plus an explicit
    truncation marker. Their evidence ref still binds to the full payload digest
    stored in code-analysis.json/graph evidence.
    """
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(text) <= max_chars:
            return value
        return {"truncated": True, "original_chars": len(text), "excerpt": text[:max_chars]}
    if isinstance(value, str) and len(value) > max_chars:
        return {"truncated": True, "original_chars": len(value), "excerpt": value[:max_chars]}
    return value


def build_semantic_request(
    result: CodeAnalysisResult,
    *,
    output_path: str,
    max_payload_chars: int = 12000,
) -> Dict[str, Any]:
    structured = result.structured_analysis
    findings = []
    for item in structured.get("structural_findings") or []:
        if not isinstance(item, Mapping):
            continue
        finding: Dict[str, Any] = {
            "point": dict(item.get("point") or {}),
            "evidence_ref": item.get("evidence_ref"),
        }
        for key in ("ai_context", "callers", "callees", "dependency_graph", "impact"):
            detail = item.get(key)
            if isinstance(detail, Mapping):
                finding[key] = {
                    "success": bool(detail.get("success")),
                    "payload_digest": detail.get("payload_digest"),
                    "payload": _compact(detail.get("payload"), max_chars=max_payload_chars),
                }
        findings.append(finding)

    source_change = dict(structured.get("source_change") or {})
    request: Dict[str, Any] = {
        "schema_version": 1,
        "request_type": "RC8_CODE_ANALYSIS_SEMANTIC",
        "snapshot_id": result.snapshot_id,
        "git_head": result.git_head,
        "base_ref": result.base_ref,
        "head_ref": result.head_ref,
        "source_change": source_change,
        "structural_sufficiency": {
            "state": result.structural_sufficiency.state,
            "score": result.structural_sufficiency.score,
            "changed_file_count": result.structural_sufficiency.changed_file_count,
            "covered_file_count": result.structural_sufficiency.covered_file_count,
            "query_point_count": result.structural_sufficiency.query_point_count,
            "successful_tool_calls": result.structural_sufficiency.successful_tool_calls,
            "total_tool_calls": result.structural_sufficiency.total_tool_calls,
            "gaps": list(result.structural_sufficiency.gaps),
        },
        "structural_findings": findings,
        "risk_hypotheses": list(structured.get("risk_hypotheses") or []),
        "test_impact_candidates": list(structured.get("test_impact_candidates") or []),
        "context": dict(structured.get("context") or {}),
        "allowed_evidence_refs": list(structured.get("evidence_refs") or []),
        "rules": [
            "Do not invent APIs, routes, database objects, call chains, business rules or test impacts.",
            "Every formal claim must cite one or more allowed_evidence_refs exactly.",
            "Hypotheses/candidates are not facts unless supported by evidence.",
            "Put unresolved items in unknowns and set sufficiency.state=INSUFFICIENT when material uncertainty remains.",
            "Do not cite DSH session IDs as source evidence; sessions are provenance only.",
        ],
        "output_contract": {
            "required": ["summary", "changes", "impact_chains", "risks", "test_impacts", "unknowns", "claims", "sufficiency"],
            "claim": {"claim": "string", "evidence_refs": ["one-or-more values from allowed_evidence_refs"]},
            "sufficiency": {"state": "PASS|INSUFFICIENT", "reason": "string"},
        },
        "truth_note": "This request is a bounded view of immutable structural evidence. Full payloads remain in RC8 artifacts and are identified by payload digests/evidence refs.",
    }
    request["request_digest"] = _canonical_sha256(request)
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(request, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(str(temp), str(path))
    return request


def promote_with_semantic(
    result: CodeAnalysisResult,
    semantic_analysis: Mapping[str, Any],
    *,
    output_path: str,
    semantic_source: str,
    dsh_provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    allowed = result.structured_analysis.get("evidence_refs") or []
    validated = validate_semantic_analysis(semantic_analysis, allowed)
    semantic_state = str(validated["sufficiency"]["state"]).upper()
    full_pass = result.structural_sufficiency.state == "PASS" and semantic_state == "PASS"
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "state": "PASS" if full_pass else "INSUFFICIENT",
        "classification": "CODE_ANALYSIS_SUFFICIENT" if full_pass else "CODE_ANALYSIS_SEMANTIC_INSUFFICIENT",
        "overall_sufficiency": "PASS" if full_pass else "SEMANTIC_INSUFFICIENT",
        "project_dir": result.project_dir,
        "base_ref": result.base_ref,
        "head_ref": result.head_ref,
        "git_head": result.git_head,
        "snapshot_id": result.snapshot_id,
        "changed_java_files": list(result.changed_java_files),
        "rounds": list(result.rounds),
        "structural_sufficiency": {
            "state": result.structural_sufficiency.state,
            "score": result.structural_sufficiency.score,
            "changed_file_count": result.structural_sufficiency.changed_file_count,
            "covered_file_count": result.structural_sufficiency.covered_file_count,
            "query_point_count": result.structural_sufficiency.query_point_count,
            "successful_tool_calls": result.structural_sufficiency.successful_tool_calls,
            "total_tool_calls": result.structural_sufficiency.total_tool_calls,
            "snapshot_stable": result.structural_sufficiency.snapshot_stable,
            "gaps": list(result.structural_sufficiency.gaps),
        },
        "structured_analysis": result.structured_analysis,
        "semantic_analysis": validated,
        "semantic_source": semantic_source,
        "dsh_provenance": dict(dsh_provenance or {}),
        "structural_evidence_digest": result.evidence_digest,
        "truth_note": "Semantic promotion reuses the already-captured structural evidence on the same snapshot; no second CodeGraph run is used to hide evidence drift.",
    }
    digest_material = dict(payload)
    payload["evidence_digest"] = _canonical_sha256(digest_material)
    path = Path(output_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    os.replace(str(temp), str(path))
    return payload
