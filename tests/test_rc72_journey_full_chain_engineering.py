"""C09 composed production-interface rehearsal with concrete CDP evidence files.

A FakeBrowser supplies the browser protocol for deterministic CI. This exercises
actual services and R1 from teaching to benchmark, and deliberately proves that
NO official Journey can emerge without independent real Field human evidence.
It is not a claim of running Chromium, BSK or bank 4A.
"""
from pathlib import Path

import pytest

from rc7_runtime.models import Task
from rc7_runtime.rc72_domain import ExecutionTaskUnit
from rc7_runtime.rc72_journey_benchmark import JourneyBenchmarkPolicy, JourneyBenchmarkService
from rc7_runtime.rc72_journey_compiler import JourneyCompiler
from rc7_runtime.rc72_journey_cdp_capture import JourneyCDPTeachingRecorder
from rc7_runtime.rc72_journey_playwright import JourneyPlaywrightAdapter
from rc7_runtime.rc72_journey_promotion import JourneyPromotionService
from rc7_runtime.rc72_journey_replay import JourneyReplayService
from rc7_runtime.rc72_browser_resources import BrowserAccessMode
from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.truth_overlay import append_entity

from test_rc72_phase9_journey_teaching_capture_contract import _setup as teaching_setup
from test_rc72_journey_playwright_adapter import FakeBrowser, FakePage, resolver


class NoFakeFieldApproval:
    verifier_kind = "BANK_HUMAN_GATE"

    def resolve(self, reference):
        raise ValueError("NO_REAL_BANK_HUMAN_ATTESTATION")


def test_journey_teaching_compile_real_step_adapter_twice_benchmark_field_gate(tmp_path: Path):
    truth, teaching, pool, teaching_lease = teaching_setup(tmp_path)
    page = FakePage(text="Saved")
    page.url = "https://fat1.example/config?temporary_token=never-export"
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "teaching-evidence",
        connector=lambda endpoint: FakeBrowser(page))
    recorder.begin(
        recording_id="JR-E2E", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
        workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        session_id="SESSION-1", browser_lease_id=teaching_lease.browser_lease_id,
        human_operator_ref="human://operator/001",
        auth_asset_ref="auth://4a/session-asset")
    page.events = [{"type": "CLICK", "element_ref": "css:#save",
                    "url": "https://fat1.example/config"}]
    assert recorder.poll(page_role="configuration") == ["JR-E2E:2"]
    recorder.record_assertion(
        page_role="configuration", oracle_ref="oracle://success-toast",
        element_ref="css:#toast")
    assert recorder.finish().state.value == "CAPTURED"
    recording = truth.query("rc72_journey_recording", recording_id="JR-E2E")[0]
    assert recording["case_id"] == "TC-1"
    assert recording["executable"] is False

    candidate_result = JourneyCompiler(truth, release_id="RC7.2").compile(
        candidate_id="JC-E2E", recording_id="JR-E2E")
    assert candidate_result.state.value == "COMPILED_CANDIDATE"
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-E2E")[0]
    assert candidate["case_id"] == "TC-1"
    assert [x["action_type"] for x in candidate["steps"]] == ["NAVIGATE", "CLICK", "ASSERT"]
    assert candidate["executable"] is False and candidate["official"] is False

    pool.release(teaching_lease.browser_lease_id, reason="teaching done")
    repository = CanonicalRC72Repository(truth, release_id="RC7.2")
    for index in (1, 2):
        workitem = "WI-REPLAY-%s" % index
        attempt = "ATT-REPLAY-%s" % index
        worker = "WORKER-REPLAY-%s" % index
        session = "SESSION-REPLAY-%s" % index
        append_entity(truth, Task(
            task_id=workitem, mission_id="M-1", node="N6_EXECUTABLE_READINESS",
            task_type="JOURNEY_REPLAY", objective="benchmark captured journey",
            required_capabilities=["browser:write"], input_artifact_refs=["ETU-1", "JC-E2E"],
            acceptance_criteria=["actual browser evidence persisted"]),
            release_id="RC7.2")
        repository.persist(WorkItemAttemptBinding(
            binding_id="BIND-REPLAY-%s" % index,
            mission_id="M-1", etu_id="ETU-1", workitem_id=workitem,
            case_id="TC-1", attempt_id=attempt, worker_id=worker,
            session_id=session, task_lease_ref="TASKLEASE-REPLAY-%s" % index,
            state=WorkItemAttemptState.RUNNING))
        browser_lease = pool.acquire(
            mission_id="M-1", workitem_id=workitem, attempt_id=attempt,
            worker_id=worker, access_mode=BrowserAccessMode.WRITE,
            purpose="JOURNEY_REPLAY", ttl_seconds=300)
        adapter = JourneyPlaywrightAdapter(
            browser_pool=pool, evidence_root=tmp_path / "replay-evidence",
            reference_resolver=resolver, connector=lambda endpoint: FakeBrowser(page))
        replay = JourneyReplayService(
            truth, release_id="RC7.2", browser_pool=pool, adapter=adapter)
        result = replay.replay(
            replay_id="JRP-E2E-%s" % index, candidate_id="JC-E2E",
            workitem_id=workitem, attempt_id=attempt, worker_id=worker,
            session_id=session, browser_lease_id=browser_lease.browser_lease_id)
        assert result.state.value == "PASSED"
        assert truth.query(
            "rc72_journey_replay", replay_id="JRP-E2E-%s" % index)[0]["case_id"] == "TC-1"
        assert len(truth.query(
            "rc72_journey_replay_step", replay_id="JRP-E2E-%s" % index)) == 3
        assert (tmp_path / "replay-evidence" /
                ("JRP-E2E-%s" % index) / "step-0003" / "actual.json").is_file()
        adapter.close()
        pool.release(browser_lease.browser_lease_id, reason="benchmark run complete")

    result = JourneyBenchmarkService(truth, release_id="RC7.2").evaluate(
        benchmark_id="JB-E2E", candidate_id="JC-E2E",
        replay_ids=["JRP-E2E-1", "JRP-E2E-2"],
        policy=JourneyBenchmarkPolicy(min_replays=2))
    assert result.state.value == "PASSED"
    benchmark = truth.query("rc72_journey_benchmark", benchmark_id="JB-E2E")[0]
    assert benchmark["passed_count"] == 2
    assert benchmark["field_verified_count"] == 0
    assert benchmark["field_benchmark_verified"] is False

    promotion = JourneyPromotionService(
        truth, release_id="RC7.2", approval_verifier=NoFakeFieldApproval(),
        trusted_field_verifier_kinds=())
    with pytest.raises(Exception, match="JOURNEY_PROMOTION_FIELD_BENCHMARK_REQUIRED"):
        promotion.review_and_promote(
            review_id="JR-E2E-REVIEW", official_asset_id="OJ-E2E",
            candidate_id="JC-E2E", benchmark_id="JB-E2E",
            attestation_ref="human-gate://NO_REAL_ATTESTATION")
    assert not truth.query("rc72_official_journey_asset")
    assert truth.query("rc72_journey_candidate", candidate_id="JC-E2E")[0]["executable"] is False
