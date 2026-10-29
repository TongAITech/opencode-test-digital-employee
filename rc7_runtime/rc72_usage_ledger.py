"""RC7.2 canonical token Usage Ledger.

This ledger is an observability/control-plane projection over real DSH token
usage receipts. It never schedules, suppresses, merges or defers mandatory test
work. Attribution to N1-N10 is allowed only through canonical R1 lineage:
usage.assignment -> worker session -> WorkItemAttemptBinding -> MissionNode.
Missing/ambiguous lineage is UNRESOLVED, never guessed. UNKNOWN usage is never
converted to zero.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Mapping, Optional

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_model_usage import install_rc72_token_usage_overlay
from .rc72_truth import install_rc72_truth_overlay
from .rc72_worker_lifecycle import install_rc72_worker_lifecycle_overlay


_ARTIFACT_TYPE = "rc72_usage_ledger"
_EVENT_TYPE = "RC72_USAGE_LEDGER_UPSERTED"
_BUCKET = "rc72_usage_ledgers"
_USAGE_ARTIFACT = "rc72_token_usage"
_SESSION_ARTIFACT = "rc72_worker_session"
_BINDING_ARTIFACT = "rc72_workitem_attempt_binding"
_NODE_ARTIFACT = "rc72_mission_node"
_TOKEN_FIELDS = (
    "input_tokens", "output_tokens", "total_tokens", "cached_input_tokens",
    "cache_read_tokens", "cache_write_tokens",
)
_LEDGER_STATUSES = {"EMPTY", "UNKNOWN", "PARTIAL", "MEASURED"}
_SOURCE_ARTIFACTS = (_USAGE_ARTIFACT, _SESSION_ARTIFACT, _BINDING_ARTIFACT, _NODE_ARTIFACT)


def _now() -> int:
    return int(time.time())


def _required(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("USAGE_LEDGER_%s_REQUIRED" % name.upper())
    return value.strip()


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _contracts.DomainValidationError("USAGE_LEDGER_%s_INVALID" % name.upper())
    return value


def _validate_optional_tokens(values: Any, name: str) -> Dict[str, Optional[int]]:
    if not isinstance(values, dict):
        raise _contracts.DomainValidationError("USAGE_LEDGER_%s_MUST_BE_OBJECT" % name.upper())
    out: Dict[str, Optional[int]] = {}
    for field in _TOKEN_FIELDS:
        value = values.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise _contracts.DomainValidationError("USAGE_LEDGER_%s_%s_INVALID" % (name.upper(), field.upper()))
        out[field] = value
    return out


def _validate_counter_counts(values: Any) -> Dict[str, int]:
    if not isinstance(values, dict):
        raise _contracts.DomainValidationError("USAGE_LEDGER_COUNTER_OBSERVATION_COUNTS_MUST_BE_OBJECT")
    return {
        field: _nonnegative_int(values.get(field), "COUNTER_OBSERVATION_COUNTS_%s" % field)
        for field in _TOKEN_FIELDS
    }


def validate_rc72_usage_ledger(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in ("usage_ledger_id", "release_id", "mission_id", "status", "source_digest"):
        out[name] = _contracts._require_str(out, name)
    out["status"] = out["status"].upper()
    if out["status"] not in _LEDGER_STATUSES:
        raise _contracts.DomainValidationError("USAGE_LEDGER_STATUS_INVALID")
    for name in (
        "source_usage_count", "measured_usage_count", "unknown_usage_count",
        "resolved_lineage_count", "unresolved_lineage_count", "built_at",
    ):
        out[name] = _nonnegative_int(out.get(name), name)
    if out["source_usage_count"] != out["measured_usage_count"] + out["unknown_usage_count"]:
        raise _contracts.DomainValidationError("USAGE_LEDGER_OBSERVATION_COUNTS_INCONSISTENT")
    if out["source_usage_count"] != out["resolved_lineage_count"] + out["unresolved_lineage_count"]:
        raise _contracts.DomainValidationError("USAGE_LEDGER_LINEAGE_COUNTS_INCONSISTENT")
    out["tokens"] = _validate_optional_tokens(out.get("tokens"), "TOKENS")
    out["counter_observation_counts"] = _validate_counter_counts(out.get("counter_observation_counts"))
    for name in ("node_summaries", "workitem_summaries", "attempt_summaries", "receipts", "unresolved_lineages"):
        value = out.get(name)
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise _contracts.DomainValidationError("USAGE_LEDGER_%s_INVALID" % name.upper())
    if out["status"] == "EMPTY" and out["source_usage_count"] != 0:
        raise _contracts.DomainValidationError("USAGE_LEDGER_EMPTY_WITH_USAGE")
    if out["status"] == "UNKNOWN" and (out["source_usage_count"] == 0 or out["measured_usage_count"] != 0):
        raise _contracts.DomainValidationError("USAGE_LEDGER_UNKNOWN_STATUS_INCONSISTENT")
    if out["status"] == "MEASURED" and (
        out["source_usage_count"] == 0 or out["unknown_usage_count"] != 0 or out["unresolved_lineage_count"] != 0
    ):
        raise _contracts.DomainValidationError("USAGE_LEDGER_MEASURED_STATUS_INCONSISTENT")
    version = out.get("artifact_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contracts.DomainValidationError("USAGE_LEDGER_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version
    out["artifact_type"] = _ARTIFACT_TYPE
    return out


def install_rc72_usage_ledger_overlay() -> None:
    install_rc72_truth_overlay()
    install_rc72_worker_lifecycle_overlay()
    install_rc72_token_usage_overlay()
    _contracts.VALIDATORS[_ARTIFACT_TYPE] = validate_rc72_usage_ledger
    _truth.BUCKETS[_ARTIFACT_TYPE] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT_TYPE] = "usage_ledger_id"
    _truth.EVENT_TYPES[_EVENT_TYPE] = (_ARTIFACT_TYPE, "usage_ledger_id")


def _ensure_projection_buckets(truth: TruthRuntime) -> None:
    """Add only missing empty buckets when overlays are installed after R1 boot.

    Existing source events can only have been appended after their overlay was
    installed, so their projection buckets already exist. This helper covers the
    legitimate empty-source case without resetting/replaying or mutating truth.
    """
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    artifact_types = (_ARTIFACT_TYPE,) + _SOURCE_ARTIFACTS
    for artifact_type in artifact_types:
        bucket = _truth.BUCKETS[artifact_type]
        if not hasattr(projection, bucket):
            setattr(projection, bucket, {})
        versions = getattr(projection, "_versions", None)
        if isinstance(versions, dict):
            versions.setdefault(artifact_type, {})


def _ledger_id(release_id: str, mission_id: str) -> str:
    digest = hashlib.sha256((release_id + "\x1f" + mission_id).encode("utf-8")).hexdigest()[:24]
    return "USAGELEDGER-" + digest


def _summary() -> Dict[str, Any]:
    return {
        "call_count": 0,
        "measured_call_count": 0,
        "unknown_call_count": 0,
        "tokens": {field: None for field in _TOKEN_FIELDS},
        "counter_observation_counts": {field: 0 for field in _TOKEN_FIELDS},
    }


def _add_usage(summary: Dict[str, Any], usage: Mapping[str, Any]) -> None:
    summary["call_count"] += 1
    if usage.get("observation_status") == "OBSERVED":
        summary["measured_call_count"] += 1
    else:
        summary["unknown_call_count"] += 1
    for field in _TOKEN_FIELDS:
        value = usage.get(field)
        if value is None:
            continue
        previous = summary["tokens"][field]
        summary["counter_observation_counts"][field] += 1
        summary["tokens"][field] = value if previous is None else previous + value


def _finalize_scoped(summaries: Dict[str, Dict[str, Any]], key_name: str) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for key in sorted(summaries):
        row = dict(summaries[key])
        row[key_name] = key
        result.append(row)
    return result


class UsageLedgerService:
    """Build and persist an honest Mission/N/WorkItem/Attempt usage ledger."""

    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_usage_ledger_overlay()
        _ensure_projection_buckets(truth)
        self.truth = truth
        self.release_id = _required(release_id, "release_id")

    def _resolve_lineage(self, usage: Mapping[str, Any]) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "lineage_status": "UNRESOLVED", "lineage_reason": None,
            "lifecycle_session_id": None, "worker_id": None, "release_batch_id": None,
            "binding_id": None, "workitem_id": None, "etu_id": None,
            "mission_node_id": None, "mission_node_type": None,
        }
        sessions = self.truth.query(_SESSION_ARTIFACT, runtime_assignment_id=usage.get("assignment_id"))
        if len(sessions) != 1:
            base["lineage_reason"] = "WORKER_SESSION_NOT_UNIQUE:%d" % len(sessions)
            return base
        session = sessions[0]
        base.update({
            "lifecycle_session_id": session.get("session_id"),
            "worker_id": session.get("runtime_worker_id") or session.get("worker_id"),
            "release_batch_id": session.get("release_batch_id"),
            "binding_id": session.get("binding_id"),
            "workitem_id": session.get("workitem_id"),
            "etu_id": session.get("etu_id"),
        })
        for actual, expected, reason in (
            (session.get("release_id"), usage.get("release_id"), "WORKER_SESSION_RELEASE_MISMATCH"),
            (session.get("mission_id"), usage.get("mission_id"), "WORKER_SESSION_MISSION_MISMATCH"),
            (session.get("runtime_attempt_id"), usage.get("attempt_id"), "WORKER_SESSION_ATTEMPT_MISMATCH"),
        ):
            if actual != expected:
                base["lineage_reason"] = reason
                return base
        usage_dsh, session_dsh = usage.get("dsh_session_id"), session.get("dsh_session_id")
        if usage_dsh and session_dsh and usage_dsh != session_dsh:
            base["lineage_reason"] = "WORKER_SESSION_DSH_SESSION_MISMATCH"
            return base
        binding_id = session.get("binding_id")
        if not isinstance(binding_id, str) or not binding_id.strip():
            base["lineage_reason"] = "WORKER_SESSION_BINDING_MISSING"
            return base
        bindings = self.truth.query(_BINDING_ARTIFACT, binding_id=binding_id)
        if len(bindings) != 1:
            base["lineage_reason"] = "WORKITEM_BINDING_NOT_UNIQUE:%d" % len(bindings)
            return base
        binding = bindings[0]
        for actual, expected, reason in (
            (binding.get("mission_id"), usage.get("mission_id"), "WORKITEM_BINDING_MISSION_MISMATCH"),
            (binding.get("attempt_id"), usage.get("attempt_id"), "WORKITEM_BINDING_ATTEMPT_MISMATCH"),
            (binding.get("workitem_id"), session.get("workitem_id"), "WORKITEM_BINDING_WORKITEM_MISMATCH"),
            (binding.get("etu_id"), session.get("etu_id"), "WORKITEM_BINDING_ETU_MISMATCH"),
        ):
            if actual != expected:
                base["lineage_reason"] = reason
                return base
        if binding.get("session_id") and binding.get("session_id") != session.get("session_id"):
            base["lineage_reason"] = "WORKITEM_BINDING_SESSION_MISMATCH"
            return base
        if binding.get("mission_node_lineage_status") != "RESOLVED":
            base["lineage_reason"] = "WORKITEM_BINDING_MISSION_NODE_LINEAGE_UNRESOLVED"
            return base
        node_id, node_type = binding.get("mission_node_id"), binding.get("mission_node_type")
        if not isinstance(node_id, str) or not node_id.strip() or not isinstance(node_type, str) or not node_type.strip():
            base["lineage_reason"] = "WORKITEM_BINDING_MISSION_NODE_MISSING"
            return base
        nodes = self.truth.query(_NODE_ARTIFACT, mission_node_id=node_id)
        if len(nodes) != 1:
            base["lineage_reason"] = "MISSION_NODE_NOT_UNIQUE:%d" % len(nodes)
            return base
        node = nodes[0]
        if node.get("mission_id") != usage.get("mission_id") or node.get("node_type") != node_type:
            base["lineage_reason"] = "MISSION_NODE_LINEAGE_MISMATCH"
            return base
        base["mission_node_id"] = node_id
        base["mission_node_type"] = node_type
        base["lineage_status"] = "RESOLVED"
        return base

    def build(self, *, mission_id: str, persist: bool = True) -> Dict[str, Any]:
        mission_id = _required(mission_id, "mission_id")
        usages = sorted(
            self.truth.query(_USAGE_ARTIFACT, release_id=self.release_id, mission_id=mission_id),
            key=lambda row: str(row.get("token_usage_id", "")),
        )
        mission_summary = _summary()
        node_summaries: Dict[str, Dict[str, Any]] = {}
        workitem_summaries: Dict[str, Dict[str, Any]] = {}
        attempt_summaries: Dict[str, Dict[str, Any]] = {}
        receipts: List[Dict[str, Any]] = []
        unresolved: List[Dict[str, Any]] = []
        resolved_count = 0
        for usage in usages:
            _add_usage(mission_summary, usage)
            lineage = self._resolve_lineage(usage)
            receipt = {
                "token_usage_id": usage.get("token_usage_id"),
                "assignment_id": usage.get("assignment_id"),
                "attempt_id": usage.get("attempt_id"),
                "dsh_session_id": usage.get("dsh_session_id"),
                "provider": usage.get("provider"), "model": usage.get("model"),
                "observation_status": usage.get("observation_status"),
                "unknown_reason": usage.get("unknown_reason"),
                "tokens": {field: usage.get(field) for field in _TOKEN_FIELDS},
            }
            receipt.update(lineage)
            receipts.append(receipt)
            if lineage["lineage_status"] != "RESOLVED":
                unresolved.append({
                    "token_usage_id": usage.get("token_usage_id"),
                    "assignment_id": usage.get("assignment_id"),
                    "reason": lineage.get("lineage_reason"),
                })
                continue
            resolved_count += 1
            node_id = str(lineage["mission_node_id"])
            workitem_id = str(lineage["workitem_id"])
            attempt_id = str(usage.get("attempt_id"))
            node_summary = node_summaries.setdefault(node_id, _summary())
            node_summary["mission_node_type"] = lineage["mission_node_type"]
            _add_usage(node_summary, usage)
            _add_usage(workitem_summaries.setdefault(workitem_id, _summary()), usage)
            _add_usage(attempt_summaries.setdefault(attempt_id, _summary()), usage)

        source_count = len(usages)
        measured_count = mission_summary["measured_call_count"]
        unknown_count = mission_summary["unknown_call_count"]
        unresolved_count = source_count - resolved_count
        if source_count == 0:
            status = "EMPTY"
        elif measured_count == 0:
            status = "UNKNOWN"
        elif unknown_count or unresolved_count:
            status = "PARTIAL"
        else:
            status = "MEASURED"
        node_rows = _finalize_scoped(node_summaries, "mission_node_id")
        workitem_rows = _finalize_scoped(workitem_summaries, "workitem_id")
        attempt_rows = _finalize_scoped(attempt_summaries, "attempt_id")
        digest_payload = {
            "release_id": self.release_id, "mission_id": mission_id, "status": status,
            "mission_summary": mission_summary, "node_summaries": node_rows,
            "workitem_summaries": workitem_rows, "attempt_summaries": attempt_rows,
            "receipts": receipts, "unresolved_lineages": unresolved,
        }
        source_digest = hashlib.sha256(
            json.dumps(digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        payload: Dict[str, Any] = {
            "usage_ledger_id": _ledger_id(self.release_id, mission_id),
            "release_id": self.release_id, "mission_id": mission_id, "status": status,
            "source_digest": source_digest, "source_usage_count": source_count,
            "measured_usage_count": measured_count, "unknown_usage_count": unknown_count,
            "resolved_lineage_count": resolved_count, "unresolved_lineage_count": unresolved_count,
            "tokens": mission_summary["tokens"],
            "counter_observation_counts": mission_summary["counter_observation_counts"],
            "node_summaries": node_rows, "workitem_summaries": workitem_rows,
            "attempt_summaries": attempt_rows, "receipts": receipts,
            "unresolved_lineages": unresolved, "built_at": _now(),
        }
        if not persist:
            payload["artifact_version"] = 1
            payload["artifact_type"] = _ARTIFACT_TYPE
            return payload
        return self._persist(payload)

    def _persist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ledger_id = str(payload["usage_ledger_id"])
        existing = self.truth.query(_ARTIFACT_TYPE, usage_ledger_id=ledger_id)
        if len(existing) > 1:
            raise ContractError("USAGE_LEDGER_TRUTH_NOT_UNIQUE")
        if existing and existing[0].get("source_digest") == payload.get("source_digest"):
            return existing[0]
        payload["artifact_version"] = int(existing[0].get("artifact_version", 1)) + 1 if existing else 1
        self.truth.append_atomic(_EVENT_TYPE, payload)
        rows = self.truth.query(_ARTIFACT_TYPE, usage_ledger_id=ledger_id)
        if len(rows) != 1:
            raise ContractError("USAGE_LEDGER_PERSISTENCE_FAILED")
        return rows[0]
