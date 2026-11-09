"""C09 real Chromium CDP plus HTTP application smoke, not a bank Field proof.

No FakeBrowser or synthetic actual:// references. This validates actual CDP,
HTTP POST, DOM business Oracle, PNG bytes and canonical R1 replay receipts.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen, url2pathname

# Deliberately required: any CI suite collecting this module must provision
# Python Playwright and the matching real Chromium. Never silently skip a
# required browser proof in an RC7.2 qualification job.
from playwright.sync_api import expect, sync_playwright

from rc7_runtime.rc72_journey_playwright import JourneyPlaywrightAdapter
from rc7_runtime.rc72_journey_replay import JourneyReplayService
from test_rc72_phase9_journey_replay_contract import _setup as replay_setup

def _local_evidence_path(ref: str) -> Path:
    """Parse canonical file URI on Linux AND Windows (never strip file://).

    On Windows file:///C:/... must become C:\\..., not invalid \\C:\\...
    This verifier is read-only and rejects nonlocal evidence locations.
    """
    parsed = urlsplit(ref)
    assert parsed.scheme == "file" and parsed.netloc in ("", "localhost")
    return Path(url2pathname(parsed.path))


def test_local_evidence_uri_round_trip_with_spaces(tmp_path: Path):
    target = tmp_path / "actual screen.png"
    target.write_bytes(b"evidence-local-path")
    assert _local_evidence_path(target.resolve().as_uri()).read_bytes() == b"evidence-local-path"


_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>Actual Browser Test</title>
<body>
 <button id="save" type="button">Save configuration</button>
 <div id="toast" role="status">Before save</div>
 <script>
 document.querySelector("#save").addEventListener("click", async () => {
   const response = await fetch("/api/save?private=never-leak", {method: "POST"});
   const result = await response.json();
   document.querySelector("#toast").textContent = result.message;
 });
 </script>
</body></html>""".encode("utf-8")


class LocalSUT(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/config"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(_PAGE)))
            self.end_headers()
            self.wfile.write(_PAGE)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path.startswith("/api/save"):
            raw = b'{"message":"Saved on server"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


def _reserved_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _export_ci_evidence(tmp_path: Path, label: str) -> None:
    """Ship auditable local-CI R1+actual PNG/JSON, never Chrome profile/cookies."""
    root = os.environ.get("RC72_C09_EVIDENCE_EXPORT_ROOT")
    if not root:
        return
    destination = Path(root) / label
    destination.mkdir(parents=True, exist_ok=True)
    truth_file = tmp_path / "r1.jsonl"
    if truth_file.is_file():
        shutil.copy2(str(truth_file), str(destination / "r1.jsonl"))
    for name in ("actual-browser-evidence", "real-teaching-evidence"):
        source = tmp_path / name
        if source.is_dir():
            shutil.copytree(str(source), str(destination / name), dirs_exist_ok=True)


def test_real_chromium_cdp_journey_replay_and_business_oracles(tmp_path: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalSUT)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = "http://127.0.0.1:%d" % server.server_address[1]
    cdp_port = _reserved_port()
    cdp_endpoint = "http://127.0.0.1:%d" % cdp_port
    adapter = None
    process = None
    try:
        with sync_playwright() as playwright:
            browser_binary = Path(playwright.chromium.executable_path)
            assert browser_binary.is_file(), "REAL_CHROMIUM_BINARY_REQUIRED"
        process = subprocess.Popen(
            [
                str(browser_binary), "--headless=new", "--no-sandbox",
                "--disable-dev-shm-usage", "--disable-gpu",
                "--no-first-run", "--no-default-browser-check",
                "--remote-allow-origins=*", "--remote-debugging-port=%d" % cdp_port,
                "--user-data-dir=%s" % (tmp_path / "chromium-profile"),
                "--app=" + origin + "/config",
            ],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        connected = False
        for _ in range(100):
            if process.poll() is not None:
                raise AssertionError("REAL_CHROMIUM_EXITED_BEFORE_CDP_READY")
            try:
                with urlopen(cdp_endpoint + "/json/version", timeout=0.5) as response:
                    connected = b"Browser" in response.read()
                if connected:
                    break
            except Exception:
                time.sleep(0.2)
        assert connected, "REAL_CHROMIUM_CDP_NOT_READY"

        truth, pool, lease, _, _ = replay_setup(tmp_path)
        instance = truth.query("rc72_browser_instance", browser_instance_id="BROWSER-R1")[0]
        replaced_instance = dict(instance)
        replaced_instance.pop("artifact_type", None)
        replaced_instance["artifact_version"] += 1
        replaced_instance["cdp_endpoint"] = cdp_endpoint
        truth.append_atomic("RC72_BROWSER_INSTANCE_UPSERTED", replaced_instance)

        candidate = truth.query("rc72_journey_candidate", candidate_id="JC-1")[0]
        updated = dict(candidate)
        updated.pop("artifact_type", None)
        updated["artifact_version"] += 1
        updated["case_id"] = "TC-R1"
        navigate = dict(candidate["steps"][0], url=origin + "/config")
        navigate["wait_semantics"] = "network-idle"
        click = dict(candidate["steps"][1])
        click.update(
            source_step_id="S-POST", sequence=2, action_type="CLICK",
            url=origin + "/config", element_ref="css:#save",
            wait_semantics="network-idle",
        )
        click.pop("oracle_ref", None)
        assertion = dict(candidate["steps"][1])
        assertion.update(
            sequence=3, url=origin + "/config", element_ref="css:#toast",
            oracle_ref="oracle://server-saved",
        )
        network = dict(assertion, source_step_id="S-HTTP", sequence=4,
                       oracle_ref="oracle://real-post", wait_semantics="none")
        updated["steps"] = [navigate, click, assertion, network]
        truth.append_atomic("RC72_JOURNEY_CANDIDATE_UPSERTED", updated)

        def resolver(ref, kind, context):
            if kind == "oracle" and ref == "oracle://server-saved":
                return {"type": "text_equals", "element_ref": "css:#toast",
                        "expected": "Saved on server"}
            if kind == "oracle" and ref == "oracle://real-post":
                return {"type": "network_status", "method": "POST",
                        "url": origin + "/api/save", "status": 200,
                        "trigger_source_step_id": "S-POST"}
            return None

        adapter = JourneyPlaywrightAdapter(
            browser_pool=pool,
            evidence_root=tmp_path / "actual-browser-evidence",
            reference_resolver=resolver,
        )
        service = JourneyReplayService(
            truth, release_id="RC7.2", browser_pool=pool, adapter=adapter)
        result = service.replay(
            replay_id="REAL-CHROMIUM-1", candidate_id="JC-1",
            workitem_id="WI-R1", attempt_id="ATT-R1", worker_id="WORKER-R1",
            session_id="SESSION-R1", browser_lease_id=lease.browser_lease_id)
        assert result.state.value == "PASSED"
        receipt = truth.query("rc72_journey_replay", replay_id="REAL-CHROMIUM-1")[0]
        assert receipt["executed_step_count"] == 4
        assert receipt["field_verified"] is False
        steps = sorted(
            truth.query("rc72_journey_replay_step", replay_id="REAL-CHROMIUM-1"),
            key=lambda row: row["sequence"],
        )
        assert [row["status"] for row in steps] == ["PASSED"] * 4
        for seq in range(1, 5):
            folder = tmp_path / "actual-browser-evidence" / "REAL-CHROMIUM-1" / ("step-%04d" % seq)
            assert (folder / "screen.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            assert (folder / "actual.json").is_file()
        # A SPA response can arrive after click() returned. The authoritative
        # HTTP Oracle Actual stores the response under the source click's
        # request-origin, not whatever later step happened to receive it.
        observed = json.loads(
            (tmp_path / "actual-browser-evidence" / "REAL-CHROMIUM-1" /
             "step-0004" / "actual.json").read_text()
        )
        proof = observed["network_oracle_proof"]
        assert proof["method"] == "POST"
        assert proof["url"] == origin + "/api/save"
        assert proof["status"] == 200
        assert proof["source_step_id"] == "S-POST"
        assert proof["action_type"] == "CLICK"
        assert "never-leak" not in json.dumps(observed)
        assert (tmp_path / "r1.jsonl").is_file()
    finally:
        _export_ci_evidence(tmp_path, "real-browser-replay")
        if adapter is not None:
            adapter.close()
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)
        server.shutdown()
        server.server_close()
        thread.join(timeout=8)



def test_real_chromium_cdp_teaching_captures_dom_event_network_and_png(tmp_path: Path):
    """A scripted user click through live Chrome exercises the real recorder.

    This is engineering CDP capture, NOT a human-in-bank or BSK Field proof.
    """
    from rc7_runtime.rc72_journey_cdp_capture import JourneyCDPTeachingRecorder
    from rc7_runtime.rc72_journey_compiler import JourneyCompiler
    from test_rc72_phase9_journey_teaching_capture_contract import _setup as teaching_setup

    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalSUT)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = "http://127.0.0.1:%d" % server.server_address[1]
    cdp_port = _reserved_port()
    endpoint = "http://127.0.0.1:%d" % cdp_port
    process = None
    recorder = None
    try:
        with sync_playwright() as playwright:
            binary = Path(playwright.chromium.executable_path)
            assert binary.is_file(), "REAL_CHROMIUM_BINARY_REQUIRED"
        process = subprocess.Popen([
            str(binary), "--headless=new", "--no-sandbox",
            "--disable-dev-shm-usage", "--disable-gpu",
            "--no-first-run", "--no-default-browser-check",
            "--remote-allow-origins=*", "--remote-debugging-port=%d" % cdp_port,
            "--user-data-dir=%s" % (tmp_path / "teaching-chrome-profile"),
            "--app=" + origin + "/config",
        ], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ready = False
        for _ in range(100):
            if process.poll() is not None:
                raise AssertionError("REAL_TEACHING_CHROMIUM_EXITED")
            try:
                with urlopen(endpoint + "/json/list", timeout=0.5) as response:
                    targets = json.loads(response.read().decode("utf-8"))
                ready = any(row.get("type") == "page"
                            and row.get("url", "").startswith(origin + "/config")
                            for row in targets)
                if ready:
                    break
            except Exception:
                pass
            time.sleep(0.2)
        assert ready, "REAL_TEACHING_CDP_PAGE_NOT_READY"

        truth, teaching, pool, lease = teaching_setup(tmp_path)
        instance = truth.query("rc72_browser_instance", browser_instance_id="BROWSER-1")[0]
        revised = dict(instance)
        revised.pop("artifact_type", None)
        revised["artifact_version"] += 1
        revised["cdp_endpoint"] = endpoint
        truth.append_atomic("RC72_BROWSER_INSTANCE_UPSERTED", revised)

        recorder = JourneyCDPTeachingRecorder(
            teaching=teaching, evidence_root=tmp_path / "real-teaching-evidence")
        recorder.begin(
            recording_id="REAL-TEACHING-1",
            mission_id="M-1", release_batch_id="RB-1",
            requirement_id="REQ-1", sst_id="SST-1", obligation_id="TO-1",
            workitem_id="WI-1", attempt_id="ATT-1", worker_id="WORKER-1",
            session_id="SESSION-1", browser_lease_id=lease.browser_lease_id,
            human_operator_ref="human://ci-scripted-click-not-bank-signature",
            auth_asset_ref="auth://4a/session-asset",
        )
        assert recorder.page is not None
        # FG17: a successful click is NOT proof that CDP delivered the SPA
        # fetch response. Fence on the actual POST response BEFORE taking the
        # teaching action's network snapshot; still verify recorder evidence.
        # This does not skip an HTTP Oracle or fabricate recorded responses.
        with recorder.page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and response.url.split("?", 1)[0] == origin + "/api/save"
            ),
            timeout=15000,
        ) as save_response:
            recorder.page.locator("#save").click(timeout=10000)
        observed_response = save_response.value
        assert observed_response.status == 200, (
            "FG17_SUT_POST_RESPONSE_NOT_200: " + str(observed_response.status)
        )
        # networkidle may already have fired before this XHR starts; it is
        # not a fence for the SPA promise continuation. Wait for the exact
        # business Oracle, without sleeping or weakening the expected value.
        try:
            expect(recorder.page.locator("#toast")).to_have_text(
                re.compile(r"^Saved on server$"),
                timeout=15000, use_inner_text=True)
        except AssertionError as exc:
            raise AssertionError("FG17_SUT_TOAST_ORACLE_NOT_MET") from exc
        observed_events = []
        for _ in range(30):
            observed_events = recorder.poll(page_role="CONFIGURATION")
            if observed_events:
                break
            time.sleep(0.05)
        assert observed_events == ["REAL-TEACHING-1:2"]
        recorder.record_assertion(
            page_role="CONFIGURATION", element_ref="css:#toast",
            oracle_ref="oracle://server-saved",
        )
        result = recorder.finish()
        recorder = None
        assert result.state.value == "CAPTURED"

        steps = sorted(truth.query(
            "rc72_journey_capture_step", recording_id="REAL-TEACHING-1"),
            key=lambda row: row["sequence"])
        assert [step["action_type"] for step in steps] == [
            "NAVIGATE", "CLICK", "ASSERT"]
        assert steps[1]["element_ref"] == "css:#save"
        assert steps[1]["page_role"] == "CONFIGURATION"
        for row in steps:
            assert row["page_state_ref"].startswith("file://")
            assert row["dom_ref"].startswith("file://")
            assert row["screenshot_ref"].startswith("file://")
            assert _local_evidence_path(row["screenshot_ref"]).read_bytes().startswith(
                b"\x89PNG\r\n\x1a\n")
        response_path = _local_evidence_path(steps[1]["network_refs"][0])
        responses = json.loads(response_path.read_text())["responses"]
        assert any(item["method"] == "POST" and
                   item["url"] == origin + "/api/save" and
                   item["status"] == 200 for item in responses), (
                       "FG17_RECORDER_NETWORK_RESPONSE_NOT_ATTACHED_TO_CLICK: "
                       + repr(responses)
                   )
        assert "never-leak" not in response_path.read_text()

        compiled = JourneyCompiler(truth, release_id="RC7.2").compile(
            candidate_id="REAL-TEACHING-CANDIDATE",
            recording_id="REAL-TEACHING-1")
        assert compiled.state.value == "COMPILED_CANDIDATE"
        candidate = truth.query(
            "rc72_journey_candidate", candidate_id="REAL-TEACHING-CANDIDATE")[0]
        assert candidate["case_id"] == "TC-1"
        assert candidate["official"] is False
        assert candidate["executable"] is False
        assert not truth.query("rc72_official_journey_asset")
    finally:
        _export_ci_evidence(tmp_path, "real-browser-teaching")
        if recorder is not None:
            recorder.stop()
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)
        server.shutdown()
        server.server_close()
        thread.join(timeout=8)
