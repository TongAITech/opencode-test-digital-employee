"""C09 production-adapter tests: real R1 lease + actual files; no fake Field PASS."""
from pathlib import Path
import json

import pytest

from rc6_runtime.truth import TruthRuntime
from rc7_runtime.rc72_browser_resources import BrowserPool
from rc7_runtime.rc72_journey_cdp_capture import JourneyCDPTeachingRecorder
from rc7_runtime.rc72_journey_playwright import JourneyPlaywrightAdapter
from rc7_runtime.rc72_journey_replay import JourneyReplayService

from test_rc72_phase9_journey_replay_contract import _setup as replay_fixture
from test_rc72_phase9_journey_teaching_capture_contract import _setup as teaching_fixture, _start


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def click(self, **kwargs):
        self.page.actions.append(("click", self.selector))

    def fill(self, value, **kwargs):
        self.page.actions.append(("fill", self.selector, value))

    def select_option(self, value, **kwargs):
        self.page.actions.append(("select", self.selector, value))

    def wait_for(self, **kwargs):
        pass

    def is_visible(self):
        return self.page.visible

    def inner_text(self, **kwargs):
        return self.page.text

    def get_attribute(self, name, **kwargs):
        return self.page.attributes.get(name)


class FakePage:
    def __init__(self, *, text="Saved"):
        self.url = "about:blank"
        self.actions = []
        self.handlers = {}
        self.context = None
        self.text = text
        self.visible = True
        self.attributes = {}
        self.events = []

    def on(self, kind, handler):
        self.handlers.setdefault(kind, []).append(handler)

    def remove_listener(self, kind, handler):
        self.handlers[kind].remove(handler)

    def goto(self, url, **kwargs):
        self.url = url
        self.actions.append(("goto", url))

        class Request:
            method = "GET"
        class Response:
            request = Request()
            status = 200
            def __init__(self, url):
                self.url = url
        for handler in self.handlers.get("response", []):
            handler(Response(url + "?token=should-not-leak"))

    def locator(self, ref):
        return FakeLocator(self, ref)

    def get_by_test_id(self, ref):
        return FakeLocator(self, ref)

    def get_by_text(self, ref, **kwargs):
        return FakeLocator(self, ref)

    def wait_for_load_state(self, kind, **kwargs):
        self.actions.append(("wait", kind))

    def screenshot(self, *, path, **kwargs):
        Path(path).write_bytes(b"valid-fixture-screenshot")

    def evaluate(self, code):
        if "__rc72Capture.drain()" in code:
            copied = self.events
            self.events = []
            return copied
        if "document.querySelectorAll" in code:
            return {"ready_state": "complete", "title": "Test", "elements": [{"tag": "BUTTON"}]}
        return None


class FakeContext:
    def __init__(self, page):
        self.pages = [page]
        self.init_script = None
        page.context = self

    def add_init_script(self, *, script):
        self.init_script = script


class FakeBrowser:
    def __init__(self, page):
        self.contexts = [FakeContext(page)]


def resolver(ref, kind, context):
    if kind == "locator" and ref == "dom://toast/success":
        return {"css": "#toast"}
    if kind == "oracle" and ref == "oracle://success-toast":
        return {"type": "text_equals", "element_ref": "css:#toast", "expected": "Saved"}
    return None


def make_replay(tmp_path, *, page=None, adapter=None):
    truth, pool, lease, _, _ = replay_fixture(tmp_path)
    page = page or FakePage()
    adapter = adapter or JourneyPlaywrightAdapter(
        browser_pool=pool, evidence_root=tmp_path / "evidence",
        reference_resolver=resolver, connector=lambda endpoint: FakeBrowser(page))
    service = JourneyReplayService(truth, release_id="RC7.2", browser_pool=pool, adapter=adapter)
    return truth, pool, lease, page, adapter, service


def run_replay(service, lease, replay_id="REAL-1"):
    return service.replay(
        replay_id=replay_id, candidate_id="JC-1", workitem_id="WI-R1",
        attempt_id="ATT-R1", worker_id="WORKER-R1", session_id="SESSION-R1",
        browser_lease_id=lease.browser_lease_id)


def test_cdp_adapter_passes_with_durable_actual_and_screenshot(tmp_path):
    truth, pool, lease, page, adapter, service = make_replay(tmp_path)
    assert run_replay(service, lease).state.value == "PASSED"
    assert page.actions[0] == ("goto", "https://fat1.example/config")
    rows = truth.query("rc72_journey_replay_step", replay_id="REAL-1")
    assert len(rows) == 2
    for step in rows:
        assert all(ref.startswith("file://") for ref in step["evidence_refs"])
        for ref in step["evidence_refs"]:
            assert Path(ref[7:]).is_file()
    actual = json.loads((tmp_path / "evidence" / "REAL-1" / "step-0001" / "actual.json").read_text())
    assert actual["status"] == "PASSED"
    assert actual["response_metadata"][0]["url"] == "https://fat1.example/config"
    assert "should-not-leak" not in json.dumps(actual)
    assert truth.query("rc72_journey_replay", replay_id="REAL-1")[0]["field_verified"] is False


def test_real_replay_assertion_failure_has_failure_file_and_screenshot(tmp_path):
    truth, pool, lease, page, adapter, service = make_replay(tmp_path, page=FakePage(text="Not saved"))
    result = run_replay(service, lease)
    assert result.state.value == "FAILED"
    steps = sorted(truth.query("rc72_journey_replay_step", replay_id="REAL-1"), key=lambda x: x["sequence"])
    assert [r["status"] for r in steps] == ["PASSED", "FAILED"]
    assert Path(tmp_path / "evidence" / "REAL-1" / "step-0002" / "screen.png").is_file()
    failure = json.loads((tmp_path / "evidence" / "REAL-1" / "step-0002" / "actual.json").read_text())
    assert failure["failure_code"] == "JOURNEY_ASSERT_TEXT_MISMATCH"
    assert truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]["executable"] is False


def test_released_browser_fails_closed_before_any_browser_action(tmp_path):
    truth, pool, lease, page, adapter, service = make_replay(tmp_path)
    pool.release(lease.browser_lease_id, reason="worker revoked")
    with pytest.raises(Exception, match="BROWSER_LEASE_NOT_ACTIVE"):
        run_replay(service, lease)
    assert not page.actions
    assert not truth.query("rc72_journey_replay", replay_id="REAL-1")


def test_lease_revoked_during_browser_action_cannot_emit_pass(tmp_path):
    truth, pool, lease, page, adapter, service = make_replay(tmp_path)
    original = page.goto

    def goto_and_revoke(url, **kwargs):
        original(url, **kwargs)
        pool.release(lease.browser_lease_id, reason="revoked during navigation")

    page.goto = goto_and_revoke
    result = run_replay(service, lease)
    assert result.state.value == "FAILED"
    failure = json.loads((tmp_path / "evidence" / "REAL-1" / "step-0001" / "actual.json").read_text())
    assert failure["failure_code"] == "BROWSER_LEASE_NOT_ACTIVE"
    assert failure["status"] == "FAILED"


def test_cold_restart_reads_recorded_files_and_r1_without_replaying(tmp_path):
    truth, pool, lease, page, adapter, service = make_replay(tmp_path)
    assert run_replay(service, lease).state.value == "PASSED"
    adapter.close()
    reloaded = TruthRuntime(tmp_path / "r1.jsonl")
    pool2 = BrowserPool(reloaded, release_id="RC7.2")
    adapter2 = JourneyPlaywrightAdapter(
        browser_pool=pool2, evidence_root=tmp_path / "evidence",
        reference_resolver=resolver, connector=lambda endpoint: FakeBrowser(FakePage()))
    service2 = JourneyReplayService(reloaded, release_id="RC7.2", browser_pool=pool2, adapter=adapter2)
    with pytest.raises(Exception, match="JOURNEY_REPLAY_ALREADY_EXISTS"):
        run_replay(service2, lease)
    assert reloaded.query("rc72_journey_replay", replay_id="REAL-1")[0]["state"] == "PASSED"
    assert len(reloaded.query("rc72_journey_replay_step", replay_id="REAL-1")) == 2


def test_capture_real_dom_events_and_network_metadata_without_input_values(tmp_path):
    truth, teaching, pool, lease = teaching_fixture(tmp_path)
    page = FakePage()
    page.url = "https://fat1.example/config?secret=not-persisted"
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "capture",
        connector=lambda endpoint: FakeBrowser(page))
    args = dict(
        recording_id="JR-REAL", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
        workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
        human_operator_ref="human://operator/001", auth_asset_ref="auth://4a/session-asset")
    recorder.begin(**args)
    page.events = [{"type": "CLICK", "element_ref": "css:#save", "tag": "BUTTON"}]
    assert recorder.poll(page_role="config") == ["JR-REAL:1"]
    recorder.record_assertion(page_role="config", oracle_ref="oracle://success-toast")
    recorder.finish()
    assert truth.query("rc72_journey_recording", recording_id="JR-REAL")[0]["state"] == "CAPTURED"
    events = truth.query("rc72_journey_capture_step", recording_id="JR-REAL")
    assert len(events) == 2
    assert events[0]["screenshot_ref"].startswith("file://")
    assert all("not-persisted" not in json.dumps(event) for event in events)
    assert not truth.query("rc72_official_journey_asset")


def test_capture_rejects_browser_ownership_loss(tmp_path):
    truth, teaching, pool, lease = teaching_fixture(tmp_path)
    page = FakePage()
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "capture",
        connector=lambda endpoint: FakeBrowser(page))
    recorder.begin(
        recording_id="JR-LOST", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
        workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
        human_operator_ref="human://operator/001")
    pool.release(lease.browser_lease_id, reason="authkeeper contention")
    with pytest.raises(Exception, match="BROWSER_LEASE_NOT_ACTIVE"):
        recorder.poll(page_role="config")
