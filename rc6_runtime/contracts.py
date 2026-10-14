"""Canonical RC6 domain contracts for durable testing truth.

R1 rule: one artifact payload is one domain entity. Batch-shaped payloads are
migration input only and are never accepted by the live append path. Wave 12
extends the same R1 stream to analysis/execution/evidence/defect/coverage/report
truth so Admin and reports never need a shadow business store.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


class DomainValidationError(ValueError):
    pass


LAYERS = {f"L{i}" for i in range(1, 8)}
CASE_STATUSES = {"CANDIDATE", "TEST_READY", "FROZEN", "QUARANTINED"}
EXECUTION_STATUSES = {"PASS", "FAIL", "BLOCKED", "SKIPPED", "NOT_RUN"}
DEFECT_STATUSES = {"CANDIDATE", "CONFIRMED", "REJECTED", "CLOSED", "EXTERNAL_SYNCED"}
SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


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


def _require_bool(payload: Dict[str, Any], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise DomainValidationError(f"MISSING_OR_INVALID_{field.upper()}")
    return value


def _reject_batch_shape(payload: Dict[str, Any]) -> None:
    for field in (
        "intents", "conditions", "cases", "analyses", "executions", "assertions",
        "evidence", "defects", "coverage", "reports",
    ):
        if field in payload:
            raise DomainValidationError("BATCH_SHAPED_ARTIFACT_FORBIDDEN")


def _artifact_version(payload: Dict[str, Any]) -> int:
    value = payload.get("artifact_version", 1)
    if not isinstance(value, int) or value < 1:
        raise DomainValidationError("INVALID_ARTIFACT_VERSION")
    return value


def _require_string_list(payload: Dict[str, Any], field: str, *, nonempty: bool = False) -> list:
    values = _require_list(payload, field, nonempty=nonempty)
    if not all(isinstance(x, str) and x.strip() for x in values):
        raise DomainValidationError(f"INVALID_{field.upper()}")
    return values


def _common(payload: Dict[str, Any], artifact_type: str, identity_field: str = "id") -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    _reject_batch_shape(payload)
    out = deepcopy(payload)
    out[identity_field] = _require_str(out, identity_field)
    out["release_id"] = _require_str(out, "release_id")
    out["artifact_version"] = _artifact_version(out)
    out["artifact_type"] = artifact_type
    return out


def validate_test_intent(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(payload, "test_intent")
    out["requirement_id"] = _require_str(out, "requirement_id")
    out["objective"] = _require_str(out, "objective")
    _optional_str(out, "sst_id")
    _require_string_list(out, "source_refs", nonempty=True)
    return out


def validate_test_condition(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(payload, "test_condition")
    out["requirement_id"] = _require_str(out, "requirement_id")
    out["intent_id"] = _require_str(out, "intent_id")
    out["condition"] = _require_str(out, "condition")
    out["risk"] = _require_str(out, "risk").upper()
    _optional_str(out, "sst_id")
    _require_string_list(out, "source_refs", nonempty=True)
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


def validate_requirement_analysis(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(payload, "requirement_analysis")
    out["requirement_id"] = _require_str(out, "requirement_id")
    _optional_str(out, "sst_id")
    out["br"] = _require_list(out, "br")
    out["sr"] = _require_list(out, "sr")
    out["tr"] = _require_list(out, "tr")
    _require_string_list(out, "evidence_refs", nonempty=True)
    return out


def validate_code_analysis(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(payload, "code_analysis")
    out["requirement_id"] = _require_str(out, "requirement_id")
    _require_string_list(out, "revision_refs", nonempty=True)
    _require_string_list(out, "impact_refs", nonempty=True)
    _require_string_list(out, "evidence_refs", nonempty=True)
    return out


def validate_execution_attempt(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(payload, "execution_attempt", "attempt_id")
    out["requirement_id"] = _require_str(out, "requirement_id")
    out["tc_id"] = _require_str(out, "tc_id")
    version = out.get("case_version")
    if not isinstance(version, int) or version < 1:
        raise DomainValidationError("INVALID_CASE_VERSION")
    out["target_id"] = _require_str(out, "target_id")
    layer = _require_str(out, "layer").upper()
    if layer not in LAYERS:
        raise DomainValidationError("INVALID_EXECUTION_LAYER")
    out["layer"] = layer
    status = _require_str(out, "status").upper()
    if status not in EXECUTION_STATUSES:
        raise DomainValidationError("INVALID_EXECUTION_STATUS")
    out["status"] = status
    out["tool_call_refs"] = _require_string_list(out, "tool_call_refs")
    out["evidence_refs"] = _require_string_list(out, "evidence_refs")
    if status in {"PASS", "FAIL"}:
        if not isinstance(out.get("actual_result"), dict) or not out["actual_result"]:
            raise DomainValidationError("EXECUTED_ATTEMPT_ACTUAL_RESULT_REQUIRED")
        if not out["tool_call_refs"]:
            raise DomainValidationError("EXECUTED_ATTEMPT_TOOL_CALL_REQUIRED")
        if not out["evidence_refs"]:
            raise DomainValidationError("EXECUTED_ATTEMPT_EVIDENCE_REQUIRED")
    return out


def validate_assertion(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(payload, "assertion")
    out["attempt_id"] = _require_str(out, "attempt_id")
    out["tc_id"] = _require_str(out, "tc_id")
    out["oracle_ref"] = _require_str(out, "oracle_ref")
    out["passed"] = _require_bool(out, "passed")
    _require_string_list(out, "evidence_refs", nonempty=True)
    return out


def _reject_secret_keys(value: Any, path: str = "root") -> None:
    secret_words = {"password", "passwd", "secret", "token", "credential", "authorization"}
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(word in normalized for word in secret_words):
                raise DomainValidationError("SECRET_FIELD_FORBIDDEN_IN_R1_EVIDENCE")
            _reject_secret_keys(child, path + "." + str(key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_keys(child, f"{path}[{index}]")


def validate_evidence(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(payload, "evidence")
    out["kind"] = _require_str(out, "kind")
    out["ref"] = _require_str(out, "ref")
    out["source_artifact_ref"] = _require_str(out, "source_artifact_ref")
    _optional_str(out, "requirement_id")
    _optional_str(out, "tc_id")
    _optional_str(out, "attempt_id")
    if "metadata" in out and not isinstance(out["metadata"], dict):
        raise DomainValidationError("INVALID_EVIDENCE_METADATA")
    _reject_secret_keys(out.get("metadata", {}))
    return out


def validate_defect(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(payload, "defect")
    out["requirement_id"] = _require_str(out, "requirement_id")
    out["tc_id"] = _require_str(out, "tc_id")
    out["attempt_id"] = _require_str(out, "attempt_id")
    out["title"] = _require_str(out, "title")
    severity = _require_str(out, "severity").upper()
    if severity not in SEVERITIES:
        raise DomainValidationError("INVALID_DEFECT_SEVERITY")
    out["severity"] = severity
    status = _require_str(out, "status").upper()
    if status not in DEFECT_STATUSES:
        raise DomainValidationError("INVALID_DEFECT_STATUS")
    out["status"] = status
    _require_string_list(out, "evidence_refs", nonempty=True)
    return out


def validate_coverage_observation(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(payload, "coverage_observation")
    out["target_id"] = _require_str(out, "target_id")
    out["attempt_id"] = _require_str(out, "attempt_id")
    out["tc_id"] = _require_str(out, "tc_id")
    layer = _require_str(out, "layer").upper()
    if layer not in LAYERS:
        raise DomainValidationError("INVALID_COVERAGE_LAYER")
    out["layer"] = layer
    out["subject_id"] = _require_str(out, "subject_id")
    out["dimension"] = _require_str(out, "dimension")
    out["covered"] = _require_bool(out, "covered")
    out["tool_call_ref"] = _require_str(out, "tool_call_ref")
    out["evidence_ref"] = _require_str(out, "evidence_ref")
    return out


def validate_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _common(payload, "report")
    out["mission_id"] = _require_str(out, "mission_id")
    out["status"] = _require_str(out, "status").upper()
    _require_string_list(out, "artifact_refs", nonempty=True)
    generated_at = out.get("generated_at")
    if not isinstance(generated_at, int) or generated_at < 0:
        raise DomainValidationError("INVALID_GENERATED_AT")
    return out


VALIDATORS = {
    "test_intent": validate_test_intent,
    "test_condition": validate_test_condition,
    "test_case": validate_test_case,
    "requirement_analysis": validate_requirement_analysis,
    "code_analysis": validate_code_analysis,
    "execution_attempt": validate_execution_attempt,
    "assertion": validate_assertion,
    "evidence": validate_evidence,
    "defect": validate_defect,
    "coverage_observation": validate_coverage_observation,
    "report": validate_report,
}


def validate_artifact(artifact_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        validator = VALIDATORS[artifact_type]
    except KeyError as exc:
        raise DomainValidationError("UNSUPPORTED_ARTIFACT_TYPE") from exc
    return validator(payload)
