from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Task
from rc7_runtime.rc72_browser_resources import BrowserAccessMode, BrowserPool
from rc7_runtime.rc72_domain import ExecutionTaskUnit, ReleaseBatch, TestObligation
from rc7_runtime.rc72_journey_compiler import JourneyCandidateState, JourneyCompiler
from rc7_runtime.rc72_journey_teaching import JourneyActionType, JourneyTeachingService
from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.truth_overlay import append_entity


def _setup(tmp_path: Path, *, complete=True, include_input=False, include_assert=False):
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
        risk_level="HIGH", test_level="L5",
        code_slice_refs=["ui://configuration-journey"], oracle_refs=["UI", "NETWORK"],
    ))
    repo.persist(ExecutionTaskUnit(
        etu_id="ETU-1", mission_id="M-1", release_batch_id="RB-1", obligation_id="TO-1",
        case_ids=["TC-1"], primary_goal="teach journey", primary_code_slice="ui://configuration-journey",
        test_level="L5", primary_oracle="UI+NETWORK", data_domain="browser",
        primary_tool_family="browser", planning_snapshot_ref="PLAN-1", cohesion_score=1.0,
        cohesion_explanation="single journey", required_capabilities=["browser:write"],
        estimated_duration_minutes=10, estimated_cost=1.0,
    ))
    append_entity(truth, Task(
        task_id="WI-1", mission_id="M-1", node="N4_TEST_DESIGN", task_type="JOURNEY_TEACHING",
        objective="capture flow", required_capabilities=["browser:write"], input_artifact_refs=["ETU-1"],
        acceptance_criteria=["capture persisted"],
    ), release_id="RC7.2")
    repo.persist(WorkItemAttemptBinding(
        binding_id="BIND-1", mission_id="M-1", etu_id="ETU-1", workitem_id="WI-1",
        case_id="TC-1", attempt_id="ATT-1", worker_id="WORKER-1", session_id="SESSION-1",
        task_lease_ref="TASKLEASE-1", state=WorkItemAttemptState.RUNNING,
    ))
    pool = BrowserPool(truth, release_id="RC7.2")
    pool.register_instance(
        browser_instance_id="BROWSER-1", profile_dir="profiles/teach",
        cdp_endpoint="http://127.0.0.1:9222", bsk_endpoint="http://127.0.0.1:4096",
        auth_asset_ref="auth://4a/asset",
    )
    lease = pool.acquire(
        mission_id="M-1", workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        access_mode=BrowserAccessMode.WRITE, purpose="JOURNEY_TEACHING", ttl_seconds=300,
    )
    teaching = JourneyTeachingService(truth, release_id="RC7.2", browser_pool=pool)
    teaching.start_recording(
        recording_id="JR-1", mission_id="M-1", release_batch_id="RB-1", requirement_id="REQ-1",
        sst_id="SST-1", obligation_id="TO-1", workitem_id="WI-1", attempt_id="ATT-1",
        worker_id="WORKER-1", session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
        human_operator_ref="human://operator/1", auth_asset_ref="auth://4a/asset",
    )
    teaching.append_step(
        recording_id="JR-1", step_id="S1", sequence=1, action_type=JourneyActionType.NAVIGATE,
        url="https://fat1.example/config", page_role="config", element_ref=None,
        page_state_ref="page://1", dom_ref="dom://1", network_refs=["net://1"], screenshot_ref="shot://1",
        wait_semantics="network-idle", evidence_refs=["ev://1"], capture_metadata={"label": "open page"},
    )
    seq = 2
    if include_input:
        teaching.append_step(
            recording_id="JR-1", step_id="S2", sequence=seq, action_type=JourneyActionType.INPUT,
            url="https://fat1.example/config", page_role="config", element_ref="dom://field/name",
            page_state_ref="page://2", dom_ref="dom://2", network_refs=[], screenshot_ref="shot://2",
            wait_semantics="none", evidence_refs=["ev://2"], capture_metadata={"value_ref": "var://config-name"},
        )
        seq += 1
    if include_assert:
        teaching.append_step(
            recording_id="JR-1", step_id=f"S{seq}", sequence=seq, action_type=JourneyActionType.ASSERT,
            url="https://fat1.example/config", page_role="config", element_ref="dom://toast/success",
            page_state_ref=f"page://{seq}", dom_ref=f"dom://{seq}", network_refs=["net://save"],
            screenshot_ref=f"shot://{seq}", wait_semantics="visible", evidence_refs=[f"ev://{seq}"],
            capture_metadata={"oracle_ref": "oracle://success-toast"},
        )
    if complete:
        teaching.complete_recording(recording_id="JR-1", evidence_refs=["ev://recording"])
    return truth, teaching, JourneyCompiler(truth, release_id="RC7.2")


def test_compiler_rejects_non_captured_recording(tmp_path: Path):
    _, _, compiler = _setup(tmp_path, complete=False)
    with pytest.raises(Exception, match="JOURNEY_COMPILER_REQUIRES_CAPTURED_RECORDING"):
        compiler.compile(candidate_id="JC-1", recording_id="JR-1")


def test_compiled_candidate_preserves_business_lineage_and_step_provenance(tmp_path: Path):
    truth, _, compiler = _setup(tmp_path, include_input=True, include_assert=True)
    result = compiler.compile(candidate_id="JC-1", recording_id="JR-1")
    assert result.state == JourneyCandidateState.COMPILED_CANDIDATE
    row = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    assert row["release_batch_id"] == "RB-1"
    assert row["requirement_id"] == "REQ-1"
    assert row["sst_id"] == "SST-1"
    assert row["obligation_id"] == "TO-1"
    assert row["source_recording_id"] == "JR-1"
    assert [step["source_step_id"] for step in row["steps"]] == ["S1", "S2", "S3"]
    assert [step["sequence"] for step in row["steps"]] == [1, 2, 3]


def test_input_compiles_only_reference_not_plaintext_value(tmp_path: Path):
    truth, _, compiler = _setup(tmp_path, include_input=True)
    compiler.compile(candidate_id="JC-1", recording_id="JR-1")
    row = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    input_step = [step for step in row["steps"] if step["action_type"] == "INPUT"][0]
    assert input_step["value_ref"] == "var://config-name"
    assert "capture_metadata" not in input_step
    assert "value" not in input_step


def test_input_without_value_or_credential_ref_is_rejected(tmp_path: Path):
    truth, teaching, compiler = _setup(tmp_path, complete=False)
    teaching.append_step(
        recording_id="JR-1", step_id="S2", sequence=2, action_type=JourneyActionType.INPUT,
        url="https://fat1.example/config", page_role="config", element_ref="dom://field/name",
        page_state_ref="page://2", dom_ref="dom://2", network_refs=[], screenshot_ref="shot://2",
        wait_semantics="none", evidence_refs=["ev://2"], capture_metadata={"label": "unsafe incomplete input"},
    )
    teaching.complete_recording(recording_id="JR-1", evidence_refs=["ev://recording"])
    with pytest.raises(Exception, match="JOURNEY_INPUT_REFERENCE_REQUIRED"):
        compiler.compile(candidate_id="JC-1", recording_id="JR-1")
    assert not truth.query("rc72_journey_candidate")


def test_assert_requires_explicit_oracle_ref(tmp_path: Path):
    truth, teaching, compiler = _setup(tmp_path, complete=False)
    teaching.append_step(
        recording_id="JR-1", step_id="S2", sequence=2, action_type=JourneyActionType.ASSERT,
        url="https://fat1.example/config", page_role="config", element_ref="dom://toast",
        page_state_ref="page://2", dom_ref="dom://2", network_refs=[], screenshot_ref="shot://2",
        wait_semantics="visible", evidence_refs=["ev://2"], capture_metadata={"label": "success"},
    )
    teaching.complete_recording(recording_id="JR-1", evidence_refs=["ev://recording"])
    with pytest.raises(Exception, match="JOURNEY_ASSERT_ORACLE_REQUIRED"):
        compiler.compile(candidate_id="JC-1", recording_id="JR-1")
    assert not truth.query("rc72_journey_candidate")


def test_candidate_is_not_official_or_executable(tmp_path: Path):
    truth, _, compiler = _setup(tmp_path, include_assert=True)
    compiler.compile(candidate_id="JC-1", recording_id="JR-1")
    row = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    assert row["state"] == "COMPILED_CANDIDATE"
    assert row["asset_class"] == "CANDIDATE"
    assert row["executable"] is False
    assert row["official"] is False
    assert row["replay_status"] == "NOT_RUN"
    assert row["benchmark_status"] == "NOT_RUN"
    assert row["review_status"] == "NOT_REVIEWED"


def test_same_recording_cannot_create_competing_candidates(tmp_path: Path):
    truth, _, compiler = _setup(tmp_path)
    compiler.compile(candidate_id="JC-1", recording_id="JR-1")
    with pytest.raises(Exception, match="JOURNEY_RECORDING_ALREADY_COMPILED"):
        compiler.compile(candidate_id="JC-2", recording_id="JR-1")
    assert len(truth.query("rc72_journey_candidate")) == 1


def test_candidate_survives_r1_replay(tmp_path: Path):
    truth, _, compiler = _setup(tmp_path, include_input=True, include_assert=True)
    compiler.compile(candidate_id="JC-1", recording_id="JR-1")
    replay = TruthRuntime(tmp_path / "r1.jsonl")
    compiler.install_overlay()
    row = replay.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    assert row["source_recording_id"] == "JR-1"
    assert row["state"] == "COMPILED_CANDIDATE"
    assert row["executable"] is False
    assert [step["source_step_id"] for step in row["steps"]] == ["S1", "S2", "S3"]
