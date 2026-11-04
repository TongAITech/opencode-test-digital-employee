"""BSK live capture lifecycle: debug start, one-action snapshot, stop/export, R1."""
import json
from pathlib import Path

import pytest

from rc7_runtime.rc72_journey_bsk_live_teaching import JourneyBSKLiveTeaching
from rc7_runtime.rc72_journey_compiler import JourneyCompiler
from test_rc72_journey_bsk_import import _fixture, _owned_receipt, _PNG


class FakeBSKRecordingCLI:
    def __init__(self, exported, *, pending_overflow=False, bad_png=False):
        self.doc = exported
        self.calls = []
        self.pending_overflow = pending_overflow
        self.bad_png = bad_png

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        if "debug" in argv:
            action = argv[argv.index("debug") + 1]
            if action == "start":
                run = dict(self.doc["run"])
                run["state"] = "capturing"
                run["stopped_at"] = None
                return {"returncode": 0, "stdout": json.dumps({"run": run})}
            if action == "operations":
                since = int(argv[argv.index("--since") + 1])
                operations = [op for op in self.doc["operations"]
                              if op["sequence"] > since]
                if not self.pending_overflow:
                    operations = operations[:1]
                return {"returncode": 0, "stdout": json.dumps({
                    "run": {"id": self.doc["run"]["id"]},
                    "operations": operations})}
            if action == "stop":
                return {"returncode": 0, "stdout": json.dumps({
                    "run": self.doc["run"]})}
            if action == "export":
                target = Path(argv[argv.index("--output") + 1])
                target.write_text(json.dumps(self.doc))
                return {"returncode": 0, "stdout": json.dumps({
                    "path": str(target), "run_id": self.doc["run"]["id"],
                    "bytes": target.stat().st_size})}
        if "cooperate" in argv:
            dest = Path(argv[argv.index("--save-full") + 1])
            source = {
                "session_id": "bsk-task-a1", "tab_id": 1,
                "context_id": "BSK-LIVE-CONTEXT",
                "source": "BSK_COOPERATE_SYNC"}
            dest.write_text(json.dumps(source))
            return {"returncode": 0, "stdout": json.dumps(source)}
        if "screenshot" in argv:
            dest = Path(argv[argv.index("--out") + 1])
            dest.write_bytes(b"not-an-image" if self.bad_png else _PNG)
            return {"returncode": 0, "stdout": json.dumps({
                "tab_id": 1, "format": "png",
                "width": 1, "height": 1,
                "byte_size": dest.stat().st_size})}
        raise AssertionError("unexpected BrowserSkill command %r" % argv)


def _live(tmp_path, *, pending_overflow=False, bad_png=False):
    truth, importer, doc, exported, args, evidence = _fixture(tmp_path)
    args["recording_id"] = "JR-LIVE"
    receipt = _owned_receipt(importer, args)
    fake = FakeBSKRecordingCLI(doc, pending_overflow=pending_overflow,
                               bad_png=bad_png)
    client = JourneyBSKLiveTeaching(
        importer=importer, bsk_executable=tmp_path / "bsk",
        bsk_session_receipt=receipt, recording_args=args, runner=fake)
    return truth, client, fake


def test_bsk_live_human_capture_to_compiled_candidate_without_playwright(tmp_path):
    truth, client, cli = _live(tmp_path)
    assert client.start(capture_name="human config save") == "debug-1"
    assert client.capture_next(page_role="CONFIG") == "operation-1"
    assert client.capture_next(
        locator_ref="css:#save", page_role="CONFIG") == "operation-2"
    receipt = client.finish(assertions=[
        {"source_operation_id": "operation-2",
         "locator_ref": "css:#toast",
         "oracle_ref": "oracle://business-save"}])
    assert receipt.state.value == "CAPTURED"
    assert client.stopped is True
    assert not any("session" in x and "stop" in x for x in cli.calls)
    steps = sorted(
        truth.query("rc72_journey_capture_step", recording_id="JR-LIVE"),
        key=lambda row: row["sequence"])
    assert [row["action_type"] for row in steps] == ["NAVIGATE", "CLICK", "ASSERT"]
    for step in steps[:2]:
        assert Path(step["dom_ref"][7:]).is_file()
        assert Path(step["screenshot_ref"][7:]).is_file()
    compiled = JourneyCompiler(truth, release_id="RC7.2").compile(
        candidate_id="JC-BSK-LIVE", recording_id="JR-LIVE")
    assert compiled.state.value == "COMPILED_CANDIDATE"
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-BSK-LIVE")[0]
    assert candidate["executable"] is False and candidate["official"] is False


def test_bsk_live_rejects_two_unobserved_actions_instead_of_fake_screenshots(tmp_path):
    truth, client, cli = _live(tmp_path, pending_overflow=True)
    client.start(capture_name="two actions")
    with pytest.raises(Exception, match="JOURNEY_BSK_LIVE_EXACTLY_ONE_OPERATION_REQUIRED"):
        client.capture_next(page_role="CONFIG")
    assert not truth.query("rc72_journey_recording", recording_id="JR-LIVE")
    assert not any("screenshot" in x for x in cli.calls)


def test_bsk_live_rejects_corrupt_image_without_recording_step(tmp_path):
    truth, client, cli = _live(tmp_path, bad_png=True)
    client.start(capture_name="screenshot corrupt")
    with pytest.raises(Exception, match="JOURNEY_BSK_SCREENSHOT"):
        client.capture_next(page_role="CONFIG")
    assert client.evidence == {}
    assert not truth.query("rc72_journey_capture_step", recording_id="JR-LIVE")


def test_bsk_live_rejects_cross_identity_before_debug_start(tmp_path):
    truth, client, cli = _live(tmp_path)
    client.receipt["auth_asset_ref"] = "auth://4a/unrelated"
    with pytest.raises(Exception, match="JOURNEY_BSK_LIVE_OWNERSHIP_SCOPE_MISMATCH"):
        client.start(capture_name="unsafe")
    assert cli.calls == []


def test_bsk_live_fails_if_second_human_action_occurs_during_screenshot(tmp_path):
    truth, client, original = _live(tmp_path)

    class ConcurrentHuman:
        def __init__(self, backing):
            self.backing = backing
            self.shot = False
            self.calls = []

        def __call__(self, argv):
            self.calls.append(list(argv))
            if "screenshot" in argv:
                self.shot = True
            if "debug" in argv and "operations" in argv and self.shot:
                return {"returncode": 0, "stdout": json.dumps({
                    "run": {"id": "debug-1"},
                    "operations": self.backing.doc["operations"]})}
            return self.backing(argv)

    runner = ConcurrentHuman(original)
    client.runner = runner
    client.start(capture_name="concurrent-human")
    with pytest.raises(Exception, match="JOURNEY_BSK_LIVE_CONCURRENT_ACTION_EVIDENCE_UNSAFE"):
        client.capture_next(page_role="CONFIG")
    assert client.evidence == {}
    assert client.last_sequence == 0
    assert not truth.query("rc72_journey_recording", recording_id="JR-LIVE")


def test_bsk_live_denied_by_external_b_authority_before_debug_start(tmp_path):
    truth, client, cli = _live(tmp_path)
    client.importer.verify_session = lambda ownership, scope, instance: False
    with pytest.raises(Exception, match="JOURNEY_BSK_LIVE_EXTERNAL_AUTHORITY_REJECTED"):
        client.start(capture_name="not-authorized")
    assert cli.calls == []
    assert not truth.query("rc72_journey_recording", recording_id="JR-LIVE")


def test_bsk_live_refuses_export_from_other_debug_run_even_same_tab_and_session(tmp_path):
    truth, client, cli = _live(tmp_path)
    class SwappedRun:
        def __init__(self, backing):
            self.backing = backing
            self.calls = []
        def __call__(self, argv):
            self.calls.append(list(argv))
            if "debug" in argv and "export" in argv:
                reply = self.backing(argv)
                result = json.loads(reply["stdout"])
                result["run_id"] = "debug-from-another-task"
                reply["stdout"] = json.dumps(result)
                return reply
            return self.backing(argv)
    swapped = SwappedRun(cli)
    client.runner = swapped
    client.start(capture_name="session-swapping")
    client.capture_next(page_role="CONFIG")
    client.capture_next(page_role="CONFIG", locator_ref="css:#save")
    with pytest.raises(Exception, match="JOURNEY_BSK_LIVE_EXPORT_PROVENANCE_MISMATCH"):
        client.finish()
    assert not truth.query("rc72_journey_recording", recording_id="JR-LIVE")
    assert client.stopped is True


def test_bsk_live_refuses_lying_png_dimensions_from_native_capture(tmp_path):
    truth, client, cli = _live(tmp_path)
    class WrongDimensions:
        def __init__(self, original):
            self.original = original
        def __call__(self, argv):
            reply = self.original(argv)
            if "screenshot" in argv:
                payload = json.loads(reply["stdout"])
                payload["width"] = 1024
                reply["stdout"] = json.dumps(payload)
            return reply
    client.runner = WrongDimensions(cli)
    client.start(capture_name="invalid-picture-provenance")
    with pytest.raises(Exception, match="JOURNEY_BSK_LIVE_SCREENSHOT_UNVERIFIED"):
        client.capture_next(page_role="CONFIG")
    assert client.evidence == {}
    assert not truth.query("rc72_journey_recording", recording_id="JR-LIVE")
