from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_journey_benchmark import install_rc72_journey_benchmark_overlay
from rc7_runtime.rc72_journey_compiler import install_rc72_journey_compiler_overlay
from rc7_runtime.rc72_journey_promotion import (
    JourneyHumanReviewDecision,
    JourneyPromotionService,
    approval_scope_digest,
)


class ContractHumanApprovalVerifier:
    verifier_kind = "BANK_HUMAN_GATE"

    def __init__(self, attestations):
        self.attestations = dict(attestations)

    def resolve(self, attestation_ref):
        if attestation_ref not in self.attestations:
            raise ValueError("ATTESTATION_NOT_FOUND")
        return dict(self.attestations[attestation_ref])


def _candidate(truth: TruthRuntime):
    install_rc72_journey_compiler_overlay()
    truth.append_atomic("RC72_JOURNEY_CANDIDATE_UPSERTED", {
        "candidate_id": "JC-1", "mission_id": "M-1", "release_id": "RC7.2",
        "release_batch_id": "RB-1", "requirement_id": "REQ-1", "sst_id": "SST-1",
        "obligation_id": "TO-1", "source_recording_id": "JR-1",
        "state": "COMPILED_CANDIDATE", "asset_class": "CANDIDATE",
        "executable": False, "official": False, "replay_status": "PASSED",
        "benchmark_status": "PASSED", "review_status": "NOT_REVIEWED",
        "steps": [{
            "source_step_id": "S1", "sequence": 1, "action_type": "ASSERT",
            "url": "https://fat1.example/config", "page_role": "config", "element_ref": "dom://toast",
            "page_state_ref": "page://1", "dom_ref": "dom://1", "network_refs": ["net://1"],
            "screenshot_ref": "shot://1", "wait_semantics": "visible", "evidence_refs": ["ev://1"],
            "oracle_ref": "oracle://success",
        }],
        "compiled_at": 1, "artifact_version": 3,
    })


def _benchmark(truth: TruthRuntime, *, field_verified=True):
    install_rc72_journey_benchmark_overlay()
    truth.append_atomic("RC72_JOURNEY_BENCHMARK_UPSERTED", {
        "benchmark_id": "JB-1", "candidate_id": "JC-1", "mission_id": "M-1", "release_id": "RC7.2",
        "release_batch_id": "RB-1", "requirement_id": "REQ-1", "sst_id": "SST-1", "obligation_id": "TO-1",
        "state": "PASSED", "replay_ids": ["R1", "R2"],
        "policy": {
            "min_replays": 2, "require_all_passed": True,
            "require_consistent_step_count": True, "min_field_verified_replays": 2 if field_verified else 0,
        },
        "total_replay_count": 2, "passed_count": 2, "failed_count": 0,
        "field_verified_count": 2 if field_verified else 0,
        "field_benchmark_verified": field_verified,
        "failure_reasons": [], "evaluated_at": 2, "artifact_version": 2,
    })


def _truth(tmp_path: Path, *, field_benchmark=True):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    _candidate(truth)
    _benchmark(truth, field_verified=field_benchmark)
    return truth


def _attestation(truth, *, decision="APPROVED", actor_type="HUMAN", field_verified=True,
                 candidate_version=3, benchmark_version=2, scope_digest=None):
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    benchmark = truth.query("rc72_journey_benchmark", benchmark_id="JB-1")[0]
    return {
        "attestation_ref": "human-gate://approval/A1",
        "actor_type": actor_type,
        "human_actor_ref": "employee://reviewer-001",
        "decision": decision,
        "candidate_id": "JC-1",
        "benchmark_id": "JB-1",
        "release_batch_id": "RB-1",
        "requirement_id": "REQ-1",
        "sst_id": "SST-1",
        "obligation_id": "TO-1",
        "candidate_artifact_version": candidate_version,
        "benchmark_artifact_version": benchmark_version,
        "scope_digest": scope_digest or approval_scope_digest(candidate, benchmark),
        "rationale": "independent human review completed",
        "evidence_refs": ["human-evidence://A1"],
        "issued_at": 100,
        "field_verified": field_verified,
    }


def _service(truth, attestation, *, trusted=("BANK_HUMAN_GATE",)):
    verifier = ContractHumanApprovalVerifier({attestation["attestation_ref"]: attestation})
    return JourneyPromotionService(
        truth, release_id="RC7.2", approval_verifier=verifier,
        trusted_field_verifier_kinds=trusted,
    )


def test_repository_only_benchmark_cannot_be_promoted(tmp_path: Path):
    truth = _truth(tmp_path, field_benchmark=False)
    attestation = _attestation(truth)
    service = _service(truth, attestation)
    with pytest.raises(Exception, match="JOURNEY_PROMOTION_FIELD_BENCHMARK_REQUIRED"):
        service.review_and_promote(review_id="JREV-1", official_asset_id="JOURNEY-1",
                                   candidate_id="JC-1", benchmark_id="JB-1",
                                   attestation_ref=attestation["attestation_ref"])
    assert not truth.query("rc72_official_journey_asset")


def test_worker_or_agent_cannot_self_approve(tmp_path: Path):
    truth = _truth(tmp_path)
    attestation = _attestation(truth, actor_type="WORKER")
    service = _service(truth, attestation)
    with pytest.raises(Exception, match="JOURNEY_HUMAN_REVIEW_ACTOR_MUST_BE_HUMAN"):
        service.review_and_promote(review_id="JREV-1", official_asset_id="JOURNEY-1",
                                   candidate_id="JC-1", benchmark_id="JB-1",
                                   attestation_ref=attestation["attestation_ref"])


def test_untrusted_or_non_field_verifier_cannot_create_official_asset(tmp_path: Path):
    truth = _truth(tmp_path)
    attestation = _attestation(truth, field_verified=False)
    service = _service(truth, attestation)
    with pytest.raises(Exception, match="JOURNEY_HUMAN_REVIEW_FIELD_ATTESTATION_REQUIRED"):
        service.review_and_promote(review_id="JREV-1", official_asset_id="JOURNEY-1",
                                   candidate_id="JC-1", benchmark_id="JB-1",
                                   attestation_ref=attestation["attestation_ref"])
    assert not truth.query("rc72_official_journey_asset")


def test_stale_approval_scope_or_versions_fail_closed(tmp_path: Path):
    truth = _truth(tmp_path)
    stale = _attestation(truth, candidate_version=2, scope_digest="sha256:stale")
    service = _service(truth, stale)
    with pytest.raises(Exception, match="JOURNEY_HUMAN_REVIEW_STALE_SCOPE"):
        service.review_and_promote(review_id="JREV-1", official_asset_id="JOURNEY-1",
                                   candidate_id="JC-1", benchmark_id="JB-1",
                                   attestation_ref=stale["attestation_ref"])


def test_rejected_human_review_is_persisted_without_official_asset(tmp_path: Path):
    truth = _truth(tmp_path)
    attestation = _attestation(truth, decision="REJECTED")
    service = _service(truth, attestation)
    result = service.review_and_promote(review_id="JREV-1", official_asset_id="JOURNEY-1",
                                        candidate_id="JC-1", benchmark_id="JB-1",
                                        attestation_ref=attestation["attestation_ref"])
    assert result.decision == JourneyHumanReviewDecision.REJECTED
    review = truth.query("rc72_journey_human_review", review_id="JREV-1")[0]
    assert review["decision"] == "REJECTED"
    assert review["human_actor_ref"] == "employee://reviewer-001"
    assert not truth.query("rc72_official_journey_asset")
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    assert candidate["review_status"] == "REJECTED"
    assert candidate["official"] is False
    assert candidate["executable"] is False


def test_trusted_field_human_approval_creates_separate_official_asset(tmp_path: Path):
    truth = _truth(tmp_path)
    attestation = _attestation(truth, decision="APPROVED")
    service = _service(truth, attestation)
    result = service.review_and_promote(review_id="JREV-1", official_asset_id="JOURNEY-1",
                                        candidate_id="JC-1", benchmark_id="JB-1",
                                        attestation_ref=attestation["attestation_ref"])
    assert result.decision == JourneyHumanReviewDecision.APPROVED
    official = truth.query("rc72_official_journey_asset", official_asset_id="JOURNEY-1")[0]
    assert official["official"] is True
    assert official["executable"] is True
    assert official["source_candidate_id"] == "JC-1"
    assert official["source_benchmark_id"] == "JB-1"
    assert official["human_review_id"] == "JREV-1"
    assert official["steps"][0]["source_step_id"] == "S1"
    assert official["release_batch_id"] == "RB-1"
    assert official["requirement_id"] == "REQ-1"
    assert official["sst_id"] == "SST-1"
    assert official["obligation_id"] == "TO-1"
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    assert candidate["review_status"] == "APPROVED"
    assert candidate["asset_class"] == "CANDIDATE"
    assert candidate["official"] is False
    assert candidate["executable"] is False


def test_duplicate_or_competing_promotion_fails_closed(tmp_path: Path):
    truth = _truth(tmp_path)
    attestation = _attestation(truth)
    service = _service(truth, attestation)
    service.review_and_promote(review_id="JREV-1", official_asset_id="JOURNEY-1",
                               candidate_id="JC-1", benchmark_id="JB-1",
                               attestation_ref=attestation["attestation_ref"])
    with pytest.raises(Exception, match="JOURNEY_ALREADY_PROMOTED"):
        service.review_and_promote(review_id="JREV-2", official_asset_id="JOURNEY-2",
                                   candidate_id="JC-1", benchmark_id="JB-1",
                                   attestation_ref=attestation["attestation_ref"])


def test_review_and_official_asset_survive_r1_restart(tmp_path: Path):
    truth = _truth(tmp_path)
    attestation = _attestation(truth)
    service = _service(truth, attestation)
    service.review_and_promote(review_id="JREV-1", official_asset_id="JOURNEY-1",
                               candidate_id="JC-1", benchmark_id="JB-1",
                               attestation_ref=attestation["attestation_ref"])
    replay_truth = TruthRuntime(tmp_path / "r1.jsonl")
    service.install_overlay()
    review = replay_truth.query("rc72_journey_human_review", review_id="JREV-1")[0]
    official = replay_truth.query("rc72_official_journey_asset", official_asset_id="JOURNEY-1")[0]
    assert review["decision"] == "APPROVED"
    assert official["official"] is True
    assert official["executable"] is True
