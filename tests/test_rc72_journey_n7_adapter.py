"""C09 N7 adapter contract: signed tool entry cannot bypass official lineage."""
from pathlib import Path

import pytest

from rc7_runtime.rc72_journey_n7_adapter import SignedN7OfficialJourneyAdapter
from test_rc72_phase9_official_journey_consumption_contract import _setup


def _contract():
    return {
        "contract_id": "CONTRACT-OJ",
        "case_id": "TC-OJ",
        "mission_id": "M-1",
        "release_batch_id": "RB-1",
        "requirement_id": "REQ-1",
        "sst_id": "SST-1",
        "obligation_id": "TO-1",
        "tool_route": {"tool": "journey_playwright"},
        "request": {
            "source_ref": "official-journey://JOURNEY-1",
            "official_asset_id": "JOURNEY-1",
            "approval_scope_digest": "sha256:approved",
        },
    }


def _context(lease):
    return {
        "workitem_id": "WI-OJ", "attempt_id": "ATT-OJ",
        "worker_id": "WORKER-OJ", "session_id": "SESSION-OJ",
        "browser_lease_ids": [lease.browser_lease_id],
    }


def test_signed_n7_adapter_consumes_only_approved_l5_case_and_emits_raw_receipt(tmp_path: Path):
    truth, pool, lease, browser, service = _setup(tmp_path)
    adapter = SignedN7OfficialJourneyAdapter(service)
    adapter.preflight(contract=_contract(), context=_context(lease))
    raw = adapter(contract=_contract(), context=_context(lease))
    assert raw["journey"]["state"] == "PASSED"
    assert raw["journey"]["case_id"] == "TC-OJ"
    assert truth.query("rc72_official_journey_asset", official_asset_id="JOURNEY-1")[0]["case_id"] == "TC-OJ"
    assert len(raw["journey"]["actual_refs"]) == 2
    assert "passed" not in raw and "field_verified" not in raw
    assert truth.query("rc72_official_journey_execution")[0]["field_verified"] is False
    # New service object may not silently replay a side-effecting signed Attempt.
    with pytest.raises(Exception, match="JOURNEY_N7_ATTEMPT_ALREADY_USED_DIAGNOSIS_REQUIRED"):
        adapter(contract=_contract(), context=_context(lease))


@pytest.mark.parametrize("field,value,error", [
    ("case_id", "WRONG", "OFFICIAL_CASE_MISMATCH"),
    ("obligation_id", "WRONG", "OBLIGATION_ID_MISMATCH"),
    ("sst_id", "WRONG", "SST_ID_MISMATCH"),
    ("requirement_id", "WRONG", "REQUIREMENT_ID_MISMATCH"),
    ("release_batch_id", "WRONG", "RELEASE_BATCH_ID_MISMATCH"),
])
def test_signed_n7_rejects_wrong_business_lineage_before_io(tmp_path, field, value, error):
    truth, pool, lease, browser, service = _setup(tmp_path)
    adapter = SignedN7OfficialJourneyAdapter(service)
    contract = _contract()
    contract[field] = value
    with pytest.raises(Exception, match=error):
        adapter(contract=contract, context=_context(lease))
    assert not browser.calls
    assert not truth.query("rc72_official_journey_execution")


def test_n7_adapter_rejects_wrong_scope_digest_and_nonexclusive_browser(tmp_path):
    truth, pool, lease, browser, service = _setup(tmp_path)
    adapter = SignedN7OfficialJourneyAdapter(service)
    contract = _contract()
    contract["request"]["approval_scope_digest"] = "sha256:old-version"
    with pytest.raises(Exception, match="APPROVAL_DIGEST_MISMATCH"):
        adapter(contract=contract, context=_context(lease))
    context = _context(lease)
    context["browser_lease_ids"] = [lease.browser_lease_id, "BRLEASE-OTHER"]
    with pytest.raises(Exception, match="ONE_BROWSER_LEASE_REQUIRED"):
        adapter(contract=_contract(), context=context)
    assert not browser.calls


def test_n7_cold_reentry_does_not_duplicate_business_actions(tmp_path):
    from rc6_runtime.truth import TruthRuntime
    from rc7_runtime.rc72_browser_resources import BrowserPool
    from rc7_runtime.rc72_official_journey_execution import OfficialJourneyExecutionService
    truth, pool, lease, browser, service = _setup(tmp_path)
    SignedN7OfficialJourneyAdapter(service)(contract=_contract(), context=_context(lease))
    assert len(browser.calls) == 2
    restarted = TruthRuntime(tmp_path / "r1.jsonl")
    reloaded = OfficialJourneyExecutionService(
        restarted, release_id="RC7.2",
        browser_pool=BrowserPool(restarted, release_id="RC7.2"), adapter=browser)
    with pytest.raises(Exception, match="JOURNEY_N7_ATTEMPT_ALREADY_USED_DIAGNOSIS_REQUIRED"):
        SignedN7OfficialJourneyAdapter(reloaded)(contract=_contract(), context=_context(lease))
    assert len(browser.calls) == 2


def test_n7_preflight_rejects_authkeeper_lease_without_dispatch_side_effects(tmp_path):
    from rc7_runtime.rc72_browser_resources import BrowserAccessMode
    truth, pool, lease, browser, service = _setup(tmp_path)
    pool.release(lease.browser_lease_id, reason="auth-only")
    auth = pool.acquire(
        mission_id="M-1", workitem_id="WI-OJ", attempt_id="ATT-OJ",
        worker_id="WORKER-OJ", access_mode=BrowserAccessMode.WRITE,
        purpose="AUTH_KEEPER", ttl_seconds=300)
    signed = SignedN7OfficialJourneyAdapter(service)
    with pytest.raises(Exception, match="JOURNEY_N7_OFFICIAL_BROWSER_PURPOSE_MISMATCH"):
        signed.preflight(contract=_contract(), context=_context(auth))
    assert not browser.calls
    assert not truth.query("rc72_official_journey_execution")


def test_n7_preflight_rejects_workitem_missing_authorized_official_asset(tmp_path):
    truth, pool, lease, browser, service = _setup(tmp_path)
    task = truth.query("rc7_task", task_id="WI-OJ")[0]
    # Truth projection overwrite simulates a canonical replan that revoked
    # this WorkItem's official source. No browser action may survive it.
    from rc7_runtime.models import Task
    from rc7_runtime.truth_overlay import append_entity
    new_task = Task(
        task_id="WI-OJ", mission_id="M-1", node="N7_EXECUTION",
        task_type="OFFICIAL_JOURNEY_EXECUTION",
        objective="replanned and no longer owns the official asset",
        required_capabilities=["browser:write"],
        input_artifact_refs=["ETU-OJ"],
        acceptance_criteria=["report mismatch"])
    append_entity(truth, new_task, release_id="RC7.2", artifact_version=2)
    with pytest.raises(Exception, match="JOURNEY_N7_WORKITEM_ASSET_SCOPE_MISMATCH"):
        SignedN7OfficialJourneyAdapter(service).preflight(
            contract=_contract(), context=_context(lease))
    assert not browser.calls
    assert not truth.query("rc72_official_journey_execution")


def test_signed_n7_bsk_native_route_uses_real_backend_and_original_preflight(tmp_path):
    from rc7_runtime.rc72_journey_n7_adapter import SignedN7OfficialBSKAdapter
    from rc7_runtime.rc72_official_journey_execution import OfficialJourneyExecutionService
    from test_rc72_journey_bsk_native_adapter import TestBSK, _adapter
    truth, pool, lease, _, _ = _setup(tmp_path)
    cli = TestBSK()
    browser = _adapter(pool, tmp_path, cli)
    service = OfficialJourneyExecutionService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=browser)
    signed = SignedN7OfficialBSKAdapter(service)
    contract = _contract()
    contract["tool_route"] = {"tool": "journey_bsk"}
    signed.preflight(contract=contract, context=_context(lease))
    receipt = signed(contract=contract, context=_context(lease))
    assert receipt["journey"]["state"] == "PASSED"
    assert receipt["journey"]["case_id"] == "TC-OJ"
    assert len(receipt["journey"]["actual_refs"]) == 2
    assert any("step" in cmd for cmd in cli.calls)
    assert any("evaluate" in cmd for cmd in cli.calls)
    assert "field_verified" not in receipt["journey"]
    assert truth.query("rc72_official_journey_execution")[0]["field_verified"] is False
    with pytest.raises(Exception, match="JOURNEY_N7_ATTEMPT_ALREADY_USED_DIAGNOSIS_REQUIRED"):
        signed(contract=contract, context=_context(lease))


def test_signed_n7_bsk_refuses_non_bsk_backend_and_old_tool_route(tmp_path):
    from rc7_runtime.rc72_journey_n7_adapter import SignedN7OfficialBSKAdapter
    from rc7_runtime.rc72_official_journey_execution import OfficialJourneyExecutionService
    from test_rc72_journey_bsk_native_adapter import TestBSK, _adapter
    truth, pool, lease, fake, service = _setup(tmp_path)
    with pytest.raises(Exception, match="JOURNEY_N7_BSK_NATIVE_BACKEND_REQUIRED"):
        SignedN7OfficialBSKAdapter(service)
    cli = TestBSK()
    real_backend = OfficialJourneyExecutionService(
        truth, release_id="RC7.2", browser_pool=pool,
        adapter=_adapter(pool, tmp_path, cli))
    signed = SignedN7OfficialBSKAdapter(real_backend)
    with pytest.raises(Exception, match="JOURNEY_N7_TOOL_ROUTE_MISMATCH"):
        signed.preflight(contract=_contract(), context=_context(lease))
    assert not cli.calls
