"""RC7.2 coverage feedback mapping and convergence support.

Coverage is a feedback/convergence signal, never the test-asset root.  This
module persists Libra-like coverage observations, deterministically maps an
uncovered code slice back to existing ReleaseBatch -> Requirement -> SST ->
TestObligation lineage, and records an evidence-backed gap classification.
It never creates TestCases/ETUs and it never guesses CASE_MISSING merely from
coverage.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .truth_overlay import install_rc7_truth_overlay


_COVERAGE_OBSERVATION = "rc72_coverage_observation"
_COVERAGE_GAP = "rc72_coverage_gap"

_EVENT_TYPES = {
    "RC72_COVERAGE_OBSERVATION_UPSERTED": (_COVERAGE_OBSERVATION, "observation_id"),
    "RC72_COVERAGE_GAP_UPSERTED": (_COVERAGE_GAP, "gap_id"),
}
_BUCKETS = {
    _COVERAGE_OBSERVATION: "rc72_coverage_observations",
    _COVERAGE_GAP: "rc72_coverage_gaps",
}


class CoverageGapReason(str, Enum):
    NO_REQUIREMENT_MAPPING = "NO_REQUIREMENT_MAPPING"
    AMBIGUOUS_OBLIGATION_MAPPING = "AMBIGUOUS_OBLIGATION_MAPPING"
    ANALYSIS_MISSING = "ANALYSIS_MISSING"
    CASE_MISSING = "CASE_MISSING"
    DATA_BLOCKED = "DATA_BLOCKED"
    EXECUTABLE_BLOCKED = "EXECUTABLE_BLOCKED"
    PATH_NOT_REACHED = "PATH_NOT_REACHED"
    UNREACHABLE = "UNREACHABLE"
    ALREADY_COVERED_NO_GAIN = "ALREADY_COVERED_NO_GAIN"


class CoverageMappingStatus(str, Enum):
    MAPPED = "MAPPED"
    UNMAPPED = "UNMAPPED"
    AMBIGUOUS = "AMBIGUOUS"
    CLASSIFIED = "CLASSIFIED"
    EXCLUSION_REVIEW_REQUIRED = "EXCLUSION_REVIEW_REQUIRED"


_REASON_ROUTES = {
    CoverageGapReason.ANALYSIS_MISSING: (["N3_CODE_ANALYSIS"], "REPAIR_ANALYSIS"),
    CoverageGapReason.CASE_MISSING: (["N4_TEST_DESIGN"], "REPAIR_TEST_DESIGN"),
    CoverageGapReason.DATA_BLOCKED: (["N5_TEST_DATA"], "REPAIR_TEST_DATA"),
    CoverageGapReason.EXECUTABLE_BLOCKED: (["N6_EXECUTABLE_READINESS"], "REPAIR_EXECUTABLE"),
    CoverageGapReason.PATH_NOT_REACHED: (["N8_DIAGNOSIS_RECOVERY"], "DIAGNOSE_PATH"),
    CoverageGapReason.ALREADY_COVERED_NO_GAIN: (["N10_RELEASE_CONVERGENCE"], "DEPRIORITIZE_OR_INVESTIGATE"),
}


@dataclass(frozen=True)
class CoverageMappingResult:
    gap_id: str
    status: CoverageMappingStatus
    requirement_id: Optional[str] = None
    sst_id: Optional[str] = None
    obligation_id: Optional[str] = None
    candidate_obligation_ids: List[str] = field(default_factory=list)
    gap_reason: Optional[CoverageGapReason] = None
    responsible_nodes: List[str] = field(default_factory=list)
    action: str = ""


def _now() -> int:
    return int(time.time())


def _required(out: Dict[str, Any], name: str) -> str:
    return _contracts._require_str(out, name)


def _optional(out: Dict[str, Any], name: str) -> None:
    value = out.get(name)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise _contracts.DomainValidationError("%s_INVALID" % name.upper())


def _string_list(out: Dict[str, Any], name: str) -> List[str]:
    value = out.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    out[name] = list(value)
    return out[name]


def _base(payload: Dict[str, Any], artifact_type: str, identity: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    out[identity] = _required(out, identity)
    out["mission_id"] = _required(out, "mission_id")
    out["release_id"] = _required(out, "release_id")
    out["artifact_type"] = artifact_type
    out["artifact_version"] = _contracts._artifact_version(out)
    return out


def _validate_observation(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _COVERAGE_OBSERVATION, "observation_id")
    for name in ("release_batch_id", "application_id", "source", "evidence_ref"):
        out[name] = _required(out, name)
    for name in ("covered_units", "total_units"):
        if not isinstance(out.get(name), int) or out[name] < 0:
            raise _contracts.DomainValidationError("COVERAGE_OBSERVATION_%s_INVALID" % name.upper())
    if out["total_units"] <= 0 or out["covered_units"] > out["total_units"]:
        raise _contracts.DomainValidationError("COVERAGE_OBSERVATION_UNITS_INVALID")
    ratio = out.get("target_ratio")
    if not isinstance(ratio, (int, float)) or not 0.0 <= float(ratio) <= 1.0:
        raise _contracts.DomainValidationError("COVERAGE_OBSERVATION_TARGET_RATIO_INVALID")
    out["target_ratio"] = float(ratio)
    if not isinstance(out.get("observed_at"), int) or out["observed_at"] < 0:
        raise _contracts.DomainValidationError("COVERAGE_OBSERVATION_AT_INVALID")
    return out


def _validate_gap(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _COVERAGE_GAP, "gap_id")
    for name in ("observation_id", "release_batch_id", "application_id", "code_slice", "status", "action"):
        out[name] = _required(out, name)
    if not isinstance(out.get("uncovered_units"), int) or out["uncovered_units"] < 0:
        raise _contracts.DomainValidationError("COVERAGE_GAP_UNCOVERED_UNITS_INVALID")
    try:
        out["status"] = CoverageMappingStatus(out["status"].upper()).value
    except ValueError as exc:
        raise _contracts.DomainValidationError("COVERAGE_GAP_STATUS_INVALID") from exc
    for name in ("requirement_id", "sst_id", "obligation_id", "gap_reason", "rationale"):
        _optional(out, name)
    _string_list(out, "candidate_obligation_ids")
    _string_list(out, "responsible_nodes")
    _string_list(out, "evidence_refs")
    reason = out.get("gap_reason")
    if reason is not None:
        try:
            out["gap_reason"] = CoverageGapReason(reason).value
        except ValueError as exc:
            raise _contracts.DomainValidationError("COVERAGE_GAP_REASON_INVALID") from exc
    if not isinstance(out.get("excluded"), bool):
        raise _contracts.DomainValidationError("COVERAGE_GAP_EXCLUDED_INVALID")
    if not isinstance(out.get("created_at"), int) or out["created_at"] < 0:
        raise _contracts.DomainValidationError("COVERAGE_GAP_CREATED_AT_INVALID")
    if out.get("updated_at") is not None and (not isinstance(out["updated_at"], int) or out["updated_at"] < 0):
        raise _contracts.DomainValidationError("COVERAGE_GAP_UPDATED_AT_INVALID")
    return out


def install_rc72_coverage_overlay() -> None:
    install_rc7_truth_overlay()
    validators = {
        _COVERAGE_OBSERVATION: _validate_observation,
        _COVERAGE_GAP: _validate_gap,
    }
    for artifact_type, validator in validators.items():
        _contracts.VALIDATORS[artifact_type] = validator
        _truth.BUCKETS[artifact_type] = _BUCKETS[artifact_type]
    for event_type, (artifact_type, identity) in _EVENT_TYPES.items():
        _truth.EVENT_TYPES[event_type] = (artifact_type, identity)
        _truth.IDENTITY_FIELDS[artifact_type] = identity


def _ensure_projection_buckets(truth: TruthRuntime) -> None:
    projection = truth.projection
    for artifact_type, bucket in _BUCKETS.items():
        if not hasattr(projection, bucket):
            setattr(projection, bucket, {})
        projection._versions.setdefault(artifact_type, {})


class CoverageFeedbackService:
    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_coverage_overlay()
        _ensure_projection_buckets(truth)
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("COVERAGE_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()

    def install_overlay(self) -> None:
        install_rc72_coverage_overlay()

    def _append(self, event_type: str, payload: Dict[str, Any]):
        out = dict(payload)
        out["release_id"] = self.release_id
        out.setdefault("artifact_version", 1)
        return self.truth.append_atomic(event_type, out)

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("COVERAGE_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    def _upsert_gap(self, row: Mapping[str, Any], **changes: Any) -> Dict[str, Any]:
        updated = dict(row)
        updated.pop("artifact_type", None)
        updated.update(changes)
        updated["artifact_version"] = int(row.get("artifact_version", 1)) + 1
        updated["updated_at"] = _now()
        self._append("RC72_COVERAGE_GAP_UPSERTED", updated)
        return self._one(_COVERAGE_GAP, gap_id=str(updated["gap_id"]))

    def record_observation(
        self,
        *,
        observation_id: str,
        mission_id: str,
        release_batch_id: str,
        application_id: str,
        source: str,
        covered_units: int,
        total_units: int,
        target_ratio: float,
        evidence_ref: str,
    ) -> None:
        if self.truth.query(_COVERAGE_OBSERVATION, observation_id=observation_id):
            raise ContractError("COVERAGE_OBSERVATION_ALREADY_EXISTS")
        batches = self.truth.query("rc72_release_batch", release_batch_id=release_batch_id)
        if len(batches) != 1 or batches[0].get("mission_id") != mission_id:
            raise ContractError("COVERAGE_OBSERVATION_RELEASE_BATCH_MISMATCH")
        if application_id not in list(batches[0].get("application_ids") or []):
            raise ContractError("COVERAGE_OBSERVATION_APPLICATION_OUT_OF_SCOPE")
        self._append(
            "RC72_COVERAGE_OBSERVATION_UPSERTED",
            {
                "observation_id": observation_id,
                "mission_id": mission_id,
                "release_batch_id": release_batch_id,
                "application_id": application_id,
                "source": source,
                "covered_units": covered_units,
                "total_units": total_units,
                "target_ratio": target_ratio,
                "evidence_ref": evidence_ref,
                "observed_at": _now(),
            },
        )

    def _matching_obligations(self, observation: Mapping[str, Any], code_slice: str) -> List[Dict[str, Any]]:
        rows = self.truth.query("rc72_test_obligation", mission_id=str(observation["mission_id"]))
        matched = []
        for row in rows:
            if row.get("release_batch_id") != observation.get("release_batch_id"):
                continue
            if row.get("application_id") != observation.get("application_id"):
                continue
            refs = set(row.get("code_slice_refs") or []) | set(row.get("coverage_targets") or [])
            if code_slice in refs:
                matched.append(row)
        return sorted(matched, key=lambda row: str(row.get("obligation_id")))

    def map_gap(
        self,
        *,
        gap_id: str,
        observation_id: str,
        code_slice: str,
        uncovered_units: int,
    ) -> CoverageMappingResult:
        if self.truth.query(_COVERAGE_GAP, gap_id=gap_id):
            raise ContractError("COVERAGE_GAP_ALREADY_EXISTS")
        observation = self._one(_COVERAGE_OBSERVATION, observation_id=observation_id)
        matches = self._matching_obligations(observation, code_slice)

        base = {
            "gap_id": gap_id,
            "observation_id": observation_id,
            "mission_id": observation["mission_id"],
            "release_batch_id": observation["release_batch_id"],
            "application_id": observation["application_id"],
            "code_slice": code_slice,
            "uncovered_units": uncovered_units,
            "candidate_obligation_ids": [str(row["obligation_id"]) for row in matches],
            "evidence_refs": [],
            "rationale": None,
            "excluded": False,
            "created_at": _now(),
            "updated_at": _now(),
        }
        if not matches:
            base.update(
                {
                    "status": CoverageMappingStatus.UNMAPPED.value,
                    "requirement_id": None,
                    "sst_id": None,
                    "obligation_id": None,
                    "gap_reason": CoverageGapReason.NO_REQUIREMENT_MAPPING.value,
                    "responsible_nodes": ["N2_REQUIREMENT", "N3_CODE_ANALYSIS"],
                    "action": "INVESTIGATE_LINEAGE",
                }
            )
            self._append("RC72_COVERAGE_GAP_UPSERTED", base)
            return CoverageMappingResult(
                gap_id=gap_id,
                status=CoverageMappingStatus.UNMAPPED,
                gap_reason=CoverageGapReason.NO_REQUIREMENT_MAPPING,
                responsible_nodes=["N2_REQUIREMENT", "N3_CODE_ANALYSIS"],
                action="INVESTIGATE_LINEAGE",
            )
        if len(matches) > 1:
            base.update(
                {
                    "status": CoverageMappingStatus.AMBIGUOUS.value,
                    "requirement_id": None,
                    "sst_id": None,
                    "obligation_id": None,
                    "gap_reason": CoverageGapReason.AMBIGUOUS_OBLIGATION_MAPPING.value,
                    "responsible_nodes": ["N3_CODE_ANALYSIS", "N10_RELEASE_CONVERGENCE"],
                    "action": "INVESTIGATE_LINEAGE",
                }
            )
            self._append("RC72_COVERAGE_GAP_UPSERTED", base)
            return CoverageMappingResult(
                gap_id=gap_id,
                status=CoverageMappingStatus.AMBIGUOUS,
                candidate_obligation_ids=list(base["candidate_obligation_ids"]),
                gap_reason=CoverageGapReason.AMBIGUOUS_OBLIGATION_MAPPING,
                responsible_nodes=["N3_CODE_ANALYSIS", "N10_RELEASE_CONVERGENCE"],
                action="INVESTIGATE_LINEAGE",
            )

        obligation = matches[0]
        base.update(
            {
                "status": CoverageMappingStatus.MAPPED.value,
                "requirement_id": obligation["requirement_id"],
                "sst_id": obligation["sst_id"],
                "obligation_id": obligation["obligation_id"],
                "gap_reason": None,
                "responsible_nodes": [],
                "action": "CLASSIFY_GAP_REASON",
            }
        )
        self._append("RC72_COVERAGE_GAP_UPSERTED", base)
        return CoverageMappingResult(
            gap_id=gap_id,
            status=CoverageMappingStatus.MAPPED,
            requirement_id=str(obligation["requirement_id"]),
            sst_id=str(obligation["sst_id"]),
            obligation_id=str(obligation["obligation_id"]),
            candidate_obligation_ids=[str(obligation["obligation_id"])],
            action="CLASSIFY_GAP_REASON",
        )

    def classify_gap(
        self,
        *,
        gap_id: str,
        gap_reason: CoverageGapReason,
        evidence_refs: Sequence[str],
        rationale: str,
    ) -> CoverageMappingResult:
        row = self._one(_COVERAGE_GAP, gap_id=gap_id)
        if row.get("status") != CoverageMappingStatus.MAPPED.value or not row.get("obligation_id"):
            raise ContractError("COVERAGE_GAP_REQUIRES_UNIQUE_MAPPING")
        try:
            reason = gap_reason if isinstance(gap_reason, CoverageGapReason) else CoverageGapReason(str(gap_reason))
        except ValueError as exc:
            raise ContractError("COVERAGE_GAP_REASON_INVALID") from exc
        if reason in {CoverageGapReason.NO_REQUIREMENT_MAPPING, CoverageGapReason.AMBIGUOUS_OBLIGATION_MAPPING}:
            raise ContractError("COVERAGE_GAP_REASON_REQUIRES_MAPPING_PHASE")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ContractError("COVERAGE_GAP_RATIONALE_REQUIRED")
        evidence = [str(ref).strip() for ref in evidence_refs if isinstance(ref, str) and str(ref).strip()]
        if reason == CoverageGapReason.UNREACHABLE:
            if len(evidence) < 2:
                raise ContractError("COVERAGE_EXCLUSION_EVIDENCE_REQUIRED")
            status = CoverageMappingStatus.EXCLUSION_REVIEW_REQUIRED
            nodes = ["N3_CODE_ANALYSIS", "N10_RELEASE_CONVERGENCE"]
            action = "HUMAN_REVIEW_COVERAGE_EXCLUSION"
        else:
            if not evidence:
                raise ContractError("COVERAGE_GAP_CLASSIFICATION_EVIDENCE_REQUIRED")
            if reason not in _REASON_ROUTES:
                raise ContractError("COVERAGE_GAP_REASON_UNSUPPORTED")
            status = CoverageMappingStatus.CLASSIFIED
            nodes, action = _REASON_ROUTES[reason]
        updated = self._upsert_gap(
            row,
            status=status.value,
            gap_reason=reason.value,
            responsible_nodes=list(nodes),
            action=action,
            evidence_refs=evidence,
            rationale=rationale,
            excluded=False,
        )
        return CoverageMappingResult(
            gap_id=gap_id,
            status=status,
            requirement_id=updated.get("requirement_id"),
            sst_id=updated.get("sst_id"),
            obligation_id=updated.get("obligation_id"),
            candidate_obligation_ids=list(updated.get("candidate_obligation_ids") or []),
            gap_reason=reason,
            responsible_nodes=list(nodes),
            action=action,
        )
