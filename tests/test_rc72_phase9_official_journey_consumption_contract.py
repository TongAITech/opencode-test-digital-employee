from pathlib import Path

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.models import Task
from rc7_runtime.rc72_browser_resources import BrowserAccessMode, BrowserPool
from rc7_runtime.rc72_domain import ExecutionTaskUnit, ReleaseBatch, TestObligation
from rc7_runtime.rc72_linkage import WorkItemAttemptBinding, WorkItemAttemptState
from rc7_runtime.rc72_official_journey_execution import OfficialJourneyExecutionService, OfficialJourneyExecutionState
from rc7_runtime.rc72_promotion import install_rc72_journey_promotion_overlay
from rc7_runtime.rc72_repository import CanonicalRC72Repository
from rc7_runtime.truth_overlay import append_entity


class ContractOfficialJourneyAdapter:
    adapter_kind = "CONTRACT_BROWSER"
    field_verified = False

    def __init__(self, *, fail_at=None, self_claim_field=False):
        self.fail_at = fail_at
        self.calls = []
        if self_claim_field:
            self.field_verified = True

    def execute_step(self, step, context):
        self.calls.append((step["sequence"], context["official_asset_id"]))
        if self.fail_at == step["sequence"]:
            return {
                "status": "FAILED",
                "actual_refs": ["actual://official/%s" % step["sequence"]],
                "evidence_refs": ["evidence://official/%s" % step["sequence"]],
                "failure_code": "ASSERTION_DIVERGENCE",
            }
        return {
            "status": "PASSED",
            "actual_refs": ["actual://official/%s" % step["sequence"]],
            "evidence_refs": ["evidence://official/%s" % step["sequence"]],
        }


def _setup(tmp_path: Path, *, test_level="L5", adapter=None, trusted_field_adapter_kinds=()):
    truth = TruthRuntime(tmp_path / "r1.jsonl")
    repo = CanonicalRC72Repository(truth, release_id="RC7.2")
    repo.persist(ReleaseBatch(
        release_batch_id="RB-1", mission_id="M-1", name="batch",
        application_ids=["cfg-admin"], requirement_ids=["REQ-1"],
    ))
    repo.persist(TestObligation(
        obligation_id="TO-1", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", application_id="cfg-admin",
        business_scenario="official journey", business_rule="authorized configuration save",
        risk_level="HIGH", test_level=test_level, code_slice_refs=["ui://configuration"],
        oracle_refs=["UI", "NETWORK"],
    ))
    repo.persist(ExecutionTaskUnit(
        etu_id="ETU-OJ", mission_id="M-1", release_batch_id="RB-1", obligation_id="TO-1",
        case_ids=["TC-OJ"], primary_goal="execute official journey", primary_code_slice="ui://configuration",
        test_level=test_level, primary_oracle="UI+NETWORK", data_domain="browser",
        primary_tool_family="browser", planning_snapshot_ref="PLAN-OJ", cohesion_score=1.0,
        cohesion_explanation="single official journey", required_capabilities=["browser:write"],
        estimated_duration_minutes=10, estimated_cost=1.0,
    ))
    append_entity(truth, Task(
        task_id="WI-OJ", mission_id="M-1", node="N7_EXECUTION",
        task_type="OFFICIAL_JOURNEY_EXECUTION", objective="execute official journey asset",
        required_capabilities=["browser:write"], input_artifact_refs=["ETU-OJ", "JOURNEY-1"],
        acceptance_criteria=["official journey evidence persisted"],
    ), release_id="RC7.2")
    repo.persist(WorkItemAttemptBinding(
        binding_id="BIND-OJ", mission_id="M-1", etu_id="ETU-OJ", workitem_id="WI-OJ",
        case_id="TC-OJ", attempt_id="ATT-OJ", worker_id="WORKER-OJ", session_id="SESSION-OJ",
        task_lease_ref="TASKLEASE-OJ", state=WorkItemAttemptState.RUNNING,
    ))

    install_rc72_journey_promotion_overlay()
    truth.append_atomic("RC72_OFFICIAL_JOURNEY_ASSET_UPSERTED", {
        "official_asset_id": "JOURNEY-1", "mission_id": "M-1", "release_id": "RC7.2",
        "release_batch_id": "RB-1", "requirement_id": "REQ-1", "sst_id": "SST-1", "obligation_id": "TO-1",
        "source_candidate_id": "JC-1", "source_candidate_artifact_version": 3,
        "source_benchmark_id": "JB-1", "source_benchmark_artifact_version": 2,
        "human_review_id": "JREV-1", "approval_scope_digest": "sha256:approved",
        "status": "OFFICIAL", "official": True, "executable": True,
        "field_benchmark_verified": True, "human_field_verified": True,
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
        "approval_evidence_refs": ["human-evidence://A1"], "promoted_at": 10, "artifact_version": 1,
    })

    pool = BrowserPool(truth, release_id="RC7.2")
    pool.register_instance(
        browser_instance_id="BROWSER-OJ", profile_dir="profiles/official",
        cdp_endpoint="http://127.0.0.1:9444", bsk_endpoint="http://127.0.0.1:4197",
        auth_asset_ref="auth://4a/official",
    )
    lease = pool.acquire(
        mission_id="M-1", workitem_id="WI-OJ", attempt_id="ATT-OJ", worker_id="WORKER-OJ",
        access_mode=BrowserAccessMode.WRITE, purpose="OFFICIAL_JOURNEY_EXECUTION", ttl_seconds=300,
    )
    adapter = adapter or ContractOfficialJourneyAdapter()
    service = OfficialJourneyExecutionService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=adapter,
        trusted_field_adapter_kinds=trusted_field_adapter_kinds,
    )
    return truth, pool, lease, adapter, service


def _run(service, lease, execution_id="OJEXEC-1", session_id="SESSION-OJ"):
    return service.execute(
        execution_id=execution_id, official_asset_id="JOURNEY-1", workitem_id="WI-OJ",
        attempt_id="ATT-OJ", worker_id="WORKER-OJ", session_id=session_id,
        browser_lease_id=lease.browser_lease_id,
    )


def test_official_journey_consumption_is_l4_l5_only(tmp_path: Path):
    truth, _, lease, _, service = _setup(tmp_path, test_level="L3")
    with pytest.raises(Exception, match="OFFICIAL_JOURNEY_REQUIRES_L4_L5_ETU"):
        _run(service, lease)
    assert not truth.query("rc72_official_journey_execution")


def test_official_journey_requires_canonical_attempt_and_active_write_browser(tmp_path: Path):
    truth, pool, lease, _, service = _setup(tmp_path)
    pool.release(lease.browser_lease_id, reason="expired ownership")
    with pytest.raises(Exception, match="BROWSER_LEASE_NOT_ACTIVE"):
        _run(service, lease)
    with pytest.raises(Exception, match="OFFICIAL_JOURNEY_ATTEMPT_BINDING_MISMATCH"):
        service.execute(
            execution_id="OJEXEC-2", official_asset_id="JOURNEY-1", workitem_id="WI-OJ",
            attempt_id="ATT-OJ", worker_id="WORKER-OJ", session_id="WRONG-SESSION",
            browser_lease_id=lease.browser_lease_id,
        )
    assert not truth.query("rc72_official_journey_execution")


def test_official_journey_executes_ordered_steps_and_persists_actual_evidence(tmp_path: Path):
    truth, _, lease, adapter, service = _setup(tmp_path)
    result = _run(service, lease)
    assert result.state == OfficialJourneyExecutionState.PASSED
    assert adapter.calls == [(1, "JOURNEY-1"), (2, "JOURNEY-1")]
    rows = sorted(truth.query("rc72_official_journey_execution_step", execution_id="OJEXEC-1"), key=lambda row: row["sequence"])
    assert [row["source_step_id"] for row in rows] == ["S1", "S2"]
    assert rows[0]["actual_refs"] == ["actual://official/1"]
    assert rows[1]["evidence_refs"] == ["evidence://official/2"]


def test_official_journey_execution_is_fail_fast(tmp_path: Path):
    adapter = ContractOfficialJourneyAdapter(fail_at=1)
    truth, _, lease, _, service = _setup(tmp_path, adapter=adapter)
    result = _run(service, lease)
    assert result.state == OfficialJourneyExecutionState.FAILED
    assert adapter.calls == [(1, "JOURNEY-1")]
    row = truth.query("rc72_official_journey_execution", execution_id="OJEXEC-1")[0]
    assert row["failure_code"] == "ASSERTION_DIVERGENCE"


def test_contract_adapter_cannot_self_claim_field_execution(tmp_path: Path):
    adapter = ContractOfficialJourneyAdapter(self_claim_field=True)
    truth, _, lease, _, service = _setup(tmp_path, adapter=adapter, trusted_field_adapter_kinds=())
    _run(service, lease)
    row = truth.query("rc72_official_journey_execution", execution_id="OJEXEC-1")[0]
    assert row["field_verified"] is False


def test_official_asset_is_immutable_across_execution(tmp_path: Path):
    truth, _, lease, _, service = _setup(tmp_path)
    before = truth.query("rc72_official_journey_asset", official_asset_id="JOURNEY-1")[0]
    _run(service, lease)
    after = truth.query("rc72_official_journey_asset", official_asset_id="JOURNEY-1")[0]
    assert after == before
    assert after["official"] is True
    assert after["executable"] is True


def test_official_execution_truth_survives_r1_restart(tmp_path: Path):
    truth, _, lease, _, service = _setup(tmp_path)
    _run(service, lease)
    replay_truth = TruthRuntime(tmp_path / "r1.jsonl")
    service.install_overlay()
    execution = replay_truth.query("rc72_official_journey_execution", execution_id="OJEXEC-1")[0]
    steps = replay_truth.query("rc72_official_journey_execution_step", execution_id="OJEXEC-1")
    assert execution["state"] == "PASSED"
    assert execution["official_asset_id"] == "JOURNEY-1"
    assert len(steps) == 2
