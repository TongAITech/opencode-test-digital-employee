"""BSK-native debug-export teaching tests; never claim bank Field approval."""
import base64
import json
from pathlib import Path

import pytest

from rc7_runtime.rc72_journey_bsk_import import BSKJourneyTeachingImporter
from rc7_runtime.rc72_journey_compiler import JourneyCompiler
from test_rc72_phase9_journey_teaching_capture_contract import _setup


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4"
    "nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


def _fixture(tmp_path):
    truth, teaching, pool, lease = _setup(tmp_path)
    folder = tmp_path / "bsk-origin"
    folder.mkdir(parents=True)
    screenshots = []
    doms = []
    for seq in (1, 2):
        screenshot = folder / ("screen-%d.png" % seq)
        screenshot.write_bytes(_PNG)
        screenshots.append(screenshot)
        dom = folder / ("observed-dom-%d.json" % seq)
        dom.write_text(json.dumps({
            "source": "BSK_OBSERVE", "operation_sequence": seq,
            "element": "button#save"}))
        doms.append(dom)
    operations = [
        {"id": "operation-1", "run_id": "debug-1", "sequence": 1,
         "method": "tool.navigate", "source": "agent", "state": "completed",
         "request_ids": [], "truncated": False,
         "after": {"state": "available", "url": "https://fat1.example/config?token=private"}},
        {"id": "operation-2", "run_id": "debug-1", "sequence": 2,
         "method": "tool.click", "source": "human", "state": "completed",
         "request_ids": ["request-1"], "truncated": False,
         "after": {"state": "available", "url": "https://fat1.example/config"}},
    ]
    doc = {
        "version": 1, "saved_at": 10000,
        "run": {"id": "debug-1", "session_id": "bsk-task-a1",
                "tab_id": 1, "name": "teaching", "url": "https://fat1.example/config",
                "started_at": 1000, "stopped_at": 9000, "state": "stopped",
                "coverage": [], "dropped_requests": 0,
                "dropped_operations": 0, "dropped_console": 0},
        "operations": operations,
        "requests": [{"id": "request-1", "run_id": "debug-1",
                      "sequence": 1, "method": "POST",
                      "url": "https://fat1.example/api/save?token=private",
                      "state": "complete", "status": 200}],
        "console": [], "pages": [],
    }
    export = folder / "debug-export.json"
    export.write_text(json.dumps(doc), encoding="utf-8")
    evidence_map = {
        "operation-1": {"dom_ref": doms[0].resolve().as_uri(),
                        "screenshot_ref": screenshots[0].resolve().as_uri(),
                        "page_role": "CONFIG"},
        "operation-2": {"dom_ref": doms[1].resolve().as_uri(),
                        "screenshot_ref": screenshots[1].resolve().as_uri(),
                        "page_role": "CONFIG", "locator_ref": "css:#save"},
    }
    recording_args = dict(
        recording_id="JR-BSK-1", mission_id="M-1", release_batch_id="RB-1",
        requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
        workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
        session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
        human_operator_ref="human://operator", auth_asset_ref="auth://4a/session-asset")
    importer = BSKJourneyTeachingImporter(
        teaching=teaching, evidence_root=tmp_path / "canonical-bsk",
        authorized_capture_root=folder)
    return truth, importer, doc, export, recording_args, evidence_map


def _owned_receipt(importer, args, *, tab_id=1):
    pool = importer.teaching.browser_pool
    lease = pool.lease(args["browser_lease_id"])
    instance = pool.truth.query(
        "rc72_browser_instance", browser_instance_id=lease["browser_instance_id"])[0]
    return {
        "bsk_session_id": "bsk-task-a1", "tab_id": tab_id,
        "state": "ACTIVE", "source_receipt_ref": "r1://bsk-bound-session",
        "browser_instance_id": instance["browser_instance_id"],
        "profile_dir": instance["profile_dir"],
        "bsk_endpoint": instance["bsk_endpoint"],
        "auth_asset_ref": instance["auth_asset_ref"],
        "browser_lease_id": args["browser_lease_id"],
        "mission_id": args["mission_id"], "workitem_id": args["workitem_id"],
        "attempt_id": args["attempt_id"], "worker_id": args["worker_id"],
        "dsh_session_id": args["session_id"],
    }


def _invoke(importer, export, args, mapping, assertions=(), receipt=None):
    return importer.import_export(
        export_file=export, bsk_session_id="bsk-task-a1",
        recording_args=args,
        bsk_session_receipt=receipt if receipt is not None else _owned_receipt(importer, args),
        evidence_map=mapping, assertions=assertions)


def test_bsk_human_click_source_produces_nonexecuting_compiled_candidate(tmp_path):
    truth, importer, doc, export, args, mapping = _fixture(tmp_path)
    result = _invoke(importer, export, args, mapping, assertions=[
        {"source_operation_id": "operation-2",
         "locator_ref": "css:#toast",
         "oracle_ref": "oracle://business-save-confirmed"}])
    assert result.state.value == "CAPTURED"
    steps = sorted(
        truth.query("rc72_journey_capture_step", recording_id="JR-BSK-1"),
        key=lambda row: row["sequence"])
    assert [s["action_type"] for s in steps] == ["NAVIGATE", "CLICK", "ASSERT"]
    assert steps[1]["element_ref"] == "css:#save"
    actual = json.loads(Path(steps[1]["network_refs"][0][7:]).read_text())
    assert actual["responses"][0]["method"] == "POST"
    assert actual["responses"][0]["status"] == 200
    assert actual["responses"][0]["association"] == "BSK_OPERATION_WINDOW_NOT_CAUSAL_PROOF"
    assert "private" not in json.dumps(actual)
    compiled = JourneyCompiler(truth, release_id="RC7.2").compile(
        candidate_id="JC-BSK-1", recording_id="JR-BSK-1")
    assert compiled.state.value == "COMPILED_CANDIDATE"
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-BSK-1")[0]
    assert candidate["case_id"] == "TC-1"
    assert candidate["official"] is False and candidate["executable"] is False
    assert any(s.get("oracle_ref") == "oracle://business-save-confirmed"
               for s in candidate["steps"])


@pytest.mark.parametrize("mutation,error", [
    ("wrong_session", "JOURNEY_BSK_SESSION_SCOPE_MISMATCH"),
    ("capture_running", "JOURNEY_BSK_CAPTURE_NOT_STOPPED"),
    ("dropped_ops", "JOURNEY_BSK_CAPTURE_INCOMPLETE"),
    ("partial_coverage", "JOURNEY_BSK_CAPTURE_COVERAGE_GAP"),
    ("incomplete_operation", "JOURNEY_BSK_OPERATION_INCOMPLETE"),
    ("mocked_request", "JOURNEY_BSK_REQUEST_UNKNOWN_OR_MODIFIED"),
    ("unbound_ref", "JOURNEY_BSK_STABLE_LOCATOR_BINDING_REQUIRED"),
    ("missing_png", "JOURNEY_BSK_REAL_EVIDENCE_FILE_REQUIRED"),
    ("missing_dom", "JOURNEY_BSK_REAL_EVIDENCE_FILE_REQUIRED"),
])
def test_bsk_rejects_bad_capture_before_any_r1_mutation(tmp_path, mutation, error):
    truth, importer, doc, export, args, mapping = _fixture(tmp_path)
    if mutation == "wrong_session":
        doc["run"]["session_id"] = "wrong-session"
    elif mutation == "capture_running":
        doc["run"]["state"] = "capturing"
    elif mutation == "dropped_ops":
        doc["run"]["dropped_operations"] = 1
    elif mutation == "partial_coverage":
        doc["run"]["coverage"] = ["observer_incomplete"]
    elif mutation == "incomplete_operation":
        doc["operations"][1]["state"] = "interrupted"
    elif mutation == "mocked_request":
        doc["requests"][0]["intervention"] = {"type": "mock", "state": "applied"}
    elif mutation == "unbound_ref":
        mapping["operation-2"].pop("locator_ref")
    elif mutation == "missing_png":
        mapping["operation-1"]["screenshot_ref"] = (tmp_path / "absent.png").as_uri()
    elif mutation == "missing_dom":
        mapping["operation-2"]["dom_ref"] = (tmp_path / "absent.json").as_uri()
    export.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(Exception, match=error):
        _invoke(importer, export, args, mapping)
    assert not truth.query("rc72_journey_recording", recording_id="JR-BSK-1")
    assert not truth.query("rc72_journey_capture_step", recording_id="JR-BSK-1")


def test_bsk_never_invents_business_oracle_from_http_200(tmp_path):
    truth, importer, doc, export, args, mapping = _fixture(tmp_path)
    _invoke(importer, export, args, mapping)
    JourneyCompiler(truth, release_id="RC7.2").compile(
        candidate_id="JC-NO-ORACLE", recording_id="JR-BSK-1")
    candidate = truth.query("rc72_journey_candidate", candidate_id="JC-NO-ORACLE")[0]
    assert not any(s.get("oracle_ref") for s in candidate["steps"])
    assert candidate["executable"] is False


@pytest.mark.parametrize("mutation,error", [
    ("other_attempt", "JOURNEY_BSK_TEACHING_SESSION_SCOPE_MISMATCH"),
    ("other_profile", "JOURNEY_BSK_TEACHING_SESSION_SCOPE_MISMATCH"),
    ("other_4a", "JOURNEY_BSK_TEACHING_SESSION_SCOPE_MISMATCH"),
    ("other_dsh", "JOURNEY_BSK_TEACHING_SESSION_SCOPE_MISMATCH"),
    ("other_tab", "JOURNEY_BSK_TEACHING_SESSION_PROVENANCE_INVALID"),
    ("missing_receipt", "JOURNEY_BSK_TEACHING_SESSION_PROVENANCE_INVALID"),
])
def test_bsk_import_requires_live_b_group_tab_4a_attempt_receipt(tmp_path, mutation, error):
    truth, importer, doc, export, args, mapping = _fixture(tmp_path)
    receipt = _owned_receipt(importer, args)
    if mutation == "other_attempt":
        receipt["attempt_id"] = "ATT-OTHER"
    elif mutation == "other_profile":
        receipt["profile_dir"] = "profiles/unrelated"
    elif mutation == "other_4a":
        receipt["auth_asset_ref"] = "auth://wrong"
    elif mutation == "other_dsh":
        receipt["dsh_session_id"] = "SESSION-OTHER"
    elif mutation == "other_tab":
        receipt["tab_id"] = 99
    elif mutation == "missing_receipt":
        receipt.pop("source_receipt_ref")
    with pytest.raises(Exception, match=error):
        _invoke(importer, export, args, mapping, receipt=receipt)
    assert not truth.query("rc72_journey_recording", recording_id="JR-BSK-1")


@pytest.mark.parametrize("mutation,error", [
    ("outside_root", "JOURNEY_BSK_EVIDENCE_OUTSIDE_AUTHORIZED_CAPTURE_ROOT"),
    ("same_dom", "JOURNEY_BSK_OPERATION_EVIDENCE_REUSED"),
    ("same_png", "JOURNEY_BSK_OPERATION_EVIDENCE_REUSED"),
    ("extra_operation", "JOURNEY_BSK_EVIDENCE_OPERATION_SET_MISMATCH"),
])
def test_bsk_evidence_is_per_operation_and_scoped_to_authorized_capture(tmp_path, mutation, error):
    truth, importer, doc, export, args, mapping = _fixture(tmp_path)
    if mutation == "outside_root":
        outside = tmp_path / "outside.json"
        outside.write_text('{"source":"wrong task"}')
        mapping["operation-1"]["dom_ref"] = outside.resolve().as_uri()
    elif mutation == "same_dom":
        mapping["operation-2"]["dom_ref"] = mapping["operation-1"]["dom_ref"]
    elif mutation == "same_png":
        mapping["operation-2"]["screenshot_ref"] = mapping["operation-1"]["screenshot_ref"]
    elif mutation == "extra_operation":
        mapping["operation-not-in-BSK"] = dict(mapping["operation-1"])
    with pytest.raises(Exception, match=error):
        _invoke(importer, export, args, mapping)
    assert not truth.query("rc72_journey_recording", recording_id="JR-BSK-1")
