"""Canonical RC6 domain contracts for durable testing truth.

Wave 2 rule: one artifact payload is one domain entity. Batch-shaped payloads are
migration input only and are never accepted by the live append path.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


class DomainValidationError(ValueError):
    pass


LAYERS = {f"L{i}" for i in range(1, 8)}
CASE_STATUSES = {"CANDIDATE", "TEST_READY", "FROZEN", "QUARANTINED"}


def _require_str(payload: Dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"MISSING_OR_INVALID_{field.upper()}")
    return value.strip()


def _optional_str(payload: Dict[str, Any], field: str) -> None:
    value = payload.get(field)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise DomainValidationError(f"INVALID_{field.upper()}")


def _require_list(payload: Dict[str, Any], field: str, *, nonempty: bool = False) -> list:
    value = payload.get(field)
    if not isinstance(value, list):
        raise DomainValidationError(f"MISSING_OR_INVALID_{field.upper()}")
    if nonempty and not value:
        raise DomainValidationError(f"EMPTY_{field.upper()}")
    return value


def _reject_batch_shape(payload: Dict[str, Any]) -> None:
    for field in ("intents", "conditions", "cases"):
        if field in payload:
            raise DomainValidationError("BATCH_SHAPED_ARTIFACT_FORBIDDEN")


def _artifact_version(payload: Dict[str, Any]) -> int:
    value = payload.get("artifact_version", 1)
    if not isinstance(value, int) or value < 1:
        raise DomainValidationError("INVALID_ARTIFACT_VERSION")
    return value


def validate_test_intent(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    _reject_batch_shape(payload)
    out = deepcopy(payload)
    out["id"] = _require_str(out, "id")
    out["release_id"] = _require_str(out, "release_id")
    out["requirement_id"] = _require_str(out, "requirement_id")
    out["objective"] = _require_str(out, "objective")
    _optional_str(out, "sst_id")
    refs = _require_list(out, "source_refs", nonempty=True)
    if not all(isinstance(x, str) and x.strip() for x in refs):
        raise DomainValidationError("INVALID_SOURCE_REFS")
    out["artifact_version"] = _artifact_version(out)
    out["artifact_type"] = "test_intent"
    return out


def validate_test_condition(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    _reject_batch_shape(payload)
    out = deepcopy(payload)
    out["id"] = _require_str(out, "id")
    out["release_id"] = _require_str(out, "release_id")
    out["requirement_id"] = _require_str(out, "requirement_id")
    out["intent_id"] = _require_str(out, "intent_id")
    out["condition"] = _require_str(out, "condition")
    out["risk"] = _require_str(out, "risk").upper()
    _optional_str(out, "sst_id")
    refs = _require_list(out, "source_refs", nonempty=True)
    if not all(isinstance(x, str) and x.strip() for x in refs):
        raise DomainValidationError("INVALID_SOURCE_REFS")
    out["artifact_version"] = _artifact_version(out)
    out["artifact_type"] = "test_condition"
    return out


def validate_test_case(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    _reject_batch_shape(payload)
    out = deepcopy(payload)
    out["tc_id"] = _require_str(out, "tc_id")
    version = out.get("case_version")
    if not isinstance(version, int) or version < 1:
        raise DomainValidationError("INVALID_CASE_VERSION")
    out["release_id"] = _require_str(out, "release_id")
    out["requirement_id"] = _require_str(out, "requirement_id")
    out["condition_id"] = _require_str(out, "condition_id")
    out["objective"] = _require_str(out, "objective")
    _optional_str(out, "sst_id")
    layer = _require_str(out, "layer").upper()
    if layer not in LAYERS:
        raise DomainValidationError("INVALID_OR_MIXED_CASE_LAYER")
    out["layer"] = layer
    out["preconditions"] = _require_list(out, "preconditions")
    if "test_data" not in out:
        raise DomainValidationError("MISSING_TEST_DATA")
    out["steps"] = _require_list(out, "steps", nonempty=True)
    out["expected"] = _require_str(out, "expected")
    if "oracle" not in out or out["oracle"] in (None, "", [], {}):
        raise DomainValidationError("MISSING_ORACLE")
    out["evidence_requirements"] = _require_list(out, "evidence_requirements", nonempty=True)
    status = str(out.get("status", "CANDIDATE")).upper()
    if status not in CASE_STATUSES:
        raise DomainValidationError("INVALID_CASE_STATUS")
    out["status"] = status
    out["artifact_type"] = "test_case"
    return out


VALIDATORS = {
    "test_intent": validate_test_intent,
    "test_condition": validate_test_condition,
    "test_case": validate_test_case,
}


def validate_artifact(artifact_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        validator = VALIDATORS[artifact_type]
    except KeyError as exc:
        raise DomainValidationError("UNSUPPORTED_ARTIFACT_TYPE") from exc
    return validator(payload)
