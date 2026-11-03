"""C09 drift quarantine, new approval and exception-evidence negative proofs."""
import json
from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_browser_resources import BrowserPool
from rc7_runtime.rc72_journey_drift import JourneyDriftService
from rc7_runtime.rc72_journey_promotion import JourneyPromotionService
from rc7_runtime.rc72_journey_replay import JourneyReplayService
from rc7_runtime.rc72_official_journey_execution import OfficialJourneyExecutionService

from test_rc72_phase9_official_journey_consumption_contract import _setup as official_setup, _run
from test_rc72_phase9_journey_human_promotion_contract import _truth, _attestation, _service
from test_rc72_phase9_journey_replay_contract import _setup as replay_setup


class RealFileFailAdapter:
    adapter_kind = "ENGINEERING_TEST"
    field_verified = False

    def __init__(self, root):
        self.root = Path(root)
        self.calls = 0

    def execute_step(self, step, context):
        self.calls += 1
        path = self.root / "real-failure.json"
        path.write_text(json.dumps({"status": "FAILED", "step": step["sequence"]}))
        ref = path.resolve().as_uri()
        return {"status": "FAILED", "actual_refs": [ref],
                "evidence_refs": [ref], "failure_code": "LOCATOR_NOT_FOUND"}


def test_drift_requires_actual_failure_and_quarantines_official_asset(tmp_path):
    adapter = RealFileFailAdapter(tmp_path)
    truth, pool, lease, _, service = official_setup(tmp_path, adapter=adapter)
    drift = JourneyDriftService(truth, release_id="RC7.2")
    with pytest.raises(Exception, match="REQUIRES_FAILED_EXECUTION"):
        drift.report(drift_id="DRIFT-1", execution_id="OJ-1", reason="LOCATOR_CHANGED")
    assert _run(service, lease, execution_id="OJ-1").state.value == "FAILED"
    report = drift.report(drift_id="DRIFT-1", execution_id="OJ-1", reason="LOCATOR_CHANGED")
    assert report["status"] == "BLOCKED_REAPPROVAL"
    assert report["failure_evidence_refs"][0].startswith("file://")
    assert adapter.calls == 1
    with pytest.raises(Exception, match="OFFICIAL_JOURNEY_DRIFT_REAPPROVAL_REQUIRED"):
        _run(service, lease, execution_id="OJ-2")
    assert adapter.calls == 1
    restarted = TruthRuntime(tmp_path / "r1.jsonl")
    recovered = OfficialJourneyExecutionService(
        restarted, release_id="RC7.2",
        browser_pool=BrowserPool(restarted, release_id="RC7.2"), adapter=adapter)
    with pytest.raises(Exception, match="OFFICIAL_JOURNEY_DRIFT_REAPPROVAL_REQUIRED"):
        _run(recovered, lease, execution_id="OJ-3")
    assert adapter.calls == 1


class RaisesSecret:
    adapter_kind = "ENGINEERING_TEST"
    field_verified = False

    def execute_step(self, step, context):
        raise RuntimeError("do not persist credentials")


def test_unexpected_adapter_exception_is_real_receipt_not_fabricated_uri(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    service = JourneyReplayService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=RaisesSecret())
    result = service.replay(
        replay_id="JRP-EX", candidate_id="JC-1", workitem_id="WI-R1",
        attempt_id="ATT-R1", worker_id="WORKER-R1", session_id="SESSION-R1",
        browser_lease_id=lease.browser_lease_id)
    assert result.state.value == "FAILED"
    receipt = truth.query("rc72_journey_replay_step", replay_id="JRP-EX")[0]["evidence_refs"][0]
    assert receipt.startswith("file://") and "adapter-error://" not in receipt
    evidence = Path(receipt[7:]).read_text()
    assert "ADAPTER_RUNTIME_FAILURE_NOT_SUT_ASSERTION" in evidence
    assert "do not persist credentials" not in evidence


def test_failed_latest_replay_blocks_old_benchmark_promotion(tmp_path):
    truth = _truth(tmp_path)
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    changed = dict(candidate)
    changed.pop("artifact_type")
    changed["artifact_version"] += 1
    changed["replay_status"] = "FAILED"
    truth.append_atomic("RC72_JOURNEY_CANDIDATE_UPSERTED", changed)
    attestation = _attestation(truth, candidate_version=4)
    service = _service(truth, attestation)
    with pytest.raises(Exception, match="JOURNEY_PROMOTION_LATEST_REPLAY_PASS_REQUIRED"):
        service.review_and_promote(
            review_id="JREV-FAIL", official_asset_id="OJ-FAIL",
            candidate_id="JC-1", benchmark_id="JB-1",
            attestation_ref=attestation["attestation_ref"])
    assert not truth.query("rc72_official_journey_asset")


class MalformedReceiptAdapter:
    adapter_kind = "ENGINEERING_TEST"
    field_verified = False

    def __init__(self):
        self.calls = 0

    def execute_step(self, step, context):
        self.calls += 1
        # Post-I/O adapter bug: no actual/evidence refs and no valid status.
        return {"status": "PASSED", "actual_refs": [], "evidence_refs": []}


def test_malformed_browser_return_is_failed_with_durable_runtime_receipt(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    malformed = MalformedReceiptAdapter()
    service = JourneyReplayService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=malformed)
    result = service.replay(
        replay_id="JRP-MALFORMED", candidate_id="JC-1", workitem_id="WI-R1",
        attempt_id="ATT-R1", worker_id="WORKER-R1", session_id="SESSION-R1",
        browser_lease_id=lease.browser_lease_id)
    assert result.state.value == "FAILED"
    assert malformed.calls == 1
    step = truth.query("rc72_journey_replay_step", replay_id="JRP-MALFORMED")[0]
    assert step["status"] == "FAILED"
    evidence = Path(step["evidence_refs"][0][7:])
    assert evidence.is_file()
    assert "ADAPTER_RUNTIME_FAILURE_NOT_SUT_ASSERTION" in evidence.read_text()
    with pytest.raises(Exception, match="JOURNEY_REPLAY_ATTEMPT_ALREADY_USED"):
        service.replay(
            replay_id="JRP-NEW-ID", candidate_id="JC-1", workitem_id="WI-R1",
            attempt_id="ATT-R1", worker_id="WORKER-R1", session_id="SESSION-R1",
            browser_lease_id=lease.browser_lease_id)
    assert malformed.calls == 1


def test_official_same_attempt_cannot_replay_with_a_different_execution_id(tmp_path):
    truth, pool, lease, browser, service = official_setup(tmp_path)
    assert _run(service, lease, execution_id="OJ-ONE").state.value == "PASSED"
    with pytest.raises(Exception, match="OFFICIAL_JOURNEY_ATTEMPT_ALREADY_USED"):
        _run(service, lease, execution_id="OJ-OTHER-ID")
    assert len(browser.calls) == 2


class RevokesMidStep:
    adapter_kind = "CONTRACT_BROWSER"
    field_verified = False

    def __init__(self):
        self.pool = None
        self.lease = None
        self.calls = 0

    def execute_step(self, step, context):
        self.calls += 1
        self.pool.release(self.lease.browser_lease_id, reason="handoff to other worker")
        return {"status": "PASSED", "actual_refs": ["actual://claimed"],
                "evidence_refs": ["evidence://claimed"]}


def test_generic_replay_adapter_cannot_fake_pass_after_browser_lease_revoke(tmp_path):
    adapter = RevokesMidStep()
    truth, pool, lease, _, _ = replay_setup(tmp_path, adapter=adapter)
    adapter.pool, adapter.lease = pool, lease
    service = JourneyReplayService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=adapter)
    result = service.replay(
        replay_id="JRP-REVOKED", candidate_id="JC-1", workitem_id="WI-R1",
        attempt_id="ATT-R1", worker_id="WORKER-R1", session_id="SESSION-R1",
        browser_lease_id=lease.browser_lease_id)
    assert result.state.value == "FAILED"
    assert adapter.calls == 1
    step = truth.query("rc72_journey_replay_step", replay_id="JRP-REVOKED")[0]
    assert step["status"] == "FAILED"
    assert step["evidence_refs"][0].startswith("file://")


def test_generic_official_adapter_cannot_fake_pass_after_browser_lease_revoke(tmp_path):
    adapter = RevokesMidStep()
    truth, pool, lease, _, service = official_setup(tmp_path, adapter=adapter)
    adapter.pool, adapter.lease = pool, lease
    assert _run(service, lease, execution_id="OJ-REVOKED").state.value == "FAILED"
    assert adapter.calls == 1
    step = truth.query("rc72_official_journey_execution_step", execution_id="OJ-REVOKED")[0]
    assert step["status"] == "FAILED"
    assert Path(step["evidence_refs"][0][7:]).exists()


def test_teaching_completion_rejects_revoked_browser_lease(tmp_path):
    from test_rc72_phase9_journey_teaching_capture_contract import (
        _setup as teaching_setup, _start, _step,
    )
    truth, teaching, pool, lease = teaching_setup(tmp_path)
    _start(teaching, lease.browser_lease_id)
    _step(teaching)
    pool.release(lease.browser_lease_id, reason="teaching browser lost")
    with pytest.raises(Exception, match="BROWSER_LEASE_NOT_ACTIVE"):
        teaching.complete_recording(recording_id="JR-1", evidence_refs=["file://evidence"])
    assert truth.query("rc72_journey_recording", recording_id="JR-1")[0]["state"] == "CAPTURING"


class BrowserProcessInterrupted:
    adapter_kind = "ENGINEERING_TEST"
    field_verified = False

    def __init__(self):
        self.calls = 0

    def execute_step(self, step, context):
        self.calls += 1
        # Uncatchable process abort: the SUT may have received the CLICK.
        raise KeyboardInterrupt()


def test_replay_cold_crash_holds_unknown_side_effects_without_duplicate_browser_io(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    crashed = BrowserProcessInterrupted()
    service = JourneyReplayService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=crashed)
    arguments = dict(candidate_id="JC-1", workitem_id="WI-R1",
                     attempt_id="ATT-R1", worker_id="WORKER-R1",
                     session_id="SESSION-R1", browser_lease_id=lease.browser_lease_id)
    with pytest.raises(KeyboardInterrupt):
        service.replay(replay_id="JRP-CRASH", **arguments)
    assert truth.query("rc72_journey_replay", replay_id="JRP-CRASH")[0]["state"] == "STARTED"
    reloaded = TruthRuntime(tmp_path / "r1.jsonl")
    recovered = JourneyReplayService(
        reloaded, release_id="RC7.2",
        browser_pool=BrowserPool(reloaded, release_id="RC7.2"),
        adapter=crashed)
    with pytest.raises(Exception, match="UNKNOWN_SIDE_EFFECTS_RECOVERY_REQUIRED"):
        recovered.replay(replay_id="JRP-CRASH-NEW", **arguments)
    assert crashed.calls == 1
    assert not reloaded.query("rc72_journey_replay", replay_id="JRP-CRASH-NEW")


def test_official_cold_crash_holds_unknown_side_effects_without_duplicate_browser_io(tmp_path):
    crashed = BrowserProcessInterrupted()
    truth, pool, lease, _, service = official_setup(tmp_path, adapter=crashed)
    with pytest.raises(KeyboardInterrupt):
        _run(service, lease, execution_id="OJ-CRASH")
    assert truth.query("rc72_official_journey_execution", execution_id="OJ-CRASH")[0]["state"] == "STARTED"
    reloaded = TruthRuntime(tmp_path / "r1.jsonl")
    recovered = OfficialJourneyExecutionService(
        reloaded, release_id="RC7.2",
        browser_pool=BrowserPool(reloaded, release_id="RC7.2"), adapter=crashed)
    with pytest.raises(Exception, match="UNKNOWN_SIDE_EFFECTS_RECOVERY_REQUIRED"):
        _run(recovered, lease, execution_id="OJ-NEW")
    assert crashed.calls == 1
    assert not reloaded.query("rc72_official_journey_execution", execution_id="OJ-NEW")


def test_auth_keeper_browser_lease_cannot_be_reused_for_official_l5(tmp_path):
    from rc7_runtime.rc72_browser_resources import BrowserAccessMode
    truth, pool, lease, browser, service = official_setup(tmp_path)
    pool.release(lease.browser_lease_id, reason="switch actor")
    auth = pool.acquire(
        mission_id="M-1", workitem_id="WI-OJ", attempt_id="ATT-OJ",
        worker_id="WORKER-OJ", access_mode=BrowserAccessMode.WRITE,
        purpose="AUTH_KEEPER", ttl_seconds=300)
    with pytest.raises(Exception, match="OFFICIAL_JOURNEY_BROWSER_PURPOSE_MISMATCH"):
        service.execute(
            execution_id="OJ-AUTH-OWNERSHIP", official_asset_id="JOURNEY-1",
            workitem_id="WI-OJ", attempt_id="ATT-OJ", worker_id="WORKER-OJ",
            session_id="SESSION-OJ", browser_lease_id=auth.browser_lease_id)
    assert not browser.calls


def test_auth_keeper_browser_lease_cannot_be_reused_for_human_teaching(tmp_path):
    from rc7_runtime.rc72_browser_resources import BrowserAccessMode
    from test_rc72_phase9_journey_teaching_capture_contract import (
        _setup as teaching_setup, _start,
    )
    truth, service, pool, lease = teaching_setup(tmp_path)
    pool.release(lease.browser_lease_id, reason="switch actor")
    auth = pool.acquire(
        mission_id="M-1", workitem_id="WI-1", attempt_id="ATT-1",
        worker_id="WORKER-1", access_mode=BrowserAccessMode.WRITE,
        purpose="AUTH_KEEPER", ttl_seconds=300)
    with pytest.raises(Exception, match="JOURNEY_TEACHING_BROWSER_PURPOSE_MISMATCH"):
        _start(service, auth.browser_lease_id)
    assert not truth.query("rc72_journey_recording")


def test_replay_rejects_candidate_cross_case_attempt_scope_before_browser_io(tmp_path):
    truth, pool, lease, adapter, service = replay_setup(tmp_path)
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    updated = dict(candidate)
    updated.pop("artifact_type", None)
    updated["artifact_version"] += 1
    updated["case_id"] = "TC-ANOTHER-CASE"
    truth.append_atomic("RC72_JOURNEY_CANDIDATE_UPSERTED", updated)
    with pytest.raises(Exception, match="JOURNEY_REPLAY_CANONICAL_CASE_MISMATCH"):
        service.replay(
            replay_id="JRP-CROSS-CASE", candidate_id="JC-1",
            workitem_id="WI-R1", attempt_id="ATT-R1", worker_id="WORKER-R1",
            session_id="SESSION-R1", browser_lease_id=lease.browser_lease_id)
    assert not adapter.calls
    assert not truth.query("rc72_journey_replay", replay_id="JRP-CROSS-CASE")
