"""RC7.2 deterministic-first evaluator routing.

A model is not the default oracle. Fixed executable rules run first. Their
outcome is conclusive when they fail, and may be conclusive on PASS only when
the caller explicitly declares the deterministic contract complete and no fresh
runtime/tool/session proof is required. Every other case escalates to the
semantic evaluator without converting uncertainty into PASS.

This module does not replace existing independent DSH reviewers. It provides the
control-plane primitive that lets callers avoid unnecessary model work while
preserving reviewer/tool requirements where semantics or fresh proof are needed.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .oracle_runtime import DeterministicOracleError, DeterministicOracleRuntime
from .rc72_model_economy import ModelCallClass
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT = "rc72_deterministic_first_evaluation"
_EVENT = "RC72_DETERMINISTIC_FIRST_EVALUATION_RECORDED"
_BUCKET = "rc72_deterministic_first_evaluations"
_FINAL_DECISIONS = {"PASS", "FAIL", "GAPS", "UNKNOWN", "BLOCKED", "MODEL_REQUIRED"}
_ROUTES = {"DETERMINISTIC", "SEMANTIC_MODEL", "BLOCKED"}


def _now() -> int:
    return int(time.time())


def _new(prefix: str) -> str:
    return "%s-%s" % (prefix, uuid.uuid4().hex[:20])


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("DETERMINISTIC_FIRST_%s_REQUIRED" % name.upper())
    return value.strip()


def _json_clone(value: Any, name: str) -> Any:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ContractError("DETERMINISTIC_FIRST_%s_NOT_CANONICAL_JSON" % name.upper()) from exc


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_string_list(out: Dict[str, Any], name: str) -> None:
    value = out.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("DETERMINISTIC_FIRST_%s_INVALID" % name.upper())


def _validate(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "evaluation_id", "release_id", "mission_id", "node", "workitem_id",
        "attempt_id", "evaluator_kind", "route", "decision", "reason",
        "model_call_class", "request_sha256",
    ):
        out[name] = _contracts._require_str(out, name)
    out["route"] = out["route"].upper()
    out["decision"] = out["decision"].upper()
    if out["route"] not in _ROUTES:
        raise _contracts.DomainValidationError("DETERMINISTIC_FIRST_ROUTE_INVALID")
    if out["decision"] not in _FINAL_DECISIONS:
        raise _contracts.DomainValidationError("DETERMINISTIC_FIRST_DECISION_INVALID")
    if out["model_call_class"] not in {item.value for item in ModelCallClass}:
        raise _contracts.DomainValidationError("DETERMINISTIC_FIRST_CALL_CLASS_INVALID")
    if len(out["request_sha256"]) != 64:
        raise _contracts.DomainValidationError("DETERMINISTIC_FIRST_REQUEST_DIGEST_INVALID")
    for name in (
        "deterministic_complete", "fresh_runtime_proof_required",
        "model_call_required", "model_call_invoked", "passed",
    ):
        if not isinstance(out.get(name), bool):
            raise _contracts.DomainValidationError("DETERMINISTIC_FIRST_%s_INVALID" % name.upper())
    _validate_string_list(out, "deterministic_evidence_refs")
    _validate_string_list(out, "semantic_evidence_refs")
    assertion_ref = out.get("deterministic_assertion_ref")
    if assertion_ref is not None and (not isinstance(assertion_ref, str) or not assertion_ref.strip()):
        raise _contracts.DomainValidationError("DETERMINISTIC_FIRST_ASSERTION_REF_INVALID")
    semantic_decision = out.get("semantic_decision")
    if semantic_decision is not None:
        if not isinstance(semantic_decision, str) or semantic_decision.upper() not in {
            "PASS", "FAIL", "GAPS", "UNKNOWN", "BLOCKED"
        }:
            raise _contracts.DomainValidationError("DETERMINISTIC_FIRST_SEMANTIC_DECISION_INVALID")
        out["semantic_decision"] = semantic_decision.upper()
    semantic_result = out.get("semantic_result")
    if semantic_result is not None and not isinstance(semantic_result, dict):
        raise _contracts.DomainValidationError("DETERMINISTIC_FIRST_SEMANTIC_RESULT_INVALID")
    deterministic_result = out.get("deterministic_result")
    if deterministic_result is not None and not isinstance(deterministic_result, dict):
        raise _contracts.DomainValidationError("DETERMINISTIC_FIRST_DETERMINISTIC_RESULT_INVALID")
    if out["passed"] != (out["decision"] == "PASS"):
        raise _contracts.DomainValidationError("DETERMINISTIC_FIRST_PASS_FLAG_MISMATCH")
    if out["route"] == "DETERMINISTIC":
        if out["model_call_required"] or out["model_call_invoked"]:
            raise _contracts.DomainValidationError("DETERMINISTIC_ROUTE_CANNOT_CLAIM_MODEL_CALL")
        if out["model_call_class"] != ModelCallClass.DETERMINISTIC_NO_LLM.value:
            raise _contracts.DomainValidationError("DETERMINISTIC_ROUTE_CALL_CLASS_MISMATCH")
    if out["route"] == "SEMANTIC_MODEL":
        if not out["model_call_required"]:
            raise _contracts.DomainValidationError("SEMANTIC_ROUTE_REQUIRES_MODEL")
        if out["model_call_class"] != ModelCallClass.LLM_REQUIRED.value:
            raise _contracts.DomainValidationError("SEMANTIC_ROUTE_CALL_CLASS_MISMATCH")
    if out["decision"] == "MODEL_REQUIRED" and out["model_call_invoked"]:
        raise _contracts.DomainValidationError("MODEL_REQUIRED_DECISION_CANNOT_BE_INVOKED")
    if out["model_call_invoked"] and out.get("semantic_decision") is None:
        raise _contracts.DomainValidationError("INVOKED_MODEL_REQUIRES_SEMANTIC_DECISION")
    recorded_at = out.get("recorded_at")
    if isinstance(recorded_at, bool) or not isinstance(recorded_at, int) or recorded_at < 0:
        raise _contracts.DomainValidationError("DETERMINISTIC_FIRST_RECORDED_AT_INVALID")
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("DETERMINISTIC_FIRST_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT
    return out


def install_rc72_deterministic_first_overlay() -> None:
    install_rc7_truth_overlay()
    _contracts.VALIDATORS[_ARTIFACT] = _validate
    _truth.BUCKETS[_ARTIFACT] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT] = "evaluation_id"
    _truth.EVENT_TYPES[_EVENT] = (_ARTIFACT, "evaluation_id")


def _ensure_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT, {})


@dataclass(frozen=True)
class DeterministicFirstRequest:
    mission_id: str
    node: str
    workitem_id: str
    attempt_id: str
    evaluator_kind: str
    oracle_snapshot: Mapping[str, Any]
    actual_result: Mapping[str, Any]
    context: Mapping[str, Any]
    deterministic_complete: bool = False
    fresh_runtime_proof_required: bool = False

    def __post_init__(self) -> None:
        for name in ("mission_id", "node", "workitem_id", "attempt_id", "evaluator_kind"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if not isinstance(self.oracle_snapshot, Mapping) or not self.oracle_snapshot:
            raise ContractError("DETERMINISTIC_FIRST_ORACLE_REQUIRED")
        if not isinstance(self.actual_result, Mapping) or not self.actual_result:
            raise ContractError("DETERMINISTIC_FIRST_ACTUAL_RESULT_REQUIRED")
        if not isinstance(self.context, Mapping):
            raise ContractError("DETERMINISTIC_FIRST_CONTEXT_REQUIRED")
        if not isinstance(self.deterministic_complete, bool):
            raise ContractError("DETERMINISTIC_FIRST_COMPLETE_FLAG_INVALID")
        if not isinstance(self.fresh_runtime_proof_required, bool):
            raise ContractError("DETERMINISTIC_FIRST_FRESH_PROOF_FLAG_INVALID")
        object.__setattr__(self, "oracle_snapshot", _json_clone(dict(self.oracle_snapshot), "oracle"))
        object.__setattr__(self, "actual_result", _json_clone(dict(self.actual_result), "actual_result"))
        object.__setattr__(self, "context", _json_clone(dict(self.context), "context"))


@dataclass(frozen=True)
class DeterministicFirstOutcome:
    evaluation_id: str
    route: str
    decision: str
    reason: str
    passed: bool
    model_call_class: ModelCallClass
    model_call_required: bool
    model_call_invoked: bool
    deterministic_assertion_ref: Optional[str]
    deterministic_evidence_refs: Tuple[str, ...]
    semantic_decision: Optional[str]
    semantic_evidence_refs: Tuple[str, ...]
    deterministic_result: Optional[Dict[str, Any]]
    semantic_result: Optional[Dict[str, Any]]


SemanticEvaluator = Callable[[DeterministicFirstRequest, Dict[str, Any]], Mapping[str, Any]]


class DeterministicFirstEvaluator:
    """Run deterministic truth first and escalate only when semantics still require it."""

    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_deterministic_first_overlay()
        _ensure_bucket(truth)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")
        self.oracle = DeterministicOracleRuntime()

    @staticmethod
    def _request_identity(request: DeterministicFirstRequest) -> Dict[str, Any]:
        return {
            "mission_id": request.mission_id,
            "node": request.node,
            "workitem_id": request.workitem_id,
            "attempt_id": request.attempt_id,
            "evaluator_kind": request.evaluator_kind,
            "oracle_snapshot": request.oracle_snapshot,
            "actual_result": request.actual_result,
            "context": request.context,
            "deterministic_complete": request.deterministic_complete,
            "fresh_runtime_proof_required": request.fresh_runtime_proof_required,
        }

    @staticmethod
    def _normalize_semantic_result(result: Mapping[str, Any]) -> Dict[str, Any]:
        if not isinstance(result, Mapping):
            raise ContractError("DETERMINISTIC_FIRST_SEMANTIC_RESULT_REQUIRED")
        cloned = _json_clone(dict(result), "semantic_result")
        decision = cloned.get("decision")
        if not isinstance(decision, str) or decision.upper() not in {
            "PASS", "FAIL", "GAPS", "UNKNOWN", "BLOCKED"
        }:
            raise ContractError("DETERMINISTIC_FIRST_SEMANTIC_DECISION_INVALID")
        cloned["decision"] = decision.upper()
        refs = cloned.get("evidence_refs", [])
        if not isinstance(refs, list) or not all(isinstance(ref, str) and ref.strip() for ref in refs):
            raise ContractError("DETERMINISTIC_FIRST_SEMANTIC_EVIDENCE_INVALID")
        if cloned["decision"] in {"PASS", "FAIL", "GAPS"} and not refs:
            raise ContractError("DETERMINISTIC_FIRST_SEMANTIC_EVIDENCE_REQUIRED")
        return cloned

    def evaluate(
        self,
        request: DeterministicFirstRequest,
        *,
        semantic_evaluator: Optional[SemanticEvaluator] = None,
    ) -> DeterministicFirstOutcome:
        if not isinstance(request, DeterministicFirstRequest):
            raise ContractError("DETERMINISTIC_FIRST_REQUEST_REQUIRED")
        evaluation_id = _new("DETFEVAL")
        request_sha = _digest(self._request_identity(request))

        deterministic: Optional[Dict[str, Any]] = None
        try:
            deterministic = self.oracle.evaluate(
                dict(request.oracle_snapshot),
                dict(request.actual_result),
                dict(request.context),
            )
        except DeterministicOracleError as exc:
            return self._persist(
                request,
                evaluation_id=evaluation_id,
                request_sha=request_sha,
                route="BLOCKED",
                decision="BLOCKED",
                reason="DETERMINISTIC_CONTRACT_INVALID:%s" % str(exc),
                model_call_class=ModelCallClass.DETERMINISTIC_NO_LLM,
                model_call_required=False,
                model_call_invoked=False,
                deterministic_result=None,
                semantic_result=None,
            )

        if not bool(deterministic.get("passed")):
            return self._persist(
                request,
                evaluation_id=evaluation_id,
                request_sha=request_sha,
                route="DETERMINISTIC",
                decision="FAIL",
                reason="DETERMINISTIC_ASSERTION_FAILED",
                model_call_class=ModelCallClass.DETERMINISTIC_NO_LLM,
                model_call_required=False,
                model_call_invoked=False,
                deterministic_result=deterministic,
                semantic_result=None,
            )

        if request.deterministic_complete and not request.fresh_runtime_proof_required:
            return self._persist(
                request,
                evaluation_id=evaluation_id,
                request_sha=request_sha,
                route="DETERMINISTIC",
                decision="PASS",
                reason="DETERMINISTIC_CONTRACT_COMPLETE",
                model_call_class=ModelCallClass.DETERMINISTIC_NO_LLM,
                model_call_required=False,
                model_call_invoked=False,
                deterministic_result=deterministic,
                semantic_result=None,
            )

        if semantic_evaluator is None:
            reason = (
                "FRESH_RUNTIME_PROOF_REQUIRES_SEMANTIC_EVALUATOR"
                if request.fresh_runtime_proof_required
                else "DETERMINISTIC_CONTRACT_INCOMPLETE"
            )
            return self._persist(
                request,
                evaluation_id=evaluation_id,
                request_sha=request_sha,
                route="SEMANTIC_MODEL",
                decision="MODEL_REQUIRED",
                reason=reason,
                model_call_class=ModelCallClass.LLM_REQUIRED,
                model_call_required=True,
                model_call_invoked=False,
                deterministic_result=deterministic,
                semantic_result=None,
            )

        semantic = self._normalize_semantic_result(semantic_evaluator(request, deterministic))
        semantic_decision = str(semantic["decision"])
        return self._persist(
            request,
            evaluation_id=evaluation_id,
            request_sha=request_sha,
            route="SEMANTIC_MODEL",
            decision=semantic_decision,
            reason="SEMANTIC_EVALUATOR_REQUIRED_AFTER_DETERMINISTIC_PASS",
            model_call_class=ModelCallClass.LLM_REQUIRED,
            model_call_required=True,
            model_call_invoked=True,
            deterministic_result=deterministic,
            semantic_result=semantic,
        )

    def _persist(
        self,
        request: DeterministicFirstRequest,
        *,
        evaluation_id: str,
        request_sha: str,
        route: str,
        decision: str,
        reason: str,
        model_call_class: ModelCallClass,
        model_call_required: bool,
        model_call_invoked: bool,
        deterministic_result: Optional[Dict[str, Any]],
        semantic_result: Optional[Dict[str, Any]],
    ) -> DeterministicFirstOutcome:
        deterministic_assertion_ref = None
        deterministic_evidence_refs: Tuple[str, ...] = ()
        if deterministic_result is not None:
            ref = deterministic_result.get("assertion_ref")
            if isinstance(ref, str) and ref.strip():
                deterministic_assertion_ref = ref.strip()
            refs = deterministic_result.get("evidence_refs", [])
            if isinstance(refs, list):
                deterministic_evidence_refs = tuple(
                    str(item).strip() for item in refs if isinstance(item, str) and item.strip()
                )
        semantic_decision = None
        semantic_evidence_refs: Tuple[str, ...] = ()
        if semantic_result is not None:
            semantic_decision = str(semantic_result.get("decision") or "").upper() or None
            refs = semantic_result.get("evidence_refs", [])
            if isinstance(refs, list):
                semantic_evidence_refs = tuple(
                    str(item).strip() for item in refs if isinstance(item, str) and item.strip()
                )

        payload = {
            "evaluation_id": evaluation_id,
            "release_id": self.release_id,
            "mission_id": request.mission_id,
            "node": request.node,
            "workitem_id": request.workitem_id,
            "attempt_id": request.attempt_id,
            "evaluator_kind": request.evaluator_kind,
            "route": route,
            "decision": decision,
            "reason": reason,
            "passed": decision == "PASS",
            "model_call_class": model_call_class.value,
            "model_call_required": model_call_required,
            "model_call_invoked": model_call_invoked,
            "deterministic_complete": request.deterministic_complete,
            "fresh_runtime_proof_required": request.fresh_runtime_proof_required,
            "request_sha256": request_sha,
            "deterministic_assertion_ref": deterministic_assertion_ref,
            "deterministic_evidence_refs": list(deterministic_evidence_refs),
            "deterministic_result": deterministic_result,
            "semantic_decision": semantic_decision,
            "semantic_evidence_refs": list(semantic_evidence_refs),
            "semantic_result": semantic_result,
            "recorded_at": _now(),
            "artifact_version": 1,
        }
        self.truth.append_atomic(_EVENT, payload)
        return DeterministicFirstOutcome(
            evaluation_id=evaluation_id,
            route=route,
            decision=decision,
            reason=reason,
            passed=decision == "PASS",
            model_call_class=model_call_class,
            model_call_required=model_call_required,
            model_call_invoked=model_call_invoked,
            deterministic_assertion_ref=deterministic_assertion_ref,
            deterministic_evidence_refs=deterministic_evidence_refs,
            semantic_decision=semantic_decision,
            semantic_evidence_refs=semantic_evidence_refs,
            deterministic_result=deterministic_result,
            semantic_result=semantic_result,
        )


install_rc72_deterministic_first_overlay()
