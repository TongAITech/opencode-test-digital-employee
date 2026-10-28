from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Task
from rc7_runtime.rc72_browser_resources import BrowserAccessMode, BrowserPool
from rc7_runtime.rc72_domain import ExecutionTaskUnit, ReleaseBatch, TestObligation
from rc7_runtime.rc72_journey_teaching import JourneyActionType, JourneyRecordingState, JourneyTeachingService
from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.truth_overlay import append_entity


def _setup(tmp_path: Path, *, test_level="L4"):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    repo.persist(ReleaseBatch(
        release_batch_id="RB-1", mission_id="M-1", name="batch",
        application_ids=["cfg-admin"], requirement_ids=["REQ-1"],
    ))
    repo.persist(TestObligation(
        obligation_id="TO-1", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", application_id="cfg-admin",
        business_scenario="authenticated configuration journey",
        business_rule="authorized user completes configuration flow",
        risk_level="HIGH", test_level=test_level,
        code_slice_refs=["ui://configuration-journey"], oracle_refs=["UI", "NETWORK"],
    ))
    repo.persist(ExecutionTaskUnit(
        etu_id="ETU-1", mission_id="M-1", release_batch_id="RB-1", obligation_id="TO-1",
        case_ids=["TC-1"], primary_goal="teach journey", primary_code_slice="ui://configuration-journey",
        test_level=test_level, primary_oracle="UI+NETWORK", data_domain="browser",
        primary_tool_family="browser", planning_snapshot_ref="PLAN-1", cohesion_score=1.0,
        cohesion_explanation="single journey teaching task", required_capabilities=["browser:write"],
        estimated_duration_minutes=10, estimated_cost=1.0,
    ))
    append_entity(truth, Task(
        task_id="WI-1", mission_id="M-1", node="N4_TEST_DESIGN", task_type="JOURNEY_TEACHING",
        objective="capture human teaching flow", required_capabilities=["browser:write"],
        input_artifact_refs=["ETU-1"], acceptance_criteria=["capture truth persisted"],
    ), release_id="RC7.2")
    repo.persist(WorkItemAttemptBinding(
        binding_id="BIND-1", mission_id="M-1", etu_id="ETU-1", workitem_id="WI-1",
        case_id="TC-1", attempt_id="ATT-1", worker_id="WORKER-1", session_id="SESSION-1",
        task_lease_ref="TASKLEASE-1", state=WorkItemAttemptState.RUNNING,
    ))
    pool = BrowserPool(truth, release_id="RC7.2")
    pool.register_instance(
        browser_instance_id="BROWSER-1", profile_dir="profiles/teaching",
        cdp_endpoint="http://127.0.0.1:9222", bsk_endpoint="http://127.0.0.1:4096",
        auth_asset_ref="auth://4a/session-asset",
    )
    lease = pool.acquire(
        mission_id="M-1", workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        access_mode=BrowserAccessMode.WRITE, purpose="JOURNEY_TEACHING", ttl_seconds=300,
    )
    service = JourneyTeachingService(truth, release_id="RC7.2", browser_pool=pool)
    return truth, service, pool, lease


def _start(service, lease_id, **overrides):
    args = dict(
        recording_id="JR-1", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
        workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1", session_id="SESSION-1",
        browser_lease_id=lease_id, human_operator_ref="human://operator/001",
        auth_asset_ref="auth://4a/session-asset",
    )
    args.update(overrides)
    return service.start_recording(**args)


def _step(service, recording_id="JR-1", sequence=1, **overrides):
    args = dict(
        recording_id=recording_id, step_id=f"JRS-{sequence}", sequence=sequence,
        action_type=JourneyActionType.CLICK, url="https://fat1.example/config",
        page_role="configuration-page", element_ref="dom://button/save",
        page_state_ref=f"page-state://{sequence}", dom_ref=f"dom-snapshot://{sequence}",
        network_refs=[f"network://request/{sequence}"], screenshot_ref=f"screenshot://{sequence}",
        wait_semantics="network-idle", evidence_refs=[f"evidence://journey/{sequence}"],
        capture_metadata={"label": "save configuration"},
    )
    args.update(overrides)
    return service.append_step(**args)


def test_recording_requires_exact_release_requirement_sst_obligation_lineage(tmp_path: Path):
    _, service, _, lease = _setup(tmp_path)
    with pytest.raises(Exception, match="JOURNEY_LINEAGE_MISMATCH"):
        _start(service, lease.browser_lease_id, sst_id="SST-WRONG")


def test_only_l4_l5_obligations_are_teachable_journeys(tmp_path: Path):
    _, service, _, lease = _setup(tmp_path, test_level="L3")
    with pytest.raises(Exception, match="JOURNEY_TEACHING_REQUIRES_L4_OR_L5"):
        _start(service, lease.browser_lease_id)


def test_recording_requires_active_write_browser_lease_bound_to_same_attempt_worker(tmp_path: Path):
    _, service, pool, lease = _setup(tmp_path)
    _start(service, lease.browser_lease_id)
    pool.release(lease.browser_lease_id, reason="teaching interrupted")
    with pytest.raises(Exception, match="BROWSER_LEASE_NOT_ACTIVE"):
        service.start_recording(
            recording_id="JR-2", mission_id="M-1", release_batch_id="RB-1",
            requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
            workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1", session_id="SESSION-1",
            browser_lease_id=lease.browser_lease_id, human_operator_ref="human://operator/001",
            auth_asset_ref="auth://4a/session-asset",
        )


def test_steps_are_strictly_ordered_and_capture_only_structured_refs(tmp_path: Path):
    truth, service, _, lease = _setup(tmp_path)
    _start(service, lease.browser_lease_id)
    _step(service, sequence=1)
    _step(service, sequence=2, action_type=JourneyActionType.WAIT, element_ref=None)
    with pytest.raises(Exception, match="JOURNEY_STEP_SEQUENCE_INVALID"):
        _step(service, sequence=4)
    rows = sorted(truth.query("rc72_journey_capture_step", recording_id="JR-1"), key=lambda row: row["sequence"])
    assert [row["sequence"] for row in rows] == [1, 2]
    assert rows[0]["dom_ref"] == "dom-snapshot://1"
    assert rows[0]["network_refs"] == ["network://request/1"]
    assert rows[0]["screenshot_ref"] == "screenshot://1"


@pytest.mark.parametrize("secret_key", ["password", "authorization", "cookie", "access_token", "refresh_token", "session_token", "client_secret"])
def test_plaintext_secret_capture_is_forbidden(tmp_path: Path, secret_key):
    _, service, _, lease = _setup(tmp_path)
    _start(service, lease.browser_lease_id)
    with pytest.raises(Exception, match="JOURNEY_CAPTURE_SECRET_FIELD_FORBIDDEN"):
        _step(service, capture_metadata={secret_key: "plaintext-secret"})


def test_complete_requires_steps_and_evidence_and_remains_candidate_source(tmp_path: Path):
    truth, service, _, lease = _setup(tmp_path)
    _start(service, lease.browser_lease_id)
    with pytest.raises(Exception, match="JOURNEY_RECORDING_STEPS_REQUIRED"):
        service.complete_recording(recording_id="JR-1", evidence_refs=["evidence://summary"])
    _step(service)
    result = service.complete_recording(recording_id="JR-1", evidence_refs=["evidence://summary"])
    assert result.state == JourneyRecordingState.CAPTURED
    row = truth.query("rc72_journey_recording", recording_id="JR-1")[0]
    assert row["state"] == "CAPTURED"
    assert row["asset_class"] == "CANDIDATE_SOURCE"
    assert row["executable"] is False
    assert not truth.query("rc72_journey_asset") if "rc72_journey_asset" in __import__("rc6_runtime.truth", fromlist=["BUCKETS"]).BUCKETS else True


def test_recording_cannot_be_completed_without_recording_evidence(tmp_path: Path):
    _, service, _, lease = _setup(tmp_path)
    _start(service, lease.browser_lease_id)
    _step(service)
    with pytest.raises(Exception, match="JOURNEY_RECORDING_EVIDENCE_REQUIRED"):
        service.complete_recording(recording_id="JR-1", evidence_refs=[])


def test_capture_truth_survives_r1_replay(tmp_path: Path):
    truth, service, _, lease = _setup(tmp_path)
    _start(service, lease.browser_lease_id)
    _step(service)
    service.complete_recording(recording_id="JR-1", evidence_refs=["evidence://summary"])

    replay = TruthRuntime(tmp_path / "r1.jsonl")
    service.install_overlay()
    recording = replay.query("rc72_journey_recording", recording_id="JR-1")[0]
    steps = replay.query("rc72_journey_capture_step", recording_id="JR-1")
    assert recording["state"] == "CAPTURED"
    assert recording["release_batch_id"] == "RB-1"
    assert recording["requirement_id"] == "REQ-1"
    assert recording["sst_id"] == "SST-1"
    assert recording["obligation_id"] == "TO-1"
    assert recording["browser_lease_id"] == lease.browser_lease_id
    assert len(steps) == 1
    assert steps[0]["sequence"] == 1
