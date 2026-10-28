"""R1 persistence adapter for RC7.2 Autonomous Test Runtime entities.

This module deliberately extends the inherited RC6/RC7 append/replay/projection
registries. It does not create a shadow database or session-local truth store.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from enum import Enum
from typing import Any, Dict, Tuple, Type

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth

from .rc72_domain import (
    BackEdge,
    ExecutionTaskUnit,
    MissionNodeRecord,
    NodeDelivery,
    NodeGate,
    RC72_CANONICAL_NODE_ORDER,
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

_NODE_VALUES = set(RC72_CANONICAL_NODE_ORDER)
_NODE_STATES = {
    "NOT_STARTED", "READY", "RUNNING", "REVIEW_PENDING", "PASS",
    "NEEDS_REVISION", "BLOCKED", "HUMAN_GATE", "STALE",
}
_GATE_DECISIONS = {"PASS", "NEEDS_REVISION", "BLOCKED", "HUMAN_GATE"}
_BACK_EDGE_STATES = {"OPEN", "RESOLVED", "SUPERSEDED"}


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


def _optional_nonempty_str(out: Dict[str, Any], field: str) -> None:
    value = out.get(field)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise _contracts.DomainValidationError("%s_INVALID" % field.upper())


def _optional_nonnegative_int(out: Dict[str, Any], field: str) -> None:
    value = out.get(field)
    if value is not None and (not isinstance(value, int) or value < 0):
        raise _contracts.DomainValidationError("%s_INVALID" % field.upper())


def _require_node(out: Dict[str, Any], field: str) -> None:
    value = _contracts._require_str(out, field)
    if value not in _NODE_VALUES:
        raise _contracts.DomainValidationError("%s_INVALID" % field.upper())
    out[field] = value


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
    _require_node(out, "node_type")
    out["scope_ref"] = _contracts._require_str(out, "scope_ref")
    state = _contracts._require_str(out, "state").upper()
    if state not in _NODE_STATES:
        raise _contracts.DomainValidationError("MISSION_NODE_STATE_INVALID")
    out["state"] = state
    for field in ("delivery_refs", "gate_refs", "open_gap_refs"):
        _list(out, field)
    active = out.get("active_delivery_version")
    if active is not None and (not isinstance(active, int) or active < 1):
        raise _contracts.DomainValidationError("MISSION_NODE_ACTIVE_DELIVERY_VERSION_INVALID")
    _optional_nonnegative_int(out, "entered_at")
    _optional_nonnegative_int(out, "exited_at")
    _optional_nonempty_str(out, "blocked_reason")
    revision = out.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise _contracts.DomainValidationError("MISSION_NODE_REVISION_INVALID")
    return out


def validate_node_delivery(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc72_node_delivery", "delivery_id")
    out["mission_node_id"] = _contracts._require_str(out, "mission_node_id")
    _require_node(out, "node_type")
    out["producer_ref"] = _contracts._require_str(out, "producer_ref")
    version = out.get("version")
    if not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("NODE_DELIVERY_VERSION_INVALID")
    for field in (
        "input_refs", "artifact_refs", "evidence_refs", "known_gaps", "created_by_workitems",
    ):
        _list(out, field)
    score = out.get("sufficiency_score")
    if score is not None and (not isinstance(score, (int, float)) or not 0.0 <= float(score) <= 1.0):
        raise _contracts.DomainValidationError("NODE_DELIVERY_SUFFICIENCY_SCORE_INVALID")
    return out


def validate_node_gate(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc72_node_gate", "gate_id")
    _required_fields(
        out,
        ("mission_node_id", "delivery_id", "reviewer_worker_id", "reviewer_session_id"),
    )
    _require_node(out, "node_type")
    decision = _contracts._require_str(out, "decision").upper()
    if decision not in _GATE_DECISIONS:
        raise _contracts.DomainValidationError("NODE_GATE_DECISION_INVALID")
    out["decision"] = decision
    _list(out, "criteria", required=True)
    for field in ("passed", "failed", "evidence_refs"):
        _list(out, field)
    if decision == "PASS" and out["failed"]:
        raise _contracts.DomainValidationError("NODE_GATE_PASS_CANNOT_HAVE_FAILED_CRITERIA")
    if decision == "NEEDS_REVISION":
        if not isinstance(out.get("return_node"), str) or out["return_node"] not in _NODE_VALUES:
            raise _contracts.DomainValidationError("NODE_GATE_REVISION_REQUIRES_VALID_RETURN_NODE")
    elif out.get("return_node") is not None and out["return_node"] not in _NODE_VALUES:
        raise _contracts.DomainValidationError("NODE_GATE_RETURN_NODE_INVALID")
    _optional_nonempty_str(out, "reason")
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
    _required_fields(out, ("gap_id", "from_delivery_id", "reason"))
    _require_node(out, "from_node")
    _require_node(out, "return_node")
    _list(out, "invalidated_refs")
    if out["from_node"] == out["return_node"]:
        raise _contracts.DomainValidationError("BACK_EDGE_SELF_ROUTE_FORBIDDEN")
    state = _contracts._require_str(out, "state").upper()
    if state not in _BACK_EDGE_STATES:
        raise _contracts.DomainValidationError("BACK_EDGE_STATE_INVALID")
    out["state"] = state
    _optional_nonempty_str(out, "resolved_by_delivery_id")
    if state == "RESOLVED" and not out.get("resolved_by_delivery_id"):
        raise _contracts.DomainValidationError("BACK_EDGE_RESOLVED_REQUIRES_DELIVERY")
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
