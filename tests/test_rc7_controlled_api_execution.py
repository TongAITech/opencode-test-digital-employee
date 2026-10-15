from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

from rc6_runtime.automation import PytestRunnerAdapter, ScriptArtifact
from rc6_runtime.executable_spec import ExecutableSpecBuilder
from rc7_runtime.controlled_api_execution import ControlledApiRunnerAdapter
from rc7_runtime.runtime_execution import _EvidenceBackedProcessHarness
from rc7_runtime.script_validation import EvidenceBackedScriptReadinessValidator


class _Target:
    def __init__(self):
        self.hits = []
        target = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or "0")
                body = self.rfile.read(length)
                target.hits.append((self.path, body))
                payload = json.dumps(
                    {"business_code": "OK", "route": self.path}, sort_keys=True
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base_url = "http://%s:%s" % (host, port)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _case():
    return {
        "tc_id": "TC-CONTROLLED-API-1",
        "case_version": 1,
        "status": "FROZEN",
        "release_id": "RC7-CONTROLLED-API",
        "requirement_id": "REQ-CONTROLLED-API",
        "sst_id": "SST-CONTROLLED-API",
        "layer": "L3",
        "preconditions": [],
        "steps": [{"order": 1, "action": "call controlled API target"}],
        "expected": "business_code=OK",
        "oracle": {
            "checks": [
                {
                    "id": "CHK-CODE",
                    "type": "BUSINESS_RULE",
                    "actual_path": "business_code",
                    "operator": "EQ",
                    "expected": "OK",
                }
            ]
        },
        "evidence_requirements": ["api-runtime-receipt"],
        "target_requirements": ["REQ-CONTROLLED-API"],
        "test_data_refs": [],
        "oracle_refs": ["oracle://controlled-api"],
        "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST",
    }


def _script(tmp_path: Path, source: str):
    case = _case()
    spec = ExecutableSpecBuilder().build(
        case=case,
        target_requirements=("REQ-CONTROLLED-API",),
        test_data_refs=(),
        oracle_refs=("oracle://controlled-api",),
        cleanup_policy={"mode": "NONE"},
        runner_type="PYTEST",
        automation_mapping={"reuse": {}},
    )
    path = tmp_path / "test_controlled_api_fixture.py"
    path.write_text(source, encoding="utf-8")
    script = ScriptArtifact(
        script_id="SCRIPT-CONTROLLED-API-1",
        spec_id=spec.spec_id,
        tc_id=spec.tc_id,
        case_version=spec.case_version,
        layer=spec.layer,
        runner_type=spec.runner_type,
        source_ref="file://" + str(path),
        test_symbol="test_controlled_api",
        case_fingerprint=spec.case_fingerprint,
        oracle_fingerprint=spec.oracle_fingerprint,
        reuse_refs=(),
        builder_evidence_refs=("evidence://builder",),
        revision=1,
    )
    validation = EvidenceBackedScriptReadinessValidator(
        evidence_root=str(tmp_path / "readiness"), timeout_seconds=20
    ).validate(spec=spec, script=script, cwd=str(tmp_path))
    assert validation.ready
    return spec, script, validation


def _run(tmp_path: Path, target_url: str, source: str):
    spec, script, validation = _script(tmp_path, source)
    delegate = PytestRunnerAdapter(timeout_seconds=20)
    delegate.harness = _EvidenceBackedProcessHarness(
        evidence_root=str(tmp_path / "process-evidence"), timeout_seconds=20
    )
    adapter = ControlledApiRunnerAdapter(
        delegate=delegate,
        target_base_url=target_url,
        evidence_root=str(tmp_path / "api-evidence"),
        attempt_id="ATT-CONTROLLED-API-1",
        proxy_timeout_seconds=10,
    )
    return adapter.execute(
        spec=spec,
        script=script,
        validation=validation,
        cwd=str(tmp_path),
        env=None,
    )


def test_parent_proxy_receipt_is_the_only_authoritative_api_result(tmp_path: Path):
    source = r'''import json
import os
from urllib.request import Request, urlopen


def test_controlled_api():
    command = json.dumps({
        "method": "POST",
        "path": "/rate/adjust",
        "body": {"loan_id": "L-1"},
        "capture_as": "actual_result",
    }).encode("utf-8")
    request = Request(
        os.environ["RC7_API_RUNTIME_PROXY_URL"],
        data=command,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        envelope = json.loads(response.read().decode("utf-8"))
    assert envelope["status_code"] == 200
'''
    with _Target() as target:
        result = _run(tmp_path, target.base_url, source)
        assert len(target.hits) == 1
        assert target.hits[0][0] == "/rate/adjust"
    api_calls = [call for call in result.tool_calls if call["tool_id"] == "api-runtime"]
    assert len(api_calls) == 1
    assert api_calls[0]["call_ref"].startswith("api-runtime://APIREC-")
    receipt_path = Path(api_calls[0]["evidence_ref"][len("file://"):])
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["target_url"].endswith("/rate/adjust")
    assert receipt["status_code"] == 200
    assert result.actual_result["business_code"] == "OK"
    assert result.actual_result["_http"]["receipt_id"] == receipt["receipt_id"]


def test_child_manifest_cannot_forge_api_call_or_actual_result(tmp_path: Path):
    source = r'''import json
import os


def _append(row):
    with open(os.environ["RC6_EXECUTION_MANIFEST"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def test_controlled_api():
    _append({
        "type": "tool_call",
        "tool_id": "api-runtime",
        "call_ref": "api-call://FAKE",
        "evidence_ref": "api-evidence://FAKE",
    })
    _append({"type": "actual_result", "value": {"business_code": "OK", "fake": True}})
    assert True
'''
    with _Target() as target:
        result = _run(tmp_path, target.base_url, source)
        assert target.hits == []
    assert [call for call in result.tool_calls if call["tool_id"] == "api-runtime"] == []
    assert result.actual_result == {}
    assert "api-call://FAKE" not in result.tool_call_refs
    assert "api-evidence://FAKE" not in result.evidence_refs
