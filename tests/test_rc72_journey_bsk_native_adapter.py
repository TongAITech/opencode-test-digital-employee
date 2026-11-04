"""BSK native C09 action and Oracle contracts (fake CLI, not Field proof)."""
import base64
import json
from pathlib import Path

import pytest
import time

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
                "session_id": argv[argv.index("--session") + 1]})}
        if "step" in argv:
            return {"returncode": 0, "stdout": json.dumps({
                "ok": self.step_ok,
                "phase": "observed" if self.step_ok else "needs_attention",
                "action_replayed": False,
                "action": {"result": {"tab_id": 37}} if self.step_ok else {},
                "post": {"context_id": "ctx-live", "tab_id": 37} if self.step_ok else {}})}
        if "evaluate" in argv:
            return {"returncode": 0, "stdout": json.dumps({
                "ok": self.evaluate_ok, "tab_id": 37,
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
                "width": 1, "height": 1,
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
        session_receipt_verifier=lambda ownership, scope, instance: (
            ownership.get("source_receipt_ref") == "r1://bsk-session-binding"),
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
    eval_commands = [c for c in cli.calls if "evaluate" in c]
    assert len(eval_commands) == 2  # post-NAVIGATE URL plus business Oracle
    assert all(cmd[cmd.index("--context") + 1] == "ctx-live"
               for cmd in eval_commands)
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
    ("WHEEL", {"delta_x": -20, "delta_y": 500}, "wheel"),
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
    elif action == "WHEEL":
        assert params == {"selector": "#source", "delta_x": -20, "delta_y": 500}
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


def test_bsk_navigate_to_4a_login_instead_of_requested_sut_is_not_pass(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)

    class RedirectedBSK(TestBSK):
        def __call__(self, argv):
            result = super().__call__(argv)
            if "evaluate" in argv:
                data = json.loads(result["stdout"])
                data["value"]["url"] = "https://fat1.example/4a-login"
                result["stdout"] = json.dumps(data)
            return result

    runner = RedirectedBSK()
    adapter = _adapter(pool, tmp_path, runner)
    service = JourneyReplayService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=adapter)
    result = service.replay(
        replay_id="BSK-SSO-REDIRECT", candidate_id="JC-1",
        workitem_id="WI-R1", attempt_id="ATT-R1",
        worker_id="WORKER-R1", session_id="SESSION-R1",
        browser_lease_id=lease.browser_lease_id)
    assert result.state.value == "FAILED"
    rows = truth.query(
        "rc72_journey_replay_step", replay_id="BSK-SSO-REDIRECT")
    assert len(rows) == 1
    assert rows[0]["failure_code"] == "JOURNEY_BSK_NAVIGATION_TARGET_MISMATCH"
    assert len([cmd for cmd in runner.calls if "step" in cmd]) == 1


def test_bsk_crash_after_dispatch_intent_never_reissues_sut_action_on_cold_restart(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    cli = TestBSK()
    adapter = _adapter(pool, tmp_path, cli)
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
    step = candidate["steps"][0]
    context = {
        "replay_id": "BSK-COLD-CRASH", "mission_id": "M-1",
        "workitem_id": "WI-R1", "attempt_id": "ATT-R1",
        "worker_id": "WORKER-R1", "session_id": "SESSION-R1",
        "browser_lease_id": lease.browser_lease_id}
    folder = tmp_path / "bsk-evidence" / "BSK-COLD-CRASH" / "step-0001"
    folder.mkdir(parents=True)
    intent = folder / "dispatch-intent.json"
    original = '{"status":"EFFECT_UNKNOWN_UNTIL_ACTUAL","attempt_id":"ATT-R1"}'
    intent.write_text(original)
    assert not (folder / "actual.json").exists()
    assert not (folder / "screen.png").exists()
    # Simulate losing all in-process guard state; this adapter has never seen
    # the step and only the pre-existing fsynced intent can protect SUT.
    outcome = adapter.execute_step(step, context)
    assert outcome["status"] == "FAILED"
    assert outcome["failure_code"] == "JOURNEY_BSK_DUPLICATE_STEP_EFFECT_UNKNOWN"
    assert intent.read_text() == original
    assert cli.calls == []
    assert not (folder / "screen.png").exists()


def test_bsk_persists_intent_before_first_mutating_cli_and_keeps_it_on_success(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    evidence_root = tmp_path / "bsk-evidence"
    class CheckIntentBeforeAction(TestBSK):
        def __call__(self, argv):
            if "step" in argv:
                intent = evidence_root / "BSK-INTENT-ORDER" / "step-0001" / "dispatch-intent.json"
                assert intent.is_file()
                marker = json.loads(intent.read_text())
                assert marker["status"] == "EFFECT_UNKNOWN_UNTIL_ACTUAL"
                assert marker["attempt_id"] == "ATT-R1"
            return super().__call__(argv)
    cli = CheckIntentBeforeAction()
    adapter = _adapter(pool, tmp_path, cli)
    step = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]["steps"][0]
    outcome = adapter.execute_step(step, {
        "replay_id": "BSK-INTENT-ORDER", "mission_id": "M-1",
        "workitem_id": "WI-R1", "attempt_id": "ATT-R1",
        "worker_id": "WORKER-R1", "session_id": "SESSION-R1",
        "browser_lease_id": lease.browser_lease_id})
    assert outcome["status"] == "PASSED"
    marker_path = evidence_root / "BSK-INTENT-ORDER" / "step-0001" / "dispatch-intent.json"
    assert marker_path.is_file()
    actual = json.loads(Path(outcome["actual_refs"][0][7:]).read_text())
    assert actual["dispatch_intent_ref"] == marker_path.resolve().as_uri()
    assert marker_path.resolve().as_uri() in outcome["evidence_refs"]


def test_bsk_matching_session_receipt_is_not_enough_without_b_authority(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    cli = TestBSK()
    adapter = _adapter(pool, tmp_path, cli)
    adapter.verify_session = lambda ownership, scope, instance: False
    step = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]["steps"][0]
    outcome = adapter.execute_step(step, {
        "replay_id": "BSK-AUTHORITY-REJECTED",
        "mission_id": "M-1", "workitem_id": "WI-R1",
        "attempt_id": "ATT-R1", "worker_id": "WORKER-R1",
        "session_id": "SESSION-R1",
        "browser_lease_id": lease.browser_lease_id})
    assert outcome["status"] == "FAILED"
    assert outcome["failure_code"] == "JOURNEY_BSK_EXTERNAL_SESSION_AUTHORITY_REJECTED"
    assert cli.calls == []


def test_bsk_requires_external_session_authority_at_construction(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    from rc7_runtime.rc72_journey_bsk import JourneyBSKAdapter
    with pytest.raises(Exception, match="JOURNEY_BSK_EXTERNAL_SESSION_AUTHORITY_REQUIRED"):
        JourneyBSKAdapter(
            browser_pool=pool, evidence_root=tmp_path / "no-authority",
            bsk_executable=tmp_path / "bsk.exe",
            session_resolver=lambda ctx, instance: {},
            session_receipt_verifier=None,
            reference_resolver=lambda ref, kind, ctx: None,
            runner=TestBSK())


def test_bsk_wheel_does_not_dispatch_unsafe_unbounded_coordinates(tmp_path):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    cli = TestBSK()
    adapter = _adapter(pool, tmp_path, cli)
    step = dict(truth.query(
        "rc72_journey_candidate", candidate_id="JC-1")[0]["steps"][0])
    step.update(action_type="WHEEL", element_ref="css:#panel",
                delta_x=0, delta_y=500000)
    actual = adapter.execute_step(step, {
        "replay_id": "BSK-WHEEL-UNSAFE", "mission_id": "M-1",
        "workitem_id": "WI-R1", "attempt_id": "ATT-R1",
        "worker_id": "WORKER-R1", "session_id": "SESSION-R1",
        "browser_lease_id": lease.browser_lease_id})
    assert actual["status"] == "FAILED"
    assert actual["failure_code"] == "JOURNEY_BSK_WHEEL_DELTA_INVALID"
    assert not any("step" in c for c in cli.calls)


@pytest.mark.parametrize("phase,mutate,failure", [
    ("step", lambda doc: doc["action"]["result"].update(tab_id=98),
     "JOURNEY_BSK_ACTION_UNKNOWN_OR_UNOBSERVED"),
    ("evaluate", lambda doc: doc.update(tab_id=98),
     "JOURNEY_BSK_EVALUATE_TAB_MISMATCH"),
    ("screenshot", lambda doc: doc.update(width=200),
     "JOURNEY_BSK_SCREENSHOT_INVALID"),
    ("screenshot", lambda doc: doc.update(capture_unavailable="blocked"),
     "JOURNEY_BSK_SCREENSHOT_INVALID"),
])
def test_bsk_mismatched_action_oracle_or_png_provenance_cannot_pass(
        tmp_path, phase, mutate, failure):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    class Mismatch(TestBSK):
        def __call__(self, argv):
            response = super().__call__(argv)
            if phase in argv:
                reply = json.loads(response["stdout"])
                mutate(reply)
                response["stdout"] = json.dumps(reply)
            return response

    runner = Mismatch()
    adapter = _adapter(pool, tmp_path, runner)
    result = JourneyReplayService(
        truth, release_id="RC7.2",
        browser_pool=pool, adapter=adapter).replay(
        replay_id="BSK-PROVENANCE-" + phase,
        candidate_id="JC-1", workitem_id="WI-R1",
        attempt_id="ATT-R1", worker_id="WORKER-R1",
        session_id="SESSION-R1",
        browser_lease_id=lease.browser_lease_id)
    assert result.state.value == "FAILED"
    rows = sorted(truth.query(
        "rc72_journey_replay_step", replay_id="BSK-PROVENANCE-" + phase),
        key=lambda x: x["sequence"])
    assert next(r for r in rows if r["status"] == "FAILED")["failure_code"] == failure


def _backend_oracle_replay(tmp_path, *, tamper=None, trust=True):
    truth, pool, lease, _, _ = replay_setup(tmp_path)
    cli = TestBSK()
    adapter = _adapter(pool, tmp_path, cli)
    normal = adapter.resolve
    def resolve(ref, kind, context):
        if kind == "oracle" and ref == "oracle://success-toast":
            return {"type": "backend_state",
                    "business_rule_ref": "pcc://configuration-saved",
                    "expected": "SAVED_EFFECTIVE"}
        return normal(ref, kind, context)
    adapter.resolve = resolve

    def independent_bank_oracle(oracle, context):
        receipt = {
            "oracle_ref": "oracle://success-toast",
            "business_rule_ref": "pcc://configuration-saved",
            "mission_id": context["mission_id"],
            "release_batch_id": context["release_batch_id"],
            "requirement_id": context["requirement_id"],
            "sst_id": context["sst_id"],
            "obligation_id": context["obligation_id"],
            "case_id": context["case_id"],
            "attempt_id": context["attempt_id"],
            "browser_lease_id": context["browser_lease_id"],
            "verifier_kind": "TEST_BANK_EXTERNAL_DATA_ORACLE",
            "signature_verified": True,
            "source_kind": "INDEPENDENT_DB_STATE",
            "observed_state": "SAVED_EFFECTIVE",
            "matched": True, "observed_at": int(time.time()),
            "evidence_refs": ["r1://test-bank-db-snapshot"],
        }
        if tamper:
            tamper(receipt)
        return receipt

    adapter.business_oracle_verifier = independent_bank_oracle
    adapter.trusted_business_verifier_kinds = (
        {"TEST_BANK_EXTERNAL_DATA_ORACLE"} if trust else set())
    outcome = JourneyReplayService(
        truth, release_id="RC7.2", browser_pool=pool,
        adapter=adapter).replay(
            replay_id="BSK-BACKEND-BUSINESS",
            candidate_id="JC-1", workitem_id="WI-R1",
            attempt_id="ATT-R1", worker_id="WORKER-R1",
            session_id="SESSION-R1", browser_lease_id=lease.browser_lease_id)
    return truth, outcome, cli


def test_bsk_backend_business_oracle_links_independent_db_evidence_to_actual(tmp_path):
    truth, outcome, cli = _backend_oracle_replay(tmp_path)
    assert outcome.state.value == "PASSED"
    assert any("step" in command for command in cli.calls)
    rows = sorted(truth.query(
        "rc72_journey_replay_step", replay_id="BSK-BACKEND-BUSINESS"),
        key=lambda x: x["sequence"])
    assert len(rows) == 2
    assert "r1://test-bank-db-snapshot" in rows[1]["evidence_refs"]
    actual = json.loads(Path(rows[1]["actual_refs"][0][7:]).read_text())
    assert actual["business_oracle_evidence_refs"] == [
        "r1://test-bank-db-snapshot"]
    assert actual["status"] == "PASSED"
    assert actual["field_verified"] is False


@pytest.mark.parametrize("tamper,error", [
    (lambda p: p.update(attempt_id="ATT-FORGED"),
     "JOURNEY_BSK_BACKEND_ORACLE_SCOPE_MISMATCH"),
    (lambda p: p.update(signature_verified=False),
     "JOURNEY_BSK_BACKEND_ORACLE_AUTHORITY_UNTRUSTED"),
    (lambda p: p.update(observed_state="NOT_SAVED"),
     "JOURNEY_BSK_BACKEND_BUSINESS_STATE_MISMATCH"),
    (lambda p: p.update(evidence_refs=[]),
     "JOURNEY_BSK_BACKEND_ORACLE_EVIDENCE_REQUIRED"),
    (lambda p: p.update(observed_at=0),
     "JOURNEY_BSK_BACKEND_ORACLE_STALE"),
])
def test_bsk_independent_backend_oracle_rejects_fake_or_stale_business_receipt(
        tmp_path, tamper, error):
    truth, outcome, cli = _backend_oracle_replay(tmp_path, tamper=tamper)
    assert outcome.state.value == "FAILED"
    rows = sorted(truth.query(
        "rc72_journey_replay_step", replay_id="BSK-BACKEND-BUSINESS"),
        key=lambda x: x["sequence"])
    assert rows[-1]["failure_code"] == error
    actual = json.loads(Path(rows[-1]["actual_refs"][0][7:]).read_text())
    assert actual["status"] == "FAILED"


def test_bsk_backend_oracle_without_a_b_external_trust_cannot_pass(tmp_path):
    truth, outcome, cli = _backend_oracle_replay(tmp_path, trust=False)
    assert outcome.state.value == "FAILED"
    rows = truth.query(
        "rc72_journey_replay_step", replay_id="BSK-BACKEND-BUSINESS")
    assert rows[-1]["failure_code"] == (
        "JOURNEY_BSK_BACKEND_BUSINESS_ORACLE_AUTHORITY_REQUIRED")


def test_official_n7_backend_business_oracle_requires_independent_api_db_evidence(tmp_path):
    runner = TestBSK()
    truth, pool, lease, _, _ = official_setup(tmp_path)
    adapter = _adapter(pool, tmp_path, runner)
    original = adapter.resolve

    def resolver(ref, kind, ctx):
        if kind == "oracle" and ref == "oracle://success-toast":
            return {"type": "backend_state",
                    "business_rule_ref": "pcc://saved-row-effective",
                    "expected": "CONFIG_PERSISTED"}
        return original(ref, kind, ctx)

    def external_api_db(oracle, ctx):
        return {
            "oracle_ref": "oracle://success-toast",
            "business_rule_ref": "pcc://saved-row-effective",
            "mission_id": ctx["mission_id"],
            "release_batch_id": ctx["release_batch_id"],
            "requirement_id": ctx["requirement_id"],
            "sst_id": ctx["sst_id"],
            "obligation_id": ctx["obligation_id"],
            "case_id": ctx["case_id"],
            "attempt_id": ctx["attempt_id"],
            "browser_lease_id": ctx["browser_lease_id"],
            "verifier_kind": "TEST_BANK_INDEPENDENT_DB",
            "signature_verified": True,
            "source_kind": "INDEPENDENT_DB_STATE",
            "observed_state": "CONFIG_PERSISTED",
            "matched": True, "observed_at": int(time.time()),
            "evidence_refs": ["r1://official-config-row-snapshot"],
        }

    adapter.resolve = resolver
    adapter.business_oracle_verifier = external_api_db
    adapter.trusted_business_verifier_kinds = {"TEST_BANK_INDEPENDENT_DB"}
    service = OfficialJourneyExecutionService(
        truth, release_id="RC7.2", browser_pool=pool, adapter=adapter)
    result = official_run(service, lease, execution_id="OJ-BSK-DB-ORACLE")
    assert result.state.value == "PASSED"
    rows = sorted(truth.query(
        "rc72_official_journey_execution_step",
        execution_id="OJ-BSK-DB-ORACLE"),
        key=lambda row: row["sequence"])
    assert rows and all(row["status"] == "PASSED" for row in rows)
    assert "r1://official-config-row-snapshot" in rows[1]["evidence_refs"]
    actual = json.loads(Path(rows[1]["actual_refs"][0][7:]).read_text())
    assert "r1://official-config-row-snapshot" in actual["business_oracle_evidence_refs"]
    assert truth.query("rc72_official_journey_execution",
                       execution_id="OJ-BSK-DB-ORACLE")[0]["field_verified"] is False
