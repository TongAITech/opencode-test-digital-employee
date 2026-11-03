"""RC7.2 mission-completion-first model economy control.

This module is deliberately a horizontal runtime control:
- real ReleaseBatch/Mission model-call observations in canonical R1;
- exact prompt fingerprints to expose repeated-context amplification;
- actual DSH JSONL usage capture when unambiguous;
- UNKNOWN rather than guessed usage;
- bank-local quota-window classification;
- soft economy targets that WARN/replan instead of killing mandatory test work;
- hard guards only for invalid/wasteful calls such as deterministic misuse or
  exact repeated-context loops;
- a transparent launcher wrapper, so existing DSH worker/session semantics stay
  intact.

Mission completion/test sufficiency outrank token economy. Economy optimizes
HOW/WHEN/CONTEXT/BATCH/MODEL; it must not reduce WHAT MUST BE TESTED.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
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

_BANK_TZ_NAME = "Asia/Shanghai"
_BANK_TZ = timezone(timedelta(hours=8), name=_BANK_TZ_NAME)


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


class MissionCriticality(str, Enum):
    BLOCKING = "BLOCKING"
    NON_BLOCKING = "NON_BLOCKING"
    UNKNOWN = "UNKNOWN"


class SemanticCostClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
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
class BankCostWindow:
    name: str
    timezone_name: str
    quota_limited: bool
    quota_cost_factor_millis: int

    @property
    def quota_cost_factor(self) -> float:
        return float(self.quota_cost_factor_millis) / 1000.0


@dataclass(frozen=True)
class BankCostWindowConfig:
    """Bank-local *scheduling* configuration, not a mandatory-test kill switch.

    Asia/Shanghai is deliberately fixed rather than inferred from the host.
    Default 18:00-21:00 rate is 10:1; post-21:00 is quota-unlimited.
    """
    timezone_name: str = _BANK_TZ_NAME
    normal_end_hour: int = 18
    discount_end_hour: int = 21
    normal_factor_millis: int = 1000
    discount_factor_millis: int = 100
    unlimited_after_discount: bool = True
    post_discount_factor_millis: int = 0
    # Offline official bank calendar overrides: holidays may be weekdays,
    # compensatory working days may fall on weekends. Never use host timezone.
    non_working_dates: Tuple[str, ...] = ()
    makeup_work_dates: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.timezone_name != _BANK_TZ_NAME:
            raise TokenEconomyError("BANK_COST_WINDOW_TIMEZONE_MUST_BE_ASIA_SHANGHAI")
        if (
            isinstance(self.normal_end_hour, bool)
            or isinstance(self.discount_end_hour, bool)
            or not isinstance(self.normal_end_hour, int)
            or not isinstance(self.discount_end_hour, int)
            or not (0 < self.normal_end_hour < self.discount_end_hour <= 23)
        ):
            raise TokenEconomyError("BANK_COST_WINDOW_HOURS_INVALID")
        for name in ("normal_factor_millis", "discount_factor_millis", "post_discount_factor_millis"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value <= 100000):
                raise TokenEconomyError("BANK_COST_WINDOW_FACTOR_INVALID:%s" % name)
        if self.normal_factor_millis == 0 or self.discount_factor_millis == 0:
            raise TokenEconomyError("BANK_COST_WINDOW_LIMITED_FACTOR_REQUIRED")
        if not isinstance(self.unlimited_after_discount, bool):
            raise TokenEconomyError("BANK_COST_WINDOW_UNLIMITED_FLAG_INVALID")
        if self.unlimited_after_discount and self.post_discount_factor_millis != 0:
            raise TokenEconomyError("BANK_COST_WINDOW_UNLIMITED_FACTOR_MUST_BE_ZERO")
        if not self.unlimited_after_discount and self.post_discount_factor_millis == 0:
            raise TokenEconomyError("BANK_COST_WINDOW_LIMITED_FACTOR_REQUIRED")
        for name in ("non_working_dates", "makeup_work_dates"):
            raw = getattr(self, name)
            if not isinstance(raw, (list, tuple)) or any(
                not isinstance(v, str) or len(v) != 10
                or v[4:5] != "-" or v[7:8] != "-"
                for v in raw
            ):
                raise TokenEconomyError("BANK_COST_WINDOW_%s_INVALID" % name.upper())
            try:
                for item in raw:
                    if date.fromisoformat(item).isoformat() != item:
                        raise ValueError("noncanonical date")
            except ValueError as exc:
                raise TokenEconomyError("BANK_COST_WINDOW_%s_INVALID" % name.upper()) from exc
            if len(set(raw)) != len(raw):
                raise TokenEconomyError("BANK_COST_WINDOW_%s_DUPLICATE" % name.upper())
            object.__setattr__(self, name, tuple(sorted(raw)))
        if set(self.non_working_dates) & set(self.makeup_work_dates):
            raise TokenEconomyError("BANK_COST_WINDOW_CALENDAR_DATE_CONFLICT")

    def is_working_day(self, local_date: date) -> bool:
        day = local_date.isoformat()
        if day in self.makeup_work_dates:
            return True
        if day in self.non_working_dates:
            return False
        return local_date.weekday() < 5

    def as_mapping(self) -> Dict[str, Any]:
        return {
            "timezone_name": self.timezone_name,
            "normal_end_hour": self.normal_end_hour,
            "discount_end_hour": self.discount_end_hour,
            "normal_factor_millis": self.normal_factor_millis,
            "discount_factor_millis": self.discount_factor_millis,
            "unlimited_after_discount": self.unlimited_after_discount,
            "post_discount_factor_millis": self.post_discount_factor_millis,
            "non_working_dates": list(self.non_working_dates),
            "makeup_work_dates": list(self.makeup_work_dates),
        }

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "BankCostWindowConfig":
        if not isinstance(mapping, Mapping):
            raise TokenEconomyError("BANK_COST_WINDOW_CONFIGURATION_REQUIRED")
        allowed = {
            "timezone_name", "normal_end_hour", "discount_end_hour",
            "normal_factor_millis", "discount_factor_millis",
            "unlimited_after_discount", "post_discount_factor_millis",
            "non_working_dates", "makeup_work_dates",
        }
        unknown = set(mapping) - allowed
        if unknown:
            raise TokenEconomyError("BANK_COST_WINDOW_UNKNOWN_CONFIGURATION_KEYS")
        return cls(**dict(mapping))


@dataclass(frozen=True)
class TokenAdmission:
    admitted: bool
    call_id: str
    reason: str
    reserved_tokens: int
    warnings: Tuple[str, ...] = ()
    cost_window: str = "UNKNOWN"
    quota_limited: bool = True
    quota_cost_factor: float = 1.0
    schedule_recommendation: str = "RUN_NOW"


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


def classify_bank_cost_window(
    when: Optional[datetime] = None,
    *,
    config: Optional[BankCostWindowConfig] = None,
) -> BankCostWindow:
    """Classify the bank-local window independently of the machine timezone."""
    policy = config if config is not None else BankCostWindowConfig()
    if not isinstance(policy, BankCostWindowConfig):
        raise TokenEconomyError("BANK_COST_WINDOW_CONFIG_INVALID")
    current = when or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise TokenEconomyError("BANK_COST_WINDOW_REQUIRES_AWARE_DATETIME")
    local = current.astimezone(_BANK_TZ)
    if not policy.is_working_day(local.date()):
        # Whole non-working day: NO quota; includes weekends and explicitly
        # configured public holidays. Adjusted weekend workdays are excluded.
        return BankCostWindow(
            "BANK_NON_WORKING_DAY_UNLIMITED", _BANK_TZ_NAME, False, 0
        )
    standard = policy == BankCostWindowConfig()
    if local.hour >= policy.discount_end_hour:
        return BankCostWindow(
            ("BANK_AFTER_21_UNLIMITED" if standard else
             "BANK_AFTER_DISCOUNT_UNLIMITED" if policy.unlimited_after_discount
             else "BANK_AFTER_DISCOUNT_LIMITED"),
            _BANK_TZ_NAME,
            not policy.unlimited_after_discount,
            policy.post_discount_factor_millis,
        )
    if local.hour >= policy.normal_end_hour:
        return BankCostWindow(
            "BANK_18_21_TEN_TO_ONE" if standard else "BANK_CONFIGURED_DISCOUNT",
            _BANK_TZ_NAME,
            True,
            policy.discount_factor_millis,
        )
    return BankCostWindow(
        "BANK_DAYTIME_FULL_RATE" if standard else "BANK_CONFIGURED_NORMAL",
        _BANK_TZ_NAME,
        True,
        policy.normal_factor_millis,
    )


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
    for name in (
        "max_total_tokens", "max_model_calls", "max_single_call_tokens",
        "max_same_context_calls",
    ):
        out[name] = _positive_int(out, name)
    for name in ("max_retry_tokens", "max_retry_calls"):
        out[name] = _nonnegative_int(out, name)
    out["require_measured_usage"] = _boolean(out, "require_measured_usage")
    out["require_complete_lineage"] = _boolean(out, "require_complete_lineage")
    if "bank_cost_window_config" in out:
        try:
            out["bank_cost_window_config"] = BankCostWindowConfig.from_mapping(
                out["bank_cost_window_config"]
            ).as_mapping()
        except (TokenEconomyError, TypeError, ValueError) as exc:
            raise _contracts.DomainValidationError("BANK_COST_WINDOW_CONFIG_INVALID") from exc
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

    # Additive/backward-compatible fields. Older R1 events are projected with
    # safe defaults rather than becoming unreadable after this construction slice.
    # Per-native-process proof is separate from admission: a call can be
    # ADMITTED in R1 before any subprocess was actually launched. Older
    # R1 events remain UNKNOWN, never a fabricated successful process.
    # Projection describes *canonical references*, not whether the native
    # prompt actually consumed fewer tokens. Proof of prompt reduction must
    # come from native final prompt bytes, never from an inferred ref count.
    out.setdefault("context_projection_status", "NOT_BOUND")
    if out["context_projection_status"] not in {"NOT_BOUND", "REFERENCE_ONLY"}:
        raise _contracts.DomainValidationError("TOKEN_CONTEXT_PROJECTION_STATUS_INVALID")
    out.setdefault("context_projection_applied_to_prompt", False)
    if out["context_projection_applied_to_prompt"] is not False:
        raise _contracts.DomainValidationError("TOKEN_CONTEXT_SAVINGS_UNPROVEN")
    for name in (
        "context_canonical_ref_count", "context_effective_ref_count",
        "context_unhydrated_lineage_ref_count",
    ):
        out.setdefault(name, 0)
        out[name] = _nonnegative_int(out, name)
    if out["context_projection_status"] == "REFERENCE_ONLY":
        for name in ("context_envelope_id", "context_envelope_sha256", "context_mode"):
            out[name] = _required(out, name)
        if len(out["context_envelope_sha256"]) != 64:
            raise _contracts.DomainValidationError("TOKEN_CONTEXT_ENVELOPE_DIGEST_INVALID")
        if out["context_mode"] not in {"NORMAL", "RETRY_DELTA", "FULL_CONTEXT_RETRY", "RETRY_DELTA_UNKNOWN"}:
            raise _contracts.DomainValidationError("TOKEN_CONTEXT_PROJECTION_MODE_INVALID")
    out.setdefault("context_envelope_id", None)
    out.setdefault("context_envelope_sha256", None)
    out.setdefault("context_mode", "UNKNOWN")
    parent_attempt_id = out.get("parent_attempt_id")
    if parent_attempt_id is not None and (not isinstance(parent_attempt_id, str) or not parent_attempt_id.strip()):
        raise _contracts.DomainValidationError("TOKEN_CONTEXT_PARENT_ATTEMPT_INVALID")
    out.setdefault("process_outcome", "UNKNOWN")
    if out["process_outcome"] not in {"UNKNOWN", "NOT_STARTED", "RETURNED", "RAISED"}:
        raise _contracts.DomainValidationError("DSH_PROCESS_OUTCOME_INVALID")
    out.setdefault("economy_signal", "NONE")
    out.setdefault("cost_window", "UNKNOWN")
    out.setdefault("bank_timezone", _BANK_TZ_NAME)
    out.setdefault("mission_criticality", MissionCriticality.UNKNOWN.value)
    out.setdefault("semantic_cost_class", SemanticCostClass.UNKNOWN.value)
    out.setdefault("schedule_recommendation", "RUN_NOW")
    out.setdefault("quota_limited", True)
    out.setdefault("quota_cost_factor_millis", 1000)
    out.setdefault("quota_equivalent_tokens", 0)
    out["quota_limited"] = _boolean(out, "quota_limited")
    out["quota_cost_factor_millis"] = _nonnegative_int(out, "quota_cost_factor_millis")
    out["quota_equivalent_tokens"] = _nonnegative_int(out, "quota_equivalent_tokens")
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
        # Tool/MCP resource usage belongs to a tool, not the DSH provider.
        # Never charge it as measured model input even when it shares the
        # usual usage/token key names.
        kind = str(event.get("type") or event.get("event") or event.get("kind") or "").strip().lower()
        role = str(event.get("role") or "").strip().lower()
        if (kind in {"tool", "tool_call", "tool_result", "function_call", "function_result", "stderr", "session"}
                or kind.startswith(("tool.", "tool_", "mcp.", "mcp_", "function."))
                or role in {"tool", "user", "system"}):
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
    # Do not select a final snapshot over a conflicting earlier snapshot:
    # without bank DSH evidence we cannot know per-call vs cumulative usage.
    pool = candidates
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


Clock = Callable[[], datetime]


class TokenEconomyService:
    """Durable Mission economy targets and usage ledger backed by canonical R1.

    Budget fields are economy targets/telemetry. They are not Mission completion
    kill-switches. Hard admission rejection is reserved for correctness/waste
    guards.
    """

    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        clock: Optional[Clock] = None,
        cost_window_config: Optional[BankCostWindowConfig] = None,
    ) -> None:
        install_rc72_token_economy_overlay()
        _ensure_projection_buckets(truth)
        if not isinstance(release_id, str) or not release_id.strip():
            raise TokenEconomyError("TOKEN_ECONOMY_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cost_window_config = cost_window_config if cost_window_config is not None else BankCostWindowConfig()
        if not isinstance(self.cost_window_config, BankCostWindowConfig):
            raise TokenEconomyError("BANK_COST_WINDOW_CONFIG_INVALID")

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
            "bank_cost_window_config": self.cost_window_config.as_mapping(),
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

    @staticmethod
    def _quota_equivalent(tokens: int, factor_millis: int) -> int:
        if tokens <= 0 or factor_millis <= 0:
            return 0
        return (int(tokens) * int(factor_millis) + 999) // 1000

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
        measured_quota = sum(int(row.get("quota_equivalent_tokens", 0)) for row in measured)
        pending_quota = sum(
            self._quota_equivalent(
                int(row.get("reserved_tokens", 0)),
                int(row.get("quota_cost_factor_millis", 1000)),
            )
            for row in pending
        )
        unknown_quota = sum(
            self._quota_equivalent(
                int(row.get("reserved_tokens", 0)),
                int(row.get("quota_cost_factor_millis", 1000)),
            )
            for row in unknown
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
            if any(
                str(row.get(name) or "").upper() == "UNKNOWN"
                for name in ("node", "stage", "workitem_id")
            )
        ]
        warning_calls = [
            row for row in model_calls
            if str(row.get("economy_signal") or "NONE") != "NONE"
        ]
        deferred_recommended = [
            row for row in model_calls
            if row.get("schedule_recommendation") == "DEFER_RECOMMENDED"
        ]
        return {
            "mission_id": mission_id,
            "model_calls": len(model_calls),
            # An ADMITTED receipt is not evidence of a launched DSH process.
            # Count successful process returns only when the production
            # command boundary wrote an explicit outcome. Legacy direct
            # model-call receipts stay UNKNOWN rather than claiming launches.
            "dsh_process_invocations": (
                sum(row.get("process_outcome") == "RETURNED" for row in model_calls)
                if all(row.get("process_outcome") in {"RETURNED", "RAISED"} for row in model_calls)
                else None
            ),
            "dsh_process_invocation_count_status": (
                "MEASURED" if model_calls and all(
                    row.get("process_outcome") in {"RETURNED", "RAISED"} for row in model_calls
                ) else "UNKNOWN" if model_calls else "NO_CALLS"
            ),
            "dsh_process_launch_error_count": sum(
                row.get("process_outcome") == "RAISED" for row in model_calls
            ),
            "provider_inference_call_count": None,
            "provider_inference_call_count_status": (
                "UNKNOWN" if model_calls else "NO_CALLS"
            ),
            "blocked_calls": len(calls) - len(model_calls),
            "economy_warning_calls": len(warning_calls),
            "defer_recommended_calls": len(deferred_recommended),
            "pending_calls": len(pending),
            "unknown_usage_calls": len(unknown),
            "measured_calls": len(measured),
            # Legacy measured_total_tokens is only the measured SUBTOTAL.
            # Actual whole-Mission use is intentionally nullable: a partial
            # sample must never be displayed as a complete zero/total.
            "usage_total_status": (
                "UNKNOWN" if unknown else
                "PENDING" if pending else
                "MEASURED" if measured else "NO_CALLS"
            ),
            "actual_total_tokens": (
                measured_total if measured and not unknown and not pending else None
            ),
            "actual_quota_equivalent_tokens": (
                measured_quota if measured and not unknown and not pending else None
            ),
            "measured_total_tokens": measured_total,
            "pending_reserved_tokens": pending_reserved,
            "unknown_reserved_tokens": unknown_reserved,
            "effective_total_tokens": measured_total + pending_reserved + unknown_reserved,
            "measured_quota_equivalent_tokens": measured_quota,
            "pending_reserved_quota_equivalent_tokens": pending_quota,
            "unknown_reserved_quota_equivalent_tokens": unknown_quota,
            "effective_quota_equivalent_tokens": measured_quota + pending_quota + unknown_quota,
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
        mission_criticality: Any = MissionCriticality.UNKNOWN,
        semantic_cost_class: Any = SemanticCostClass.UNKNOWN,
        context_projection: Optional[Mapping[str, Any]] = None,
        when: Optional[datetime] = None,
    ) -> TokenAdmission:
        budget = self._budget(mission_id)
        if not isinstance(call_class, ModelCallClass):
            call_class = ModelCallClass(str(call_class).upper())
        if not isinstance(mission_criticality, MissionCriticality):
            mission_criticality = MissionCriticality(str(mission_criticality).upper())
        if not isinstance(semantic_cost_class, SemanticCostClass):
            semantic_cost_class = SemanticCostClass(str(semantic_cost_class).upper())

        if context_projection is not None and not isinstance(context_projection, Mapping):
            raise TokenEconomyError("TOKEN_CONTEXT_PROJECTION_INVALID")
        projection = dict(context_projection or {})
        accepted_projection = {
            "context_envelope_id", "context_envelope_sha256", "context_mode",
            "context_canonical_ref_count", "context_effective_ref_count",
            "context_unhydrated_lineage_ref_count",
            "context_projection_applied_to_prompt", "context_projection_status",
            "parent_attempt_id",
        }
        if set(projection) - accepted_projection:
            raise TokenEconomyError("TOKEN_CONTEXT_PROJECTION_FIELDS_INVALID")
        if projection and projection.get("context_projection_applied_to_prompt") is not False:
            raise TokenEconomyError("TOKEN_CONTEXT_SAVINGS_UNPROVEN")
        prompt_bytes = prompt.encode("utf-8")
        digest = hashlib.sha256(prompt_bytes).hexdigest()
        summary = self.summary(mission_id)
        window = classify_bank_cost_window(when or self.clock(), config=self.cost_window_config)
        reserve = int(budget["max_single_call_tokens"])
        reserve_quota = self._quota_equivalent(reserve, window.quota_cost_factor_millis)
        warnings: List[str] = []
        admitted = True
        hard_reason = "ADMITTED"

        # Hard guards protect correctness/waste only.
        if call_class == ModelCallClass.DETERMINISTIC_NO_LLM:
            admitted = False
            hard_reason = "DETERMINISTIC_STEP_MUST_NOT_USE_LLM"
        else:
            same_context = [
                row for row in self._calls(mission_id)
                # Distinct canonical WorkItems may legitimately share the same
                # bounded semantic prompt. Blocking them because of a mission-
                # wide fingerprint collision would silently shrink test scope.
                # A no-progress guard applies only within the same WorkItem.
                if (
                    row.get("state") != "BLOCKED"
                    and row.get("workitem_id") == workitem_id
                    and row.get("context_sha256") == digest
                )
            ]
            if len(same_context) >= int(budget["max_same_context_calls"]):
                admitted = False
                hard_reason = "SAME_CONTEXT_NO_PROGRESS_GUARD"

        # Soft economy signals. These never delete/complete mandatory work.
        if admitted:
            if bool(budget["require_measured_usage"]) and summary["unknown_usage_calls"]:
                warnings.append("PRIOR_TOKEN_USAGE_UNKNOWN")
            if summary["model_calls"] >= int(budget["max_model_calls"]):
                warnings.append("MISSION_MODEL_CALL_TARGET_EXCEEDED")
            if (
                window.quota_limited
                and summary["effective_quota_equivalent_tokens"] + reserve_quota
                > int(budget["max_total_tokens"])
            ):
                warnings.append("MISSION_QUOTA_EQUIVALENT_TARGET_EXCEEDED")
            if retry and summary["retry_calls"] >= int(budget["max_retry_calls"]):
                warnings.append("MISSION_RETRY_CALL_TARGET_EXCEEDED")
            if retry and summary["retry_effective_tokens"] + reserve > int(budget["max_retry_tokens"]):
                warnings.append("MISSION_RETRY_TOKEN_TARGET_EXCEEDED")

        schedule_recommendation = "RUN_NOW"
        if (
            admitted
            and mission_criticality == MissionCriticality.NON_BLOCKING
            and semantic_cost_class == SemanticCostClass.HIGH
            and window.quota_limited
            and window.quota_cost_factor_millis == 1000
        ):
            schedule_recommendation = "DEFER_RECOMMENDED"
            warnings.append("CHEAPER_WINDOW_AVAILABLE")

        reason = hard_reason
        if admitted and warnings:
            reason = "ADMITTED_WITH_ECONOMY_WARNINGS:" + ";".join(warnings)
        economy_signal = ";".join(warnings) if warnings else "NONE"

        call_id = _new("TOKCALL")
        now_epoch = _now()
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
            "process_outcome": "NOT_STARTED" if admitted else "UNKNOWN",
            **projection,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "reason": reason,
            "economy_signal": economy_signal,
            "cost_window": window.name,
            "bank_timezone": window.timezone_name,
            "quota_limited": window.quota_limited,
            "quota_cost_factor_millis": window.quota_cost_factor_millis,
            "quota_equivalent_tokens": 0,
            "mission_criticality": mission_criticality.value,
            "semantic_cost_class": semantic_cost_class.value,
            "schedule_recommendation": schedule_recommendation,
            "created_at": now_epoch,
            "updated_at": now_epoch,
            "artifact_version": 1,
        })
        return TokenAdmission(
            admitted,
            call_id,
            reason,
            reserve if admitted else 0,
            tuple(warnings),
            window.name,
            window.quota_limited,
            window.quota_cost_factor,
            schedule_recommendation,
        )

    def complete_call(
        self, call_id: str, usage: DshTokenUsage, *, process_outcome: str = "UNKNOWN"
    ) -> Dict[str, Any]:
        rows = self.truth.query(_TOKEN_CALL, call_id=call_id)
        if len(rows) != 1:
            raise TokenEconomyError("TOKEN_CALL_NOT_FOUND:%s" % call_id)
        current = rows[0]
        if current.get("state") != "ADMITTED":
            raise TokenEconomyError("TOKEN_CALL_NOT_ADMITTED:%s" % call_id)
        if process_outcome not in {"UNKNOWN", "RETURNED", "RAISED"}:
            raise TokenEconomyError("DSH_PROCESS_OUTCOME_INVALID")
        if not isinstance(usage, DshTokenUsage):
            usage = DshTokenUsage.unknown("INVALID_USAGE_OBJECT")
        updated = dict(current)
        updated.pop("artifact_type", None)
        updated["artifact_version"] = int(current.get("artifact_version", 1)) + 1
        updated["updated_at"] = _now()
        updated["process_outcome"] = process_outcome
        updated["usage_status"] = usage.status.value
        updated["usage_source"] = usage.source
        updated["input_tokens"] = int(usage.input_tokens)
        updated["output_tokens"] = int(usage.output_tokens)
        updated["total_tokens"] = int(usage.total_tokens)
        if usage.status == UsageStatus.MEASURED:
            updated["quota_equivalent_tokens"] = self._quota_equivalent(
                int(usage.total_tokens),
                int(current.get("quota_cost_factor_millis", 1000)),
            )
            updated["state"] = "COMPLETED"
            updated["reason"] = "DSH_USAGE_MEASURED"
        else:
            updated["quota_equivalent_tokens"] = 0
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
        status, reason = "PASS", "MODEL_ECONOMY_PASS"
        if not metrics["model_calls"]:
            status, reason = "HOLD", "TOKEN_USAGE_EVIDENCE_REQUIRED"
        elif metrics["pending_calls"]:
            status, reason = "HOLD", "TOKEN_CALLS_PENDING"
        elif metrics["unknown_usage_calls"]:
            # UNKNOWN is never qualified as measured, even if an older optional
            # budget switch disabled strict measurement for warning purposes.
            status, reason = "HOLD", "TOKEN_USAGE_UNKNOWN"
        elif bool(budget["require_complete_lineage"]) and metrics["unknown_lineage_call_ids"]:
            status, reason = "HOLD", "TOKEN_CALL_LINEAGE_INCOMPLETE"
        elif metrics["blocked_calls"]:
            status, reason = "HOLD", "MODEL_ECONOMY_WASTE_GUARD_TRIGGERED"
        elif metrics["effective_quota_equivalent_tokens"] > int(budget["max_total_tokens"]):
            status, reason = "DEGRADED", "MODEL_ECONOMY_QUOTA_TARGET_EXCEEDED"
        elif metrics["model_calls"] > int(budget["max_model_calls"]):
            status, reason = "DEGRADED", "MODEL_ECONOMY_CALL_TARGET_EXCEEDED"
        elif metrics["retry_effective_tokens"] > int(budget["max_retry_tokens"]):
            status, reason = "DEGRADED", "MODEL_ECONOMY_RETRY_TOKEN_TARGET_EXCEEDED"
        elif metrics["retry_calls"] > int(budget["max_retry_calls"]):
            status, reason = "DEGRADED", "MODEL_ECONOMY_RETRY_CALL_TARGET_EXCEEDED"
        return TokenQualification(status, mission_id, reason, metrics)

    def field_qualification(self, mission_id: str) -> TokenQualification:
        """Strict Field Q7 qualification, distinct from source-only accounting.

        A native DSH subprocess is not proof of the number of underlying
        provider inference rounds. Until a real bank JSONL event contract can
        attribute *each* inference, never promote simulated/subprocess counts
        into an independently verified MODEL_ECONOMY_STATUS=PASS.
        """
        component = self.qualification(mission_id)
        metrics = component.metrics
        if (
            component.status in {"PASS", "DEGRADED"}
            and metrics.get("provider_inference_call_count_status") != "MEASURED"
        ):
            return TokenQualification(
                "HOLD", mission_id, "PROVIDER_INFERENCE_CALL_COUNT_UNKNOWN", metrics,
            )
        return component


MetadataResolver = Callable[[Any], Mapping[str, Any]]


class TokenMeteredDshLauncher:
    """Transparent model-economy wrapper for DshHeadlessWorkerLauncher."""

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
            mission_criticality=metadata.get("mission_criticality", MissionCriticality.UNKNOWN.value),
            semantic_cost_class=metadata.get("semantic_cost_class", SemanticCostClass.UNKNOWN.value),
            when=metadata.get("when"),
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
