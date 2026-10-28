"""RC7.2 trusted Human Review and Official Journey promotion.

Promotion is deliberately separated from worker/model execution.  The caller
cannot pass an approval boolean or reviewer identity.  Instead an external
HumanApprovalVerifier resolves a canonical attestation reference.  Runtime then
checks exact Candidate/Benchmark scope, versions and digest, requires a
Field-verified Benchmark and a trusted Field human verifier, persists review
truth, and creates a separate immutable Official Journey asset.
"""
from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Set

from rc6_runtime import contracts as _contracts
from rc6_runtime import truth as _truth
from rc6_runtime.truth import TruthRuntime

from .models import ContractError
from .rc72_journey_benchmark import install_rc72_journey_benchmark_overlay

_REVIEW = "rc72_journey_human_review"
_OFFICIAL = "rc72_official_journey_asset"
_REVIEW_EVENT = "RC72_JOURNEY_HUMAN_REVIEW_UPSERTED"
_OFFICIAL_EVENT = "RC72_OFFICIAL_JOURNEY_ASSET_UPSERTED"
_REVIEW_BUCKET = "rc72_journey_human_reviews"
_OFFICIAL_BUCKET = "rc72_official_journey_assets"


class JourneyHumanReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class JourneyPromotionResult:
    review_id: str
    decision: JourneyHumanReviewDecision
    official_asset_id: Optional[str] = None


def _now() -> int:
    return int(time.time())


def _required(out: Dict[str, Any], name: str) -> str:
    return _contracts._require_str(out, name)


def _string_list(out: Dict[str, Any], name: str, *, nonempty: bool = False) -> None:
    value = out.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    if nonempty and not value:
        raise _contracts.DomainValidationError("%s_REQUIRED" % name.upper())
    out[name] = list(value)


def _digest_payload(candidate: Mapping[str, Any], benchmark: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "candidate": {
            "candidate_id": candidate.get("candidate_id"),
            "artifact_version": candidate.get("artifact_version"),
            "mission_id": candidate.get("mission_id"),
            "release_batch_id": candidate.get("release_batch_id"),
            "requirement_id": candidate.get("requirement_id"),
            "sst_id": candidate.get("sst_id"),
            "obligation_id": candidate.get("obligation_id"),
            "source_recording_id": candidate.get("source_recording_id"),
            "state": candidate.get("state"),
            "asset_class": candidate.get("asset_class"),
            "replay_status": candidate.get("replay_status"),
            "benchmark_status": candidate.get("benchmark_status"),
            "review_status": candidate.get("review_status"),
            "steps": candidate.get("steps"),
        },
        "benchmark": {
            "benchmark_id": benchmark.get("benchmark_id"),
            "artifact_version": benchmark.get("artifact_version"),
            "candidate_id": benchmark.get("candidate_id"),
            "mission_id": benchmark.get("mission_id"),
            "release_batch_id": benchmark.get("release_batch_id"),
            "requirement_id": benchmark.get("requirement_id"),
            "sst_id": benchmark.get("sst_id"),
            "obligation_id": benchmark.get("obligation_id"),
            "state": benchmark.get("state"),
            "replay_ids": benchmark.get("replay_ids"),
            "policy": benchmark.get("policy"),
            "field_verified_count": benchmark.get("field_verified_count"),
            "field_benchmark_verified": benchmark.get("field_benchmark_verified"),
            "failure_reasons": benchmark.get("failure_reasons"),
        },
    }


def approval_scope_digest(candidate: Mapping[str, Any], benchmark: Mapping[str, Any]) -> str:
    raw = json.dumps(_digest_payload(candidate, benchmark), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_review(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "review_id", "candidate_id", "benchmark_id", "mission_id", "release_id",
        "release_batch_id", "requirement_id", "sst_id", "obligation_id",
        "decision", "human_actor_ref", "attestation_ref", "verifier_kind",
        "scope_digest", "rationale",
    ):
        out[name] = _required(out, name)
    out["artifact_type"] = _REVIEW
    out["artifact_version"] = _contracts._artifact_version(out)
    try:
        out["decision"] = JourneyHumanReviewDecision(out["decision"].upper()).value
    except ValueError as exc:
        raise _contracts.DomainValidationError("JOURNEY_HUMAN_REVIEW_DECISION_INVALID") from exc
    if out.get("actor_type") != "HUMAN":
        raise _contracts.DomainValidationError("JOURNEY_HUMAN_REVIEW_ACTOR_MUST_BE_HUMAN")
    if out.get("field_verified") is not True:
        raise _contracts.DomainValidationError("JOURNEY_HUMAN_REVIEW_FIELD_ATTESTATION_REQUIRED")
    for name in ("candidate_artifact_version", "benchmark_artifact_version"):
        if not isinstance(out.get(name), int) or out[name] < 1:
            raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    _string_list(out, "evidence_refs", nonempty=True)
    if not isinstance(out.get("issued_at"), int) or out["issued_at"] < 0:
        raise _contracts.DomainValidationError("JOURNEY_HUMAN_REVIEW_ISSUED_AT_INVALID")
    if not isinstance(out.get("reviewed_at"), int) or out["reviewed_at"] < 0:
        raise _contracts.DomainValidationError("JOURNEY_HUMAN_REVIEW_REVIEWED_AT_INVALID")
    return out


def _validate_official(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _contracts.DomainValidationError("ARTIFACT_MUST_BE_OBJECT")
    out = dict(payload)
    for name in (
        "official_asset_id", "mission_id", "release_id", "release_batch_id",
        "requirement_id", "sst_id", "obligation_id", "source_candidate_id",
        "source_benchmark_id", "human_review_id", "approval_scope_digest", "status",
    ):
        out[name] = _required(out, name)
    out["artifact_type"] = _OFFICIAL
    out["artifact_version"] = _contracts._artifact_version(out)
    if out["status"] != "OFFICIAL":
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_STATUS_INVALID")
    if out.get("official") is not True or out.get("executable") is not True:
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_FLAGS_REQUIRED")
    if out.get("field_benchmark_verified") is not True or out.get("human_field_verified") is not True:
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_FIELD_PROOF_REQUIRED")
    for name in ("source_candidate_artifact_version", "source_benchmark_artifact_version"):
        if not isinstance(out.get(name), int) or out[name] < 1:
            raise _contracts.DomainValidationError("%s_INVALID" % name.upper())
    steps = out.get("steps")
    if not isinstance(steps, list) or not steps:
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_STEPS_REQUIRED")
    for step in steps:
        if not isinstance(step, dict) or "capture_metadata" in step or "value" in step:
            raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_STEP_INVALID")
    _string_list(out, "approval_evidence_refs", nonempty=True)
    if not isinstance(out.get("promoted_at"), int) or out["promoted_at"] < 0:
        raise _contracts.DomainValidationError("OFFICIAL_JOURNEY_PROMOTED_AT_INVALID")
    return out


def install_rc72_journey_promotion_overlay() -> None:
    install_rc72_journey_benchmark_overlay()
    _contracts.VALIDATORS[_REVIEW] = _validate_review
    _contracts.VALIDATORS[_OFFICIAL] = _validate_official
    _truth.BUCKETS[_REVIEW] = _REVIEW_BUCKET
    _truth.BUCKETS[_OFFICIAL] = _OFFICIAL_BUCKET
    _truth.EVENT_TYPES[_REVIEW_EVENT] = (_REVIEW, "review_id")
    _truth.EVENT_TYPES[_OFFICIAL_EVENT] = (_OFFICIAL, "official_asset_id")
    _truth.IDENTITY_FIELDS[_REVIEW] = "review_id"
    _truth.IDENTITY_FIELDS[_OFFICIAL] = "official_asset_id"


def _ensure_projection_buckets(truth: TruthRuntime) -> None:
    for artifact_type, bucket in ((_REVIEW, _REVIEW_BUCKET), (_OFFICIAL, _OFFICIAL_BUCKET)):
        if not hasattr(truth.projection, bucket):
            setattr(truth.projection, bucket, {})
        truth.projection._versions.setdefault(artifact_type, {})


class JourneyPromotionService:
    def __init__(
        self,
        truth: TruthRuntime,
        *,
        release_id: str,
        approval_verifier: Any,
        trusted_field_verifier_kinds: Sequence[str] = (),
    ) -> None:
        install_rc72_journey_promotion_overlay()
        _ensure_projection_buckets(truth)
        if not isinstance(release_id, str) or not release_id.strip():
            raise ContractError("JOURNEY_PROMOTION_RELEASE_ID_REQUIRED")
        verifier_kind = getattr(approval_verifier, "verifier_kind", None)
        if not isinstance(verifier_kind, str) or not verifier_kind.strip():
            raise ContractError("JOURNEY_HUMAN_REVIEW_VERIFIER_KIND_REQUIRED")
        if not callable(getattr(approval_verifier, "resolve", None)):
            raise ContractError("JOURNEY_HUMAN_REVIEW_VERIFIER_REQUIRED")
        self.truth = truth
        self.release_id = release_id.strip()
        self.approval_verifier = approval_verifier
        self.verifier_kind = verifier_kind.strip()
        self.trusted_field_verifier_kinds: Set[str] = {
            str(kind).strip() for kind in trusted_field_verifier_kinds
            if isinstance(kind, str) and str(kind).strip()
        }

    def install_overlay(self) -> None:
        install_rc72_journey_promotion_overlay()

    def _one(self, artifact_type: str, **filters: Any) -> Dict[str, Any]:
        rows = self.truth.query(artifact_type, **filters)
        if len(rows) != 1:
            raise ContractError("JOURNEY_PROMOTION_TRUTH_NOT_UNIQUE:%s:%d" % (artifact_type, len(rows)))
        return rows[0]

    def _resolve_attestation(self, attestation_ref: str) -> Dict[str, Any]:
        if not isinstance(attestation_ref, str) or not attestation_ref.strip():
            raise ContractError("JOURNEY_HUMAN_REVIEW_ATTESTATION_REF_REQUIRED")
        try:
            raw = self.approval_verifier.resolve(attestation_ref.strip())
        except Exception as exc:
            raise ContractError("JOURNEY_HUMAN_REVIEW_ATTESTATION_UNVERIFIED") from exc
        if not isinstance(raw, Mapping):
            raise ContractError("JOURNEY_HUMAN_REVIEW_ATTESTATION_INVALID")
        attestation = dict(raw)
        if attestation.get("attestation_ref") != attestation_ref.strip():
            raise ContractError("JOURNEY_HUMAN_REVIEW_ATTESTATION_REF_MISMATCH")
        if attestation.get("actor_type") != "HUMAN":
            raise ContractError("JOURNEY_HUMAN_REVIEW_ACTOR_MUST_BE_HUMAN")
        if self.verifier_kind not in self.trusted_field_verifier_kinds or attestation.get("field_verified") is not True:
            raise ContractError("JOURNEY_HUMAN_REVIEW_FIELD_ATTESTATION_REQUIRED")
        return attestation

    @staticmethod
    def _validate_scope(attestation: Mapping[str, Any], candidate: Mapping[str, Any], benchmark: Mapping[str, Any]) -> None:
        expected = {
            "candidate_id": candidate.get("candidate_id"),
            "benchmark_id": benchmark.get("benchmark_id"),
            "release_batch_id": candidate.get("release_batch_id"),
            "requirement_id": candidate.get("requirement_id"),
            "sst_id": candidate.get("sst_id"),
            "obligation_id": candidate.get("obligation_id"),
            "candidate_artifact_version": candidate.get("artifact_version"),
            "benchmark_artifact_version": benchmark.get("artifact_version"),
            "scope_digest": approval_scope_digest(candidate, benchmark),
        }
        if any(attestation.get(key) != value for key, value in expected.items()):
            raise ContractError("JOURNEY_HUMAN_REVIEW_STALE_SCOPE")

    def _review_payload(
        self,
        *,
        review_id: str,
        candidate: Mapping[str, Any],
        benchmark: Mapping[str, Any],
        attestation: Mapping[str, Any],
    ) -> Dict[str, Any]:
        try:
            decision = JourneyHumanReviewDecision(str(attestation.get("decision") or "").upper())
        except ValueError as exc:
            raise ContractError("JOURNEY_HUMAN_REVIEW_DECISION_INVALID") from exc
        human_actor_ref = attestation.get("human_actor_ref")
        rationale = attestation.get("rationale")
        evidence_refs = attestation.get("evidence_refs")
        issued_at = attestation.get("issued_at")
        if not isinstance(human_actor_ref, str) or not human_actor_ref.strip():
            raise ContractError("JOURNEY_HUMAN_REVIEW_ACTOR_REF_REQUIRED")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ContractError("JOURNEY_HUMAN_REVIEW_RATIONALE_REQUIRED")
        if not isinstance(evidence_refs, list) or not evidence_refs or not all(isinstance(x, str) and x.strip() for x in evidence_refs):
            raise ContractError("JOURNEY_HUMAN_REVIEW_EVIDENCE_REQUIRED")
        if not isinstance(issued_at, int) or issued_at < 0:
            raise ContractError("JOURNEY_HUMAN_REVIEW_ISSUED_AT_INVALID")
        return {
            "review_id": review_id,
            "candidate_id": candidate["candidate_id"],
            "benchmark_id": benchmark["benchmark_id"],
            "mission_id": candidate["mission_id"],
            "release_id": self.release_id,
            "release_batch_id": candidate["release_batch_id"],
            "requirement_id": candidate["requirement_id"],
            "sst_id": candidate["sst_id"],
            "obligation_id": candidate["obligation_id"],
            "decision": decision.value,
            "actor_type": "HUMAN",
            "human_actor_ref": human_actor_ref.strip(),
            "attestation_ref": attestation["attestation_ref"],
            "verifier_kind": self.verifier_kind,
            "field_verified": True,
            "candidate_artifact_version": int(candidate["artifact_version"]),
            "benchmark_artifact_version": int(benchmark["artifact_version"]),
            "scope_digest": approval_scope_digest(candidate, benchmark),
            "rationale": rationale.strip(),
            "evidence_refs": list(evidence_refs),
            "issued_at": issued_at,
            "reviewed_at": _now(),
            "artifact_version": 1,
        }

    def _update_candidate_review(self, candidate: Mapping[str, Any], decision: JourneyHumanReviewDecision) -> None:
        updated = deepcopy(dict(candidate))
        updated.pop("artifact_type", None)
        updated["artifact_version"] = int(candidate.get("artifact_version", 1)) + 1
        updated["review_status"] = decision.value
        updated["official"] = False
        updated["executable"] = False
        self.truth.append_atomic("RC72_JOURNEY_CANDIDATE_UPSERTED", updated)

    def review_and_promote(
        self,
        *,
        review_id: str,
        official_asset_id: str,
        candidate_id: str,
        benchmark_id: str,
        attestation_ref: str,
    ) -> JourneyPromotionResult:
        for value, name in (
            (review_id, "review_id"), (official_asset_id, "official_asset_id"),
            (candidate_id, "candidate_id"), (benchmark_id, "benchmark_id"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContractError("JOURNEY_%s_REQUIRED" % name.upper())
        if self.truth.query(_OFFICIAL, source_candidate_id=candidate_id):
            raise ContractError("JOURNEY_ALREADY_PROMOTED")
        if self.truth.query(_REVIEW, candidate_id=candidate_id):
            raise ContractError("JOURNEY_HUMAN_REVIEW_ALREADY_EXISTS")

        candidate = self._one("rc72_journey_candidate", candidate_id=candidate_id)
        benchmark = self._one("rc72_journey_benchmark", benchmark_id=benchmark_id)
        if benchmark.get("candidate_id") != candidate_id:
            raise ContractError("JOURNEY_PROMOTION_BENCHMARK_CANDIDATE_MISMATCH")
        if candidate.get("benchmark_status") != "PASSED" or benchmark.get("state") != "PASSED":
            raise ContractError("JOURNEY_PROMOTION_BENCHMARK_PASS_REQUIRED")
        if benchmark.get("field_benchmark_verified") is not True:
            raise ContractError("JOURNEY_PROMOTION_FIELD_BENCHMARK_REQUIRED")
        if candidate.get("official") is not False or candidate.get("executable") is not False:
            raise ContractError("JOURNEY_PROMOTION_CANDIDATE_STATE_INVALID")
        if candidate.get("review_status") != "NOT_REVIEWED":
            raise ContractError("JOURNEY_PROMOTION_CANDIDATE_ALREADY_REVIEWED")

        attestation = self._resolve_attestation(attestation_ref)
        self._validate_scope(attestation, candidate, benchmark)
        review = self._review_payload(
            review_id=review_id.strip(), candidate=candidate, benchmark=benchmark, attestation=attestation,
        )
        decision = JourneyHumanReviewDecision(review["decision"])
        self.truth.append_atomic(_REVIEW_EVENT, review)
        self._update_candidate_review(candidate, decision)
        if decision == JourneyHumanReviewDecision.REJECTED:
            return JourneyPromotionResult(review_id=review_id.strip(), decision=decision, official_asset_id=None)

        official = {
            "official_asset_id": official_asset_id.strip(),
            "mission_id": candidate["mission_id"],
            "release_id": self.release_id,
            "release_batch_id": candidate["release_batch_id"],
            "requirement_id": candidate["requirement_id"],
            "sst_id": candidate["sst_id"],
            "obligation_id": candidate["obligation_id"],
            "source_candidate_id": candidate["candidate_id"],
            "source_candidate_artifact_version": int(candidate["artifact_version"]),
            "source_benchmark_id": benchmark["benchmark_id"],
            "source_benchmark_artifact_version": int(benchmark["artifact_version"]),
            "human_review_id": review_id.strip(),
            "approval_scope_digest": review["scope_digest"],
            "status": "OFFICIAL",
            "official": True,
            "executable": True,
            "field_benchmark_verified": True,
            "human_field_verified": True,
            "steps": deepcopy(candidate["steps"]),
            "approval_evidence_refs": list(review["evidence_refs"]),
            "promoted_at": _now(),
            "artifact_version": 1,
        }
        self.truth.append_atomic(_OFFICIAL_EVENT, official)
        return JourneyPromotionResult(
            review_id=review_id.strip(), decision=decision, official_asset_id=official_asset_id.strip(),
        )


install_rc72_journey_promotion_overlay()
