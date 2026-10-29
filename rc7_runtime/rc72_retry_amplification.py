"""RC7.2 retry-amplification audit over canonical retry and model-call truth.

Step-6 scope is deliberately narrow: correlate real child->parent Attempt retry
context with the model calls that actually ran, quantify retry token/context
amplification when the evidence is measurable, and surface incomplete or
suspicious amplification without cancelling mandatory Mission work.

No retry lineage is inferred from IDs, prompts or scope strings. Retry parentage
and delta/full-context mode come only from ``rc72_retry_context``. Model usage
comes only from ``rc72_token_call``. UNKNOWN usage remains UNKNOWN rather than
being converted to zero. Exact parent-context replay is an economy signal, not
proof that semantic progress did not occur.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime.truth import TruthRuntime

from .rc72_model_economy import install_rc72_token_economy_overlay
from .rc72_retry_context import install_rc72_retry_context_overlay


_EXECUTED_STATES = {"COMPLETED", "COMPLETED_UNKNOWN"}
_NONBLOCKED_STATES = {"ADMITTED", "COMPLETED", "COMPLETED_UNKNOWN"}


class RetryAmplificationProofStatus(str, Enum):
    MEASURED = "MEASURED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RetryAttemptAmplification:
    workitem_id: str
    attempt_id: str
    parent_attempt_id: str
    context_mode: str
    context_observation_status: str
    model_call_count: int
    measured_call_count: int
    unknown_usage_call_count: int
    pending_call_count: int
    blocked_retry_call_count: int
    retry_flag_missing_call_count: int
    measured_retry_tokens: int
    retry_tokens: Optional[int]
    parent_tokens: Optional[int]
    token_amplification_factor: Optional[float]
    retry_context_bytes: int
    parent_context_bytes: int
    context_amplification_factor: Optional[float]
    exact_parent_context_replay_call_count: int
    proof_status: RetryAmplificationProofStatus
    signals: Tuple[str, ...]
    mission_progress_allowed: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "workitem_id": self.workitem_id,
            "attempt_id": self.attempt_id,
            "parent_attempt_id": self.parent_attempt_id,
            "context_mode": self.context_mode,
            "context_observation_status": self.context_observation_status,
            "model_call_count": self.model_call_count,
            "measured_call_count": self.measured_call_count,
            "unknown_usage_call_count": self.unknown_usage_call_count,
            "pending_call_count": self.pending_call_count,
            "blocked_retry_call_count": self.blocked_retry_call_count,
            "retry_flag_missing_call_count": self.retry_flag_missing_call_count,
            "measured_retry_tokens": self.measured_retry_tokens,
            "retry_tokens": self.retry_tokens,
            "parent_tokens": self.parent_tokens,
            "token_amplification_factor": self.token_amplification_factor,
            "retry_context_bytes": self.retry_context_bytes,
            "parent_context_bytes": self.parent_context_bytes,
            "context_amplification_factor": self.context_amplification_factor,
            "exact_parent_context_replay_call_count": self.exact_parent_context_replay_call_count,
            "proof_status": self.proof_status.value,
            "signals": list(self.signals),
            "mission_progress_allowed": self.mission_progress_allowed,
        }


@dataclass(frozen=True)
class RetryAmplificationQualification:
    status: str
    reason: str
    mission_progress_allowed: bool


@dataclass(frozen=True)
class RetryAmplificationReport:
    mission_id: str
    retry_attempt_count: int
    measured_retry_attempt_count: int
    partial_retry_attempt_count: int
    unknown_retry_attempt_count: int
    delta_retry_count: int
    full_context_retry_count: int
    unknown_context_retry_count: int
    exact_parent_replay_attempt_count: int
    orphan_retry_call_ids: Tuple[str, ...]
    retry_context_without_model_call_attempt_ids: Tuple[str, ...]
    measured_retry_tokens: int
    retry_tokens: Optional[int]
    attempts: Tuple[RetryAttemptAmplification, ...]
    qualification: RetryAmplificationQualification

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "retry_attempt_count": self.retry_attempt_count,
            "measured_retry_attempt_count": self.measured_retry_attempt_count,
            "partial_retry_attempt_count": self.partial_retry_attempt_count,
            "unknown_retry_attempt_count": self.unknown_retry_attempt_count,
            "delta_retry_count": self.delta_retry_count,
            "full_context_retry_count": self.full_context_retry_count,
            "unknown_context_retry_count": self.unknown_context_retry_count,
            "exact_parent_replay_attempt_count": self.exact_parent_replay_attempt_count,
            "orphan_retry_call_ids": list(self.orphan_retry_call_ids),
            "retry_context_without_model_call_attempt_ids": list(
                self.retry_context_without_model_call_attempt_ids
            ),
            "measured_retry_tokens": self.measured_retry_tokens,
            "retry_tokens": self.retry_tokens,
            "attempts": [attempt.as_dict() for attempt in self.attempts],
            "qualification": {
                "status": self.qualification.status,
                "reason": self.qualification.reason,
                "mission_progress_allowed": self.qualification.mission_progress_allowed,
            },
        }


class RetryAmplificationAuditService:
    """Join retry context and model-call truth without introducing a kill switch."""

    def __init__(self, truth: TruthRuntime) -> None:
        install_rc72_token_economy_overlay()
        install_rc72_retry_context_overlay()
        self.truth = truth

    @staticmethod
    def _sorted_rows(rows: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        return sorted(
            rows,
            key=lambda row: (
                str(row.get("workitem_id") or ""),
                str(row.get("attempt_id") or ""),
                int(row.get("created_at") or row.get("recorded_at") or 0),
                str(row.get("call_id") or row.get("retry_context_id") or ""),
            ),
        )

    @staticmethod
    def _known_total_tokens(calls: Sequence[Mapping[str, Any]]) -> Optional[int]:
        if not calls:
            return None
        if any(str(row.get("usage_status") or "").upper() != "MEASURED" for row in calls):
            return None
        return sum(int(row.get("total_tokens") or 0) for row in calls)

    @staticmethod
    def _proof_status(calls: Sequence[Mapping[str, Any]]) -> RetryAmplificationProofStatus:
        if not calls:
            return RetryAmplificationProofStatus.UNKNOWN
        statuses = [str(row.get("usage_status") or "").upper() for row in calls]
        measured = sum(1 for status in statuses if status == "MEASURED")
        if measured == len(statuses):
            return RetryAmplificationProofStatus.MEASURED
        if measured:
            return RetryAmplificationProofStatus.PARTIAL
        return RetryAmplificationProofStatus.UNKNOWN

    @staticmethod
    def _factor(numerator: Optional[int], denominator: Optional[int]) -> Optional[float]:
        if numerator is None or denominator is None or denominator <= 0:
            return None
        return float(numerator) / float(denominator)

    @staticmethod
    def _signals(
        *,
        context: Mapping[str, Any],
        calls: Sequence[Mapping[str, Any]],
        exact_parent_replays: int,
        context_factor: Optional[float],
        blocked_retry_calls: int,
    ) -> Tuple[str, ...]:
        signals: List[str] = []
        mode = str(context.get("context_mode") or "UNKNOWN").upper()
        observation = str(context.get("observation_status") or "UNKNOWN").upper()
        if observation != "OBSERVED" or mode == "RETRY_DELTA_UNKNOWN":
            signals.append("RETRY_CONTEXT_UNKNOWN")
        elif mode == "FULL_CONTEXT_RETRY":
            signals.append("FULL_CONTEXT_RETRY_JUSTIFIED")

        if not calls:
            signals.append("RETRY_MODEL_CALL_NOT_OBSERVED")
        if any(not bool(row.get("retry")) for row in calls):
            signals.append("RETRY_FLAG_MISSING_ON_CHILD_CALL")
        if any(str(row.get("usage_status") or "").upper() != "MEASURED" for row in calls):
            signals.append("RETRY_TOKEN_USAGE_UNKNOWN")
        if blocked_retry_calls:
            signals.append("RETRY_MODEL_CALL_BLOCKED")

        if exact_parent_replays:
            if mode == "RETRY_DELTA":
                signals.append("DELTA_RETRY_EXACT_PARENT_CONTEXT_REPLAY")
            elif mode == "FULL_CONTEXT_RETRY":
                signals.append("FULL_CONTEXT_PARENT_REPLAY_OBSERVED")
            else:
                signals.append("UNKNOWN_RETRY_EXACT_PARENT_CONTEXT_REPLAY")

        if mode == "RETRY_DELTA" and context_factor is not None and context_factor > 1.0:
            signals.append("DELTA_RETRY_CONTEXT_BYTES_EXCEED_PARENT")
        return tuple(dict.fromkeys(signals))

    def report(self, mission_id: str) -> RetryAmplificationReport:
        if not isinstance(mission_id, str) or not mission_id.strip():
            raise ValueError("RETRY_AMPLIFICATION_MISSION_ID_REQUIRED")
        mission_id = mission_id.strip()
        contexts = self._sorted_rows(
            self.truth.query("rc72_retry_context", mission_id=mission_id)
        )
        calls = self._sorted_rows(
            self.truth.query("rc72_token_call", mission_id=mission_id)
        )

        context_by_key: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        duplicate_context_keys = set()
        for context in contexts:
            key = (
                str(context.get("workitem_id") or "").strip(),
                str(context.get("attempt_id") or "").strip(),
            )
            if key in context_by_key:
                duplicate_context_keys.add(key)
            context_by_key[key] = context
        if duplicate_context_keys:
            raise ValueError("RETRY_CONTEXT_LINEAGE_NOT_UNIQUE")

        calls_by_key: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
        for call in calls:
            key = (
                str(call.get("workitem_id") or "").strip(),
                str(call.get("attempt_id") or "").strip(),
            )
            calls_by_key.setdefault(key, []).append(call)

        orphan_retry_call_ids = tuple(
            sorted(
                str(call.get("call_id") or "")
                for call in calls
                if bool(call.get("retry"))
                and str(call.get("state") or "").upper() != "BLOCKED"
                and (
                    str(call.get("workitem_id") or "").strip(),
                    str(call.get("attempt_id") or "").strip(),
                ) not in context_by_key
            )
        )

        attempts: List[RetryAttemptAmplification] = []
        retry_context_without_model_call: List[str] = []
        for context in contexts:
            workitem_id = str(context.get("workitem_id") or "").strip()
            attempt_id = str(context.get("attempt_id") or "").strip()
            parent_attempt_id = str(context.get("parent_attempt_id") or "").strip()
            key = (workitem_id, attempt_id)
            child_all = list(calls_by_key.get(key, []))
            child_calls = [
                row for row in child_all
                if str(row.get("state") or "").upper() in _NONBLOCKED_STATES
            ]
            child_executed = [
                row for row in child_calls
                if str(row.get("state") or "").upper() in _EXECUTED_STATES
            ]
            blocked_retry_calls = sum(
                1
                for row in child_all
                if bool(row.get("retry"))
                and str(row.get("state") or "").upper() == "BLOCKED"
            )
            if not child_calls:
                retry_context_without_model_call.append(attempt_id)

            parent_calls = [
                row
                for row in calls_by_key.get((workitem_id, parent_attempt_id), [])
                if str(row.get("state") or "").upper() in _EXECUTED_STATES
            ]
            parent_digests = {
                str(row.get("context_sha256") or "").strip()
                for row in parent_calls
                if str(row.get("context_sha256") or "").strip()
            }
            exact_parent_replays = sum(
                1
                for row in child_executed
                if str(row.get("context_sha256") or "").strip() in parent_digests
            )

            retry_context_bytes = sum(int(row.get("context_bytes") or 0) for row in child_executed)
            parent_context_bytes = sum(int(row.get("context_bytes") or 0) for row in parent_calls)
            context_factor = self._factor(retry_context_bytes, parent_context_bytes)
            retry_tokens = self._known_total_tokens(child_executed)
            parent_tokens = self._known_total_tokens(parent_calls)
            measured_retry_tokens = sum(
                int(row.get("total_tokens") or 0)
                for row in child_executed
                if str(row.get("usage_status") or "").upper() == "MEASURED"
            )
            proof_status = self._proof_status(child_executed)
            signals = self._signals(
                context=context,
                calls=child_calls,
                exact_parent_replays=exact_parent_replays,
                context_factor=context_factor,
                blocked_retry_calls=blocked_retry_calls,
            )
            attempts.append(
                RetryAttemptAmplification(
                    workitem_id=workitem_id,
                    attempt_id=attempt_id,
                    parent_attempt_id=parent_attempt_id,
                    context_mode=str(context.get("context_mode") or "UNKNOWN").upper(),
                    context_observation_status=str(
                        context.get("observation_status") or "UNKNOWN"
                    ).upper(),
                    model_call_count=len(child_calls),
                    measured_call_count=sum(
                        1
                        for row in child_calls
                        if str(row.get("usage_status") or "").upper() == "MEASURED"
                    ),
                    unknown_usage_call_count=sum(
                        1
                        for row in child_calls
                        if str(row.get("usage_status") or "").upper() == "UNKNOWN"
                    ),
                    pending_call_count=sum(
                        1
                        for row in child_calls
                        if str(row.get("usage_status") or "").upper() == "PENDING"
                    ),
                    blocked_retry_call_count=blocked_retry_calls,
                    retry_flag_missing_call_count=sum(
                        1 for row in child_calls if not bool(row.get("retry"))
                    ),
                    measured_retry_tokens=measured_retry_tokens,
                    retry_tokens=retry_tokens,
                    parent_tokens=parent_tokens,
                    token_amplification_factor=self._factor(retry_tokens, parent_tokens),
                    retry_context_bytes=retry_context_bytes,
                    parent_context_bytes=parent_context_bytes,
                    context_amplification_factor=context_factor,
                    exact_parent_context_replay_call_count=exact_parent_replays,
                    proof_status=proof_status,
                    signals=signals,
                    mission_progress_allowed=True,
                )
            )

        attempts.sort(key=lambda item: (item.workitem_id, item.attempt_id))
        measured_retry_tokens = sum(item.measured_retry_tokens for item in attempts)
        all_tokens_known = bool(attempts) and all(item.retry_tokens is not None for item in attempts)
        retry_tokens = (
            sum(int(item.retry_tokens or 0) for item in attempts)
            if all_tokens_known else None
        )

        unknown_proof = bool(orphan_retry_call_ids) or any(
            item.proof_status != RetryAmplificationProofStatus.MEASURED
            or item.context_observation_status != "OBSERVED"
            for item in attempts
        )
        degraded = any(
            signal in {
                "DELTA_RETRY_EXACT_PARENT_CONTEXT_REPLAY",
                "DELTA_RETRY_CONTEXT_BYTES_EXCEED_PARENT",
                "RETRY_FLAG_MISSING_ON_CHILD_CALL",
                "RETRY_MODEL_CALL_BLOCKED",
            }
            for item in attempts
            for signal in item.signals
        )
        if not attempts and not orphan_retry_call_ids:
            qualification = RetryAmplificationQualification(
                "PASS", "NO_RETRY_MODEL_AMPLIFICATION_OBSERVED", True
            )
        elif unknown_proof:
            qualification = RetryAmplificationQualification(
                "UNKNOWN", "RETRY_AMPLIFICATION_PROOF_INCOMPLETE", True
            )
        elif degraded:
            qualification = RetryAmplificationQualification(
                "DEGRADED", "RETRY_AMPLIFICATION_ECONOMY_SIGNAL", True
            )
        else:
            qualification = RetryAmplificationQualification(
                "PASS", "RETRY_AMPLIFICATION_AUDIT_PASS", True
            )

        return RetryAmplificationReport(
            mission_id=mission_id,
            retry_attempt_count=len(attempts),
            measured_retry_attempt_count=sum(
                1 for item in attempts
                if item.proof_status == RetryAmplificationProofStatus.MEASURED
            ),
            partial_retry_attempt_count=sum(
                1 for item in attempts
                if item.proof_status == RetryAmplificationProofStatus.PARTIAL
            ),
            unknown_retry_attempt_count=sum(
                1 for item in attempts
                if item.proof_status == RetryAmplificationProofStatus.UNKNOWN
            ),
            delta_retry_count=sum(1 for item in attempts if item.context_mode == "RETRY_DELTA"),
            full_context_retry_count=sum(
                1 for item in attempts if item.context_mode == "FULL_CONTEXT_RETRY"
            ),
            unknown_context_retry_count=sum(
                1 for item in attempts if item.context_mode == "RETRY_DELTA_UNKNOWN"
            ),
            exact_parent_replay_attempt_count=sum(
                1 for item in attempts if item.exact_parent_context_replay_call_count > 0
            ),
            orphan_retry_call_ids=orphan_retry_call_ids,
            retry_context_without_model_call_attempt_ids=tuple(
                sorted(set(retry_context_without_model_call))
            ),
            measured_retry_tokens=measured_retry_tokens,
            retry_tokens=retry_tokens,
            attempts=tuple(attempts),
            qualification=qualification,
        )
