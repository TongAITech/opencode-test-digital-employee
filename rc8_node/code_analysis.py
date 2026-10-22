"""Evidence-backed RC8 code analysis foundation.

This module intentionally separates three truths:
1. Git is source-change/snapshot truth.
2. CodeGraph is structural evidence.
3. Semantic conclusions must be evidence-bound and may be supplied by a DSH
   semantic worker later; deterministic structural analysis never impersonates
   an LLM/agent conclusion.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .codegraph import (
    CodeGraphAdapterError,
    CodeGraphExecutableAdapter,
    CodeGraphExecutionResult,
    CodeGraphQueryPoint,
    capture_git_snapshot,
    discover_java_query_points,
)


class CodeAnalysisError(RuntimeError):
    pass


_REQUIRED_TOOLS = (
    "codegraph_get_ai_context",
    "codegraph_get_callers",
    "codegraph_get_callees",
    "codegraph_get_dependency_graph",
    "codegraph_analyze_impact",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(raw)


def _git(repo: Path, args: Sequence[str], *, timeout_seconds: int = 120) -> str:
    proc = subprocess.run(
        ["git"] + list(args),
        cwd=str(repo),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout_seconds,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace").strip()
        raise CodeAnalysisError("CODE_ANALYSIS_GIT_FAILED:%s" % detail[:1000])
    return (proc.stdout or b"").decode("utf-8", errors="replace")


def capture_git_diff(repo_path: str, base_ref: str, head_ref: str) -> Dict[str, Any]:
    repo = Path(repo_path).resolve()
    diff = _git(repo, ["diff", "--no-ext-diff", "--unified=3", base_ref, head_ref, "--", "*.java"])
    name_only = _git(repo, ["diff", "--no-ext-diff", "--name-only", base_ref, head_ref, "--", "*.java"])
    files = [line.strip().replace("\\", "/") for line in name_only.splitlines() if line.strip()]
    encoded = diff.encode("utf-8")
    return {
        "base_ref": base_ref,
        "head_ref": head_ref,
        "changed_java_files": files,
        "diff_sha256": _sha256_bytes(encoded),
        "diff_chars": len(diff),
        "diff": diff,
    }


def _payload_digest(payload: object) -> str:
    return _canonical_sha256(payload)


def _risk_hypotheses(changed_files: Iterable[str]) -> List[Dict[str, str]]:
    risks: List[Dict[str, str]] = []
    seen = set()
    for file_path in changed_files:
        lowered = file_path.lower()
        candidates: List[Tuple[str, str]] = [("REGRESSION", "变更代码及其调用链需要回归验证")]
        if "controller" in lowered:
            candidates.append(("API_CONTRACT", "控制层变更可能影响接口契约、参数或返回结果"))
        if "service" in lowered:
            candidates.append(("BUSINESS_RULE", "服务层变更可能影响业务规则、分支和状态转换"))
        if any(token in lowered for token in ("repository", "mapper", "dao")):
            candidates.append(("DATA_ACCESS", "数据访问层变更可能影响查询、写入和数据一致性"))
        if any(token in lowered for token in ("auth", "security", "permission", "usercontext")):
            candidates.append(("AUTHORIZATION", "认证/权限相关变更需要权限边界和身份上下文回归"))
        for risk_type, description in candidates:
            key = (file_path, risk_type)
            if key in seen:
                continue
            seen.add(key)
            risks.append({"file": file_path, "type": risk_type, "description": description, "status": "HYPOTHESIS"})
    return risks


def _test_impact_candidates(changed_files: Iterable[str]) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for file_path in changed_files:
        result.append(
            {
                "file": file_path,
                "candidate": "TARGETED_UNIT_AND_CALL_CHAIN_REGRESSION",
                "description": "至少覆盖变更点、直接调用者、直接被调用者及 CodeGraph impact 返回的相关节点",
                "status": "CANDIDATE",
            }
        )
    return result


@dataclass(frozen=True)
class StructuralSufficiency:
    state: str
    score: float
    changed_file_count: int
    covered_file_count: int
    query_point_count: int
    successful_tool_calls: int
    total_tool_calls: int
    snapshot_stable: bool
    gaps: Tuple[Dict[str, Any], ...]


@dataclass(frozen=True)
class CodeAnalysisResult:
    state: str
    classification: str
    project_dir: str
    base_ref: str
    head_ref: str
    snapshot_id: str
    git_head: str
    changed_java_files: Tuple[str, ...]
    rounds: Tuple[Dict[str, Any], ...]
    structural_sufficiency: StructuralSufficiency
    structured_analysis: Dict[str, Any]
    semantic_analysis: Optional[Dict[str, Any]]
    overall_sufficiency: str
    evidence_digest: str
    analysis_path: str


def _group_calls(result: CodeGraphExecutionResult) -> List[Dict[str, Any]]:
    grouped: List[Dict[str, Any]] = []
    calls = list(result.tool_calls)
    width = len(_REQUIRED_TOOLS)
    for index, point in enumerate(result.query_points):
        point_calls = calls[index * width : (index + 1) * width]
        by_name = {str(item.get("tool") or ""): item for item in point_calls}
        grouped.append(
            {
                "point": asdict(point),
                "tools": {
                    tool: {
                        "success": bool(by_name.get(tool, {}).get("success")),
                        "payload_digest": _payload_digest(by_name.get(tool, {}).get("payload")),
                        "payload": by_name.get(tool, {}).get("payload"),
                    }
                    for tool in _REQUIRED_TOOLS
                },
            }
        )
    return grouped


def evaluate_structural_sufficiency(result: CodeGraphExecutionResult) -> StructuralSufficiency:
    changed_files = list(result.changed_java_files)
    covered_files = {point.file_path for point in result.query_points}
    calls = list(result.tool_calls)
    successful = sum(1 for item in calls if bool(item.get("success")))
    gaps: List[Dict[str, Any]] = []
    uncovered = [path for path in changed_files if path not in covered_files]
    if uncovered:
        gaps.append({"type": "CHANGE_FILE_NOT_QUERIED", "files": uncovered, "return_target": "CODEGRAPH_EXPAND_QUERY"})
    missing_tools: List[Dict[str, Any]] = []
    for grouped in _group_calls(result):
        failed = [name for name, detail in grouped["tools"].items() if not bool(detail.get("success"))]
        if failed:
            missing_tools.append({"point": grouped["point"], "tools": failed})
    if missing_tools:
        gaps.append({"type": "STRUCTURAL_TOOL_INCOMPLETE", "points": missing_tools, "return_target": "CODEGRAPH_RETRY"})
    stable = result.snapshot_before.snapshot_id == result.snapshot_after.snapshot_id and result.classification != "CODEGRAPH_SNAPSHOT_STALE"
    if not stable:
        gaps.append({"type": "CODE_SNAPSHOT_CHANGED", "return_target": "RESTART_CODE_ANALYSIS"})

    file_ratio = 1.0 if not changed_files else float(len(covered_files.intersection(changed_files))) / float(len(changed_files))
    tool_ratio = 1.0 if not calls else float(successful) / float(len(calls))
    stability_ratio = 1.0 if stable else 0.0
    score = round((file_ratio * 0.45) + (tool_ratio * 0.45) + (stability_ratio * 0.10), 4)
    state = "PASS" if not gaps and result.state == "PASS" else "INSUFFICIENT"
    return StructuralSufficiency(
        state=state,
        score=score,
        changed_file_count=len(changed_files),
        covered_file_count=len(covered_files.intersection(changed_files)),
        query_point_count=len(result.query_points),
        successful_tool_calls=successful,
        total_tool_calls=len(calls),
        snapshot_stable=stable,
        gaps=tuple(gaps),
    )


def validate_semantic_analysis(payload: Mapping[str, Any], allowed_evidence_refs: Iterable[str]) -> Dict[str, Any]:
    allowed = set(str(item) for item in allowed_evidence_refs)
    required_sections = ("summary", "changes", "impact_chains", "risks", "test_impacts", "unknowns", "sufficiency")
    missing = [section for section in required_sections if section not in payload]
    if missing:
        raise CodeAnalysisError("SEMANTIC_ANALYSIS_SECTION_MISSING:%s" % ",".join(missing))
    claims = payload.get("claims") or []
    if not isinstance(claims, list):
        raise CodeAnalysisError("SEMANTIC_ANALYSIS_CLAIMS_INVALID")
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise CodeAnalysisError("SEMANTIC_ANALYSIS_CLAIM_INVALID")
        refs = claim.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            raise CodeAnalysisError("SEMANTIC_ANALYSIS_CLAIM_UNEVIDENCED")
        unknown = [str(ref) for ref in refs if str(ref) not in allowed]
        if unknown:
            raise CodeAnalysisError("SEMANTIC_ANALYSIS_UNKNOWN_EVIDENCE_REF:%s" % ",".join(unknown))
    sufficiency = payload.get("sufficiency")
    if not isinstance(sufficiency, Mapping):
        raise CodeAnalysisError("SEMANTIC_ANALYSIS_SUFFICIENCY_INVALID")
    state = str(sufficiency.get("state") or "").upper()
    if state not in {"PASS", "INSUFFICIENT"}:
        raise CodeAnalysisError("SEMANTIC_ANALYSIS_SUFFICIENCY_STATE_INVALID")
    normalized = dict(payload)
    normalized["sufficiency"] = dict(sufficiency)
    normalized["validation"] = {
        "state": "PASS",
        "claim_count": len(claims),
        "evidence_ref_count": len(allowed),
    }
    return normalized


class EvidenceBackedCodeAnalysisEngine:
    def __init__(
        self,
        evidence_dir: str,
        *,
        codegraph_command: str,
        timeout_seconds: int = 120,
        max_rounds: int = 3,
        initial_points: int = 1,
        points_step: int = 2,
        max_points: int = 12,
    ) -> None:
        if max_rounds < 1 or initial_points < 1 or points_step < 1 or max_points < initial_points:
            raise CodeAnalysisError("CODE_ANALYSIS_LOOP_CONFIG_INVALID")
        self.evidence_dir = Path(evidence_dir)
        self.codegraph_command = codegraph_command
        self.timeout_seconds = timeout_seconds
        self.max_rounds = max_rounds
        self.initial_points = initial_points
        self.points_step = points_step
        self.max_points = max_points

    def execute(
        self,
        *,
        repo_path: str,
        base_ref: str,
        head_ref: str,
        target_file: Optional[str] = None,
        target_line: Optional[int] = None,
        context: Optional[Mapping[str, Any]] = None,
        semantic_analysis: Optional[Mapping[str, Any]] = None,
    ) -> CodeAnalysisResult:
        repo = Path(repo_path).resolve()
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        snapshot_start = capture_git_snapshot(str(repo))
        diff = capture_git_diff(str(repo), base_ref, head_ref)
        changed_files, all_candidate_points = discover_java_query_points(
            str(repo),
            base_ref=base_ref,
            head_ref=head_ref,
            target_file=target_file,
            target_line=target_line,
            max_points=self.max_points,
        )
        target_count = max(1, min(len(all_candidate_points), self.max_points))
        point_limit = min(self.initial_points, target_count)
        rounds: List[Dict[str, Any]] = []
        final_result: Optional[CodeGraphExecutionResult] = None
        final_sufficiency: Optional[StructuralSufficiency] = None

        for round_index in range(1, self.max_rounds + 1):
            round_dir = self.evidence_dir / ("round-%02d" % round_index)
            adapter = CodeGraphExecutableAdapter(
                str(round_dir),
                codegraph_command=self.codegraph_command,
                timeout_seconds=self.timeout_seconds,
            )
            result = adapter.execute(
                repo_path=str(repo),
                base_ref=base_ref,
                head_ref=head_ref,
                target_file=target_file,
                target_line=target_line,
                max_points=point_limit,
            )
            sufficiency = evaluate_structural_sufficiency(result)
            rounds.append(
                {
                    "round": round_index,
                    "point_limit": point_limit,
                    "classification": result.classification,
                    "state": result.state,
                    "graph_digest": result.graph_digest,
                    "evidence_path": result.evidence_path,
                    "query_points": [asdict(point) for point in result.query_points],
                    "sufficiency": asdict(sufficiency),
                }
            )
            final_result = result
            final_sufficiency = sufficiency
            if sufficiency.state == "PASS":
                break
            if not sufficiency.snapshot_stable:
                break
            next_limit = min(self.max_points, max(point_limit + self.points_step, len(changed_files)))
            if next_limit <= point_limit or point_limit >= target_count:
                break
            point_limit = min(next_limit, target_count)

        if final_result is None or final_sufficiency is None:
            raise CodeAnalysisError("CODE_ANALYSIS_NO_ROUND_EXECUTED")

        snapshot_end = capture_git_snapshot(str(repo))
        if snapshot_end.snapshot_id != snapshot_start.snapshot_id:
            raise CodeAnalysisError("CODE_ANALYSIS_SNAPSHOT_STALE_BEFORE_RESULT")

        grouped = _group_calls(final_result)
        evidence_refs: List[str] = ["git-diff:%s" % diff["diff_sha256"], "snapshot:%s" % snapshot_start.snapshot_id]
        structural_findings: List[Dict[str, Any]] = []
        for item in grouped:
            point = item["point"]
            point_ref = "point:%s:%s" % (point["file_path"], point["line_number"])
            evidence_refs.append(point_ref)
            tools: Dict[str, Any] = item["tools"]
            for tool, detail in tools.items():
                tool_ref = "%s:%s" % (tool, detail["payload_digest"])
                evidence_refs.append(tool_ref)
            structural_findings.append(
                {
                    "point": point,
                    "evidence_ref": point_ref,
                    "ai_context": tools["codegraph_get_ai_context"],
                    "callers": tools["codegraph_get_callers"],
                    "callees": tools["codegraph_get_callees"],
                    "dependency_graph": tools["codegraph_get_dependency_graph"],
                    "impact": tools["codegraph_analyze_impact"],
                }
            )

        structured_analysis: Dict[str, Any] = {
            "schema_version": 1,
            "analysis_mode": "EVIDENCE_STRUCTURED_NOT_LLM",
            "context": dict(context or {}),
            "source_change": {
                "base_ref": base_ref,
                "head_ref": head_ref,
                "git_head": snapshot_start.head_revision,
                "snapshot_id": snapshot_start.snapshot_id,
                "dirty": snapshot_start.dirty,
                "changed_java_files": list(changed_files),
                "diff_sha256": diff["diff_sha256"],
                "diff_chars": diff["diff_chars"],
            },
            "structural_findings": structural_findings,
            "risk_hypotheses": _risk_hypotheses(changed_files),
            "test_impact_candidates": _test_impact_candidates(changed_files),
            "unknowns": [
                {
                    "type": "SEMANTIC_BUSINESS_INTERPRETATION_PENDING",
                    "description": "结构证据已验证，但业务语义、需求映射和最终风险结论必须由证据约束的语义分析 Worker 完成。",
                }
            ],
            "structural_sufficiency": asdict(final_sufficiency),
            "evidence_refs": sorted(set(evidence_refs)),
        }

        validated_semantic: Optional[Dict[str, Any]] = None
        overall = "STRUCTURAL_INSUFFICIENT"
        classification = "CODE_ANALYSIS_STRUCTURAL_INSUFFICIENT"
        state = "INSUFFICIENT"
        if final_sufficiency.state == "PASS":
            overall = "SEMANTIC_PENDING"
            classification = "CODE_ANALYSIS_STRUCTURAL_EVIDENCE_SUFFICIENT_SEMANTIC_PENDING"
            state = "PARTIAL"
            if semantic_analysis is not None:
                validated_semantic = validate_semantic_analysis(semantic_analysis, structured_analysis["evidence_refs"])
                semantic_state = str(validated_semantic["sufficiency"]["state"]).upper()
                if semantic_state == "PASS":
                    overall = "PASS"
                    classification = "CODE_ANALYSIS_SUFFICIENT"
                    state = "PASS"
                else:
                    overall = "SEMANTIC_INSUFFICIENT"
                    classification = "CODE_ANALYSIS_SEMANTIC_INSUFFICIENT"
                    state = "INSUFFICIENT"

        final_payload: Dict[str, Any] = {
            "schema_version": 1,
            "state": state,
            "classification": classification,
            "project_dir": str(repo),
            "base_ref": base_ref,
            "head_ref": head_ref,
            "snapshot_id": snapshot_start.snapshot_id,
            "git_head": snapshot_start.head_revision,
            "changed_java_files": list(changed_files),
            "rounds": rounds,
            "structural_sufficiency": asdict(final_sufficiency),
            "structured_analysis": structured_analysis,
            "semantic_analysis": validated_semantic,
            "overall_sufficiency": overall,
            "truth_note": "Structural PASS is not full Code Analysis PASS. Full PASS additionally requires an evidence-bound semantic analysis result whose sufficiency is PASS.",
        }
        digest_payload = dict(final_payload)
        evidence_digest = _canonical_sha256(digest_payload)
        final_payload["evidence_digest"] = evidence_digest
        analysis_path = self.evidence_dir / "code-analysis.json"
        temp = analysis_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(final_payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        os.replace(str(temp), str(analysis_path))

        return CodeAnalysisResult(
            state=state,
            classification=classification,
            project_dir=str(repo),
            base_ref=base_ref,
            head_ref=head_ref,
            snapshot_id=snapshot_start.snapshot_id,
            git_head=snapshot_start.head_revision,
            changed_java_files=tuple(changed_files),
            rounds=tuple(rounds),
            structural_sufficiency=final_sufficiency,
            structured_analysis=structured_analysis,
            semantic_analysis=validated_semantic,
            overall_sufficiency=overall,
            evidence_digest=evidence_digest,
            analysis_path=str(analysis_path),
        )
