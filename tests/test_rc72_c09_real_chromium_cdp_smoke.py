"""C09 real Chromium CDP plus HTTP application smoke, not a bank Field proof.

No FakeBrowser or synthetic actual:// references. This validates actual CDP,
HTTP POST, DOM business Oracle, PNG bytes and canonical R1 replay receipts.
"""
from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

from rc7_runtime.rc72_journey_playwright import JourneyPlaywrightAdapter
from rc7_runtime.rc72_journey_replay import JourneyReplayService
from test_rc72_phase9_journey_replay_contract import _setup as replay_setup


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
        observed = json.loads(
            (tmp_path / "actual-browser-evidence" / "REAL-CHROMIUM-1" /
             "step-0002" / "actual.json").read_text()
        )
        assert any(row["method"] == "POST"
                   and row["url"] == origin + "/api/save"
                   and row["status"] == 200
                   for row in observed["response_metadata"])
        assert "never-leak" not in json.dumps(observed)
        assert (tmp_path / "r1.jsonl").is_file()
    finally:
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
