"""RC7.2 DSH token-usage observation and canonical R1 truth.

The in-bank DSH JSONL usage shape is not yet field-bound.  This module therefore
normalizes only token counters it can actually observe and never fabricates zero
for missing data.  Conflicting candidate snapshots are persisted as UNKNOWN
until a real bank run establishes the provider/DSH contract.

This module is intentionally launcher-independent.  Wiring it into
DshHeadlessWorkerLauncher is a separate construction step after this parser and
truth contract qualify on their own.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .truth_overlay import install_rc7_truth_overlay


_ARTIFACT_TYPE = "rc72_token_usage"
_EVENT_TYPE = "RC72_TOKEN_USAGE_OBSERVED"
_BUCKET = "rc72_token_usages"
_OBSERVED = "OBSERVED"
_UNKNOWN = "UNKNOWN"

_TOKEN_ALIASES = {
    "input_tokens": ("input_tokens", "prompt_tokens", "input_token_count", "prompt_token_count"),
    "output_tokens": ("output_tokens", "completion_tokens", "output_token_count", "completion_token_count"),
    "total_tokens": ("total_tokens", "total_token_count"),
    "cached_input_tokens": ("cached_input_tokens", "cached_prompt_tokens"),
    "cache_read_tokens": ("cache_read_tokens", "cache_read_input_tokens"),
    "cache_write_tokens": ("cache_write_tokens", "cache_creation_input_tokens"),
}
_TOKEN_FIELDS = tuple(_TOKEN_ALIASES.keys())


def _now() -> int:
    return int(time.time())


def _optional_nonempty(out: Dict[str, Any], name: str) -> None:
    value = out.get(name)
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise _contracts.DomainValidationError("INVALID_%s" % name.upper())


def _optional_token_count(out: Dict[str, Any], name: str) -> None:
    value = out.get(name)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise _contracts.DomainValidationError("INVALID_%s" % name.upper())


def validate_rc72_token_usage(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "token_usage_id",
        "release_id",
        "mission_id",
        "attempt_id",
        "assignment_id",
        "raw_output_ref",
        "observation_status",
    ):
        out[name] = _contracts._require_str(out, name)
    out["observation_status"] = out["observation_status"].upper()
    if out["observation_status"] not in {_OBSERVED, _UNKNOWN}:
        raise _contracts.DomainValidationError("TOKEN_USAGE_OBSERVATION_STATUS_INVALID")

    for name in (
        "dsh_session_id",
        "provider",
        "model",
        "usage_source_path",
        "unknown_reason",
        "observation_sha256",
    ):
        _optional_nonempty(out, name)
    for name in _TOKEN_FIELDS:
        _optional_token_count(out, name)

    candidate_count = out.get("usage_candidate_count")
    if not isinstance(candidate_count, int) or isinstance(candidate_count, bool) or candidate_count < 0:
        raise _contracts.DomainValidationError("TOKEN_USAGE_CANDIDATE_COUNT_INVALID")
    recorded_at = out.get("recorded_at")
    if not isinstance(recorded_at, int) or isinstance(recorded_at, bool) or recorded_at < 0:
        raise _contracts.DomainValidationError("TOKEN_USAGE_RECORDED_AT_INVALID")
    version = out.get("artifact_version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _contracts.DomainValidationError("TOKEN_USAGE_ARTIFACT_VERSION_INVALID")
    out["artifact_version"] = version

    observed_values = [out.get(name) for name in _TOKEN_FIELDS]
    if out["observation_status"] == _OBSERVED:
        if not any(value is not None for value in observed_values):
            raise _contracts.DomainValidationError("OBSERVED_TOKEN_USAGE_REQUIRES_COUNTER")
        if not out.get("usage_source_path") or not out.get("observation_sha256"):
            raise _contracts.DomainValidationError("OBSERVED_TOKEN_USAGE_REQUIRES_SOURCE_IDENTITY")
        if out.get("unknown_reason") is not None:
            raise _contracts.DomainValidationError("OBSERVED_TOKEN_USAGE_CANNOT_HAVE_UNKNOWN_REASON")
    else:
        if any(value is not None for value in observed_values):
            raise _contracts.DomainValidationError("UNKNOWN_TOKEN_USAGE_CANNOT_CLAIM_COUNTERS")
        if not out.get("unknown_reason"):
            raise _contracts.DomainValidationError("UNKNOWN_TOKEN_USAGE_REQUIRES_REASON")
        if out.get("observation_sha256") is not None:
            raise _contracts.DomainValidationError("UNKNOWN_TOKEN_USAGE_CANNOT_CLAIM_OBSERVATION_DIGEST")

    out["artifact_type"] = _ARTIFACT_TYPE
    return out


def install_rc72_token_usage_overlay() -> None:
    install_rc7_truth_overlay()
    _contracts.VALIDATORS[_ARTIFACT_TYPE] = validate_rc72_token_usage
    _truth.BUCKETS[_ARTIFACT_TYPE] = _BUCKET
    _truth.IDENTITY_FIELDS[_ARTIFACT_TYPE] = "token_usage_id"
    _truth.EVENT_TYPES[_EVENT_TYPE] = (_ARTIFACT_TYPE, "token_usage_id")


def _ensure_projection_bucket(truth: TruthRuntime) -> None:
    projection = getattr(truth, "projection", None)
    if projection is None:
        return
    if not hasattr(projection, _BUCKET):
        setattr(projection, _BUCKET, {})
    versions = getattr(projection, "_versions", None)
    if isinstance(versions, dict):
        versions.setdefault(_ARTIFACT_TYPE, {})


def _int_count(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _normalize_mapping(mapping: Mapping[str, Any]) -> Tuple[Dict[str, Optional[int]], bool]:
    normalized: Dict[str, Optional[int]] = {name: None for name in _TOKEN_FIELDS}
    conflict = False
    lower = {str(key).lower(): value for key, value in mapping.items()}
    for canonical, aliases in _TOKEN_ALIASES.items():
        values: List[int] = []
        for alias in aliases:
            if alias not in lower:
                continue
            count = _int_count(lower[alias])
            if count is not None:
                values.append(count)
        distinct = set(values)
        if len(distinct) > 1:
            conflict = True
        elif distinct:
            normalized[canonical] = next(iter(distinct))
    return normalized, conflict


def _walk_mappings(value: Any, path: str) -> Iterable[Tuple[str, Mapping[str, Any]]]:
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            child_path = "%s.%s" % (path, key)
            yield from _walk_mappings(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_mappings(child, "%s[%d]" % (path, index))


def _single_string(event: Mapping[str, Any], keys: Sequence[str]) -> Optional[str]:
    wanted = {key.lower() for key in keys}
    found: List[str] = []
    for _path, mapping in _walk_mappings(event, "event"):
        for key, value in mapping.items():
            if str(key).lower() in wanted and isinstance(value, str) and value.strip():
                found.append(value.strip())
    unique = list(dict.fromkeys(found))
    return unique[0] if len(unique) == 1 else None


@dataclass(frozen=True)
class ParsedTokenUsage:
    observation_status: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_write_tokens: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    usage_source_path: Optional[str] = None
    usage_candidate_count: int = 0
    unknown_reason: Optional[str] = None
    observation_sha256: Optional[str] = None

    def counters(self) -> Dict[str, Optional[int]]:
        return {name: getattr(self, name) for name in _TOKEN_FIELDS}


class DshTokenUsageParser:
    """Normalize only unambiguous usage observations from DSH JSONL events.

    Multiple identical snapshots are treated as one observation.  Multiple
    conflicting snapshots are deliberately UNKNOWN rather than summed because
    the repository has not yet proven whether DSH emits per-call deltas or
    cumulative snapshots in the bank environment.
    """

    @classmethod
    def parse(cls, events: Sequence[Dict[str, Any]]) -> ParsedTokenUsage:
        candidates: List[Tuple[int, str, Dict[str, Optional[int]], Mapping[str, Any]]] = []
        alias_conflict = False
        for event_index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            for path, mapping in _walk_mappings(event, "event[%d]" % event_index):
                normalized, conflict = _normalize_mapping(mapping)
                if conflict:
                    alias_conflict = True
                if any(value is not None for value in normalized.values()):
                    candidates.append((event_index, path, normalized, event))

        if alias_conflict:
            return ParsedTokenUsage(
                observation_status=_UNKNOWN,
                usage_candidate_count=len(candidates),
                unknown_reason="CONFLICTING_TOKEN_ALIASES",
            )
        if not candidates:
            return ParsedTokenUsage(
                observation_status=_UNKNOWN,
                usage_candidate_count=0,
                unknown_reason="TOKEN_USAGE_NOT_EXPOSED_BY_DSH_JSONL",
            )

        distinct: Dict[str, Tuple[int, str, Dict[str, Optional[int]], Mapping[str, Any]]] = {}
        for candidate in candidates:
            _index, _path, normalized, _event = candidate
            signature = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
            distinct[signature] = candidate
        if len(distinct) != 1:
            return ParsedTokenUsage(
                observation_status=_UNKNOWN,
                usage_candidate_count=len(candidates),
                unknown_reason="MULTIPLE_CONFLICTING_USAGE_SNAPSHOTS",
            )

        event_index, path, normalized, event = candidates[-1]
        provider = _single_string(event, ("provider", "provider_name", "providerName"))
        model = _single_string(event, ("model", "model_name", "modelName"))
        digest_payload = {
            "event_index": event_index,
            "usage_source_path": path,
            "counters": normalized,
            "provider": provider,
            "model": model,
        }
        digest = hashlib.sha256(
            json.dumps(digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return ParsedTokenUsage(
            observation_status=_OBSERVED,
            provider=provider,
            model=model,
            usage_source_path=path,
            usage_candidate_count=len(candidates),
            observation_sha256=digest,
            **normalized,
        )


def _token_usage_id(release_id: str, mission_id: str, attempt_id: str, assignment_id: str) -> str:
    raw = "\x1f".join((release_id, mission_id, attempt_id, assignment_id))
    return "TOKENUSE-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class TokenUsageAuditService:
    """Persist one honest usage receipt per DSH assignment into canonical R1."""

    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_token_usage_overlay()
        _ensure_projection_bucket(truth)
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("TOKEN_USAGE_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()

    def observe(
        self,
        *,
        mission_id: str,
        attempt_id: str,
        assignment_id: str,
        raw_output_ref: str,
        events: Sequence[Dict[str, Any]],
        dsh_session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        for name, value in (
            ("MISSION_ID", mission_id),
            ("ATTEMPT_ID", attempt_id),
            ("ASSIGNMENT_ID", assignment_id),
            ("RAW_OUTPUT_REF", raw_output_ref),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContractError("TOKEN_USAGE_%s_REQUIRED" % name)
        if dsh_session_id is not None and (not isinstance(dsh_session_id, str) or not dsh_session_id.strip()):
            raise ContractError("TOKEN_USAGE_DSH_SESSION_ID_INVALID")

        parsed = DshTokenUsageParser.parse(events)
        payload: Dict[str, Any] = {
            "token_usage_id": _token_usage_id(self.release_id, mission_id, attempt_id, assignment_id),
            "release_id": self.release_id,
            "mission_id": mission_id,
            "attempt_id": attempt_id,
            "assignment_id": assignment_id,
            "dsh_session_id": dsh_session_id,
            "raw_output_ref": raw_output_ref,
            "observation_status": parsed.observation_status,
            "input_tokens": parsed.input_tokens,
            "output_tokens": parsed.output_tokens,
            "total_tokens": parsed.total_tokens,
            "cached_input_tokens": parsed.cached_input_tokens,
            "cache_read_tokens": parsed.cache_read_tokens,
            "cache_write_tokens": parsed.cache_write_tokens,
            "provider": parsed.provider,
            "model": parsed.model,
            "usage_source_path": parsed.usage_source_path,
            "usage_candidate_count": parsed.usage_candidate_count,
            "unknown_reason": parsed.unknown_reason,
            "observation_sha256": parsed.observation_sha256,
            "recorded_at": _now(),
        }
        return self._persist(payload)

    def _persist(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        usage_id = payload["token_usage_id"]
        existing = self.truth.query(_ARTIFACT_TYPE, token_usage_id=usage_id)
        if len(existing) > 1:
            raise ContractError("TOKEN_USAGE_TRUTH_NOT_UNIQUE")
        if existing:
            row = existing[0]
            old_status = row.get("observation_status")
            new_status = payload.get("observation_status")
            if old_status == _OBSERVED:
                if new_status == _UNKNOWN:
                    return row
                immutable = (
                    "mission_id",
                    "attempt_id",
                    "assignment_id",
                    "raw_output_ref",
                    "dsh_session_id",
                    "observation_sha256",
                )
                if all(row.get(name) == payload.get(name) for name in immutable):
                    return row
                raise ContractError("TOKEN_USAGE_OBSERVATION_IMMUTABLE")
            if old_status == _UNKNOWN and new_status == _UNKNOWN:
                return row
            if old_status != _UNKNOWN or new_status != _OBSERVED:
                raise ContractError("TOKEN_USAGE_STATE_TRANSITION_INVALID")
            payload["artifact_version"] = int(row.get("artifact_version", 1)) + 1
        else:
            payload["artifact_version"] = 1

        self.truth.append_atomic(_EVENT_TYPE, payload)
        rows = self.truth.query(_ARTIFACT_TYPE, token_usage_id=usage_id)
        if len(rows) != 1:
            raise ContractError("TOKEN_USAGE_PERSISTENCE_FAILED")
        return rows[0]
