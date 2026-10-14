"""RC6 Execution Closure Overlay registration for canonical R1 truth.

This intentionally extends, rather than replaces, the frozen Wave 2/12 truth
runtime. The underlying JSONL Event Stream, replay semantics and projection
remain unchanged; only new canonical artifact/event types are registered.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from . import contracts as _contracts
from . import truth as _truth


EXECUTION_CLOSURE_EVENT_TYPES = {
    "EXECUTABLE_TEST_SPEC_UPSERTED": ("executable_test_spec", "spec_id"),
    "AUTOMATION_MAPPING_UPSERTED": ("automation_mapping", "mapping_id"),
    "SCRIPT_ARTIFACT_UPSERTED": ("script_artifact", "script_id"),
    "SCRIPT_VALIDATION_UPSERTED": ("script_validation", "validation_id"),
    "FAILURE_DIAGNOSIS_UPSERTED": ("failure_diagnosis", "diagnosis_id"),
    "ROOT_CAUSE_CANDIDATE_UPSERTED": ("root_cause_candidate", "candidate_id"),
    "RECOVERY_DECISION_UPSERTED": ("recovery_decision", "decision_id"),
    "RECOVERY_ACTION_UPSERTED": ("recovery_action", "recovery_action_id"),
    "EXECUTION_CONVERGENCE_UPSERTED": ("execution_convergence", "convergence_id"),
}

EXECUTION_CLOSURE_BUCKETS = {
    "executable_test_spec": "executable_test_specs",
    "automation_mapping": "automation_mappings",
    "script_artifact": "script_artifacts",
    "script_validation": "script_validations",
    "failure_diagnosis": "failure_diagnoses",
    "root_cause_candidate": "root_cause_candidates",
    "recovery_decision": "recovery_decisions",
    "recovery_action": "recovery_actions",
    "execution_convergence": "execution_convergences",
}


def _base(payload: Dict[str, Any], artifact_type: str, identity: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = deepcopy(payload)
    out[identity] = _contracts._require_str(out, identity)
    out["release_id"] = _contracts._require_str(out, "release_id")
    out["artifact_version"] = _contracts._artifact_version(out)
    out["artifact_type"] = artifact_type
    return out


def _string_sequence(out: Dict[str, Any], field: str, *, nonempty: bool = False) -> list:
    """Normalize runtime tuples to canonical JSON-array lists before R1 write.

    Runtime contracts intentionally use immutable tuples. R1 canonical payloads
    are JSON objects, so tuple values are accepted only at this overlay boundary
    and normalized to lists before the frozen Wave2 validator sees them.
    """
    value = out.get(field)
    if isinstance(value, tuple):
        out[field] = list(value)
    return _contracts._require_string_list(out, field, nonempty=nonempty)


def _dict_sequence(out: Dict[str, Any], field: str, *, nonempty: bool = False) -> list:
    value = out.get(field)
    if isinstance(value, tuple):
        out[field] = [deepcopy(item) for item in value]
    values = _contracts._require_list(out, field, nonempty=nonempty)
    if not all(isinstance(item, dict) for item in values):
        raise _contracts.DomainValidationError("INVALID_%s" % field.upper())
    return values


def _case_link(out: Dict[str, Any]) -> None:
    out["requirement_id"] = _contracts._require_str(out, "requirement_id")
    out["tc_id"] = _contracts._require_str(out, "tc_id")
    version = out.get("case_version")
    if not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("INVALID_CASE_VERSION")
    layer = _contracts._require_str(out, "layer").upper()
    if layer not in _contracts.LAYERS:
        raise _contracts.DomainValidationError("INVALID_EXECUTION_LAYER")
    out["layer"] = layer


def validate_executable_test_spec(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "executable_test_spec", "spec_id")
    _case_link(out)
    _contracts._optional_str(out, "sst_id")
    out["case_fingerprint"] = _contracts._require_str(out, "case_fingerprint")
    out["oracle_fingerprint"] = _contracts._require_str(out, "oracle_fingerprint")
    _string_sequence(out, "target_requirements", nonempty=True)
    _dict_sequence(out, "preconditions")
    _string_sequence(out, "test_data_refs")
    _dict_sequence(out, "ordered_actions", nonempty=True)
    _string_sequence(out, "oracle_refs", nonempty=True)
    _string_sequence(out, "evidence_requirements", nonempty=True)
    if not isinstance(out.get("cleanup_policy"), dict):
        raise _contracts.DomainValidationError("INVALID_CLEANUP_POLICY")
    out["runner_type"] = _contracts._require_str(out, "runner_type").upper()
    if not isinstance(out.get("automation_mapping"), dict):
        raise _contracts.DomainValidationError("INVALID_AUTOMATION_MAPPING")
    if str(out.get("status", "")).upper() != "EXECUTABLE_SPEC":
        raise _contracts.DomainValidationError("INVALID_EXECUTABLE_SPEC_STATUS")
    out["status"] = "EXECUTABLE_SPEC"
    return out


def validate_automation_mapping(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "automation_mapping", "mapping_id")
    _case_link(out)
    out["spec_id"] = _contracts._require_str(out, "spec_id")
    if not isinstance(out.get("reuse"), dict):
        raise _contracts.DomainValidationError("INVALID_AUTOMATION_REUSE_MAPPING")
    _string_sequence(out, "evidence_refs")
    return out


def validate_script_artifact(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "script_artifact", "script_id")
    _case_link(out)
    out["spec_id"] = _contracts._require_str(out, "spec_id")
    out["runner_type"] = _contracts._require_str(out, "runner_type").upper()
    out["source_ref"] = _contracts._require_str(out, "source_ref")
    out["test_symbol"] = _contracts._require_str(out, "test_symbol")
    out["case_fingerprint"] = _contracts._require_str(out, "case_fingerprint")
    out["oracle_fingerprint"] = _contracts._require_str(out, "oracle_fingerprint")
    _string_sequence(out, "reuse_refs")
    _string_sequence(out, "builder_evidence_refs", nonempty=True)
    revision = out.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise _contracts.DomainValidationError("INVALID_SCRIPT_REVISION")
    status = _contracts._require_str(out, "status").upper()
    if status not in {"SCRIPT_GENERATED", "SCRIPT_REPAIRED"}:
        raise _contracts.DomainValidationError("INVALID_SCRIPT_STATUS")
    out["status"] = status
    return out


def validate_script_validation(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "script_validation", "validation_id")
    out["script_id"] = _contracts._require_str(out, "script_id")
    out["runner_type"] = _contracts._require_str(out, "runner_type").upper()
    out["test_symbol"] = _contracts._require_str(out, "test_symbol")
    _dict_sequence(out, "steps", nonempty=True)
    _string_sequence(out, "evidence_refs", nonempty=True)
    status = _contracts._require_str(out, "status").upper()
    if status not in {"SCRIPT_READY", "SCRIPT_INVALID"}:
        raise _contracts.DomainValidationError("INVALID_SCRIPT_VALIDATION_STATUS")
    out["status"] = status
    return out


def validate_failure_diagnosis(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "failure_diagnosis", "diagnosis_id")
    out["attempt_id"] = _contracts._require_str(out, "attempt_id")
    out["failure_class"] = _contracts._require_str(out, "failure_class").upper()
    _string_sequence(out, "evidence_refs", nonempty=True)
    out["classifier_ref"] = _contracts._require_str(out, "classifier_ref")
    out["rationale"] = _contracts._require_str(out, "rationale")
    out["failure_signature_id"] = _contracts._require_str(out, "failure_signature_id")
    _contracts._optional_str(out, "root_cause_candidate_id")
    return out


def validate_root_cause_candidate(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "root_cause_candidate", "candidate_id")
    out["attempt_id"] = _contracts._require_str(out, "attempt_id")
    out["symbol"] = _contracts._require_str(out, "symbol")
    _string_sequence(out, "call_path", nonempty=True)
    _string_sequence(out, "git_change_refs", nonempty=True)
    _string_sequence(out, "requirement_refs", nonempty=True)
    _string_sequence(out, "evidence_refs", nonempty=True)
    confidence = out.get("confidence")
    if not isinstance(confidence, (int, float)) or float(confidence) < 0 or float(confidence) > 1:
        raise _contracts.DomainValidationError("INVALID_RCA_CONFIDENCE")
    out["confidence"] = float(confidence)
    return out


def validate_recovery_decision(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "recovery_decision", "decision_id")
    out["diagnosis_id"] = _contracts._require_str(out, "diagnosis_id")
    out["attempt_id"] = _contracts._require_str(out, "attempt_id")
    out["action"] = _contracts._require_str(out, "action")
    _contracts._require_bool(out, "terminal")
    _contracts._optional_str(out, "next_attempt_id")
    return out


def validate_recovery_action(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "recovery_action", "recovery_action_id")
    out["action"] = _contracts._require_str(out, "action")
    out["prior_attempt_id"] = _contracts._require_str(out, "prior_attempt_id")
    _contracts._optional_str(out, "next_attempt_id")
    out["status"] = _contracts._require_str(out, "status").upper()
    _string_sequence(out, "evidence_refs", nonempty=True)
    _string_sequence(out, "output_refs")
    out["verified"] = _contracts._require_bool(out, "verified")
    _contracts._optional_str(out, "terminal_status")
    return out


def validate_execution_convergence(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, "execution_convergence", "convergence_id")
    out["attempt_id"] = _contracts._require_str(out, "attempt_id")
    out["status"] = _contracts._require_str(out, "status").upper()
    if out["status"] not in {
        "PASS", "PRODUCT_DEFECT_CONFIRMED", "MANUAL_REQUIRED", "BLOCKED_EXTERNAL",
        "RETRY_BUDGET_EXHAUSTED", "UNKNOWN_ROOT_CAUSE", "RECOVERY_ALLOWED",
    }:
        raise _contracts.DomainValidationError("INVALID_CONVERGENCE_STATUS")
    out["reason"] = _contracts._require_str(out, "reason")
    _string_sequence(out, "evidence_refs")
    return out


EXECUTION_CLOSURE_VALIDATORS = {
    "executable_test_spec": validate_executable_test_spec,
    "automation_mapping": validate_automation_mapping,
    "script_artifact": validate_script_artifact,
    "script_validation": validate_script_validation,
    "failure_diagnosis": validate_failure_diagnosis,
    "root_cause_candidate": validate_root_cause_candidate,
    "recovery_decision": validate_recovery_decision,
    "recovery_action": validate_recovery_action,
    "execution_convergence": validate_execution_convergence,
}


def install_execution_closure_overlay() -> None:
    _contracts.VALIDATORS.update(EXECUTION_CLOSURE_VALIDATORS)
    _truth.EVENT_TYPES.update(EXECUTION_CLOSURE_EVENT_TYPES)
    _truth.BUCKETS.update(EXECUTION_CLOSURE_BUCKETS)
    _truth.IDENTITY_FIELDS.update({artifact: identity for _, (artifact, identity) in EXECUTION_CLOSURE_EVENT_TYPES.items()})


# Importing the overlay is explicit opt-in; rc6_runtime.__init__ and MCP install it.
install_execution_closure_overlay()
