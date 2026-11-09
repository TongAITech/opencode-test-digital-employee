"""C09 production-adapter tests: real R1 lease + actual files; no fake Field PASS."""
from pathlib import Path
from rc72_file_uri_test_support import local_file_evidence_ref
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
        if self.selector in {"#save", "css:#save"}:
            from types import SimpleNamespace
            response = SimpleNamespace(
                url="https://fat1.example/api/config?token=never-persist",
                status=200, request=SimpleNamespace(method="POST"))
            for listener in list(self.page.handlers.get("response", [])):
                listener(response)

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

    def wait_for_text(self, expected, *, timeout_ms):
        self.page.actions.append(("wait_text", expected, timeout_ms))
        for value in getattr(self.page, "text_sequence", [self.page.text]):
            self.page.text = value
            if self.page.text == expected:
                return
        raise TimeoutError("FAKE_TEXT_ORACLE_NOT_REACHED")

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
            assert local_file_evidence_ref(ref).is_file()
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

def test_text_equals_oracle_waits_for_late_exact_dom_value(tmp_path):
    truth, pool, lease, page, adapter, service = make_replay(
        tmp_path, page=FakePage(text="Before save"))
    page.text_sequence = ["Before save", "Saving", "Saved"]
    result = run_replay(service, lease)
    assert result.state.value == "PASSED"
    assert ("wait_text", "Saved", 15000) in page.actions
    assert truth.query("rc72_journey_replay")[0]["state"] == "PASSED"



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
    screenshot_calls = []
    page.screenshot = lambda **kwargs: screenshot_calls.append(kwargs)
    result = run_replay(service, lease)
    assert result.state.value == "FAILED"
    failure = json.loads((tmp_path / "evidence" / "REAL-1" / "step-0001" / "actual.json").read_text())
    assert failure["failure_code"] == "BROWSER_LEASE_NOT_ACTIVE"
    assert failure["status"] == "FAILED"
    assert screenshot_calls == []  # never inspect another owner's browser


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
    assert recorder.poll(page_role="config") == ["JR-REAL:2"]
    assert recorder.record_wait(page_role="config", wait_semantics="network-idle") == "JR-REAL:3"
    recorder.record_assertion(page_role="config", oracle_ref="oracle://success-toast")
    recorder.finish()
    assert truth.query("rc72_journey_recording", recording_id="JR-REAL")[0]["state"] == "CAPTURED"
    events = truth.query("rc72_journey_capture_step", recording_id="JR-REAL")
    assert len(events) == 4
    assert [e["action_type"] for e in sorted(events, key=lambda e: e["sequence"])] == ["NAVIGATE", "CLICK", "WAIT", "ASSERT"]
    assert events[0]["screenshot_ref"].startswith("file://")
    assert all("not-persisted" not in json.dumps(event) for event in events)
    from rc7_runtime.rc72_journey_promotion import install_rc72_journey_promotion_overlay
    install_rc72_journey_promotion_overlay()
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


def test_click_before_navigation_preserves_precise_teaching_order(tmp_path):
    truth, teaching, pool, lease = teaching_fixture(tmp_path)
    page = FakePage()
    page.url = "https://fat1.example/config"
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "captures",
        connector=lambda endpoint: FakeBrowser(page))
    recorder.begin(
        recording_id="JR-NAV", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
        workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
        human_operator_ref="human://operator/001")
    page.events = [{"type": "CLICK", "element_ref": "css:#next", "url": "https://fat1.example/config"}]
    page.url = "https://fat1.example/confirmation"
    with pytest.raises(Exception, match="JOURNEY_TEACHING_PRE_NAVIGATION_EVIDENCE_REQUIRED"):
        recorder.poll(page_role="config")
    recorded = sorted(truth.query("rc72_journey_capture_step", recording_id="JR-NAV"), key=lambda row: row["sequence"])
    assert [row["action_type"] for row in recorded] == ["NAVIGATE"]
    assert truth.query("rc72_journey_recording", recording_id="JR-NAV")[0]["state"] == "CAPTURING"
    assert len(recorder.events) == 1  # old-page action remains available for diagnosis
    with pytest.raises(Exception, match="JOURNEY_TEACHING_PENDING_ACTIONS_NOT_CAPTURED"):
        recorder.finish()


class FakeDialog:
    type = "confirm"

    def __init__(self):
        self.accepted = False
        self.dismissed = False

    def accept(self, **kwargs):
        self.accepted = True

    def dismiss(self):
        self.dismissed = True


def _page_with_dialog(page):
    dialog = FakeDialog()
    navigate = page.goto

    def with_confirmation(url, **kwargs):
        navigate(url, **kwargs)
        for listener in list(page.handlers.get("dialog", [])):
            listener(dialog)

    page.goto = with_confirmation
    return dialog


def test_unexpected_js_dialog_is_dismissed_and_fails_with_actual_evidence(tmp_path):
    truth, pool, lease, page, adapter, service = make_replay(tmp_path)
    dialog = _page_with_dialog(page)
    result = run_replay(service, lease)
    assert result.state.value == "FAILED"
    assert dialog.dismissed is True and dialog.accepted is False
    actual = json.loads((tmp_path / "evidence" / "REAL-1" / "step-0001" / "actual.json").read_text())
    assert actual["failure_code"] == "JOURNEY_UNEXPECTED_DIALOG"
    assert truth.query("rc72_journey_replay", replay_id="REAL-1")[0]["field_verified"] is False


def test_explicit_reference_bound_dialog_policy_allows_confirm_and_preserves_evidence(tmp_path):
    truth, pool, lease, page, adapter, service = make_replay(tmp_path)
    dialog = _page_with_dialog(page)
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    updated = dict(candidate)
    updated.pop("artifact_type", None)
    updated["artifact_version"] += 1
    updated["steps"] = [dict(item) for item in candidate["steps"]]
    updated["steps"][0]["dialog_policy_ref"] = "dialog://confirmed"
    truth.append_atomic("RC72_JOURNEY_CANDIDATE_UPSERTED", updated)

    def policy_resolver(ref, kind, context):
        if ref == "dialog://confirmed" and kind == "dialog":
            return {"type": "confirm", "action": "accept"}
        return resolver(ref, kind, context)

    adapter.resolve = policy_resolver
    result = run_replay(service, lease)
    assert result.state.value == "PASSED"
    assert dialog.accepted is True and dialog.dismissed is False
    assert Path(tmp_path / "evidence" / "REAL-1" / "step-0001" / "actual.json").is_file()


def test_visible_wait_without_element_fails_closed_not_faked_as_pass(tmp_path):
    truth, pool, lease, page, adapter, service = make_replay(tmp_path)
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    updated = dict(candidate)
    updated.pop("artifact_type", None)
    updated["artifact_version"] += 1
    updated["steps"] = [dict(item) for item in candidate["steps"]]
    updated["steps"][0]["action_type"] = "WAIT"
    updated["steps"][0]["wait_semantics"] = "visible"
    updated["steps"][0]["element_ref"] = None
    truth.append_atomic("RC72_JOURNEY_CANDIDATE_UPSERTED", updated)
    assert run_replay(service, lease).state.value == "FAILED"
    actual = json.loads((tmp_path / "evidence" / "REAL-1" / "step-0001" / "actual.json").read_text())
    assert actual["failure_code"] == "JOURNEY_VISIBLE_WAIT_ELEMENT_REQUIRED"


@pytest.mark.parametrize("expected,trigger,status", [
    (200, "S-CLICK", "PASSED"),
    (201, "S-CLICK", "FAILED"),
    (200, "S1", "FAILED"),
])
def test_business_network_oracle_reads_actual_observed_post_not_recording_ref(tmp_path, expected, trigger, status):
    truth, pool, lease, page, adapter, service = make_replay(tmp_path)
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    updated = dict(candidate)
    updated.pop("artifact_type", None)
    updated["artifact_version"] += 1
    steps = [dict(item) for item in candidate["steps"]]
    click_step = dict(steps[1])
    click_step.update(source_step_id="S-CLICK", sequence=2, action_type="CLICK",
                      element_ref="css:#save", wait_semantics="none")
    click_step.pop("oracle_ref", None)
    steps[1]["sequence"] = 3
    steps[1]["oracle_ref"] = "oracle://save-network"
    updated["steps"] = [steps[0], click_step, steps[1]]
    truth.append_atomic("RC72_JOURNEY_CANDIDATE_UPSERTED", updated)

    def network_resolver(ref, kind, context):
        if kind == "oracle" and ref == "oracle://save-network":
            return {"type": "network_status", "method": "POST",
                    "url": "https://fat1.example/api/config", "status": expected,
                    "trigger_source_step_id": trigger}
        return resolver(ref, kind, context)

    adapter.resolve = network_resolver
    result = run_replay(service, lease)
    assert result.state.value == status
    click_actual = json.loads(
        (tmp_path / "evidence" / "REAL-1" / "step-0002" / "actual.json").read_text())
    assert click_actual["response_metadata"][0]["method"] == "POST"
    assert click_actual["response_metadata"][0]["url"] == "https://fat1.example/api/config"
    assert "never-persist" not in json.dumps(click_actual)
    if status == "FAILED":
        assert truth.query("rc72_journey_replay", replay_id="REAL-1")[0][
            "failure_code"] == "JOURNEY_ASSERT_NETWORK_STATUS_MISMATCH"


def test_teaching_finish_rejects_unpolled_browser_events_and_can_recover(tmp_path):
    truth, teaching, pool, lease = teaching_fixture(tmp_path)
    page = FakePage()
    page.url = "https://fat1.example/config"
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "capture",
        connector=lambda endpoint: FakeBrowser(page))
    recorder.begin(
        recording_id="JR-PENDING", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
        workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
        human_operator_ref="human://operator/001")
    page.events = [{"type": "CLICK", "element_ref": "css:#save",
                    "url": "https://fat1.example/config"}]
    with pytest.raises(Exception, match="JOURNEY_TEACHING_PENDING_ACTIONS_NOT_CAPTURED"):
        recorder.finish()
    assert len(recorder.events) == 1
    assert truth.query("rc72_journey_recording", recording_id="JR-PENDING")[0]["state"] == "CAPTURING"
    assert recorder.poll(page_role="config") == ["JR-PENDING:2"]
    recorder.record_assertion(page_role="config", oracle_ref="oracle://success-toast")
    assert recorder.finish().state.value == "CAPTURED"
    steps = sorted(truth.query("rc72_journey_capture_step", recording_id="JR-PENDING"),
                   key=lambda row: row["sequence"])
    assert [step["action_type"] for step in steps] == ["NAVIGATE", "CLICK", "ASSERT"]


def test_teaching_preflight_validation_is_atomic_and_retains_partial_batch(tmp_path):
    truth, teaching, pool, lease = teaching_fixture(tmp_path)
    page = FakePage()
    page.url = "https://fat1.example/config"
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "capture",
        connector=lambda endpoint: FakeBrowser(page))
    recorder.begin(
        recording_id="JR-ATOMIC", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
        workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
        human_operator_ref="human://operator/001")
    page.events = [
        {"type": "CLICK", "element_ref": "css:#save"},
        {"type": "INPUT", "element_ref": "css:#amount"},
    ]
    with pytest.raises(Exception, match="JOURNEY_TEACHING_VALUE_REFERENCE_REQUIRED"):
        recorder.poll(page_role="config")
    assert len(recorder.events) == 2
    assert truth.query("rc72_journey_recording", recording_id="JR-ATOMIC")[0]["step_count"] == 1
    assert recorder.poll(page_role="config", bindings={
        "css:#amount": {"value_ref": "var://approved-amount"}
    }) == ["JR-ATOMIC:2", "JR-ATOMIC:3"]
    recorder.record_assertion(page_role="config", oracle_ref="oracle://business-value")
    assert recorder.finish().state.value == "CAPTURED"
    steps = sorted(truth.query("rc72_journey_capture_step", recording_id="JR-ATOMIC"),
                   key=lambda row: row["sequence"])
    assert [step["action_type"] for step in steps] == ["NAVIGATE", "CLICK", "INPUT", "ASSERT"]
    assert steps[2]["capture_metadata"]["value_ref"] == "var://approved-amount"
    assert "approved-amount" not in json.dumps(page.actions)


def test_manual_assert_cannot_appear_before_unpolled_human_action(tmp_path):
    truth, teaching, pool, lease = teaching_fixture(tmp_path)
    page = FakePage()
    page.url = "https://fat1.example/config"
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "capture",
        connector=lambda endpoint: FakeBrowser(page))
    recorder.begin(
        recording_id="JR-ACTION-ORDER", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
        workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
        human_operator_ref="human://operator/001")
    page.events = [{"type": "CLICK", "element_ref": "css:#save",
                    "url": "https://fat1.example/config"}]
    with pytest.raises(Exception, match="JOURNEY_TEACHING_PENDING_ACTIONS_NOT_CAPTURED"):
        recorder.record_assertion(page_role="config", oracle_ref="oracle://success-toast")
    assert truth.query("rc72_journey_recording", recording_id="JR-ACTION-ORDER")[0]["step_count"] == 1
    assert recorder.poll(page_role="config") == ["JR-ACTION-ORDER:2"]
    assert recorder.record_assertion(page_role="config",
                                    oracle_ref="oracle://success-toast") == "JR-ACTION-ORDER:3"
    assert recorder.finish().state.value == "CAPTURED"
    steps = sorted(truth.query("rc72_journey_capture_step", recording_id="JR-ACTION-ORDER"),
                   key=lambda x: x["sequence"])
    assert [s["action_type"] for s in steps] == ["NAVIGATE", "CLICK", "ASSERT"]


def test_manual_wait_cannot_skip_page_navigation_not_yet_captured(tmp_path):
    truth, teaching, pool, lease = teaching_fixture(tmp_path)
    page = FakePage()
    page.url = "https://fat1.example/config"
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "capture",
        connector=lambda endpoint: FakeBrowser(page))
    recorder.begin(
        recording_id="JR-WAIT-ORDER", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
        workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
        human_operator_ref="human://operator/001")
    page.url = "https://fat1.example/new-page"
    with pytest.raises(Exception, match="JOURNEY_TEACHING_PENDING_NAVIGATION_NOT_CAPTURED"):
        recorder.record_wait(page_role="config", wait_semantics="domcontentloaded")
    assert recorder.poll(page_role="config") == ["JR-WAIT-ORDER:2"]
    assert recorder.record_wait(page_role="config",
                                wait_semantics="domcontentloaded") == "JR-WAIT-ORDER:3"
    recorder.record_assertion(page_role="config", oracle_ref="oracle://visible")
    assert recorder.finish().state.value == "CAPTURED"


def test_replay_rejects_nonexistent_screenshot_as_real_browser_evidence(tmp_path):
    truth, pool, lease, page, adapter, service = make_replay(tmp_path)
    page.screenshot = lambda **kwargs: None  # API returned, no screenshot bytes
    result = run_replay(service, lease)
    assert result.state.value == "FAILED"
    actual_file = tmp_path / "evidence" / "REAL-1" / "step-0001" / "actual.json"
    assert actual_file.is_file()
    actual = json.loads(actual_file.read_text())
    assert actual["status"] == "FAILED"
    assert actual["failure_code"] == "JOURNEY_SCREENSHOT_EVIDENCE_FAILED"
    assert not (tmp_path / "evidence" / "REAL-1" / "step-0001" / "screen.png").exists()
    assert truth.query("rc72_journey_replay", replay_id="REAL-1")[0]["field_verified"] is False


def test_teaching_requires_valid_dom_projection_not_null_json(tmp_path):
    truth, teaching, pool, lease = teaching_fixture(tmp_path)
    page = FakePage()
    page.url = "https://fat1.example/config"
    original = page.evaluate
    def invalid_dom(code):
        if "document.querySelectorAll" in code:
            return None
        return original(code)
    page.evaluate = invalid_dom
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "capture",
        connector=lambda endpoint: FakeBrowser(page))
    with pytest.raises(Exception, match="JOURNEY_TEACHING_DOM_EVIDENCE_INVALID"):
        recorder.begin(
            recording_id="JR-NO-DOM", mission_id="M-1", release_batch_id="RB-1",
            requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
            workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
            session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
            human_operator_ref="human://operator/001")
    recording = truth.query("rc72_journey_recording", recording_id="JR-NO-DOM")[0]
    assert recording["state"] == "CAPTURING"
    assert recording["step_count"] == 0


def test_teaching_does_not_commit_step_if_screenshot_bytes_missing(tmp_path):
    truth, teaching, pool, lease = teaching_fixture(tmp_path)
    page = FakePage()
    page.url = "https://fat1.example/config"
    page.screenshot = lambda **kwargs: None
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "capture",
        connector=lambda endpoint: FakeBrowser(page))
    with pytest.raises(Exception, match="JOURNEY_TEACHING_SCREENSHOT_REQUIRED"):
        recorder.begin(
            recording_id="JR-NO-SHOT", mission_id="M-1", release_batch_id="RB-1",
            requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
            workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
            session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
            human_operator_ref="human://operator/001")
    row = truth.query("rc72_journey_recording", recording_id="JR-NO-SHOT")[0]
    assert row["state"] == "CAPTURING"
    assert row["step_count"] == 0


def test_playwright_connector_does_not_reuse_network_or_browser_session_across_attempts(tmp_path):
    truth, pool, lease, page, adapter, service = make_replay(tmp_path)
    assert run_replay(service, lease).state.value == "PASSED"
    before = list(page.actions)
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    step = candidate["steps"][0]
    changed_context = {
        "replay_id": "FRESH-ATTEMPT",
        "candidate_id": "JC-1",
        "mission_id": "M-1",
        "workitem_id": "WI-R1",
        "attempt_id": "ATT-R1",
        "worker_id": "WORKER-R1",
        "session_id": "SESSION-R1",
        "browser_lease_id": lease.browser_lease_id,
    }
    rejected = adapter.execute_step(step, changed_context)
    assert rejected["status"] == "FAILED"
    assert rejected["failure_code"] == "JOURNEY_ADAPTER_ATTEMPT_SWITCH_REQUIRES_CLOSE"
    assert page.actions == before
    receipt = tmp_path / "evidence" / "FRESH-ATTEMPT" / "step-0001" / "actual.json"
    assert receipt.is_file()
    assert json.loads(receipt.read_text())["status"] == "FAILED"
    adapter.close()
    # The service, not the adapter, owns approval of a new Attempt. Never
    # invoke the SUT twice with the same Case/Attempt after a failed receipt.
    assert adapter._active_run_id is None


def test_replay_rejects_mid_action_cdp_profile_identity_swap(tmp_path):
    truth, pool, lease, page, adapter, service = make_replay(tmp_path)
    navigate = page.goto
    def navigate_then_switch_profile(url, **kwargs):
        navigate(url, **kwargs)
        instance = truth.query("rc72_browser_instance", browser_instance_id="BROWSER-R1")[0]
        updated = dict(instance)
        updated.pop("artifact_type", None)
        updated["artifact_version"] += 1
        updated["profile_dir"] = "profiles/other-worker"
        updated["cdp_endpoint"] = "http://127.0.0.1:9551"
        truth.append_atomic("RC72_BROWSER_INSTANCE_UPSERTED", updated)
    page.goto = navigate_then_switch_profile
    result = run_replay(service, lease)
    assert result.state.value == "FAILED"
    assert page.actions == [("goto", "https://fat1.example/config")]
    actual = json.loads((tmp_path / "evidence" / "REAL-1" /
                         "step-0001" / "actual.json").read_text())
    assert actual["failure_code"] == "JOURNEY_BROWSER_INSTANCE_IDENTITY_CHANGED"
    assert not (tmp_path / "evidence" / "REAL-1" / "step-0001" / "screen.png").exists()


def test_teaching_rejects_cdp_identity_switch_mid_capture(tmp_path):
    truth, teaching, pool, lease = teaching_fixture(tmp_path)
    page = FakePage()
    page.url = "https://fat1.example/config"
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "capture",
        connector=lambda endpoint: FakeBrowser(page))
    recorder.begin(
        recording_id="JR-INSTANCE-SWITCH", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
        workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
        human_operator_ref="human://operator/001")
    instance = truth.query("rc72_browser_instance", browser_instance_id="BROWSER-1")[0]
    replaced = dict(instance)
    replaced.pop("artifact_type", None)
    replaced["artifact_version"] += 1
    replaced["auth_asset_ref"] = "auth://other-person"
    truth.append_atomic("RC72_BROWSER_INSTANCE_UPSERTED", replaced)
    with pytest.raises(Exception, match="JOURNEY_TEACHING_BROWSER_INSTANCE_IDENTITY_CHANGED"):
        recorder.poll(page_role="config")
    recording = truth.query("rc72_journey_recording", recording_id="JR-INSTANCE-SWITCH")[0]
    assert recording["state"] == "CAPTURING"
    assert recording["step_count"] == 1


def test_teaching_refuses_foreign_4a_auth_asset_before_any_r1_recording(tmp_path):
    truth, teaching, pool, lease = teaching_fixture(tmp_path)
    page = FakePage()
    page.url = "https://fat1.example/config"
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "capture",
        connector=lambda endpoint: FakeBrowser(page))
    with pytest.raises(Exception, match="JOURNEY_TEACHING_AUTH_ASSET_MISMATCH"):
        recorder.begin(
            recording_id="JR-FOREIGN-AUTH", mission_id="M-1",
            release_batch_id="RB-1", requirement_id="REQ-1",
            sst_id="SST-1", obligation_id="TO-1",
            workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
            session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
            human_operator_ref="human://operator/001",
            auth_asset_ref="auth://4a/some-other-user")
    assert not truth.query("rc72_journey_recording", recording_id="JR-FOREIGN-AUTH")
    assert recorder.recording is None
    assert recorder.page is None


def test_teaching_failed_screenshot_does_not_lose_network_receipt_on_retry(tmp_path):
    from types import SimpleNamespace

    truth, teaching, pool, lease = teaching_fixture(tmp_path)
    page = FakePage()
    page.url = "https://fat1.example/config"
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "capture",
        connector=lambda endpoint: FakeBrowser(page))
    recorder.begin(
        recording_id="JR-RETRY-NET", mission_id="M-1",
        release_batch_id="RB-1", requirement_id="REQ-1",
        sst_id="SST-1", obligation_id="TO-1",
        workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
        human_operator_ref="human://operator/001")
    page.events = [{"type": "CLICK", "element_ref": "css:#save",
                    "url": "https://fat1.example/config"}]
    response = SimpleNamespace(
        url="https://fat1.example/api/save?bearer=private",
        status=201, request=SimpleNamespace(method="POST"))
    for listener in list(page.handlers["response"]):
        listener(response)
    assert len(recorder.responses) == 1
    original_screenshot = page.screenshot
    page.screenshot = lambda **kwargs: (_ for _ in ()).throw(IOError("disk full"))
    with pytest.raises(Exception, match="JOURNEY_TEACHING_SCREENSHOT_REQUIRED"):
        recorder.poll(page_role="CONFIGURATION")
    recording = truth.query("rc72_journey_recording", recording_id="JR-RETRY-NET")[0]
    assert recording["step_count"] == 1
    assert len(recorder.events) == 1
    assert len(recorder.responses) == 1

    page.screenshot = original_screenshot
    assert recorder.poll(page_role="CONFIGURATION") == ["JR-RETRY-NET:2"]
    steps = truth.query("rc72_journey_capture_step", recording_id="JR-RETRY-NET")
    assert len(steps) == 2
    click = next(row for row in steps if row["sequence"] == 2)
    actual = json.loads(local_file_evidence_ref(click["network_refs"][0]).read_text())
    assert actual["responses"] == [{
        "url": "https://fat1.example/api/save", "method": "POST",
        "status": 201, "captured_at": actual["responses"][0]["captured_at"]}]
    assert recorder.responses == []
    assert recorder.events == []
    recorder.stop()


def test_teaching_stop_clears_unacknowledged_events_across_recordings(tmp_path):
    truth, teaching, pool, lease = teaching_fixture(tmp_path)
    page = FakePage()
    page.url = "https://fat1.example/config"
    recorder = JourneyCDPTeachingRecorder(
        teaching=teaching, evidence_root=tmp_path / "capture",
        connector=lambda endpoint: FakeBrowser(page))
    recorder.begin(
        recording_id="JR-FIRST", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
        workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
        human_operator_ref="human://operator/001")
    recorder.events.append({
        "type": "CLICK", "element_ref": "css:#stale-button",
        "url": "https://fat1.example/config"})
    recorder.responses.append({
        "method": "POST", "url": "https://fat1.example/api/stale",
        "status": 200})
    recorder.stop()
    assert recorder.events == []
    assert recorder.responses == []
    assert recorder.last_url == ""
    assert recorder.recording is None
    assert recorder._instance_fingerprint is None
