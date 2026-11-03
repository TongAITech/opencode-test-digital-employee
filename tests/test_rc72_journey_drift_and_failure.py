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
