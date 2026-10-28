"""RC7.2 Journey Benchmark aggregation.

Benchmark consumes persisted replay truth only.  It does not drive a browser and
cannot promote a Candidate to official/executable.  The applied policy is stored
with the benchmark result so the readiness decision is reproducible.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Sequence

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_journey_replay import install_rc72_journey_replay_overlay

_BENCHMARK = "rc72_journey_benchmark"
_EVENT = "RC72_JOURNEY_BENCHMARK_UPSERTED"
_BUCKET = "rc72_journey_benchmarks"


class JourneyBenchmarkState(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class JourneyBenchmarkPolicy:
    min_replays: int = 2
    require_all_passed: bool = True
    require_consistent_step_count: bool = True
    min_field_verified_replays: int = 0

    def validate(self) -> "JourneyBenchmarkPolicy":
        if not isinstance(self.min_replays, int) or self.min_replays < 2:
            raise ContractError("JOURNEY_BENCHMARK_MIN_REPLAYS_INVALID")
        if not isinstance(self.min_field_verified_replays, int) or self.min_field_verified_replays < 0:
            raise ContractError("JOURNEY_BENCHMARK_MIN_FIELD_REPLAYS_INVALID")
        if self.min_field_verified_replays > self.min_replays:
            raise ContractError("JOURNEY_BENCHMARK_FIELD_REPLAYS_EXCEED_MIN_REPLAYS")
        if not isinstance(self.require_all_passed, bool) or not isinstance(self.require_consistent_step_count, bool):
            raise ContractError("JOURNEY_BENCHMARK_POLICY_BOOLEAN_INVALID")
        return self


@dataclass(frozen=True)
class JourneyBenchmarkResult:
    benchmark_id: str
    state: JourneyBenchmarkState


def _now() -> int:
    return int(time.time())


def _required(out: Dict[str, Any], name: str) -> str:
    return _contracts._require_str(out, name)


def _validate_benchmark(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "benchmark_id", "candidate_id", "mission_id", "release_id", "release_batch_id",
        "requirement_id", "sst_id", "obligation_id", "state",
    ):
        out[name] = _required(out, name)
    out["artifact_type"] = _BENCHMARK
    out["artifact_version"] = _contracts._artifact_version(out)
    try:
        out["state"] = JourneyBenchmarkState(out["state"].upper()).value
    except ValueError as exc:
        raise _contracts.DomainValidationError("JOURNEY_BENCHMARK_STATE_INVALID") from exc
    replay_ids = out.get("replay_ids")
    if not isinstance(replay_ids, list) or not all(isinstance(x, str) and x.strip() for x in replay_ids):
        raise _contracts.DomainValidationError("JOURNEY_BENCHMARK_REPLAY_IDS_INVALID")
    if len(replay_ids) != len(set(replay_ids)):
        raise _contracts.DomainValidationError("JOURNEY_BENCHMARK_REPLAY_IDS_DUPLICATE")
    policy = out.get("policy")
    if not isinstance(policy, dict):
        raise _contracts.DomainValidationError("JOURNEY_BENCHMARK_POLICY_INVALID")
    for name in ("min_replays", "min_field_verified_replays"):
        if not isinstance(policy.get(name), int) or policy[name] < 0:
            raise _contracts.DomainValidationError("JOURNEY_BENCHMARK_POLICY_%s_INVALID" % name.upper())
    for name in ("require_all_passed", "require_consistent_step_count"):
        if not isinstance(policy.get(name), bool):
            raise _contracts.DomainValidationError("JOURNEY_BENCHMARK_POLICY_%s_INVALID" % name.upper())
    for name in ("total_replay_count", "passed_count", "failed_count", "field_verified_count"):
        if not isinstance(out.get(name), int) or out[name] < 0:
            raise _contracts.DomainValidationError("JOURNEY_BENCHMARK_%s_INVALID" % name.upper())
    if out["passed_count"] + out["failed_count"] != out["total_replay_count"]:
        raise _contracts.DomainValidationError("JOURNEY_BENCHMARK_COUNT_MISMATCH")
    if not isinstance(out.get("field_benchmark_verified"), bool):
        raise _contracts.DomainValidationError("JOURNEY_BENCHMARK_FIELD_VERIFIED_INVALID")
    reasons = out.get("failure_reasons")
    if not isinstance(reasons, list) or not all(isinstance(x, str) and x.strip() for x in reasons):
        raise _contracts.DomainValidationError("JOURNEY_BENCHMARK_FAILURE_REASONS_INVALID")
    if out["state"] == JourneyBenchmarkState.PASSED.value and reasons:
        raise _contracts.DomainValidationError("JOURNEY_BENCHMARK_PASS_WITH_FAILURES")
    if out["state"] == JourneyBenchmarkState.FAILED.value and not reasons:
        raise _contracts.DomainValidationError("JOURNEY_BENCHMARK_FAIL_WITHOUT_REASON")
    if not isinstance(out.get("evaluated_at"), int) or out["evaluated_at"] < 0:
        raise _contracts.DomainValidationError("JOURNEY_BENCHMARK_EVALUATED_AT_INVALID")
    return out


def install_rc72_journey_benchmark_overlay() -> None:
    install_rc72_journey_replay_overlay()
    _contracts.VALIDATORS[_BENCHMARK] = _validate_benchmark
    _truth.BUCKETS[_BENCHMARK] = _BUCKET
    _truth.EVENT_TYPES[_EVENT] = (_BENCHMARK, "benchmark_id")
    _truth.IDENTITY_FIELDS[_BENCHMARK] = "benchmark_id"


def _ensure_projection_bucket(truth: TruthRuntime) -> None:
    if not hasattr(truth.projection, _BUCKET):
        setattr(truth.projection, _BUCKET, {})
    truth.projection._versions.setdefault(_BENCHMARK, {})


class JourneyBenchmarkService:
    def __init__(self, truth: TruthRuntime, *, release_id: str) -> None:
        install_rc72_journey_benchmark_overlay()
        _ensure_projection_bucket(truth)
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("JOURNEY_BENCHMARK_RELEASE_ID_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()

    def install_overlay(self) -> None:
        install_rc72_journey_benchmark_overlay()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("JOURNEY_BENCHMARK_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    def _update_candidate(self, candidate: Dict[str, Any], state: JourneyBenchmarkState) -> None:
        updated = dict(candidate)
        updated.pop("artifact_type", None)
        updated["artifact_version"] = int(candidate.get("artifact_version", 1)) + 1
        updated["benchmark_status"] = state.value
        self.truth.append_atomic("RC72_JOURNEY_CANDIDATE_UPSERTED", updated)

    def evaluate(
        self,
        *,
        benchmark_id: str,
        candidate_id: str,
        replay_ids: Sequence[str],
        policy: JourneyBenchmarkPolicy,
    ) -> JourneyBenchmarkResult:
        if not isinstance(benchmark_id, str) or not benchmark_id.strip():
            raise ContractError("JOURNEY_BENCHMARK_ID_REQUIRED")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ContractError("JOURNEY_BENCHMARK_CANDIDATE_ID_REQUIRED")
        if self.truth.query(_BENCHMARK, benchmark_id=benchmark_id):
            raise ContractError("JOURNEY_BENCHMARK_ALREADY_EXISTS")
        if not isinstance(policy, JourneyBenchmarkPolicy):
            raise ContractError("JOURNEY_BENCHMARK_POLICY_REQUIRED")
        policy.validate()
        ids = list(replay_ids)
        if not ids or not all(isinstance(x, str) and x.strip() for x in ids):
            raise ContractError("JOURNEY_BENCHMARK_REPLAY_IDS_REQUIRED")
        if len(ids) != len(set(ids)):
            raise ContractError("JOURNEY_BENCHMARK_REPLAY_IDS_DUPLICATE")

        candidate = self._one("rc72_journey_candidate", candidate_id=candidate_id)
        if candidate.get("state") != "COMPILED_CANDIDATE":
            raise ContractError("JOURNEY_BENCHMARK_REQUIRES_COMPILED_CANDIDATE")
        if candidate.get("official") is not False or candidate.get("executable") is not False:
            raise ContractError("JOURNEY_BENCHMARK_CANDIDATE_PROMOTION_INVALID")

        replays: List[Dict[str, Any]] = []
        for replay_id in ids:
            replay = self._one("rc72_journey_replay", replay_id=replay_id)
            if replay.get("candidate_id") != candidate_id:
                raise ContractError("JOURNEY_BENCHMARK_REPLAY_CANDIDATE_MISMATCH")
            if replay.get("state") not in {"PASSED", "FAILED"}:
                raise ContractError("JOURNEY_BENCHMARK_REPLAY_NOT_TERMINAL")
            replays.append(replay)

        passed_count = sum(1 for row in replays if row.get("state") == "PASSED")
        failed_count = len(replays) - passed_count
        field_verified_count = sum(1 for row in replays if row.get("state") == "PASSED" and row.get("field_verified") is True)
        failure_reasons: List[str] = []
        if len(replays) < policy.min_replays:
            failure_reasons.append("MIN_REPLAYS_NOT_MET")
        if policy.require_all_passed and failed_count:
            failure_reasons.append("REPLAY_FAILURE_PRESENT")
        if policy.require_consistent_step_count and len({int(row.get("total_step_count") or 0) for row in replays}) > 1:
            failure_reasons.append("STEP_COUNT_INCONSISTENT")
        if field_verified_count < policy.min_field_verified_replays:
            failure_reasons.append("FIELD_REPLAYS_NOT_MET")

        state = JourneyBenchmarkState.FAILED if failure_reasons else JourneyBenchmarkState.PASSED
        field_benchmark_verified = (
            state == JourneyBenchmarkState.PASSED
            and policy.min_field_verified_replays > 0
            and field_verified_count >= policy.min_field_verified_replays
        )
        payload = {
            "benchmark_id": benchmark_id.strip(),
            "candidate_id": candidate_id.strip(),
            "mission_id": candidate["mission_id"],
            "release_id": self.release_id,
            "release_batch_id": candidate["release_batch_id"],
            "requirement_id": candidate["requirement_id"],
            "sst_id": candidate["sst_id"],
            "obligation_id": candidate["obligation_id"],
            "state": state.value,
            "replay_ids": ids,
            "policy": asdict(policy),
            "total_replay_count": len(replays),
            "passed_count": passed_count,
            "failed_count": failed_count,
            "field_verified_count": field_verified_count,
            "field_benchmark_verified": field_benchmark_verified,
            "failure_reasons": failure_reasons,
            "evaluated_at": _now(),
            "artifact_version": 1,
        }
        self.truth.append_atomic(_EVENT, payload)
        self._update_candidate(candidate, state)
        return JourneyBenchmarkResult(benchmark_id=benchmark_id.strip(), state=state)


install_rc72_journey_benchmark_overlay()
