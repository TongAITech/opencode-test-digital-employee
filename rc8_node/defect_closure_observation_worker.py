"""Fail-closed N9 defect-closure observation contract.

This module deliberately does not create canonical defects. Only Center may consume
an N8 PRODUCT route and mutate the first-class defect lifecycle. Node output is
candidate Evidence for reproduction/RCA/impact/fix verification review.
"""
from __future__ import annotations

from typing import Any, Dict


class DefectClosureObservationWorkerError(RuntimeError):
    pass


class DefectClosureObservationWorker:
    producer_ref = "RC8_DEFECT_CLOSURE_OBSERVATION_WORKER"

    @staticmethod
    def validate_candidate(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise DefectClosureObservationWorkerError("DEFECT_CLOSURE_OUTPUT_OBJECT_REQUIRED")
        route_ref = str(value.get("route_decision_ref") or "").strip()
        source_observation_ref = str(value.get("source_observation_ref") or "").strip()
        source_attempt_ref = str(value.get("source_attempt_ref") or "").strip()
        if not route_ref:
            raise DefectClosureObservationWorkerError("N9_CANONICAL_N8_ROUTE_REF_REQUIRED")
        if not source_observation_ref or not source_attempt_ref:
            raise DefectClosureObservationWorkerError("N9_SOURCE_OBSERVATION_AND_ATTEMPT_REQUIRED")
        classification = str(value.get("classification") or "").strip().upper()
        if classification != "PRODUCT":
            raise DefectClosureObservationWorkerError("N9_REQUIRES_PRODUCT_CLASSIFICATION")
        evidence = value.get("evidence_refs")
        if not isinstance(evidence, list) or not evidence or any(not str(ref).strip() for ref in evidence):
            raise DefectClosureObservationWorkerError("N9_EVIDENCE_REFS_NONEMPTY_REQUIRED")
        normalized = [str(ref).strip() for ref in evidence]
        if len(set(normalized)) != len(normalized):
            raise DefectClosureObservationWorkerError("N9_EVIDENCE_REFS_UNIQUE_REQUIRED")
        observations = value.get("observations")
        if not isinstance(observations, list) or not observations:
            raise DefectClosureObservationWorkerError("N9_OBSERVATIONS_NONEMPTY_REQUIRED")
        allowed = {"REPRODUCTION", "RCA", "IMPACT", "FIX_VERIFICATION", "REGRESSION"}
        seen = set()
        for item in observations:
            if not isinstance(item, dict):
                raise DefectClosureObservationWorkerError("N9_OBSERVATION_OBJECT_REQUIRED")
            observation_id = str(item.get("observation_id") or "").strip()
            kind = str(item.get("kind") or "").strip().upper()
            item_evidence = item.get("evidence_refs")
            if not observation_id or observation_id in seen:
                raise DefectClosureObservationWorkerError("N9_OBSERVATION_ID_UNIQUE_REQUIRED")
            if kind not in allowed:
                raise DefectClosureObservationWorkerError("N9_OBSERVATION_KIND_INVALID")
            if not isinstance(item_evidence, list) or not item_evidence or any(not str(ref).strip() for ref in item_evidence):
                raise DefectClosureObservationWorkerError("N9_OBSERVATION_EVIDENCE_REQUIRED")
            seen.add(observation_id)
        result = dict(value)
        result["classification"] = "PRODUCT"
        result["authority"] = "NODE_OBSERVATION_ONLY"
        result["defect_lifecycle_authority"] = "CENTER_ONLY"
        result["may_file_defect"] = False
        result["may_close_defect"] = False
        return result
