"""RC7 control-plane overlay for the inherited R1 Event Stream.

RC7 does not create a shadow state database. Canonical Mission/Task/Artifact/
Evidence/Gap/Evaluation/Event records, plus the Defect lifecycle projection,
are registered as additional atomic R1 artifact types and therefore use the
same append/replay/projection mechanism as RC6 business truth.

Acceptance authority is enforced twice: by in-memory state machines and by
this durable R1 boundary. Direct object construction therefore cannot bypass
independent Evaluation for PASS/RESOLVED/CONVERGED/CLOSED truth.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Tuple, Type

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth

from .defect_loop import DefectRecord
from .models import Artifact, Evaluation, EventRecord, Evidence, Gap, Mission, Task, to_payload


RC7_EVENT_TYPES = {
    "RC7_MISSION_UPSERTED": ("rc7_mission", "mission_id"),
    "RC7_TASK_UPSERTED": ("rc7_task", "task_id"),
    "RC7_ARTIFACT_UPSERTED": ("rc7_artifact", "artifact_id"),
    "RC7_EVIDENCE_UPSERTED": ("rc7_evidence", "evidence_id"),
    "RC7_GAP_UPSERTED": ("rc7_gap", "gap_id"),
    "RC7_EVALUATION_UPSERTED": ("rc7_evaluation", "evaluation_id"),
    "RC7_CONTROL_EVENT_UPSERTED": ("rc7_control_event", "event_id"),
    "RC7_DEFECT_UPSERTED": ("rc7_defect", "defect_id"),
}

RC7_BUCKETS = {
    "rc7_mission": "rc7_missions",
    "rc7_task": "rc7_tasks",
    "rc7_artifact": "rc7_artifacts",
    "rc7_evidence": "rc7_evidence_records",
    "rc7_gap": "rc7_gaps",
    "rc7_evaluation": "rc7_evaluations",
    "rc7_control_event": "rc7_control_events",
    "rc7_defect": "rc7_defects",
}


_MODEL_EVENT: Dict[Type[Any], str] = {
    Mission: "RC7_MISSION_UPSERTED",
    Task: "RC7_TASK_UPSERTED",
    Artifact: "RC7_ARTIFACT_UPSERTED",
    Evidence: "RC7_EVIDENCE_UPSERTED",
    Gap: "RC7_GAP_UPSERTED",
    Evaluation: "RC7_EVALUATION_UPSERTED",
    EventRecord: "RC7_CONTROL_EVENT_UPSERTED",
    DefectRecord: "RC7_DEFECT_UPSERTED",
}


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


def _list_of_strings(out: Dict[str, Any], field: str) -> None:
    value = out.get(field, [])
    if isinstance(value, tuple):
        out[field] = list(value)
    _contracts._require_string_list(out, field)


def _optional_nonempty_str(out: Dict[str, Any], field: str) -> None:
    value = out.get(field)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise _contracts.DomainValidationError("INVALID_%s" % field.upper())


def validate_rc7_mission(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc7_mission", "mission_id")
    out["goal"] = _contracts._require_str(out, "goal")
    out["state"] = _contracts._require_str(out, "state").upper()
    out["sufficiency_state"] = _contracts._require_str(out, "sufficiency_state").upper()
    revision = out.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise _contracts.DomainValidationError("INVALID_MISSION_REVISION")
    for field in ("artifact_refs", "open_gap_ids", "active_task_ids", "residual_risk_ids"):
        _list_of_strings(out, field)
    _optional_nonempty_str(out, "latest_evaluation_id")
    if out["state"] == "CONVERGED":
        if out["sufficiency_state"] != "SUFFICIENT":
            raise _contracts.DomainValidationError("CONVERGED_MISSION_REQUIRES_SUFFICIENT_STATE")
        if not isinstance(out.get("latest_evaluation_id"), str) or not out["latest_evaluation_id"].strip():
            raise _contracts.DomainValidationError("CONVERGED_MISSION_REQUIRES_EVALUATION")
        if out["open_gap_ids"]:
            raise _contracts.DomainValidationError("CONVERGED_MISSION_CANNOT_HAVE_OPEN_GAPS")
    return out


def validate_rc7_task(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc7_task", "task_id")
    for field in ("node", "task_type", "objective", "state"):
        out[field] = _contracts._require_str(out, field)
    out["state"] = out["state"].upper()
    for field in (
        "required_capabilities", "input_artifact_refs", "gap_refs",
        "acceptance_criteria", "output_artifact_refs",
    ):
        _list_of_strings(out, field)
    _optional_nonempty_str(out, "evaluation_id")
    if out["state"] == "PASS":
        if not isinstance(out.get("evaluation_id"), str) or not out["evaluation_id"].strip():
            raise _contracts.DomainValidationError("TASK_PASS_REQUIRES_EVALUATION")
    return out


def validate_rc7_artifact(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc7_artifact", "artifact_id")
    for field in ("artifact_type_name", "producer_task_id", "content_ref", "state"):
        out[field] = _contracts._require_str(out, field)
    version = out.get("version")
    if not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("INVALID_RC7_ARTIFACT_VERSION")
    for field in ("parent_refs", "evidence_refs"):
        _list_of_strings(out, field)
    return out


def validate_rc7_evidence(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc7_evidence", "evidence_id")
    for field in ("kind", "source_ref", "content_ref"):
        out[field] = _contracts._require_str(out, field)
    _list_of_strings(out, "subject_refs")
    return out


def validate_rc7_gap(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc7_gap", "gap_id")
    for field in ("source_node", "category", "severity", "target_node", "description", "state"):
        out[field] = _contracts._require_str(out, field)
    for field in ("subject_refs", "evidence_refs", "acceptance_criteria"):
        _list_of_strings(out, field)
    _optional_nonempty_str(out, "resolution_evaluation_id")
    if out["state"] == "RESOLVED":
        if not isinstance(out.get("resolution_evaluation_id"), str) or not out["resolution_evaluation_id"].strip():
            raise _contracts.DomainValidationError("GAP_RESOLUTION_REQUIRES_EVALUATION")
    return out


def validate_rc7_evaluation(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc7_evaluation", "evaluation_id")
    for field in ("node", "result", "evaluator_ref"):
        out[field] = _contracts._require_str(out, field)
    for field in ("artifact_refs", "gap_refs", "evidence_refs"):
        _list_of_strings(out, field)
    if not isinstance(out.get("dimensions"), dict):
        raise _contracts.DomainValidationError("INVALID_RC7_EVALUATION_DIMENSIONS")
    return out


def validate_rc7_control_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc7_control_event", "event_id")
    for field in ("event_type_name", "subject_type", "subject_id"):
        out[field] = _contracts._require_str(out, field)
    _list_of_strings(out, "refs")
    if not isinstance(out.get("data"), dict):
        raise _contracts.DomainValidationError("INVALID_RC7_CONTROL_EVENT_DATA")
    occurred_at = out.get("occurred_at")
    if not isinstance(occurred_at, int) or occurred_at < 0:
        raise _contracts.DomainValidationError("INVALID_RC7_CONTROL_EVENT_TIME")
    return out


def validate_rc7_defect(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "rc7_defect", "defect_id")
    out["source_gap_id"] = _contracts._require_str(out, "source_gap_id")
    out["severity"] = _contracts._require_str(out, "severity").upper()
    out["state"] = _contracts._require_str(out, "state").upper()
    for field in (
        "requirement_refs", "test_case_ids", "execution_attempt_ids", "evidence_refs",
        "verification_refs", "regression_refs",
    ):
        _list_of_strings(out, field)
    if not out["test_case_ids"] or not out["execution_attempt_ids"] or not out["evidence_refs"]:
        raise _contracts.DomainValidationError("DEFECT_EXECUTION_AND_EVIDENCE_TRACE_REQUIRED")
    for field in ("duplicate_of", "fix_revision", "latest_evaluation_id"):
        _optional_nonempty_str(out, field)
    attempts = out.get("reproduction_attempts")
    passes = out.get("reproduction_passes")
    if not isinstance(attempts, int) or attempts < 0 or not isinstance(passes, int) or passes < 0 or passes > attempts:
        raise _contracts.DomainValidationError("DEFECT_REPRODUCTION_COUNTER_INVALID")
    if out["state"] in {"EVIDENCE_READY", "READY_FOR_REVIEW", "CONFIRMED", "FIX_PENDING", "FIX_DETECTED", "VERIFYING", "FIXED", "REGRESSION_TESTING", "CLOSED"}:
        if not isinstance(out.get("latest_evaluation_id"), str) or not out["latest_evaluation_id"].strip():
            raise _contracts.DomainValidationError("DEFECT_ACCEPTED_STATE_REQUIRES_EVALUATION")
    if out["state"] in {"FIX_DETECTED", "VERIFYING", "FIXED", "REGRESSION_TESTING", "CLOSED"}:
        if not isinstance(out.get("fix_revision"), str) or not out["fix_revision"].strip():
            raise _contracts.DomainValidationError("DEFECT_FIX_STATE_REQUIRES_REVISION")
    if out["state"] in {"FIXED", "REGRESSION_TESTING", "CLOSED"} and not out["verification_refs"]:
        raise _contracts.DomainValidationError("DEFECT_FIXED_STATE_REQUIRES_VERIFICATION")
    if out["state"] == "CLOSED" and not out["regression_refs"]:
        raise _contracts.DomainValidationError("DEFECT_CLOSE_REQUIRES_REGRESSION")
    if out["state"] == "DUPLICATE" and not isinstance(out.get("duplicate_of"), str):
        raise _contracts.DomainValidationError("DEFECT_DUPLICATE_TARGET_REQUIRED")
    return out


RC7_VALIDATORS = {
    "rc7_mission": validate_rc7_mission,
    "rc7_task": validate_rc7_task,
    "rc7_artifact": validate_rc7_artifact,
    "rc7_evidence": validate_rc7_evidence,
    "rc7_gap": validate_rc7_gap,
    "rc7_evaluation": validate_rc7_evaluation,
    "rc7_control_event": validate_rc7_control_event,
    "rc7_defect": validate_rc7_defect,
}


def install_rc7_truth_overlay() -> None:
    _contracts.VALIDATORS.update(RC7_VALIDATORS)
    _truth.EVENT_TYPES.update(RC7_EVENT_TYPES)
    _truth.BUCKETS.update(RC7_BUCKETS)
    _truth.IDENTITY_FIELDS.update(
        {artifact_type: identity for _, (artifact_type, identity) in RC7_EVENT_TYPES.items()}
    )


def _r1_payload(entity: Any, *, release_id: str, artifact_version: int = 1) -> Tuple[str, Dict[str, Any]]:
    event_type = _MODEL_EVENT.get(type(entity))
    if event_type is None:
        raise TypeError("UNSUPPORTED_RC7_ENTITY")
    if not isinstance(release_id, str) or not release_id.strip():
        raise ValueError("RELEASE_ID_REQUIRED")
    if not isinstance(artifact_version, int) or artifact_version < 1:
        raise ValueError("ARTIFACT_VERSION_INVALID")

    payload = to_payload(entity)
    payload["release_id"] = release_id.strip()
    payload["artifact_version"] = artifact_version

    if isinstance(entity, Artifact):
        payload["artifact_type_name"] = payload.pop("artifact_type")
    if isinstance(entity, EventRecord):
        payload["event_type_name"] = payload.pop("event_type")
    return event_type, payload


def append_entity(
    truth_runtime: _truth.TruthRuntime,
    entity: Any,
    *,
    release_id: str,
    artifact_version: int = 1,
):
    """Append an RC7 control entity to inherited R1 truth and verify RAW."""
    install_rc7_truth_overlay()
    event_type, payload = _r1_payload(entity, release_id=release_id, artifact_version=artifact_version)
    return truth_runtime.append_atomic(event_type, payload)


install_rc7_truth_overlay()
