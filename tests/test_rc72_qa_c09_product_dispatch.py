"""Independent C09 L4/L5 formal product-dispatch admission.

Merging Journey components or passing fake CDP replay is NOT evidence that
ReleaseBatch Mission N7 dispatch actually uses approved official Journey.
This is a necessary product composition gate, not Field/browser qualification.
"""
from rc7_runtime.rc72_journey_n7_adapter import SignedN7OfficialJourneyAdapter
from rc7_runtime.rc72_formal_runner import FormalN7RunnerAdapter
from rc7_runtime.rc72_mission_factory import create_mission_driver
from test_rc72_mission_factory import _setup


def test_official_journey_is_formally_bound_to_signed_n7_dispatch_not_generic_http_runner(tmp_path):
    truth, options = _setup(tmp_path)
    options["tool_registry"]["journey_playwright"] = ("journey_playwright",)
    from rc72_qa_c09_host import bind_native_playwright_host
    bind_native_playwright_host(truth, options, tmp_path)
    before = truth.store.path.read_bytes()
    driver = create_mission_driver(truth, **options)
    adapters = driver.n7_pipeline.dispatch.adapters
    assert "journey_playwright" in adapters, (
        "C09: approved L4/L5 Journey tool absent from formal N7 dispatch"
    )
    assert type(adapters["journey_playwright"]) is SignedN7OfficialJourneyAdapter, (
        "C09 PRODUCT INTEGRATION P0: formal N7 maps journey_playwright to "
        "generic FormalN7RunnerAdapter (or another unapproved callback), "
        "not SignedN7OfficialJourneyAdapter. Merged component code != N7 entry."
    )
    assert adapters["journey_playwright"].execution.truth is truth
    assert adapters["journey_playwright"].execution.release_id == options["release_id"]
    assert not isinstance(adapters["journey_playwright"], FormalN7RunnerAdapter)
    assert truth.store.path.read_bytes() == before, (
        "C09: constructing a formal L4/L5 dispatch must not fabricate R1 PASS"
    )


def test_qa_c09_playwright_registry_string_without_host_cannot_admit_browser_access(tmp_path):
    """No automatic CDP dispatch from a string-only tool registry."""
    import pytest
    from rc7_runtime.models import ContractError

    truth, options = _setup(tmp_path)
    options["tool_registry"]["journey_playwright"] = ("journey_playwright",)
    before = truth.store.path.read_bytes()
    with pytest.raises(ContractError, match="MISSION_FACTORY_PLAYWRIGHT_APPROVED_TOOL_AND_EXECUTOR_REQUIRED"):
        create_mission_driver(truth, **options)
    assert truth.store.path.read_bytes() == before
    assert not truth.query("rc72_official_journey_execution")
