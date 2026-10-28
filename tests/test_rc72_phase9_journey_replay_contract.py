from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Task
from rc7_runtime.rc72_browser_resources import BrowserAccessMode, BrowserPool
from rc7_runtime.rc72_domain import ExecutionTaskUnit, ReleaseBatch, TestObligation
from rc7_runtime.rc72_journey_compiler import JourneyCompiler, install_rc72_journey_compiler_overlay
from rc7_runtime.rc72_journey_replay import JourneyReplayService, JourneyReplayState
from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.truth_overlay import append_entity


class ContractReplayAdapter:
    adapter_kind = "CONTRACT_BROWSER"
    field_verified = False

    def __init__(self, *, fail_at=None, self_claim_field=False):
        self.fail_at = fail_at
        self.calls = []
        if self_claim_field:
            self.field_verified = True

    def execute_step(self, step, context):
        self.calls.append((step["sequence"], context["replay_id"]))
        if self.fail_at == step["sequence"]:
            return {
                "status": "FAILED",
                "actual_refs": ["actual://%s" % step["sequence"]],
                "evidence_refs": ["evidence://%s" % step["sequence"]],
                "failure_code": "ASSERTION_DIVERGENCE",
            }
        return {
            "status": "PASSED",
            "actual_refs": ["actual://%s" % step["sequence"]],
            "evidence_refs": ["evidence://%s" % step["sequence"]],
        }


def _setup(tmp_path: Path, *, adapter=None, trusted_field_adapter_kinds=()):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    repo.persist(ReleaseBatch(
        release_batch_id="RB-1", mission_id="M-1", name="batch",
        application_ids=["cfg-admin"], requirement_ids=["REQ-1"],
    ))
    repo.persist(TestObligation(
        obligation_id="TO-1", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", application_id="cfg-admin",
        business_scenario="configuration journey", business_rule="authorized save",
        risk_level="HIGH", test_level="L5", code_slice_refs=["ui://configuration"],
        oracle_refs=["UI", "NETWORK"],
    ))
    repo.persist(ExecutionTaskUnit(
        etu_id="ETU-R1", mission_id="M-1", release_batch_id="RB-1", obligation_id="TO-1",
        case_ids=["TC-R1"], primary_goal="replay journey", primary_code_slice="ui://configuration",
        test_level="L5", primary_oracle="UI+NETWORK", data_domain="browser",
        primary_tool_family="browser", planning_snapshot_ref="PLAN-R1", cohesion_score=1.0,
        cohesion_explanation="single journey replay", required_capabilities=["browser:write"],
        estimated_duration_minutes=10, estimated_cost=1.0,
    ))
    append_entity(truth, Task(
        task_id="WI-R1", mission_id="M-1", node="N6_EXECUTABLE_READINESS",
        task_type="JOURNEY_REPLAY", objective="replay compiled journey",
        required_capabilities=["browser:write"], input_artifact_refs=["ETU-R1", "JC-1"],
        acceptance_criteria=["replay evidence persisted"],
    ), release_id="RC7.2")
    repo.persist(WorkItemAttemptBinding(
        binding_id="BIND-R1", mission_id="M-1", etu_id="ETU-R1", workitem_id="WI-R1",
        case_id="TC-R1", attempt_id="ATT-R1", worker_id="WORKER-R1", session_id="SESSION-R1",
        task_lease_ref="TASKLEASE-R1", state=WorkItemAttemptState.RUNNING,
    ))

    install_rc72_journey_compiler_overlay()
    truth.append_atomic("RC72_JOURNEY_CANDIDATE_UPSERTED", {
        "candidate_id": "JC-1", "mission_id": "M-1", "release_id": "RC7.2",
        "release_batch_id": "RB-1", "requirement_id": "REQ-1", "sst_id": "SST-1",
        "obligation_id": "TO-1", "source_recording_id": "JR-1",
        "state": "COMPILED_CANDIDATE", "asset_class": "CANDIDATE",
        "executable": False, "official": False, "replay_status": "NOT_RUN",
        "benchmark_status": "NOT_RUN", "review_status": "NOT_REVIEWED",
        "steps": [
            {
                "source_step_id": "S1", "sequence": 1, "action_type": "NAVIGATE",
                "url": "https://fat1.example/config", "page_role": "config", "element_ref": None,
                "page_state_ref": "page://1", "dom_ref": "dom://1", "network_refs": ["net://1"],
                "screenshot_ref": "shot://1", "wait_semantics": "network-idle", "evidence_refs": ["ev://1"],
            },
            {
                "source_step_id": "S2", "sequence": 2, "action_type": "ASSERT",
                "url": "https://fat1.example/config", "page_role": "config", "element_ref": "dom://toast/success",
                "page_state_ref": "page://2", "dom_ref": "dom://2", "network_refs": ["net://save"],
                "screenshot_ref": "shot://2", "wait_semantics": "visible", "evidence_refs": ["ev://2"],
                "oracle_ref": "oracle://success-toast",
            },
        ],
        "compiled_at": 1, "artifact_version": 1,
    })

    pool = BrowserPool(truth, release_id="RC7.2")
    pool.register_instance(
        browser_instance_id="BROWSER-R1", profile_dir="profiles/replay",
        cdp_endpoint="http://127.0.0.1:9333", bsk_endpoint="http://127.0.0.1:4196",
        auth_asset_ref="auth://4a/replay",
    )
    lease = pool.acquire(
        mission_id="M-1", workitem_id="WI-R1", attempt_id="ATT-R1", worker_id="WORKER-R1",
        access_mode=BrowserAccessMode.WRITE, purpose="JOURNEY_REPLAY", ttl_seconds=300,
    )
    adapter = adapter or ContractReplayAdapter()
    service = JourneyReplayService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=adapter,
        trusted_field_adapter_kinds=trusted_field_adapter_kinds,
    )
    return truth, pool, lease, adapter, service


def _run(service, lease, replay_id="JRP-1"):
    return service.replay(
        replay_id=replay_id, candidate_id="JC-1", workitem_id="WI-R1", attempt_id="ATT-R1",
        worker_id="WORKER-R1", session_id="SESSION-R1", browser_lease_id=lease.browser_lease_id,
    )


def test_replay_requires_active_write_browser_lease_bound_to_attempt(tmp_path: Path):
    truth, pool, lease, _, service = _setup(tmp_path)
    pool.release(lease.browser_lease_id, reason="test release")
    with pytest.raises(Exception, match="BROWSER_LEASE_NOT_ACTIVE"):
        _run(service, lease)
    assert not truth.query("rc72_journey_replay")


def test_replay_persists_ordered_step_actual_and_evidence_truth(tmp_path: Path):
    truth, _, lease, adapter, service = _setup(tmp_path)
    result = _run(service, lease)
    assert result.state == JourneyReplayState.PASSED
    assert adapter.calls == [(1, "JRP-1"), (2, "JRP-1")]
    rows = sorted(truth.query("rc72_journey_replay_step", replay_id="JRP-1"), key=lambda row: row["sequence"])
    assert [row["source_step_id"] for row in rows] == ["S1", "S2"]
    assert [row["status"] for row in rows] == ["PASSED", "PASSED"]
    assert rows[0]["actual_refs"] == ["actual://1"]
    assert rows[1]["evidence_refs"] == ["evidence://2"]


def test_successful_contract_replay_does_not_promote_candidate(tmp_path: Path):
    truth, _, lease, _, service = _setup(tmp_path)
    _run(service, lease)
    replay = truth.query("rc72_journey_replay", replay_id="JRP-1")[0]
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    assert replay["state"] == "PASSED"
    assert replay["field_verified"] is False
    assert candidate["replay_status"] == "PASSED"
    assert candidate["executable"] is False
    assert candidate["official"] is False
    assert candidate["benchmark_status"] == "NOT_RUN"
    assert candidate["review_status"] == "NOT_REVIEWED"


def test_adapter_cannot_self_claim_field_verification(tmp_path: Path):
    adapter = ContractReplayAdapter(self_claim_field=True)
    truth, _, lease, _, service = _setup(tmp_path, adapter=adapter, trusted_field_adapter_kinds=())
    _run(service, lease)
    replay = truth.query("rc72_journey_replay", replay_id="JRP-1")[0]
    assert replay["adapter_kind"] == "CONTRACT_BROWSER"
    assert replay["field_verified"] is False


def test_explicitly_trusted_field_adapter_kind_can_mark_field_verified(tmp_path: Path):
    adapter = ContractReplayAdapter(self_claim_field=True)
    adapter.adapter_kind = "BSK_FIELD"
    truth, _, lease, _, service = _setup(
        tmp_path, adapter=adapter, trusted_field_adapter_kinds=("BSK_FIELD",),
    )
    _run(service, lease)
    replay = truth.query("rc72_journey_replay", replay_id="JRP-1")[0]
    assert replay["field_verified"] is True


def test_failed_step_is_fail_fast_and_candidate_remains_non_executable(tmp_path: Path):
    adapter = ContractReplayAdapter(fail_at=1)
    truth, _, lease, _, service = _setup(tmp_path, adapter=adapter)
    result = _run(service, lease)
    assert result.state == JourneyReplayState.FAILED
    assert adapter.calls == [(1, "JRP-1")]
    replay = truth.query("rc72_journey_replay", replay_id="JRP-1")[0]
    assert replay["failure_code"] == "ASSERTION_DIVERGENCE"
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    assert candidate["replay_status"] == "FAILED"
    assert candidate["executable"] is False
    assert candidate["official"] is False


def test_replay_session_must_match_canonical_attempt_binding(tmp_path: Path):
    truth, _, lease, _, service = _setup(tmp_path)
    with pytest.raises(Exception, match="JOURNEY_REPLAY_ATTEMPT_BINDING_MISMATCH"):
        service.replay(
            replay_id="JRP-1", candidate_id="JC-1", workitem_id="WI-R1", attempt_id="ATT-R1",
            worker_id="WORKER-R1", session_id="WRONG-SESSION", browser_lease_id=lease.browser_lease_id,
        )
    assert not truth.query("rc72_journey_replay")


def test_replay_truth_survives_r1_restart(tmp_path: Path):
    truth, _, lease, _, service = _setup(tmp_path)
    _run(service, lease)
    replay_truth = TruthRuntime(tmp_path / "r1.jsonl")
    service.install_overlay()
    replay = replay_truth.query("rc72_journey_replay", replay_id="JRP-1")[0]
    steps = replay_truth.query("rc72_journey_replay_step", replay_id="JRP-1")
    assert replay["state"] == "PASSED"
    assert len(steps) == 2
    assert replay["candidate_id"] == "JC-1"
