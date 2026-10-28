"""RC7.2 Journey Compiler: CAPTURED teaching truth -> non-executable Candidate IR.

This slice deliberately stops before replay/benchmark/promotion.  A compiled
candidate preserves release/requirement/SST/obligation lineage and source-step
provenance, but remains CANDIDATE, executable=False and official=False.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_journey_teaching import JourneyActionType, JourneyRecordingState, install_rc72_journey_teaching_overlay

_CANDIDATE = "rc72_journey_candidate"
_EVENT = "RC72_JOURNEY_CANDIDATE_UPSERTED"
_BUCKET = "rc72_journey_candidates"


class JourneyCandidateState(str, Enum):
    COMPILED_CANDIDATE = "COMPILED_CANDIDATE"


@dataclass(frozen=True)
class JourneyCandidateResult:
    candidate_id: str
    state: JourneyCandidateState


def _now() -> int:
    return int(time.time())


def _required(out: Dict[str, Any], name: str) -> str:
    return _contracts._require_str(out, name)


def _optional_string(out: Dict[str, Any], name: str) -> None:
    value = out.get(name)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise _contracts.DomainValidationError("%s_INVALID" % name.upper())


def _validate_candidate(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "candidate_id", "mission_id", "release_id", "release_batch_id",
        "requirement_id", "sst_id", "obligation_id", "source_recording_id",
        "state", "asset_class", "replay_status", "benchmark_status", "review_status",
    ):
        out[name] = _required(out, name)
    out["artifact_type"] = _CANDIDATE
    out["artifact_version"] = _contracts._artifact_version(out)
    try:
        out["state"] = JourneyCandidateState(out["state"].upper()).value
    except ValueError as exc:
        raise _contracts.DomainValidationError("JOURNEY_CANDIDATE_STATE_INVALID") from exc
    if out["asset_class"] != "CANDIDATE":
        raise _contracts.DomainValidationError("JOURNEY_CANDIDATE_ASSET_CLASS_INVALID")
    if out.get("executable") is not False:
        raise _contracts.DomainValidationError("JOURNEY_CANDIDATE_MUST_NOT_BE_EXECUTABLE")
    if out.get("official") is not False:
        raise _contracts.DomainValidationError("JOURNEY_CANDIDATE_MUST_NOT_BE_OFFICIAL")
    if out["replay_status"] != "NOT_RUN" or out["benchmark_status"] != "NOT_RUN" or out["review_status"] != "NOT_REVIEWED":
        raise _contracts.DomainValidationError("JOURNEY_CANDIDATE_PREMATURE_PROMOTION_STATE")
    steps = out.get("steps")
    if not isinstance(steps, list) or not steps:
        raise _contracts.DomainValidationError("JOURNEY_CANDIDATE_STEPS_REQUIRED")
    expected_sequence = 1
    for step in steps:
        if not isinstance(step, dict):
            raise _contracts.DomainValidationError("JOURNEY_CANDIDATE_STEP_INVALID")
        for name in ("source_step_id", "action_type", "url", "page_role", "page_state_ref", "dom_ref", "wait_semantics"):
            if not isinstance(step.get(name), str) or not str(step.get(name)).strip():
                raise _contracts.DomainValidationError("JOURNEY_CANDIDATE_STEP_%s_REQUIRED" % name.upper())
        if step.get("sequence") != expected_sequence:
            raise _contracts.DomainValidationError("JOURNEY_CANDIDATE_STEP_SEQUENCE_INVALID")
        expected_sequence += 1
        _optional_string(step, "element_ref")
        _optional_string(step, "screenshot_ref")
        _optional_string(step, "value_ref")
        _optional_string(step, "credential_ref")
        _optional_string(step, "oracle_ref")
        for list_name in ("network_refs", "evidence_refs"):
            refs = step.get(list_name)
            if not isinstance(refs, list) or not all(isinstance(ref, str) and ref.strip() for ref in refs):
                raise _contracts.DomainValidationError("JOURNEY_CANDIDATE_STEP_%s_INVALID" % list_name.upper())
        action_type = str(step["action_type"]).upper()
        if action_type == JourneyActionType.INPUT.value and not (step.get("value_ref") or step.get("credential_ref")):
            raise _contracts.DomainValidationError("JOURNEY_INPUT_REFERENCE_REQUIRED")
        if action_type == JourneyActionType.ASSERT.value and not step.get("oracle_ref"):
            raise _contracts.DomainValidationError("JOURNEY_ASSERT_ORACLE_REQUIRED")
        if "capture_metadata" in step or "value" in step:
            raise _contracts.DomainValidationError("JOURNEY_CANDIDATE_PLAINTEXT_CAPTURE_FORBIDDEN")
    if not isinstance(out.get("compiled_at"), int) or out["compiled_at"] < 0:
        raise _contracts.DomainValidationError("JOURNEY_CANDIDATE_COMPILED_AT_INVALID")
    return out


def install_rc72_journey_compiler_overlay() -> None:
    install_rc72_journey_teaching_overlay()
    _contracts.VALIDATORS[_CANDIDATE] = _validate_candidate
    _truth.BUCKETS[_CANDIDATE] = _BUCKET
    _truth.EVENT_TYPES[_EVENT] = (_CANDIDATE, "candidate_id")
    _truth.IDENTITY_FIELDS[_CANDIDATE] = "candidate_id"


def _ensure_projection_bucket(truth: TruthRuntime) -> None:
    if not hasattr(truth.projection, _BUCKET):
        setattr(truth.projection, _BUCKET, {})
    truth.projection._versions.setdefault(_CANDIDATE, {})


def _metadata_ref(step: Mapping[str, Any], key: str) -> Optional[str]:
    metadata = step.get("capture_metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


class JourneyCompiler:
    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_journey_compiler_overlay()
        _ensure_projection_bucket(truth)
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("JOURNEY_COMPILER_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()

    def install_overlay(self) -> None:
        install_rc72_journey_compiler_overlay()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("JOURNEY_COMPILER_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    def _compile_step(self, source: Mapping[str, Any]) -> Dict[str, Any]:
        action_type = str(source.get("action_type") or "").upper()
        compiled: Dict[str, Any] = {
            "source_step_id": str(source["step_id"]),
            "sequence": int(source["sequence"]),
            "action_type": action_type,
            "url": str(source["url"]),
            "page_role": str(source["page_role"]),
            "element_ref": source.get("element_ref"),
            "page_state_ref": str(source["page_state_ref"]),
            "dom_ref": str(source["dom_ref"]),
            "network_refs": list(source.get("network_refs") or []),
            "screenshot_ref": source.get("screenshot_ref"),
            "wait_semantics": str(source["wait_semantics"]),
            "evidence_refs": list(source.get("evidence_refs") or []),
        }
        if action_type == JourneyActionType.INPUT.value:
            value_ref = _metadata_ref(source, "value_ref")
            credential_ref = source.get("credential_ref")
            if isinstance(credential_ref, str):
                credential_ref = credential_ref.strip() or None
            if not value_ref and not credential_ref:
                raise ContractError("JOURNEY_INPUT_REFERENCE_REQUIRED")
            if value_ref:
                compiled["value_ref"] = value_ref
            if credential_ref:
                compiled["credential_ref"] = credential_ref
        elif action_type == JourneyActionType.ASSERT.value:
            oracle_ref = _metadata_ref(source, "oracle_ref")
            if not oracle_ref:
                raise ContractError("JOURNEY_ASSERT_ORACLE_REQUIRED")
            compiled["oracle_ref"] = oracle_ref
        return compiled

    def compile(self, *, candidate_id: str, recording_id: str) -> JourneyCandidateResult:
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ContractError("JOURNEY_CANDIDATE_ID_REQUIRED")
        if self.truth.query(_CANDIDATE, candidate_id=candidate_id):
            raise ContractError("JOURNEY_CANDIDATE_ALREADY_EXISTS")
        recording = self._one("rc72_journey_recording", recording_id=recording_id)
        if recording.get("state") != JourneyRecordingState.CAPTURED.value:
            raise ContractError("JOURNEY_COMPILER_REQUIRES_CAPTURED_RECORDING")
        if self.truth.query(_CANDIDATE, source_recording_id=recording_id):
            raise ContractError("JOURNEY_RECORDING_ALREADY_COMPILED")
        steps = self.truth.query("rc72_journey_capture_step", recording_id=recording_id)
        steps = sorted(steps, key=lambda row: int(row.get("sequence") or 0))
        if len(steps) != int(recording.get("step_count") or 0) or not steps:
            raise ContractError("JOURNEY_COMPILER_SOURCE_STEPS_INCOMPLETE")
        if [int(row.get("sequence") or 0) for row in steps] != list(range(1, len(steps) + 1)):
            raise ContractError("JOURNEY_COMPILER_SOURCE_SEQUENCE_INVALID")
        compiled_steps = [self._compile_step(step) for step in steps]
        payload = {
            "candidate_id": candidate_id.strip(),
            "mission_id": recording["mission_id"],
            "release_id": self.release_id,
            "release_batch_id": recording["release_batch_id"],
            "requirement_id": recording["requirement_id"],
            "sst_id": recording["sst_id"],
            "obligation_id": recording["obligation_id"],
            "source_recording_id": recording_id,
            "state": JourneyCandidateState.COMPILED_CANDIDATE.value,
            "asset_class": "CANDIDATE",
            "executable": False,
            "official": False,
            "replay_status": "NOT_RUN",
            "benchmark_status": "NOT_RUN",
            "review_status": "NOT_REVIEWED",
            "steps": compiled_steps,
            "compiled_at": _now(),
            "artifact_version": 1,
        }
        self.truth.append_atomic(_EVENT, payload)
        return JourneyCandidateResult(candidate_id=candidate_id.strip(), state=JourneyCandidateState.COMPILED_CANDIDATE)


install_rc72_journey_compiler_overlay()
