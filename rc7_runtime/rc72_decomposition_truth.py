"""Canonical R1 persistence for RC7.2 adaptive decomposition decisions.

A planning snapshot is immutable decision evidence: inputs, visible config,
priority explanation, coverage routes and emitted ETU ids are stored in the
same R1 as ReleaseBatch/TestObligation/ETU truth. No session-local planner
memory is required for later explanation or replay.
"""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Dict, Optional

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_decomposer import (
    AdaptiveTaskDecomposer,
    DecompositionResult,
    DecompositionSnapshot,
)
from .rc72_repository import CanonicalRC72Repository
from .truth_overlay import install_rc7_truth_overlay


_EVENT = "RC72_DECOMPOSITION_SNAPSHOT_UPSERTED"
_ARTIFACT = "rc72_decomposition_snapshot"
_BUCKET = "rc72_decomposition_snapshots"


def _require_dict(out: Dict[str, Any], field: str) -> None:
    if not isinstance(out.get(field), dict):
        raise _contracts.DomainValidationError("%s_MUST_BE_OBJECT" % field.upper())


def _require_numeric_dict(out: Dict[str, Any], field: str) -> None:
    _require_dict(out, field)
    for key, value in out[field].items():
        if not isinstance(key, str) or not key.strip() or not isinstance(value, (int, float)):
            raise _contracts.DomainValidationError("%s_INVALID" % field.upper())


def _validator(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for field in (
        "snapshot_id", "mission_id", "release_batch_id", "current_node",
        "config_version", "release_id",
    ):
        out[field] = _contracts._require_str(out, field)
    for field in ("obligation_ids", "case_ids", "completed_case_ids", "etu_ids"):
        _contracts._require_string_list(out, field)
    # Do not use legacy batch-reserved names such as `cases`; replay expands
    # those fields as historical TEST_CASE_UPSERTED batches before RC7.2
    # projection sees them.
    for field in (
        "planning_cases", "coverage_gaps", "execution_history",
        "planning_signals", "coverage_routes",
    ):
        if not isinstance(out.get(field), list):
            raise _contracts.DomainValidationError("%s_MUST_BE_LIST" % field.upper())
    _require_numeric_dict(out, "priority_weights")
    _require_numeric_dict(out, "obligation_priorities")
    _require_dict(out, "priority_explanations")
    for obligation_id, explanation in out["priority_explanations"].items():
        if not isinstance(obligation_id, str) or not obligation_id.strip() or not isinstance(explanation, dict):
            raise _contracts.DomainValidationError("PRIORITY_EXPLANATIONS_INVALID")
        for dimension, value in explanation.items():
            if not isinstance(dimension, str) or not dimension.strip() or not isinstance(value, (int, float)):
                raise _contracts.DomainValidationError("PRIORITY_EXPLANATIONS_INVALID")
    _require_dict(out, "replan_reasons")
    for obligation_id, reasons in out["replan_reasons"].items():
        if not isinstance(obligation_id, str) or not obligation_id.strip():
            raise _contracts.DomainValidationError("REPLAN_REASONS_INVALID")
        if not isinstance(reasons, list) or not all(isinstance(reason, str) and reason.strip() for reason in reasons):
            raise _contracts.DomainValidationError("REPLAN_REASONS_INVALID")
    created_at = out.get("created_at")
    if not isinstance(created_at, int) or created_at < 0:
        raise _contracts.DomainValidationError("DECOMPOSITION_CREATED_AT_INVALID")
    out["artifact_type"] = _ARTIFACT
    out["artifact_version"] = _contracts._artifact_version(out)
    return out


def install_rc72_decomposition_truth_overlay() -> None:
    install_rc7_truth_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = _validator
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "snapshot_id")
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "snapshot_id"


def _dict_list(values):
    return [asdict(value) for value in values]


class PersistentAdaptiveTaskDecomposer:
    """Run deterministic decomposition and commit explainable planning truth."""

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        decomposer: Optional[AdaptiveTaskDecomposer] = None,
    ) -> None:
        install_rc72_decomposition_truth_overlay()
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("DECOMPOSITION_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()
        self.decomposer = decomposer or AdaptiveTaskDecomposer()
        self.repository = CanonicalRC72Repository(truth, release_id=self.release_id)

    def plan_and_persist(self, snapshot: DecompositionSnapshot) -> DecompositionResult:
        if self.truth.query(_ARTIFACT, snapshot_id=snapshot.snapshot_id):
            raise ContractError("DECOMPOSITION_SNAPSHOT_ALREADY_EXISTS")
        self._validate_canonical_inputs(snapshot)
        result = self.decomposer.decompose(snapshot)

        for etu in result.etus:
            if self.truth.query("rc72_etu", etu_id=etu.etu_id):
                raise ContractError("DECOMPOSITION_ETU_ALREADY_EXISTS:%s" % etu.etu_id)
        for etu in result.etus:
            self.repository.persist(etu)

        payload = {
            "snapshot_id": snapshot.snapshot_id,
            "mission_id": snapshot.mission_id,
            "release_batch_id": snapshot.release_batch_id,
            "current_node": snapshot.current_node,
            "config_version": snapshot.config_version,
            "obligation_ids": [obligation.obligation_id for obligation in snapshot.obligations],
            "case_ids": [case.case_id for case in snapshot.cases],
            "planning_cases": _dict_list(snapshot.cases),
            "coverage_gaps": _dict_list(snapshot.coverage_gaps),
            "completed_case_ids": list(snapshot.completed_case_ids),
            "execution_history": _dict_list(snapshot.execution_history),
            "planning_signals": _dict_list(snapshot.planning_signals),
            "priority_weights": dict(self.decomposer.config.priority_weights),
            "priority_explanations": {
                obligation_id: dict(explanation)
                for obligation_id, explanation in result.priority_explanations.items()
            },
            "obligation_priorities": dict(result.obligation_priorities),
            "coverage_routes": _dict_list(result.coverage_routes),
            "replan_reasons": {
                obligation_id: list(reasons)
                for obligation_id, reasons in result.replan_reasons.items()
            },
            "etu_ids": [etu.etu_id for etu in result.etus],
            "created_at": int(time.time()),
            "release_id": self.release_id,
            "artifact_version": 1,
        }
        self.truth.append_atomic(_EVENT, payload)
        return result

    def _validate_canonical_inputs(self, snapshot: DecompositionSnapshot) -> None:
        batches = self.truth.query("rc72_release_batch", release_batch_id=snapshot.release_batch_id)
        if len(batches) != 1:
            raise ContractError("DECOMPOSITION_RELEASE_BATCH_NOT_UNIQUE")
        batch = batches[0]
        if batch.get("mission_id") != snapshot.mission_id:
            raise ContractError("DECOMPOSITION_RELEASE_BATCH_MISSION_MISMATCH")

        seen = set()
        for obligation in snapshot.obligations:
            if obligation.obligation_id in seen:
                raise ContractError("DECOMPOSITION_DUPLICATE_OBLIGATION")
            seen.add(obligation.obligation_id)
            rows = self.truth.query("rc72_test_obligation", obligation_id=obligation.obligation_id)
            if len(rows) != 1:
                raise ContractError("DECOMPOSITION_OBLIGATION_NOT_CANONICAL:%s" % obligation.obligation_id)
            stored = rows[0]
            if stored.get("mission_id") != snapshot.mission_id:
                raise ContractError("DECOMPOSITION_OBLIGATION_MISSION_MISMATCH")
            if stored.get("release_batch_id") != snapshot.release_batch_id:
                raise ContractError("DECOMPOSITION_OBLIGATION_BATCH_MISMATCH")
            if stored.get("requirement_id") != obligation.requirement_id or stored.get("sst_id") != obligation.sst_id:
                raise ContractError("DECOMPOSITION_OBLIGATION_LINEAGE_MISMATCH")


install_rc72_decomposition_truth_overlay()
