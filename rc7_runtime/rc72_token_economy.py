"""RC7.2 mission-level token economy control.

Additive control over the mature RC7 worker/evaluator runtime:
- durable ReleaseBatch/Mission model-call budgets in canonical R1;
- exact prompt fingerprints to expose repeated-context amplification;
- actual DSH JSONL usage capture when unambiguous;
- UNKNOWN rather than guessed usage;
- fail-closed Q7 qualification;
- a transparent launcher wrapper, so existing DSH worker/session semantics stay intact.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime


_TOKEN_BUDGET = "rc72_token_budget"
_TOKEN_CALL = "rc72_token_call"
_EVENT_TYPES = {
    "RC72_TOKEN_BUDGET_UPSERTED": (_TOKEN_BUDGET, "budget_id"),
    "RC72_TOKEN_CALL_UPSERTED": (_TOKEN_CALL, "call_id"),
}
_BUCKETS = {
    _TOKEN_BUDGET: "rc72_token_budgets",
    _TOKEN_CALL: "rc72_token_calls",
}


class TokenEconomyError(RuntimeError):
    pass


class ModelCallClass(str, Enum):
    LLM_REQUIRED = "LLM_REQUIRED"
    LLM_BATCHABLE = "LLM_BATCHABLE"
    DETERMINISTIC_NO_LLM = "DETERMINISTIC_NO_LLM"


class UsageStatus(str, Enum):
    PENDING = "PENDING"
    MEASURED = "MEASURED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DshTokenUsage:
    status: UsageStatus
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    source: str = "UNKNOWN"

    @classmethod
    def unknown(cls, source: str) -> "DshTokenUsage":
        return cls(status=UsageStatus.UNKNOWN, source=source)


@dataclass(frozen=True)
class TokenAdmission:
    admitted: bool
    call_id: str
    reason: str
    reserved_tokens: int


@dataclass(frozen=True)
class TokenQualification:
    status: str
    mission_id: str
    reason: str
    metrics: Mapping[str, Any]


def _now() -> int:
    return int(time.time())


def _new(prefix: str) -> str:
    return "%s-%s" % (prefix, uuid.uuid4().hex[:20])


def _required(out: Dict[str, Any], name: str) -> str:
    return _contracts._require_str(out, name)


def _nonnegative_int(out: Dict[str, Any], name: str) -> int:
    value = out.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    return value


def _positive_int(out: Dict[str, Any], name: str) -> int:
    value = _nonnegative_int(out, name)
    if value < 1:
        raise _contracts.DomainValidationError("%s_REQUIRED" % name.upper())
    return value


def _boolean(out: Dict[str, Any], name: str) -> bool:
    value = out.get(name)
    if not isinstance(value, bool):
        raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    return value


def _base(payload: Dict[str, Any], artifact_type: str, identity: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    out[identity] = _required(out, identity)
    out["release_id"] = _required(out, "release_id")
    out["artifact_type"] = artifact_type
    out["artifact_version"] = _contracts._artifact_version(out)
    return out


def _validate_budget(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _TOKEN_BUDGET, "budget_id")
    out["mission_id"] = _required(out, "mission_id")
    out["state"] = _required(out, "state").upper()
    if out["state"] not in {"ACTIVE", "RETIRED"}:
        raise _contracts.DomainValidationError("TOKEN_BUDGET_STATE_INVALID")
    for name in ("max_total_tokens", "max_model_calls", "max_single_call_tokens", "max_same_context_calls"):
        out[name] = _positive_int(out, name)
    for name in ("max_retry_tokens", "max_retry_calls"):
        out[name] = _nonnegative_int(out, name)
    out["require_measured_usage"] = _boolean(out, "require_measured_usage")
    out["require_complete_lineage"] = _boolean(out, "require_complete_lineage")
    out["created_at"] = _nonnegative_int(out, "created_at")
    out["updated_at"] = _nonnegative_int(out, "updated_at")
    return out


def _validate_call(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = _base(payload, _TOKEN_CALL, "call_id")
    for name in (
        "mission_id", "node", "stage", "workitem_id", "attempt_id", "agent_id",
        "call_class", "state", "usage_status", "usage_source",
        "context_sha256", "reason",
    ):
        out[name] = _required(out, name)
    if out["call_class"] not in {item.value for item in ModelCallClass}:
        raise _contracts.DomainValidationError("TOKEN_CALL_CLASS_INVALID")
    if out["state"] not in {"ADMITTED", "COMPLETED", "COMPLETED_UNKNOWN", "BLOCKED"}:
        raise _contracts.DomainValidationError("TOKEN_CALL_STATE_INVALID")
    if out["usage_status"] not in {item.value for item in UsageStatus}:
        raise _contracts.DomainValidationError("TOKEN_USAGE_STATUS_INVALID")
    out["retry"] = _boolean(out, "retry")
    for name in (
        "context_bytes", "reserved_tokens", "input_tokens", "output_tokens",
        "total_tokens", "created_at", "updated_at",
    ):
        out[name] = _nonnegative_int(out, name)
    if len(out["context_sha256"]) != 64:
        raise _contracts.DomainValidationError("TOKEN_CONTEXT_SHA256_INVALID")
    if out["usage_status"] == "MEASURED" and out["total_tokens"] < 1:
        raise _contracts.DomainValidationError("MEASURED_TOKEN_USAGE_REQUIRED")
    if out["state"] == "ADMITTED" and out["usage_status"] != "PENDING":
        raise _contracts.DomainValidationError("ADMITTED_TOKEN_CALL_MUST_BE_PENDING")
    if out["state"] == "COMPLETED" and out["usage_status"] != "MEASURED":
        raise _contracts.DomainValidationError("COMPLETED_TOKEN_CALL_MUST_BE_MEASURED")
    if out["state"] == "COMPLETED_UNKNOWN" and out["usage_status"] != "UNKNOWN":
        raise _contracts.DomainValidationError("UNKNOWN_TOKEN_CALL_STATUS_MISMATCH")
    return out


def install_rc72_token_economy_overlay() -> None:
    for artifact_type, validator in {
        _TOKEN_BUDGET: _validate_budget,
        _TOKEN_CALL: _validate_call,
    }.items():
        _contracts.VALIDATORS[artifact_type] = validator
        _truth.BUCKETS[artifact_type] = _BUCKETS[artifact_type]
    for event_type, (artifact_type, identity) in _EVENT_TYPES.items():
        _truth.EVENT_TYPES[event_type] = (artifact_type, identity)
        _truth.IDENTITY_FIELDS[artifact_type] = identity


def _ensure_projection_buckets(truth: TruthRuntime) -> None:
    projection = truth.projection
    for artifact_type, bucket in _BUCKETS.items():
        if not hasattr(projection, bucket):
            setattr(projection, bucket, {})
        projection._versions.setdefault(artifact_type, {})


install_rc72_token_economy_overlay()


def _usage_candidate(mapping: Mapping[str, Any]) -> Optional[Tuple[int, int, int]]:
    def first_int(names: Sequence[str]) -> Optional[int]:
        for name in names:
            value = mapping.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        return None

    input_tokens = first_int(("input_tokens", "prompt_tokens", "inputTokens", "promptTokens"))
    output_tokens = first_int(("output_tokens", "completion_tokens", "outputTokens", "completionTokens"))
    total_tokens = first_int(("total_tokens", "totalTokens"))
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    if total_tokens is None or total_tokens < 1:
        return None
    return (input_tokens or 0, output_tokens or 0, total_tokens)


def _walk_usage(value: Any) -> Iterable[Tuple[int, int, int]]:
    if isinstance(value, Mapping):
        candidate = _usage_candidate(value)
        if candidate is not None:
            yield candidate
        for child in value.values():
            for found in _walk_usage(child):
                yield found
    elif isinstance(value, list):
        for child in value:
            for found in _walk_usage(child):
                yield found


_FINAL_EVENT_MARKERS = ("complete", "completed", "result", "final", "message_end", "response_end")


def extract_dsh_token_usage(text: str) -> DshTokenUsage:
    """Return MEASURED only for an unambiguous provider usage observation."""
    candidates: List[Tuple[int, int, int]] = []
    final_candidates: List[Tuple[int, int, int]] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(event, Mapping):
            continue
        found = list(_walk_usage(event))
        if not found:
            continue
        candidates.extend(found)
        marker = " ".join(
            str(event.get(key) or "").lower()
            for key in ("type", "event", "event_type", "name", "status")
        )
        if any(item in marker for item in _FINAL_EVENT_MARKERS):
            final_candidates.extend(found)
    pool = final_candidates or candidates
    if not pool:
        return DshTokenUsage.unknown("DSH_USAGE_NOT_EMITTED")
    unique: List[Tuple[int, int, int]] = []
    for item in pool:
        if item not in unique:
            unique.append(item)
    if len(unique) != 1:
        return DshTokenUsage.unknown("DSH_USAGE_AMBIGUOUS_MULTIPLE_SNAPSHOTS")
    input_tokens, output_tokens, total_tokens = unique[0]
    return DshTokenUsage(
        UsageStatus.MEASURED,
        input_tokens,
        output_tokens,
        total_tokens,
        "DSH_FINAL_USAGE" if final_candidates else "DSH_SINGLE_USAGE",
    )


class TokenEconomyService:
    """Durable Mission token budget and usage ledger backed by canonical R1."""

    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_token_economy_overlay()
        _ensure_projection_buckets(truth)
        if not isinstance(release_id, str) or not release_id.strip():
            raise TokenEconomyError("TOKEN_ECONOMY_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()

    def _append(self, event_type: str, payload: Dict[str, Any]) -> None:
        out = dict(payload)
        out["release_id"] = self.release_id
        out.setdefault("artifact_version", 1)
        self.truth.append_atomic(event_type, out)

    def configure_budget(
        self,
        *,
        mission_id: str,
        max_total_tokens: int,
        max_model_calls: int,
        max_single_call_tokens: int,
        max_retry_tokens: int,
        max_retry_calls: int,
        max_same_context_calls: int = 2,
        require_measured_usage: bool = True,
        require_complete_lineage: bool = True,
    ) -> Dict[str, Any]:
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise TokenEconomyError("TOKEN_BUDGET_MISSION_ID_REQUIRED")
        budget_id = mission_id.strip()
        existing = self.truth.query(_TOKEN_BUDGET, budget_id=budget_id)
        now = _now()
        version = int(existing[0].get("artifact_version", 0)) + 1 if existing else 1
        created_at = int(existing[0].get("created_at", now)) if existing else now
        payload = {
            "budget_id": budget_id,
            "mission_id": mission_id.strip(),
            "state": "ACTIVE",
            "max_total_tokens": max_total_tokens,
            "max_model_calls": max_model_calls,
            "max_single_call_tokens": max_single_call_tokens,
            "max_retry_tokens": max_retry_tokens,
            "max_retry_calls": max_retry_calls,
            "max_same_context_calls": max_same_context_calls,
            "require_measured_usage": require_measured_usage,
            "require_complete_lineage": require_complete_lineage,
            "created_at": created_at,
            "updated_at": now,
            "artifact_version": version,
        }
        self._append("RC72_TOKEN_BUDGET_UPSERTED", payload)
        return self.truth.query(_TOKEN_BUDGET, budget_id=budget_id)[0]

    def _budget(self, mission_id: str) -> Dict[str, Any]:
        rows = self.truth.query(_TOKEN_BUDGET, budget_id=mission_id)
        if len(rows) != 1 or rows[0].get("state") != "ACTIVE":
            raise TokenEconomyError("TOKEN_BUDGET_REQUIRED:%s" % mission_id)
        return rows[0]

    def _calls(self, mission_id: str) -> List[Dict[str, Any]]:
        return list(self.truth.query(_TOKEN_CALL, mission_id=mission_id))

    def summary(self, mission_id: str) -> Dict[str, Any]:
        calls = self._calls(mission_id)
        model_calls = [row for row in calls if row.get("state") != "BLOCKED"]
        pending = [row for row in model_calls if row.get("usage_status") == "PENDING"]
        unknown = [row for row in model_calls if row.get("usage_status") == "UNKNOWN"]
        measured = [row for row in model_calls if row.get("usage_status") == "MEASURED"]
        retries = [row for row in model_calls if bool(row.get("retry"))]
        measured_total = sum(int(row.get("total_tokens", 0)) for row in measured)
        retry_measured = sum(
            int(row.get("total_tokens", 0))
            for row in retries if row.get("usage_status") == "MEASURED"
        )
        pending_reserved = sum(int(row.get("reserved_tokens", 0)) for row in pending)
        unknown_reserved = sum(int(row.get("reserved_tokens", 0)) for row in unknown)
        retry_reserved = sum(
            int(row.get("reserved_tokens", 0))
            for row in retries if row.get("usage_status") != "MEASURED"
        )
        total_context_bytes = sum(int(row.get("context_bytes", 0)) for row in model_calls)
        seen: Dict[str, int] = {}
        for row in model_calls:
            digest = str(row.get("context_sha256") or "")
            if digest and digest not in seen:
                seen[digest] = int(row.get("context_bytes", 0))
        unique_context_bytes = sum(seen.values())
        lineage_unknown = [
            row["call_id"]
            for row in model_calls
            if any(str(row.get(name) or "").upper() == "UNKNOWN" for name in ("node", "stage", "workitem_id"))
        ]
        return {
            "mission_id": mission_id,
            "model_calls": len(model_calls),
            "blocked_calls": len(calls) - len(model_calls),
            "pending_calls": len(pending),
            "unknown_usage_calls": len(unknown),
            "measured_calls": len(measured),
            "measured_total_tokens": measured_total,
            "pending_reserved_tokens": pending_reserved,
            "unknown_reserved_tokens": unknown_reserved,
            "effective_total_tokens": measured_total + pending_reserved + unknown_reserved,
            "retry_calls": len(retries),
            "retry_measured_tokens": retry_measured,
            "retry_effective_tokens": retry_measured + retry_reserved,
            "total_context_bytes": total_context_bytes,
            "unique_context_bytes": unique_context_bytes,
            "context_reuse_factor": (
                float(total_context_bytes) / float(unique_context_bytes)
                if unique_context_bytes else 0.0
            ),
            "unknown_lineage_call_ids": lineage_unknown,
        }

    def admit_call(
        self,
        *,
        mission_id: str,
        node: str,
        stage: str,
        workitem_id: str,
        attempt_id: str,
        agent_id: str,
        call_class: ModelCallClass,
        retry: bool,
        prompt: str,
    ) -> TokenAdmission:
        budget = self._budget(mission_id)
        if not isinstance(call_class, ModelCallClass):
            call_class = ModelCallClass(str(call_class).upper())
        prompt_bytes = prompt.encode("utf-8")
        digest = hashlib.sha256(prompt_bytes).hexdigest()
        summary = self.summary(mission_id)
        reason, admitted = "ADMITTED", True
        reserve = int(budget["max_single_call_tokens"])

        if call_class == ModelCallClass.DETERMINISTIC_NO_LLM:
            admitted, reason = False, "DETERMINISTIC_STEP_MUST_NOT_USE_LLM"
        elif bool(budget["require_measured_usage"]) and summary["unknown_usage_calls"]:
            admitted, reason = False, "PRIOR_TOKEN_USAGE_UNKNOWN"
        elif summary["model_calls"] >= int(budget["max_model_calls"]):
            admitted, reason = False, "MISSION_MODEL_CALL_BUDGET_EXHAUSTED"
        elif summary["effective_total_tokens"] + reserve > int(budget["max_total_tokens"]):
            admitted, reason = False, "MISSION_TOKEN_BUDGET_EXHAUSTED"
        elif retry and summary["retry_calls"] >= int(budget["max_retry_calls"]):
            admitted, reason = False, "MISSION_RETRY_CALL_BUDGET_EXHAUSTED"
        elif retry and summary["retry_effective_tokens"] + reserve > int(budget["max_retry_tokens"]):
            admitted, reason = False, "MISSION_RETRY_TOKEN_BUDGET_EXHAUSTED"
        else:
            same_context = [
                row for row in self._calls(mission_id)
                if row.get("state") != "BLOCKED" and row.get("context_sha256") == digest
            ]
            if len(same_context) >= int(budget["max_same_context_calls"]):
                admitted, reason = False, "SAME_CONTEXT_CALL_BUDGET_EXHAUSTED"

        call_id = _new("TOKCALL")
        now = _now()
        self._append("RC72_TOKEN_CALL_UPSERTED", {
            "call_id": call_id,
            "mission_id": mission_id,
            "node": node or "UNKNOWN",
            "stage": stage or "UNKNOWN",
            "workitem_id": workitem_id or "UNKNOWN",
            "attempt_id": attempt_id or "UNKNOWN",
            "agent_id": agent_id or "UNKNOWN",
            "call_class": call_class.value,
            "retry": bool(retry),
            "context_sha256": digest,
            "context_bytes": len(prompt_bytes),
            "reserved_tokens": reserve if admitted else 0,
            "state": "ADMITTED" if admitted else "BLOCKED",
            "usage_status": "PENDING",
            "usage_source": "AWAITING_DSH_USAGE" if admitted else "NOT_EXECUTED",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "reason": reason,
            "created_at": now,
            "updated_at": now,
            "artifact_version": 1,
        })
        return TokenAdmission(admitted, call_id, reason, reserve if admitted else 0)

    def complete_call(self, call_id: str, usage: DshTokenUsage) -> Dict[str, Any]:
        rows = self.truth.query(_TOKEN_CALL, call_id=call_id)
        if len(rows) != 1:
            raise TokenEconomyError("TOKEN_CALL_NOT_FOUND:%s" % call_id)
        current = rows[0]
        if current.get("state") != "ADMITTED":
            raise TokenEconomyError("TOKEN_CALL_NOT_ADMITTED:%s" % call_id)
        if not isinstance(usage, DshTokenUsage):
            usage = DshTokenUsage.unknown("INVALID_USAGE_OBJECT")
        updated = dict(current)
        updated.pop("artifact_type", None)
        updated["artifact_version"] = int(current.get("artifact_version", 1)) + 1
        updated["updated_at"] = _now()
        updated["usage_status"] = usage.status.value
        updated["usage_source"] = usage.source
        updated["input_tokens"] = int(usage.input_tokens)
        updated["output_tokens"] = int(usage.output_tokens)
        updated["total_tokens"] = int(usage.total_tokens)
        if usage.status == UsageStatus.MEASURED:
            updated["state"] = "COMPLETED"
            updated["reason"] = "DSH_USAGE_MEASURED"
        else:
            updated["state"] = "COMPLETED_UNKNOWN"
            updated["reason"] = "DSH_USAGE_UNKNOWN"
        self._append("RC72_TOKEN_CALL_UPSERTED", updated)
        return self.truth.query(_TOKEN_CALL, call_id=call_id)[0]

    def qualification(self, mission_id: str) -> TokenQualification:
        try:
            budget = self._budget(mission_id)
        except TokenEconomyError as exc:
            return TokenQualification("HOLD", mission_id, str(exc), self.summary(mission_id))
        metrics = self.summary(mission_id)
        status, reason = "PASS", "TOKEN_ECONOMY_PASS"
        if not metrics["model_calls"]:
            status, reason = "HOLD", "TOKEN_USAGE_EVIDENCE_REQUIRED"
        elif metrics["pending_calls"]:
            status, reason = "HOLD", "TOKEN_CALLS_PENDING"
        elif bool(budget["require_measured_usage"]) and metrics["unknown_usage_calls"]:
            status, reason = "HOLD", "TOKEN_USAGE_UNKNOWN"
        elif bool(budget["require_complete_lineage"]) and metrics["unknown_lineage_call_ids"]:
            status, reason = "HOLD", "TOKEN_CALL_LINEAGE_INCOMPLETE"
        elif metrics["effective_total_tokens"] > int(budget["max_total_tokens"]):
            status, reason = "BLOCKED", "MISSION_TOKEN_BUDGET_EXCEEDED"
        elif metrics["model_calls"] > int(budget["max_model_calls"]):
            status, reason = "BLOCKED", "MISSION_MODEL_CALL_BUDGET_EXCEEDED"
        elif metrics["retry_effective_tokens"] > int(budget["max_retry_tokens"]):
            status, reason = "BLOCKED", "MISSION_RETRY_TOKEN_BUDGET_EXCEEDED"
        elif metrics["retry_calls"] > int(budget["max_retry_calls"]):
            status, reason = "BLOCKED", "MISSION_RETRY_CALL_BUDGET_EXCEEDED"
        return TokenQualification(status, mission_id, reason, metrics)


MetadataResolver = Callable[[Any], Mapping[str, Any]]


class TokenMeteredDshLauncher:
    """Transparent token-governed wrapper for DshHeadlessWorkerLauncher."""

    def __init__(
        self,
        delegate: Any,
        economy: TokenEconomyService,
        *,
        metadata_resolver: Optional[MetadataResolver] = None,
    ) -> None:
        self.delegate = delegate
        self.economy = economy
        self.metadata_resolver = metadata_resolver

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    def assign(self, *args: Any, **kwargs: Any) -> Any:
        return self.delegate.assign(*args, **kwargs)

    @staticmethod
    def _raw_output_text(invocation: Any) -> Tuple[Optional[str], str]:
        for ref in list(getattr(invocation, "evidence_refs", []) or []):
            if not isinstance(ref, str) or not ref.startswith("file://"):
                continue
            path = Path(ref[len("file://"):])
            try:
                return path.read_text(encoding="utf-8"), ref
            except (OSError, UnicodeError):
                return None, ref
        return None, "NO_RAW_OUTPUT_REF"

    def execute(self, assignment: Any, prompt: str) -> Tuple[Any, Dict[str, Any]]:
        metadata = dict(self.metadata_resolver(assignment) if self.metadata_resolver else {})
        raw_class = metadata.get("call_class", ModelCallClass.LLM_REQUIRED.value)
        call_class = raw_class if isinstance(raw_class, ModelCallClass) else ModelCallClass(str(raw_class).upper())
        admission = self.economy.admit_call(
            mission_id=str(getattr(assignment, "mission_id", "") or metadata.get("mission_id") or ""),
            node=str(metadata.get("node") or "UNKNOWN"),
            stage=str(metadata.get("stage") or "UNKNOWN"),
            workitem_id=str(metadata.get("workitem_id") or "UNKNOWN"),
            attempt_id=str(getattr(assignment, "attempt_id", "") or metadata.get("attempt_id") or "UNKNOWN"),
            agent_id=str(getattr(assignment, "agent_id", "") or metadata.get("agent_id") or "UNKNOWN"),
            call_class=call_class,
            retry=bool(metadata.get("retry", False)),
            prompt=prompt,
        )
        if not admission.admitted:
            raise TokenEconomyError("TOKEN_CALL_BLOCKED:%s:%s" % (admission.call_id, admission.reason))
        try:
            invocation, output = self.delegate.execute(assignment, prompt)
        except Exception:
            self.economy.complete_call(
                admission.call_id,
                DshTokenUsage.unknown("DSH_EXECUTION_EXCEPTION_USAGE_UNKNOWN"),
            )
            raise
        raw_text, raw_ref = self._raw_output_text(invocation)
        usage = (
            extract_dsh_token_usage(raw_text)
            if raw_text is not None
            else DshTokenUsage.unknown("DSH_RAW_OUTPUT_UNREADABLE:%s" % raw_ref)
        )
        self.economy.complete_call(admission.call_id, usage)
        return invocation, output
