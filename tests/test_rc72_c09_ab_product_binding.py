"""A's actual AB factory consumes C's signed BrowserSkill N7 adapter.

These checks never substitute a fake BSK runner for bank Field proof. They
check construction, permission, no fallback and no synthetic PASS only.
"""
from dataclasses import replace
import pytest

from rc7_runtime.models import ContractError
from rc7_runtime.rc72_browser_resources import BrowserPool
from rc7_runtime.rc72_journey_bsk import JourneyBSKAdapter
from rc7_runtime.rc72_journey_n7_adapter import SignedN7OfficialBSKAdapter
from rc7_runtime.rc72_official_journey_execution import OfficialJourneyExecutionService
from rc7_runtime.rc72_mission_factory import create_mission_driver
from rc7_runtime.rc72_n7_pipeline import N7PipelineService
from rc72_n2_test_support import RELEASE
from test_rc72_mission_factory import _setup


def _approved_host(tmp_path):
    truth, options = _setup(tmp_path)
    pool = BrowserPool(truth, release_id=RELEASE)
    bsk = JourneyBSKAdapter(
        browser_pool=pool,
        evidence_root=tmp_path / "bsk-captured",
        bsk_executable=tmp_path / "bank-bsk-binary-not-present",
        session_resolver=lambda scope, instance: {},
        session_receipt_verifier=lambda session, scope, instance: False,
        reference_resolver=lambda name, kind, context: None,
        runner=lambda argv: pytest.fail("factory must not launch BSK"),
        timeout_seconds=10,
    )
    official = OfficialJourneyExecutionService(
        truth, release_id=RELEASE, browser_pool=pool, adapter=bsk)
    options["tool_registry"] = {
        "api_http": ("api_http",),
        "browser:write": ("journey_bsk",),
    }
    return truth, options, official


def test_ab_product_factory_registers_only_actual_bsk_adapter_without_browser_io(tmp_path):
    truth, options, official = _approved_host(tmp_path)
    options["official_bsk_execution"] = official
    before = truth.store.path.read_bytes()
    driver = create_mission_driver(truth, **options)
    dispatch = driver.n7_pipeline.dispatch.adapters
    assert isinstance(dispatch["journey_bsk"], SignedN7OfficialBSKAdapter)
    assert dispatch["journey_bsk"].execution is official
    assert dispatch["api_http"] is driver.n7_pipeline.runner
    assert driver.n7_pipeline.preparation.browser.truth is truth
    assert not truth.query("rc72_n7_tool_dispatch")
    assert not truth.query("rc72_official_journey_execution")
    assert truth.store.path.read_bytes() == before


@pytest.mark.parametrize("violation", ["no_binding", "unregistered", "wrong_release", "foreign_truth", "fake", "different_pool"])
def test_ab_factory_rejects_unowned_or_unregistered_bsk_without_writing_r1(tmp_path, violation):
    truth, options, official = _approved_host(tmp_path)
    options["official_bsk_execution"] = official
    if violation == "no_binding":
        options.pop("official_bsk_execution")
    elif violation == "unregistered":
        options["tool_registry"] = {"api_http": ("api_http",)}
    elif violation == "wrong_release":
        official.release_id = "other-release"
    elif violation == "foreign_truth":
        official.truth = object()
    elif violation == "fake":
        options["official_bsk_execution"] = {"status": "PASS"}
    elif violation == "different_pool":
        official.adapter.pool = BrowserPool(truth, release_id=RELEASE)
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match="MISSION_FACTORY_BSK_"):
        create_mission_driver(truth, **options)
    assert truth.store.path.read_bytes() == before
    assert not truth.query("rc72_n7_tool_dispatch")


def test_ab_bsk_adapter_preflight_fails_closed_without_human_approval(tmp_path):
    truth, options, official = _approved_host(tmp_path)
    options["official_bsk_execution"] = official
    driver = create_mission_driver(truth, **options)
    adapter = driver.n7_pipeline.dispatch.adapters["journey_bsk"]
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match="JOURNEY_N7_"):
        adapter.preflight(
            contract={"tool_route": {"tool": "journey_bsk"},
                      "request": {"official_asset_id": "never-approved",
                                  "source_ref": "official-journey://never-approved"},
                      "case_id": "TC-NOT-APPROVED"},
            context={"workitem_id": "WI-FAKE", "attempt_id": "ATT-FAKE",
                     "worker_id": "WRK-FAKE", "session_id": "SES-FAKE",
                     "browser_lease_ids": []})
    assert truth.store.path.read_bytes() == before
    assert not truth.query("rc72_n7_tool_dispatch")
