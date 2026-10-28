"""R1 persistence adapter for RC7.2 Autonomous Test Runtime entities.

This module deliberately extends the inherited RC6/RC7 append/replay/projection
registries.  It does not create a shadow database or session-local truth store.
"""
from __future__ import annotations

from copy import deepcopy
from enum import Enum
from typing import Any, Dict, Tuple, Type

from dataclasses import asdict
from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth

from .rc72_domain import (
    BackEdge,
    ExecutionTaskUnit,
    MissionNodeRecord,
    NodeDelivery,
    NodeGate,
    ReleaseBatch,
    TestObligation,
)
from .truth_overlay import install_rc7_truth_overlay


RC72_EVENT_TYPES = {
    "RC72_RELEASE_BATCH_UPSERTED": ("rc72_release_batch", "release_batch_id"),
    "RC72_MISSION_NODE_UPSERTED": ("rc72_mission_node", "mission_node_id"),
    "RC72_NODE_DELIVERY_UPSERTED": ("rc72_node_delivery", "delivery_id"),
    "RC72_NODE_GATE_UPSERTED": ("rc72_node_gate", "gate_id"),
    "RC72_TEST_OBLIGATION_UPSERTED": ("rc72_test_obligation", "obligation_id"),
    "RC72_ETU_UPSERTED": ("rc72_etu", "etu_id"),
    "RC72_BACK_EDGE_UPSERTED": ("rc72_back_edge", "back_edge_id"),
}

RC72_BUCKETS = {
    "rc72_release_batch": "rc72_release_batches",
    "rc72_mission_node": "rc72_mission_nodes",
    "rc72_node_delivery": "rc72_node_deliveries",
    "rc72_node_gate": "rc72_node_gates",
    "rc72_test_obligation": "rc72_test_obligations",
    "rc72_etu": "rc72_execution_task_units",
    "rc72_back_edge": "rc72_back_edges",
}

_MODEL_EVENT: Dict[Type[Any], str] = {
    ReleaseBatch: "RC72_RELEASE_BATCH_UPSERTED",
    MissionNodeRecord: "RC72_MISSION_NODE_UPSERTED",
    NodeDelivery: "RC72_NODE_DELIVERY_UPSERTED",
    NodeGate: "RC72_NODE_GATE_UPSERTED",
    TestObligation: "RC72_TEST_OBLIGATION_UPSERTED",
    ExecutionTaskUnit: "RC72_ETU_UPSERTED",
    BackEdge: "RC72_BACK_EDGE_UPSERTED",
}


def _json_payload(entity: Any) -> Dict[str, Any]:
    data = asdict(entity)
    for key, value in list(data.items()):
        if isinstance(value, Enum):
            data[key] = value.value
    return data


def _base(payload: Dict[str, Any], artifact_type: str, identity: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = deepcopy(payload)
    out[identity] = _contracts._require_str(out, identity)
    out["mission_id"] = _contracts._require_str(out, "mission_id")
    out["release_id"] = _contracts._require_str(out, "release_id")
    out["artifact_version"] = _contracts._artifact_version(out)
    out["artifact_type"] = artifact_type
    return out


def _list(out: Dict[str, Any], field: str, *, required: bool = False) -> None:
    value = out.get(field, [])
    if isinstance(value, tuple):
        value = list(value)
        out[field] = value
    _contracts._require_string_list(out, field)
    if required and not value:
        raise _contracts.DomainValidationError("%s_REQUIRED" % field.upper())


def _required_fields(out: Dict[str, Any], fields: Tuple[str, ...]) -> None:
    for field in fields:
        out[field] = _contracts._require_str(out, field)


def validate_release_batch(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc72_release_batch", "release_batch_id")
    _required_fields(out, ("name", "state", "readiness"))
    for field in ("version_ids", "application_ids", "requirement_ids"):
        _list(out, field)
    planned = out.get("planned_release_time")
    if planned is not None and (not isinstance(planned, str) or not planned.strip()):
        raise _contracts.DomainValidationError("PLANNED_RELEASE_TIME_INVALID")
    return out


def validate_mission_node(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc72_mission_node", "mission_node_id")
    _required_fields(out, ("node", "state"))
    for field in ("delivery_refs", "gate_refs", "open_gap_refs"):
        _list(out, field)
    revision = out.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise _contracts.DomainValidationError("MISSION_NODE_REVISION_INVALID")
    return out


def validate_node_delivery(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc72_node_delivery", "delivery_id")
    _required_fields(out, ("node", "producer_ref"))
    version = out.get("version")
    if not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("NODE_DELIVERY_VERSION_INVALID")
    for field in ("input_refs", "artifact_refs", "evidence_refs", "gap_refs"):
        _list(out, field)
    score = out.get("sufficiency_score")
    if score is not None and (not isinstance(score, (int, float)) or not 0.0 <= float(score) <= 1.0):
        raise _contracts.DomainValidationError("NODE_DELIVERY_SUFFICIENCY_SCORE_INVALID")
    return out


def validate_node_gate(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc72_node_gate", "gate_id")
    _required_fields(out, ("node", "delivery_id", "decision", "evaluator_ref"))
    _list(out, "criteria", required=True)
    for field in ("passed", "failed", "evidence_refs"):
        _list(out, field)
    decision = out["decision"].upper()
    out["decision"] = decision
    if decision == "PASS" and out["failed"]:
        raise _contracts.DomainValidationError("NODE_GATE_PASS_CANNOT_HAVE_FAILED_CRITERIA")
    if decision == "NEEDS_REVISION" and not isinstance(out.get("return_node"), str):
        raise _contracts.DomainValidationError("NODE_GATE_REVISION_REQUIRES_RETURN_NODE")
    return out


def validate_test_obligation(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc72_test_obligation", "obligation_id")
    _required_fields(
        out,
        (
            "release_batch_id", "requirement_id", "sst_id", "application_id",
            "business_scenario", "business_rule", "risk_level", "test_level", "status",
        ),
    )
    for field in ("code_slice_refs", "change_refs", "coverage_targets"):
        _list(out, field)
    _list(out, "oracle_refs", required=True)
    # Coverage is deliberately optional; ReleaseBatch/Requirement/SST lineage is not.
    return out


def validate_etu(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc72_etu", "etu_id")
    _required_fields(
        out,
        (
            "release_batch_id", "obligation_id", "primary_goal", "primary_code_slice",
            "test_level", "primary_oracle", "data_domain", "state",
        ),
    )
    _list(out, "case_ids", required=True)
    if len(out["case_ids"]) > 8:
        raise _contracts.DomainValidationError("ETU_CASE_COUNT_EXCEEDS_DEFAULT_MAX")
    _list(out, "required_capabilities")
    duration = out.get("estimated_duration_minutes")
    if not isinstance(duration, int) or duration <= 0:
        raise _contracts.DomainValidationError("ETU_ESTIMATED_DURATION_INVALID")
    cost = out.get("estimated_cost")
    if not isinstance(cost, (int, float)) or float(cost) < 0:
        raise _contracts.DomainValidationError("ETU_ESTIMATED_COST_INVALID")
    return out


def validate_back_edge(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc72_back_edge", "back_edge_id")
    _required_fields(out, ("gap_id", "from_node", "to_node", "reason"))
    _list(out, "invalidated_refs")
    if out["from_node"] == out["to_node"]:
        raise _contracts.DomainValidationError("BACK_EDGE_SELF_ROUTE_FORBIDDEN")
    return out


RC72_VALIDATORS = {
    "rc72_release_batch": validate_release_batch,
    "rc72_mission_node": validate_mission_node,
    "rc72_node_delivery": validate_node_delivery,
    "rc72_node_gate": validate_node_gate,
    "rc72_test_obligation": validate_test_obligation,
    "rc72_etu": validate_etu,
    "rc72_back_edge": validate_back_edge,
}


def install_rc72_truth_overlay() -> None:
    install_rc7_truth_overlay()
    _contracts.VALIDATORS.update(RC72_VALIDATORS)
    _truth.EVENT_TYPES.update(RC72_EVENT_TYPES)
    _truth.BUCKETS.update(RC72_BUCKETS)
    _truth.IDENTITY_FIELDS.update(
        {artifact_type: identity for _, (artifact_type, identity) in RC72_EVENT_TYPES.items()}
    )


def append_rc72_entity(
    truth_runtime: _truth.TruthRuntime,
    entity: Any,
    *,
    release_id: str,
    artifact_version: int = 1,
):
    """Append an RC7.2 canonical entity into the inherited R1 event stream."""
    install_rc72_truth_overlay()
    event_type = _MODEL_EVENT.get(type(entity))
    if event_type is None:
        raise TypeError("UNSUPPORTED_RC72_ENTITY")
    if not isinstance(release_id, str) or not release_id.strip():
        raise ValueError("RELEASE_ID_REQUIRED")
    if not isinstance(artifact_version, int) or artifact_version < 1:
        raise ValueError("ARTIFACT_VERSION_INVALID")
    payload = _json_payload(entity)
    payload["release_id"] = release_id.strip()
    payload["artifact_version"] = artifact_version
    return truth_runtime.append_atomic(event_type, payload)


install_rc72_truth_overlay()
