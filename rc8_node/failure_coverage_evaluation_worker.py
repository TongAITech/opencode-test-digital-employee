"""Fail-closed N8 FAILURE_COVERAGE_EVALUATION node worker.

Produces diagnosis/gap-routing observations only. Canonical GapRouter decisions,
MissionNode state, quality and release authority remain in Center.
"""
from __future__ import annotations

from typing import Any, Dict


class FailureCoverageEvaluationWorkerError(RuntimeError):
    pass


class FailureCoverageEvaluationWorker:
    producer_ref = "RC8_FAILURE_COVERAGE_EVALUATION_WORKER"

    @staticmethod
    def validate_candidate(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise FailureCoverageEvaluationWorkerError("FAILURE_COVERAGE_OUTPUT_OBJECT_REQUIRED")
        denominator = value.get("coverage_denominator_refs")
        evidence = value.get("evidence_refs")
        gaps = value.get("gaps")
        for name, refs in (("COVERAGE_DENOMINATOR_REFS", denominator), ("EVIDENCE_REFS", evidence)):
            if not isinstance(refs, list) or not refs or any(not str(v).strip() for v in refs):
                raise FailureCoverageEvaluationWorkerError("%s_NONEMPTY_REQUIRED" % name)
            normalized = [str(v).strip() for v in refs]
            if len(set(normalized)) != len(normalized):
                raise FailureCoverageEvaluationWorkerError("%s_UNIQUE_REQUIRED" % name)
        if not isinstance(gaps, list):
            raise FailureCoverageEvaluationWorkerError("GAPS_LIST_REQUIRED")
        known = set(str(v).strip() for v in denominator)
        seen = set()
        for gap in gaps:
            if not isinstance(gap, dict):
                raise FailureCoverageEvaluationWorkerError("GAP_OBJECT_REQUIRED")
            gap_id = str(gap.get("gap_id") or "").strip()
            ref = str(gap.get("denominator_ref") or "").strip()
            reason = str(gap.get("reason") or "").strip()
            route = str(gap.get("suggested_route") or "").strip()
            if not gap_id or not ref or not reason or not route:
                raise FailureCoverageEvaluationWorkerError("GAP_FIELDS_REQUIRED")
            if gap_id in seen:
                raise FailureCoverageEvaluationWorkerError("GAP_ID_UNIQUE_REQUIRED")
            if ref not in known:
                raise FailureCoverageEvaluationWorkerError("GAP_DENOMINATOR_REF_UNKNOWN")
            seen.add(gap_id)
        result = dict(value)
        result["authority"] = "NODE_OBSERVATION_ONLY"
        result["gap_router_authority"] = "CENTER_ONLY"
        return result
