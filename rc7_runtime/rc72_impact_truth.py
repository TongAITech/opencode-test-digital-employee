"""Canonical R1 persistence for RC7.2 ImpactSet.

Kept as a focused adapter so Phase 1 can add the frozen ImpactSet object without
creating a second truth store or coupling stale-propagation behavior into the
legacy RC7 state machine.
"""
from __future__ import annotations

from dataclasses import asdict
from enum import Enum
from typing import Any, Dict

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth

from .rc72_impact import ImpactSet
from .rc72_truth import install_rc72_truth_overlay


EVENT_TYPE = "RC72_IMPACT_SET_UPSERTED"
ARTIFACT_TYPE = "rc72_impact_set"
BUCKET = "rc72_impact_sets"
IDENTITY = "impact_set_id"


def _list(out: Dict[str, Any], field: str, *, required: bool = False) -> None:
    value = out.get(field, [])
    _contracts._require_string_list(out, field)
    if required and not value:
        raise _contracts.DomainValidationError("%s_REQUIRED" % field.upper())


def validate_impact_set(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for field in (
        "impact_set_id", "mission_id", "release_id", "source_mission_node_id",
        "source_node_type", "source_delivery_id", "strategy", "reason",
    ):
        out[field] = _contracts._require_str(out, field)
    out["artifact_version"] = _contracts._artifact_version(out)
    out["artifact_type"] = ARTIFACT_TYPE
    _list(out, "changed_refs", required=True)
    for field in (
        "affected_refs", "stale_mission_node_ids", "stale_obligation_ids", "stale_etu_ids",
    ):
        _list(out, field)
    if not (
        out["affected_refs"]
        or out["stale_mission_node_ids"]
        or out["stale_obligation_ids"]
        or out["stale_etu_ids"]
    ):
        raise _contracts.DomainValidationError("IMPACT_SET_MUST_RECORD_AFFECTED_ASSET")
    if out["strategy"] not in {"EXPLICIT_DEPENDENCY", "SAFE_FALLBACK"}:
        raise _contracts.DomainValidationError("IMPACT_STRATEGY_INVALID")
    return out


def install_rc72_impact_truth_overlay() -> None:
    install_rc72_truth_overlay()
    _contracts.VALIDATORS[ARTIFACT_TYPE] = validate_impact_set
    _truth.EVENT_TYPES[EVENT_TYPE] = (ARTIFACT_TYPE, IDENTITY)
    _truth.BUCKETS[ARTIFACT_TYPE] = BUCKET
    _truth.IDENTITY_FIELDS[ARTIFACT_TYPE] = IDENTITY


def _assert_exactly_one(truth: _truth.TruthRuntime, artifact_type: str, **filters: Any) -> Dict[str, Any]:
    rows = truth.query(artifact_type, **filters)
    if len(rows) != 1:
        details = ",".join("%s=%s" % (key, value) for key, value in sorted(filters.items()))
        raise _contracts.DomainValidationError(
            "IMPACT_LINEAGE_PARENT_NOT_UNIQUE:%s:%s:%s" % (artifact_type, details, len(rows))
        )
    return rows[0]


def append_impact_set(
    truth: _truth.TruthRuntime,
    impact: ImpactSet,
    *,
    release_id: str,
    artifact_version: int = 1,
):
    """Validate lineage and append ImpactSet to the inherited canonical R1."""
    install_rc72_impact_truth_overlay()
    if not isinstance(impact, ImpactSet):
        raise TypeError("IMPACT_SET_REQUIRED")
    source_node = _assert_exactly_one(
        truth,
        "rc72_mission_node",
        mission_node_id=impact.source_mission_node_id,
    )
    if source_node.get("mission_id") != impact.mission_id:
        raise _contracts.DomainValidationError("IMPACT_SOURCE_NODE_MISSION_MISMATCH")
    if source_node.get("node_type") != impact.source_node_type.value:
        raise _contracts.DomainValidationError("IMPACT_SOURCE_NODE_TYPE_MISMATCH")
    source_delivery = _assert_exactly_one(
        truth,
        "rc72_node_delivery",
        delivery_id=impact.source_delivery_id,
    )
    if source_delivery.get("mission_id") != impact.mission_id:
        raise _contracts.DomainValidationError("IMPACT_SOURCE_DELIVERY_MISSION_MISMATCH")
    if source_delivery.get("mission_node_id") != impact.source_mission_node_id:
        raise _contracts.DomainValidationError("IMPACT_SOURCE_DELIVERY_NODE_MISMATCH")

    for node_id in impact.stale_mission_node_ids:
        row = _assert_exactly_one(truth, "rc72_mission_node", mission_node_id=node_id)
        if row.get("mission_id") != impact.mission_id:
            raise _contracts.DomainValidationError("IMPACT_STALE_NODE_MISSION_MISMATCH")
    for obligation_id in impact.stale_obligation_ids:
        row = _assert_exactly_one(truth, "rc72_test_obligation", obligation_id=obligation_id)
        if row.get("mission_id") != impact.mission_id:
            raise _contracts.DomainValidationError("IMPACT_STALE_OBLIGATION_MISSION_MISMATCH")
    for etu_id in impact.stale_etu_ids:
        row = _assert_exactly_one(truth, "rc72_etu", etu_id=etu_id)
        if row.get("mission_id") != impact.mission_id:
            raise _contracts.DomainValidationError("IMPACT_STALE_ETU_MISSION_MISMATCH")

    payload = asdict(impact)
    for key, value in list(payload.items()):
        if isinstance(value, Enum):
            payload[key] = value.value
    payload["release_id"] = release_id
    payload["artifact_version"] = artifact_version
    return truth.append_atomic(EVENT_TYPE, payload)


install_rc72_impact_truth_overlay()
