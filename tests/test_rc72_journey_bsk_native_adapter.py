"""BSK native C09 action and Oracle contracts (fake CLI, not Field proof)."""
import base64
import json
from pathlib import Path

import pytest

from rc7_runtime.rc72_journey_bsk import JourneyBSKAdapter
from rc7_runtime.rc72_journey_replay import JourneyReplayService
from rc7_runtime.rc72_official_journey_execution import OfficialJourneyExecutionService
from test_rc72_phase9_journey_replay_contract import _setup as replay_setup
from test_rc72_phase9_official_journey_consumption_contract import _setup as official_setup, _run as official_run


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4"
    "nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


class TestBSK:
    def __init__(self, *, step_ok=True, evaluate_ok=True,
                 business_text="Saved", screenshot=True):
        self.calls = []
        self.step_ok = step_ok
        self.evaluate_ok = evaluate_ok
        self.business_text = business_text
        self.screenshot = screenshot

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        if "cooperate" in argv:
            return {"returncode": 0, "stdout": json.dumps({
                "context_id": "ctx-live", "tab_id": 37,
                "session_id": "BSK-OWNED-SESSION"})}
        if "step" in argv:
            return {"returncode": 0, "stdout": json.dumps({
                "ok": self.step_ok,
                "phase": "observed" if self.step_ok else "needs_attention",
                "action_replayed": False,
                "post": {"context_id": "ctx-live", "tab_id": 37} if self.step_ok else {}})}
        if "evaluate" in argv:
            return {"returncode": 0, "stdout": json.dumps({
                "ok": self.evaluate_ok,
                "value": {
                    "url": "https://fat1.example/config",
                    "exists": True, "visible": True, "match_count": 1,
                    "text": self.business_text,
                    "attribute": None,
                } if self.evaluate_ok else None})}
        if "screenshot" in argv:
            path = Path(argv[argv.index("--out") + 1])
            if self.screenshot:
                path.write_bytes(_PNG)
            return {"returncode": 0, "stdout": json.dumps({
                "path": str(path),
                "byte_size": len(_PNG),
                "format": "png", "tab_id": 37})}
        raise AssertionError("Unexpected BrowserSkill command: " + repr(argv))


def _adapter(pool, tmp_path, runner):
    def resolver(ref, kind, context):
        if kind == "oracle" and ref == "oracle://success-toast":
            return {"type": "text_equals", "element_ref": "css:#toast",
                    "expected": "Saved"}
        if kind == "locator" and ref == "dom://toast/success":
            return {"css": "#toast"}
        return None

    def owned_session(ctx, browser):
        return {
            "bsk_session_id": "BSK-OWNED-SESSION",
            "tab_id": 37,
            "browser_instance_id": browser["browser_instance_id"],
            "profile_dir": browser["profile_dir"],
            "bsk_endpoint": browser["bsk_endpoint"],
            "auth_asset_ref": browser.get("auth_asset_ref"),
            "browser_lease_id": ctx["browser_lease_id"],
            "mission_id": ctx["mission_id"],
            "workitem_id": ctx["workitem_id"],
            "attempt_id": ctx["attempt_id"],
            "worker_id": ctx["worker_id"],
            "dsh_session_id": ctx["session_id"],
            "state": "ACTIVE",
            "source_receipt_ref": "r1://bsk-session-binding",
        }
    return JourneyBSKAdapter(
        browser_pool=pool, evidence_root=tmp_path / "bsk-evidence",
        bsk_executable=tmp_path / "bsk.exe",
        runner=runner,
        session_resolver=owned_session,
        reference_resolver=resolver)


def _replay(tmp_path, runner):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    adapter = _adapter(pool, tmp_path, runner)
    service = JourneyReplayService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=adapter)
    result = service.replay(
        replay_id="JRP-BSK", candidate_id="JC-1",
        workitem_id="WI-R1", attempt_id="ATT-R1", worker_id="WORKER-R1",
        session_id="SESSION-R1", browser_lease_id=lease.browser_lease_id)
    return result, truth, runner


def test_bsk_native_replay_produces_real_png_and_oracle_receipts(tmp_path):
    result, truth, cli = _replay(tmp_path, TestBSK())
    assert result.state.value == "PASSED"
    assert len([c for c in cli.calls if "step" in c]) == 1
    assert len([c for c in cli.calls if "evaluate" in c]) == 1
    actuals = sorted(truth.query(
        "rc72_journey_replay_step", replay_id="JRP-BSK"), key=lambda r: r["sequence"])
    assert [r["status"] for r in actuals] == ["PASSED", "PASSED"]
    assert all(ref.startswith("file://")
               for r in actuals for ref in r["evidence_refs"])
    for row in actuals:
        for ref in row["evidence_refs"]:
            assert Path(ref[7:]).is_file()
    receipts = [json.loads(Path(r["actual_refs"][0][7:]).read_text())
                for r in actuals]
    assert [r["status"] for r in receipts] == ["PASSED", "PASSED"]
    assert all(r["field_verified"] is False for r in receipts)
    assert not any("Saved" in json.dumps(r) for r in receipts)
    assert truth.query("rc72_journey_replay", replay_id="JRP-BSK")[0]["field_verified"] is False


@pytest.mark.parametrize("settings,code", [
    ({"step_ok": False}, "JOURNEY_BSK_ACTION_UNKNOWN_OR_UNOBSERVED"),
    ({"evaluate_ok": False}, "JOURNEY_BSK_EVALUATE_UNVERIFIED"),
    ({"business_text": "Business rejected"}, "JOURNEY_BSK_BUSINESS_ORACLE_FAILED"),
    ({"screenshot": False}, "JOURNEY_BSK_SCREENSHOT_FILE_MISSING"),
])
def test_bsk_never_turns_cli_exit_zero_or_missing_picture_into_pass(tmp_path, settings, code):
    result, truth, runner = _replay(tmp_path, TestBSK(**settings))
    assert result.state.value == "FAILED"
    rows = sorted(truth.query(
        "rc72_journey_replay_step", replay_id="JRP-BSK"), key=lambda r: r["sequence"])
    failure = next(r for r in rows if r["status"] == "FAILED")
    actual = json.loads(Path(failure["actual_refs"][0][7:]).read_text())
    assert actual["failure_code"] == code


def test_bsk_replay_rejects_wrong_browser_purpose_without_dispatch(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    runner = TestBSK()
    adapter = _adapter(pool, tmp_path, runner)
    raw_lease = pool.lease(lease.browser_lease_id)
    changed = dict(raw_lease)
    changed.pop("artifact_type", None)
    changed["artifact_version"] += 1
    changed["purpose"] = "AUTH_KEEPER"
    truth.append_atomic("RC72_BROWSER_LEASE_UPSERTED", changed)
    step = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]["steps"][0]
    outcome = adapter.execute_step(step, {
        "replay_id": "REJECT-BSK", "mission_id": "M-1",
        "workitem_id": "WI-R1", "attempt_id": "ATT-R1",
        "worker_id": "WORKER-R1", "session_id": "SESSION-R1",
        "browser_lease_id": lease.browser_lease_id})
    assert outcome["status"] == "FAILED"
    assert outcome["failure_code"] == "JOURNEY_BSK_BROWSER_PURPOSE_MISMATCH"
    assert runner.calls == []


def test_bsk_official_service_uses_same_owned_browser_backend(tmp_path):
    runner = TestBSK()
    truth, pool, lease, _, _ = official_setup(tmp_path)
    adapter = _adapter(pool, tmp_path, runner)
    service = OfficialJourneyExecutionService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=adapter)
    result = official_run(service, lease, execution_id="OJ-BSK-1")
    assert result.state.value == "PASSED"
    assert runner.calls
    rows = truth.query(
        "rc72_official_journey_execution_step", execution_id="OJ-BSK-1")
    assert rows and all(row["status"] == "PASSED" for row in rows)
    assert truth.query("rc72_official_journey_execution", execution_id="OJ-BSK-1")[0]["field_verified"] is False


def test_bsk_denies_wrong_tab_in_b_session_receipt_before_click(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    runner = TestBSK()
    adapter = _adapter(pool, tmp_path, runner)
    original = adapter.session_for

    def changed_tab(ctx, instance):
        receipt = original(ctx, instance)
        receipt["tab_id"] = 99
        return receipt

    adapter.session_for = changed_tab
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    context = {
        "replay_id": "WRONG-TAB", "mission_id": "M-1",
        "workitem_id": "WI-R1", "attempt_id": "ATT-R1",
        "worker_id": "WORKER-R1", "session_id": "SESSION-R1",
        "browser_lease_id": lease.browser_lease_id}
    # B group returned tab 99, while BSK cooperative sync resolves live tab 37.
    outcome = adapter.execute_step(candidate["steps"][0], context)
    assert outcome["status"] == "FAILED"
    assert outcome["failure_code"] == "JOURNEY_BSK_CONTROL_TAB_MISMATCH"
    assert not any("step" in cmd for cmd in runner.calls)


def test_bsk_fail_closed_if_human_ownership_sync_has_no_context(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    class HumanHold(TestBSK):
        def __call__(self, argv):
            if "cooperate" in argv:
                self.calls.append(list(argv))
                return {"returncode": 0, "stdout": '{"mode":"human_control"}'}
            return super().__call__(argv)
    runner = HumanHold()
    adapter = _adapter(pool, tmp_path, runner)
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    outcome = adapter.execute_step(candidate["steps"][0], {
        "replay_id": "HUMAN-HOLD", "mission_id": "M-1",
        "workitem_id": "WI-R1", "attempt_id": "ATT-R1",
        "worker_id": "WORKER-R1", "session_id": "SESSION-R1",
        "browser_lease_id": lease.browser_lease_id})
    assert outcome["status"] == "FAILED"
    assert outcome["failure_code"] == "JOURNEY_BSK_CONTROL_SYNC_NOT_GRANTED"
    assert not any("step" in cmd for cmd in runner.calls)


def test_bsk_denies_cross_attempt_and_cross_4a_session_binding(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    for field, wrong in (("attempt_id", "ATT-SOMEONE"),
                         ("auth_asset_ref", "auth://4a/other-user")):
        runner = TestBSK()
        adapter = _adapter(pool, tmp_path, runner)
        original = adapter.session_for
        def foreign(ctx, instance):
            owned = original(ctx, instance)
            owned[field] = wrong
            return owned
        adapter.session_for = foreign
        candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
        outcome = adapter.execute_step(candidate["steps"][0], {
            "replay_id": "FOREIGN-" + field, "mission_id": "M-1",
            "workitem_id": "WI-R1", "attempt_id": "ATT-R1",
            "worker_id": "WORKER-R1", "session_id": "SESSION-R1",
            "browser_lease_id": lease.browser_lease_id})
        assert outcome["status"] == "FAILED"
        assert outcome["failure_code"] == "JOURNEY_BSK_SESSION_RECEIPT_SCOPE_MISMATCH"
        assert runner.calls == []


def test_bsk_duplicate_attempt_step_never_replays_or_overwrites_original_actual(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    runner = TestBSK()
    adapter = _adapter(pool, tmp_path, runner)
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    step = candidate["steps"][0]
    context = {
        "replay_id": "BSK-REPLAY-ONCE", "mission_id": "M-1",
        "workitem_id": "WI-R1", "attempt_id": "ATT-R1",
        "worker_id": "WORKER-R1", "session_id": "SESSION-R1",
        "browser_lease_id": lease.browser_lease_id}
    first = adapter.execute_step(step, context)
    assert first["status"] == "PASSED"
    original_bytes = Path(first["actual_refs"][0][7:]).read_bytes()
    before = sum(1 for cmd in runner.calls if "step" in cmd)
    assert before == 1
    again = adapter.execute_step(step, context)
    assert again["status"] == "FAILED"
    assert again["failure_code"] == "JOURNEY_BSK_DUPLICATE_STEP_EFFECT_UNKNOWN"
    assert sum(1 for cmd in runner.calls if "step" in cmd) == before
    assert Path(first["actual_refs"][0][7:]).read_bytes() == original_bytes
    assert Path(again["actual_refs"][0][7:]).is_file()
    assert first["actual_refs"] != again["actual_refs"]


def test_bsk_dom_oracle_rejects_ambiguous_element_even_if_first_matches(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    class Ambiguous(TestBSK):
        def __call__(self, argv):
            response = super().__call__(argv)
            if "evaluate" in argv:
                data = json.loads(response["stdout"])
                data["value"]["match_count"] = 2
                response["stdout"] = json.dumps(data)
            return response

    runner = Ambiguous()
    adapter = _adapter(pool, tmp_path, runner)
    service = JourneyReplayService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=adapter)
    result = service.replay(
        replay_id="BSK-AMBIGUOUS", candidate_id="JC-1",
        workitem_id="WI-R1", attempt_id="ATT-R1", worker_id="WORKER-R1",
        session_id="SESSION-R1", browser_lease_id=lease.browser_lease_id)
    assert result.state.value == "FAILED"
    rows = sorted(truth.query(
        "rc72_journey_replay_step", replay_id="BSK-AMBIGUOUS"),
        key=lambda row: row["sequence"])
    assert rows[-1]["failure_code"] == "JOURNEY_BSK_ORACLE_ELEMENT_NOT_UNIQUE"


@pytest.mark.parametrize("action,extra,expected_action", [
    ("PRESS", {"key": "Enter"}, "press"),
    ("HOVER", {}, "hover"),
    ("SCROLL_TO", {}, "scroll-to"),
    ("DRAG", {"target_ref": "css:#drop-zone"}, "drag"),
])
def test_bsk_native_executes_non_happy_path_keyboard_hover_scroll_drag(
        tmp_path, action, extra, expected_action):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    runner = TestBSK()
    adapter = _adapter(pool, tmp_path, runner)
    step = dict(truth.query(
        "rc72_journey_candidate", candidate_id="JC-1")[0]["steps"][0])
    step.update(sequence=1, action_type=action, element_ref="css:#source")
    step.update(extra)
    outcome = adapter.execute_step(step, {
        "replay_id": "BSK-ADVANCED-" + action, "mission_id": "M-1",
        "workitem_id": "WI-R1", "attempt_id": "ATT-R1",
        "worker_id": "WORKER-R1", "session_id": "SESSION-R1",
        "browser_lease_id": lease.browser_lease_id})
    assert outcome["status"] == "PASSED"
    dispatched = [cmd for cmd in runner.calls if "step" in cmd]
    assert len(dispatched) == 1
    argv = dispatched[0]
    assert argv[argv.index("--context") + 1] == "ctx-live"
    assert argv[argv.index("--action") + 1] == expected_action
    params = json.loads(argv[argv.index("--params") + 1])
    if action == "PRESS":
        assert params == {"selector": "#source", "key": "Enter"}
    elif action == "DRAG":
        assert params == {
            "source": {"selector": "#source"},
            "target": {"selector": "#drop-zone"}}
    else:
        assert params == {"selector": "#source"}


def test_bsk_rejects_arbitrary_key_instead_of_typing_secret_with_press(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    runner = TestBSK()
    adapter = _adapter(pool, tmp_path, runner)
    step = dict(truth.query(
        "rc72_journey_candidate", candidate_id="JC-1")[0]["steps"][0])
    step.update(action_type="PRESS", element_ref="css:#pin",
                key="123456")
    result = adapter.execute_step(step, {
        "replay_id": "BSK-PRESS-SECRET", "mission_id": "M-1",
        "workitem_id": "WI-R1", "attempt_id": "ATT-R1",
        "worker_id": "WORKER-R1", "session_id": "SESSION-R1",
        "browser_lease_id": lease.browser_lease_id})
    assert result["status"] == "FAILED"
    assert result["failure_code"] == "JOURNEY_BSK_PRESS_KEY_UNSAFE"
    assert not any("step" in cmd for cmd in runner.calls)
