from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_journey_benchmark import JourneyBenchmarkPolicy, JourneyBenchmarkService, JourneyBenchmarkState
from rc7_runtime.rc72_journey_compiler import install_rc72_journey_compiler_overlay
from rc7_runtime.rc72_journey_replay import install_rc72_journey_replay_overlay


def _candidate(truth: TruthRuntime):
    install_rc72_journey_compiler_overlay()
    truth.append_atomic("RC72_JOURNEY_CANDIDATE_UPSERTED", {
        "candidate_id": "JC-1", "mission_id": "M-1", "release_id": "RC7.2",
        "release_batch_id": "RB-1", "requirement_id": "REQ-1", "sst_id": "SST-1",
        "obligation_id": "TO-1", "source_recording_id": "JR-1",
        "state": "COMPILED_CANDIDATE", "asset_class": "CANDIDATE",
        "executable": False, "official": False, "replay_status": "PASSED",
        "benchmark_status": "NOT_RUN", "review_status": "NOT_REVIEWED",
        "steps": [{
            "source_step_id": "S1", "sequence": 1, "action_type": "ASSERT",
            "url": "https://fat1.example/config", "page_role": "config", "element_ref": "dom://toast",
            "page_state_ref": "page://1", "dom_ref": "dom://1", "network_refs": ["net://1"],
            "screenshot_ref": "shot://1", "wait_semantics": "visible", "evidence_refs": ["ev://1"],
            "oracle_ref": "oracle://success",
        }],
        "compiled_at": 1, "artifact_version": 1,
    })


def _replay(truth: TruthRuntime, replay_id: str, *, state="PASSED", field_verified=False, step_count=1):
    install_rc72_journey_replay_overlay()
    truth.append_atomic("RC72_JOURNEY_REPLAY_UPSERTED", {
        "replay_id": replay_id, "candidate_id": "JC-1", "mission_id": "M-1", "release_id": "RC7.2",
        "release_batch_id": "RB-1", "requirement_id": "REQ-1", "sst_id": "SST-1", "obligation_id": "TO-1",
        "workitem_id": "WI-%s" % replay_id, "attempt_id": "ATT-%s" % replay_id,
        "worker_id": "WORKER-%s" % replay_id, "session_id": "SESSION-%s" % replay_id,
        "browser_lease_id": "BRLEASE-%s" % replay_id, "adapter_kind": "BSK_FIELD" if field_verified else "CONTRACT_BROWSER",
        "field_verified": field_verified, "state": state, "total_step_count": step_count,
        "executed_step_count": step_count if state == "PASSED" else 1,
        "failure_code": None if state == "PASSED" else "ASSERTION_DIVERGENCE",
        "started_at": 10, "completed_at": 11, "artifact_version": 1,
    })


def _setup(tmp_path: Path):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    _candidate(truth)
    return truth, JourneyBenchmarkService(truth, release_id="RC7.2")


def test_benchmark_requires_multiple_replays(tmp_path: Path):
    truth, service = _setup(tmp_path)
    _replay(truth, "R1")
    result = service.evaluate(
        benchmark_id="JB-1", candidate_id="JC-1", replay_ids=["R1"],
        policy=JourneyBenchmarkPolicy(min_replays=2),
    )
    assert result.state == JourneyBenchmarkState.FAILED
    row = truth.query("rc72_journey_benchmark", benchmark_id="JB-1")[0]
    assert row["failure_reasons"] == ["MIN_REPLAYS_NOT_MET"]
    assert truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]["benchmark_status"] == "FAILED"


def test_contract_replays_can_prove_repository_stability_but_not_field_benchmark(tmp_path: Path):
    truth, service = _setup(tmp_path)
    _replay(truth, "R1")
    _replay(truth, "R2")
    result = service.evaluate(
        benchmark_id="JB-1", candidate_id="JC-1", replay_ids=["R1", "R2"],
        policy=JourneyBenchmarkPolicy(min_replays=2, min_field_verified_replays=0),
    )
    assert result.state == JourneyBenchmarkState.PASSED
    row = truth.query("rc72_journey_benchmark", benchmark_id="JB-1")[0]
    assert row["passed_count"] == 2
    assert row["field_verified_count"] == 0
    assert row["field_benchmark_verified"] is False
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    assert candidate["benchmark_status"] == "PASSED"
    assert candidate["official"] is False
    assert candidate["executable"] is False
    assert candidate["review_status"] == "NOT_REVIEWED"


def test_field_policy_requires_explicit_number_of_field_verified_replays(tmp_path: Path):
    truth, service = _setup(tmp_path)
    _replay(truth, "R1", field_verified=True)
    _replay(truth, "R2", field_verified=False)
    result = service.evaluate(
        benchmark_id="JB-1", candidate_id="JC-1", replay_ids=["R1", "R2"],
        policy=JourneyBenchmarkPolicy(min_replays=2, min_field_verified_replays=2),
    )
    assert result.state == JourneyBenchmarkState.FAILED
    row = truth.query("rc72_journey_benchmark", benchmark_id="JB-1")[0]
    assert "FIELD_REPLAYS_NOT_MET" in row["failure_reasons"]
    assert row["field_benchmark_verified"] is False


def test_all_passed_policy_fails_when_any_replay_failed(tmp_path: Path):
    truth, service = _setup(tmp_path)
    _replay(truth, "R1")
    _replay(truth, "R2", state="FAILED")
    result = service.evaluate(
        benchmark_id="JB-1", candidate_id="JC-1", replay_ids=["R1", "R2"],
        policy=JourneyBenchmarkPolicy(min_replays=2, require_all_passed=True),
    )
    assert result.state == JourneyBenchmarkState.FAILED
    assert "REPLAY_FAILURE_PRESENT" in truth.query("rc72_journey_benchmark", benchmark_id="JB-1")[0]["failure_reasons"]


def test_inconsistent_step_shape_fails_benchmark(tmp_path: Path):
    truth, service = _setup(tmp_path)
    _replay(truth, "R1", step_count=1)
    _replay(truth, "R2", step_count=2)
    result = service.evaluate(
        benchmark_id="JB-1", candidate_id="JC-1", replay_ids=["R1", "R2"],
        policy=JourneyBenchmarkPolicy(min_replays=2, require_consistent_step_count=True),
    )
    assert result.state == JourneyBenchmarkState.FAILED
    assert "STEP_COUNT_INCONSISTENT" in truth.query("rc72_journey_benchmark", benchmark_id="JB-1")[0]["failure_reasons"]


def test_duplicate_replay_id_is_rejected_not_double_counted(tmp_path: Path):
    truth, service = _setup(tmp_path)
    _replay(truth, "R1")
    with pytest.raises(Exception, match="JOURNEY_BENCHMARK_REPLAY_IDS_DUPLICATE"):
        service.evaluate(
            benchmark_id="JB-1", candidate_id="JC-1", replay_ids=["R1", "R1"],
            policy=JourneyBenchmarkPolicy(min_replays=2),
        )
    assert not truth.query("rc72_journey_benchmark")


def test_replay_from_other_candidate_is_rejected(tmp_path: Path):
    truth, service = _setup(tmp_path)
    _replay(truth, "R1")
    replay = truth.query("rc72_journey_replay", replay_id="R1")[0]
    # create a second immutable-looking replay truth for another candidate rather than mutating R1.
    other = dict(replay)
    other.pop("artifact_type", None)
    other["replay_id"] = "R2"
    other["candidate_id"] = "JC-OTHER"
    other["artifact_version"] = 1
    truth.append_atomic("RC72_JOURNEY_REPLAY_UPSERTED", other)
    with pytest.raises(Exception, match="JOURNEY_BENCHMARK_REPLAY_CANDIDATE_MISMATCH"):
        service.evaluate(
            benchmark_id="JB-1", candidate_id="JC-1", replay_ids=["R1", "R2"],
            policy=JourneyBenchmarkPolicy(min_replays=2),
        )


def test_benchmark_policy_and_result_survive_r1_restart(tmp_path: Path):
    truth, service = _setup(tmp_path)
    _replay(truth, "R1", field_verified=True)
    _replay(truth, "R2", field_verified=True)
    service.evaluate(
        benchmark_id="JB-1", candidate_id="JC-1", replay_ids=["R1", "R2"],
        policy=JourneyBenchmarkPolicy(min_replays=2, min_field_verified_replays=2),
    )
    replay_truth = TruthRuntime(tmp_path / "r1.jsonl")
    service.install_overlay()
    row = replay_truth.query("rc72_journey_benchmark", benchmark_id="JB-1")[0]
    assert row["state"] == "PASSED"
    assert row["policy"]["min_replays"] == 2
    assert row["policy"]["min_field_verified_replays"] == 2
    assert row["field_benchmark_verified"] is True
