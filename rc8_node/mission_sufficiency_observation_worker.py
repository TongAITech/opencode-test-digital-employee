"""Fail-closed N10 mission-sufficiency observation contract.

The node may assemble evidence-backed convergence inputs, but Center remains the sole
authority for test sufficiency, product quality, release recommendation and convergence.
"""
from __future__ import annotations

from typing import Any, Dict


class MissionSufficiencyObservationWorkerError(RuntimeError):
    pass


class MissionSufficiencyObservationWorker:
    producer_ref = "RC8_MISSION_SUFFICIENCY_OBSERVATION_WORKER"
    stage = "MISSION_SUFFICIENCY"

    @staticmethod
    def validate_candidate(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise MissionSufficiencyObservationWorkerError("N10_OUTPUT_OBJECT_REQUIRED")
        evidence = value.get("evidence_refs")
        if not isinstance(evidence, list) or not evidence or any(not str(ref).strip() for ref in evidence):
            raise MissionSufficiencyObservationWorkerError("N10_EVIDENCE_DENOMINATOR_NONEMPTY_REQUIRED")
        normalized = [str(ref).strip() for ref in evidence]
        if len(set(normalized)) != len(normalized):
            raise MissionSufficiencyObservationWorkerError("N10_EVIDENCE_DENOMINATOR_UNIQUE_REQUIRED")

        dimensions = value.get("dimensions")
        if not isinstance(dimensions, dict):
            raise MissionSufficiencyObservationWorkerError("N10_DIMENSIONS_OBJECT_REQUIRED")
        required = ("test_sufficiency", "product_quality", "release_recommendation", "residual_risk")
        missing = [name for name in required if not isinstance(dimensions.get(name), dict)]
        if missing:
            raise MissionSufficiencyObservationWorkerError("N10_REQUIRED_DIMENSIONS_MISSING:%s" % ",".join(missing))
        for name in required:
            item = dimensions[name]
            state = str(item.get("state") or "").strip().upper()
            refs = item.get("evidence_refs")
            if not state:
                raise MissionSufficiencyObservationWorkerError("N10_DIMENSION_STATE_REQUIRED:%s" % name)
            if not isinstance(refs, list) or not refs or any(not str(ref).strip() for ref in refs):
                raise MissionSufficiencyObservationWorkerError("N10_DIMENSION_EVIDENCE_REQUIRED:%s" % name)
            if any(str(ref).strip() not in normalized for ref in refs):
                raise MissionSufficiencyObservationWorkerError("N10_DIMENSION_EVIDENCE_OUTSIDE_DENOMINATOR:%s" % name)

        gaps = value.get("active_blocking_gaps")
        if not isinstance(gaps, list):
            raise MissionSufficiencyObservationWorkerError("N10_ACTIVE_BLOCKING_GAPS_LIST_REQUIRED")
        if any(not str(gap).strip() for gap in gaps):
            raise MissionSufficiencyObservationWorkerError("N10_ACTIVE_BLOCKING_GAP_REF_REQUIRED")

        result = dict(value)
        result["authority"] = "NODE_OBSERVATION_ONLY"
        result["convergence_authority"] = "CENTER_ONLY"
        result["may_declare_mission_converged"] = False
        result["may_recommend_release"] = False
        return result
