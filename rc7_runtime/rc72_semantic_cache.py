"""RC7.2 semantic cache keyed by canonical semantic digests.

The cache reuses only explicitly validated semantic derivations. A cache HIT is
never presented as a fresh DSH/model/tool execution: every reuse is persisted as
an explicit cache-use receipt pointing back to the original Mission/WorkItem/
Attempt/Assignment and validation evidence.

Key safety rules:
- digest canonical semantic inputs + producer contract, not prompt text alone;
- release scope is part of the digest so old-release truth cannot silently leak;
- work requiring fresh runtime/tool/session proof is BYPASS and cannot be stored;
- UNKNOWN/FAILED/INCOMPLETE semantic validation can never create a valid entry;
- evidence is mandatory for cacheability;
- same digest with a different validated result fails closed as nondeterminism;
- invalidated entries never produce HITs.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .truth_overlay import install_rc7_truth_overlay


_ENTRY = "rc72_semantic_cache_entry"
_USE = "rc72_semantic_cache_use"
_EVENT_TYPES = {
    "RC72_SEMANTIC_CACHE_ENTRY_UPSERTED": (_ENTRY, "cache_entry_id"),
    "RC72_SEMANTIC_CACHE_USE_RECORDED": (_USE, "cache_use_id"),
}
_BUCKETS = {
    _ENTRY: "rc72_semantic_cache_entries",
    _USE: "rc72_semantic_cache_uses",
}
_SCHEMA_VERSION = "rc72-semantic-cache-v1"
_VALIDATION_ALLOWED = {"VALIDATED", "UNKNOWN", "FAILED", "INCOMPLETE"}
_ENTRY_STATES = {"VALID", "INVALIDATED"}
_DECISIONS = {"HIT", "MISS", "BYPASS"}


def _now() -> int:
    return int(time.time())


def _new(prefix: str) -> str:
    return "%s-%s" % (prefix, uuid.uuid4().hex[:20])


def _required_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("SEMANTIC_CACHE_%s_REQUIRED" % name.upper())
    return value.strip()


def _json_clone(value: Any, name: str) -> Any:
    """Return deterministic JSON-compatible data and reject NaN/opaque objects."""
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ContractError("SEMANTIC_CACHE_%s_NOT_CANONICAL_JSON" % name.upper()) from exc


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _validate_string_list(out: Dict[str, Any], name: str, *, nonempty: bool = False) -> None:
    value = out.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_%s_INVALID" % name.upper())
    if nonempty and not value:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_%s_REQUIRED" % name.upper())


def _validate_entry(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "cache_entry_id", "release_id", "namespace", "semantic_digest",
        "semantic_inputs_digest", "producer_contract_digest", "result_sha256",
        "state", "source_mission_id", "source_workitem_id", "source_attempt_id",
        "source_assignment_id", "source_ref", "validation_status", "schema_version",
    ):
        out[name] = _contracts._require_str(out, name)
    if len(out["semantic_digest"]) != 64:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_DIGEST_INVALID")
    for name in ("semantic_inputs_digest", "producer_contract_digest", "result_sha256"):
        if len(out[name]) != 64:
            raise _contracts.DomainValidationError("SEMANTIC_CACHE_%s_INVALID" % name.upper())
    out["state"] = out["state"].upper()
    if out["state"] not in _ENTRY_STATES:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_STATE_INVALID")
    out["validation_status"] = out["validation_status"].upper()
    if out["validation_status"] not in _VALIDATION_ALLOWED:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_VALIDATION_STATUS_INVALID")
    if out["validation_status"] != "VALIDATED":
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_ENTRY_MUST_BE_VALIDATED")
    if out["schema_version"] != _SCHEMA_VERSION:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_SCHEMA_VERSION_INVALID")
    if not isinstance(out.get("semantic_inputs"), dict) or not out["semantic_inputs"]:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_INPUTS_REQUIRED")
    if not isinstance(out.get("producer_contract"), dict) or not out["producer_contract"]:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_PRODUCER_CONTRACT_REQUIRED")
    if not isinstance(out.get("result_payload"), dict) or not out["result_payload"]:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_RESULT_REQUIRED")
    _validate_string_list(out, "validation_evidence_refs", nonempty=True)
    if not isinstance(out.get("requires_fresh_runtime_proof"), bool):
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_FRESH_PROOF_FLAG_INVALID")
    if out["requires_fresh_runtime_proof"]:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_FRESH_PROOF_ENTRY_FORBIDDEN")
    for name in ("created_at", "updated_at"):
        value = out.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _contracts.DomainValidationError("SEMANTIC_CACHE_%s_INVALID" % name.upper())
    invalidated_at = out.get("invalidated_at")
    invalidation_reason = out.get("invalidation_reason")
    if out["state"] == "VALID":
        if invalidated_at is not None or invalidation_reason is not None:
            raise _contracts.DomainValidationError("SEMANTIC_CACHE_VALID_ENTRY_HAS_INVALIDATION")
    else:
        if isinstance(invalidated_at, bool) or not isinstance(invalidated_at, int) or invalidated_at < 0:
            raise _contracts.DomainValidationError("SEMANTIC_CACHE_INVALIDATED_AT_REQUIRED")
        if not isinstance(invalidation_reason, str) or not invalidation_reason.strip():
            raise _contracts.DomainValidationError("SEMANTIC_CACHE_INVALIDATION_REASON_REQUIRED")
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ENTRY
    return out


def _validate_use(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "cache_use_id", "release_id", "cache_entry_id", "semantic_digest", "namespace",
        "target_mission_id", "target_workitem_id", "target_attempt_id", "decision",
        "reason", "result_sha256", "source_mission_id", "source_workitem_id",
        "source_attempt_id", "source_assignment_id",
    ):
        out[name] = _contracts._require_str(out, name)
    out["decision"] = out["decision"].upper()
    if out["decision"] not in _DECISIONS or out["decision"] != "HIT":
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_USE_MUST_BE_HIT")
    if len(out["semantic_digest"]) != 64 or len(out["result_sha256"]) != 64:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_USE_DIGEST_INVALID")
    if not isinstance(out.get("fresh_execution"), bool) or out["fresh_execution"]:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_USE_CANNOT_CLAIM_FRESH_EXECUTION")
    _validate_string_list(out, "validation_evidence_refs", nonempty=True)
    used_at = out.get("used_at")
    if isinstance(used_at, bool) or not isinstance(used_at, int) or used_at < 0:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_USED_AT_INVALID")
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("SEMANTIC_CACHE_USE_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _USE
    return out


def install_rc72_semantic_cache_overlay() -> None:
    install_rc7_truth_overlay()
    _contracts.VALIDATORS[_ENTRY] = _validate_entry
    _contracts.VALIDATORS[_USE] = _validate_use
    for artifact_type, bucket in _BUCKETS.items():
        _truth.BUCKETS[artifact_type] = bucket
    _truth.IDENTITY_FIELDS[_ENTRY] = "cache_entry_id"
    _truth.IDENTITY_FIELDS[_USE] = "cache_use_id"
    for event_type, pair in _EVENT_TYPES.items():
        _truth.EVENT_TYPES[event_type] = pair


def _ensure_projection_buckets(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    for artifact_type, bucket in _BUCKETS.items():
        if not hasattr(projection, bucket):
            setattr(projection, bucket, {})
        versions = getattr(projection, "_versions", None)
        if isinstance(versions, dict):
            versions.setdefault(artifact_type, {})


@dataclass(frozen=True)
class SemanticCacheSpec:
    namespace: str
    semantic_inputs: Mapping[str, Any]
    producer_contract: Mapping[str, Any]
    requires_fresh_runtime_proof: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "namespace", _required_str(self.namespace, "namespace"))
        if not isinstance(self.semantic_inputs, Mapping) or not self.semantic_inputs:
            raise ContractError("SEMANTIC_CACHE_INPUTS_REQUIRED")
        if not isinstance(self.producer_contract, Mapping) or not self.producer_contract:
            raise ContractError("SEMANTIC_CACHE_PRODUCER_CONTRACT_REQUIRED")
        if not isinstance(self.requires_fresh_runtime_proof, bool):
            raise ContractError("SEMANTIC_CACHE_FRESH_PROOF_FLAG_INVALID")
        object.__setattr__(self, "semantic_inputs", _json_clone(dict(self.semantic_inputs), "inputs"))
        object.__setattr__(self, "producer_contract", _json_clone(dict(self.producer_contract), "producer_contract"))


@dataclass(frozen=True)
class SemanticCacheDecision:
    decision: str
    reason: str
    semantic_digest: str
    cache_entry_id: Optional[str] = None
    cache_use_id: Optional[str] = None
    result_payload: Optional[Dict[str, Any]] = None
    result_sha256: Optional[str] = None
    validation_evidence_refs: Tuple[str, ...] = ()
    source_mission_id: Optional[str] = None
    source_workitem_id: Optional[str] = None
    source_attempt_id: Optional[str] = None
    source_assignment_id: Optional[str] = None
    fresh_execution: bool = False

    @property
    def hit(self) -> bool:
        return self.decision == "HIT"


class SemanticCacheService:
    """Release-scoped semantic cache with explicit provenance and fail-closed reuse."""

    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_semantic_cache_overlay()
        _ensure_projection_buckets(truth)
        self.truth = truth
        self.release_id = _required_str(release_id, "release_id")

    def semantic_digest(self, spec: SemanticCacheSpec) -> str:
        if not isinstance(spec, SemanticCacheSpec):
            raise ContractError("SEMANTIC_CACHE_SPEC_REQUIRED")
        key = {
            "schema_version": _SCHEMA_VERSION,
            "release_id": self.release_id,
            "namespace": spec.namespace,
            "semantic_inputs": spec.semantic_inputs,
            "producer_contract": spec.producer_contract,
            "requires_fresh_runtime_proof": spec.requires_fresh_runtime_proof,
        }
        return _sha256(key)

    def _entry_id(self, digest: str) -> str:
        return "SEMCACHE-" + hashlib.sha256(
            (self.release_id + "\x1f" + digest).encode("utf-8")
        ).hexdigest()[:24]

    def store_validated(
        self,
        spec: SemanticCacheSpec,
        *,
        result_payload: Mapping[str, Any],
        validation_status: str,
        validation_evidence_refs: Sequence[str],
        source_mission_id: str,
        source_workitem_id: str,
        source_attempt_id: str,
        source_assignment_id: str,
        source_ref: str,
    ) -> Dict[str, Any]:
        digest = self.semantic_digest(spec)
        if spec.requires_fresh_runtime_proof:
            raise ContractError("SEMANTIC_CACHE_FRESH_RUNTIME_PROOF_REQUIRED")
        status = _required_str(validation_status, "validation_status").upper()
        if status not in _VALIDATION_ALLOWED:
            raise ContractError("SEMANTIC_CACHE_VALIDATION_STATUS_INVALID")
        if status != "VALIDATED":
            raise ContractError("SEMANTIC_CACHE_ONLY_VALIDATED_RESULTS_CACHEABLE")
        evidence = [
            _required_str(ref, "validation_evidence_ref")
            for ref in validation_evidence_refs
        ]
        if not evidence:
            raise ContractError("SEMANTIC_CACHE_VALIDATION_EVIDENCE_REQUIRED")
        if not isinstance(result_payload, Mapping) or not result_payload:
            raise ContractError("SEMANTIC_CACHE_RESULT_REQUIRED")
        result = _json_clone(dict(result_payload), "result")
        result_sha = _sha256(result)
        entry_id = self._entry_id(digest)
        existing = self.truth.query(_ENTRY, cache_entry_id=entry_id)
        if len(existing) > 1:
            raise ContractError("SEMANTIC_CACHE_ENTRY_NOT_UNIQUE")
        if existing:
            row = existing[0]
            if row.get("semantic_digest") != digest:
                raise ContractError("SEMANTIC_CACHE_ENTRY_DIGEST_COLLISION")
            if row.get("state") == "INVALIDATED":
                raise ContractError("SEMANTIC_CACHE_ENTRY_INVALIDATED")
            if row.get("result_sha256") != result_sha:
                raise ContractError("SEMANTIC_CACHE_DIGEST_NONDETERMINISTIC_RESULT")
            return row

        now = _now()
        payload = {
            "cache_entry_id": entry_id,
            "release_id": self.release_id,
            "namespace": spec.namespace,
            "semantic_digest": digest,
            "semantic_inputs": dict(spec.semantic_inputs),
            "semantic_inputs_digest": _sha256(spec.semantic_inputs),
            "producer_contract": dict(spec.producer_contract),
            "producer_contract_digest": _sha256(spec.producer_contract),
            "requires_fresh_runtime_proof": False,
            "result_payload": result,
            "result_sha256": result_sha,
            "state": "VALID",
            "validation_status": status,
            "validation_evidence_refs": list(dict.fromkeys(evidence)),
            "source_mission_id": _required_str(source_mission_id, "source_mission_id"),
            "source_workitem_id": _required_str(source_workitem_id, "source_workitem_id"),
            "source_attempt_id": _required_str(source_attempt_id, "source_attempt_id"),
            "source_assignment_id": _required_str(source_assignment_id, "source_assignment_id"),
            "source_ref": _required_str(source_ref, "source_ref"),
            "schema_version": _SCHEMA_VERSION,
            "created_at": now,
            "updated_at": now,
            "invalidated_at": None,
            "invalidation_reason": None,
            "artifact_version": 1,
        }
        self.truth.append_atomic("RC72_SEMANTIC_CACHE_ENTRY_UPSERTED", payload)
        rows = self.truth.query(_ENTRY, cache_entry_id=entry_id)
        if len(rows) != 1:
            raise ContractError("SEMANTIC_CACHE_PERSISTENCE_FAILED")
        return rows[0]

    def lookup(
        self,
        spec: SemanticCacheSpec,
        *,
        target_mission_id: str,
        target_workitem_id: str,
        target_attempt_id: str,
    ) -> SemanticCacheDecision:
        digest = self.semantic_digest(spec)
        if spec.requires_fresh_runtime_proof:
            return SemanticCacheDecision(
                "BYPASS",
                "FRESH_RUNTIME_PROOF_REQUIRED",
                digest,
                fresh_execution=False,
            )
        entry_id = self._entry_id(digest)
        rows = self.truth.query(_ENTRY, cache_entry_id=entry_id)
        if not rows:
            return SemanticCacheDecision("MISS", "SEMANTIC_DIGEST_NOT_CACHED", digest)
        if len(rows) != 1:
            raise ContractError("SEMANTIC_CACHE_ENTRY_NOT_UNIQUE")
        row = rows[0]
        if row.get("state") != "VALID":
            return SemanticCacheDecision(
                "MISS", "SEMANTIC_CACHE_ENTRY_INVALIDATED", digest, cache_entry_id=entry_id
            )
        if row.get("semantic_digest") != digest:
            raise ContractError("SEMANTIC_CACHE_ENTRY_DIGEST_MISMATCH")
        result = row.get("result_payload")
        if not isinstance(result, dict) or not result:
            raise ContractError("SEMANTIC_CACHE_RESULT_CORRUPT")
        actual_sha = _sha256(result)
        if actual_sha != row.get("result_sha256"):
            raise ContractError("SEMANTIC_CACHE_RESULT_DIGEST_MISMATCH")
        evidence = tuple(row.get("validation_evidence_refs") or ())
        if not evidence:
            raise ContractError("SEMANTIC_CACHE_VALIDATION_EVIDENCE_MISSING")

        use_id = _new("SEMCACHEUSE")
        use_payload = {
            "cache_use_id": use_id,
            "release_id": self.release_id,
            "cache_entry_id": entry_id,
            "semantic_digest": digest,
            "namespace": spec.namespace,
            "target_mission_id": _required_str(target_mission_id, "target_mission_id"),
            "target_workitem_id": _required_str(target_workitem_id, "target_workitem_id"),
            "target_attempt_id": _required_str(target_attempt_id, "target_attempt_id"),
            "decision": "HIT",
            "reason": "VALIDATED_SEMANTIC_DIGEST_REUSE",
            "result_sha256": actual_sha,
            "validation_evidence_refs": list(evidence),
            "source_mission_id": row["source_mission_id"],
            "source_workitem_id": row["source_workitem_id"],
            "source_attempt_id": row["source_attempt_id"],
            "source_assignment_id": row["source_assignment_id"],
            "fresh_execution": False,
            "used_at": _now(),
            "artifact_version": 1,
        }
        self.truth.append_atomic("RC72_SEMANTIC_CACHE_USE_RECORDED", use_payload)
        return SemanticCacheDecision(
            "HIT",
            "VALIDATED_SEMANTIC_DIGEST_REUSE",
            digest,
            cache_entry_id=entry_id,
            cache_use_id=use_id,
            result_payload=_json_clone(result, "result"),
            result_sha256=actual_sha,
            validation_evidence_refs=evidence,
            source_mission_id=row["source_mission_id"],
            source_workitem_id=row["source_workitem_id"],
            source_attempt_id=row["source_attempt_id"],
            source_assignment_id=row["source_assignment_id"],
            fresh_execution=False,
        )

    def invalidate(self, cache_entry_id: str, *, reason: str) -> Dict[str, Any]:
        cache_entry_id = _required_str(cache_entry_id, "cache_entry_id")
        rows = self.truth.query(_ENTRY, cache_entry_id=cache_entry_id)
        if len(rows) != 1:
            raise ContractError("SEMANTIC_CACHE_ENTRY_NOT_FOUND_OR_NOT_UNIQUE")
        current = rows[0]
        if current.get("state") == "INVALIDATED":
            return current
        updated = dict(current)
        updated.pop("artifact_type", None)
        updated["state"] = "INVALIDATED"
        updated["invalidated_at"] = _now()
        updated["invalidation_reason"] = _required_str(reason, "invalidation_reason")
        updated["updated_at"] = _now()
        updated["artifact_version"] = int(current.get("artifact_version", 1)) + 1
        self.truth.append_atomic("RC72_SEMANTIC_CACHE_ENTRY_UPSERTED", updated)
        return self.truth.query(_ENTRY, cache_entry_id=cache_entry_id)[0]


install_rc72_semantic_cache_overlay()
