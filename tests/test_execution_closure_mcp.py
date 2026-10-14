import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rc6_release.mcp_server import handle


REPO_ROOT = Path(__file__).resolve().parents[1]


def call(name, arguments):
    return handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})


def body(response):
    return json.loads(response["result"]["content"][0]["text"])


def frozen_case():
    return {
        "tc_id": "TC-L3-MCP-1", "case_version": 1, "release_id": "BLOAN-PF1.2.0",
        "requirement_id": "STBB19-320", "sst_id": "STB915-7489", "layer": "L3",
        "preconditions": [], "test_data": {}, "steps": ["invoke API"],
        "expected": "code 0000", "oracle": {"type": "field_equals", "field": "code", "value": "0000"},
        "evidence_requirements": ["request", "response"], "status": "FROZEN",
    }


def test_execution_closure_tools_are_exposed():
    response = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert {
        "executable_spec_build", "automation_reuse_resolve", "script_build", "script_validate",
        "runner_execute", "failure_diagnose", "recovery_decide", "recovery_execute", "execution_convergence",
    }.issubset(names)


def test_automation_engineer_builds_spec_into_canonical_r1(monkeypatch, tmp_path):
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(tmp_path / "state"))
    worker = body(call("worker_issue", {"role": "AUTOMATION_ENGINEER", "phase": "AUTOMATION", "layer": None, "generation": 0, "session_id": "dsh://worker/automation-1"}))
    lease = body(call("lease_issue", {"worker_id": worker["worker_id"], "scope_ref": "case:TC-L3-MCP-1@1", "allowed_artifact_types": ["executable_test_spec", "automation_mapping", "script_artifact", "script_validation", "evidence"], "allowed_tools": []}))
    response = call("executable_spec_build", {
        "worker_id": worker["worker_id"], "lease_id": lease["lease_id"], "case": frozen_case(),
        "target_requirements": ["TARGET-QUALIFIED", "api-runtime:READY"], "test_data_refs": [],
        "oracle_refs": ["oracle://TC-L3-MCP-1@1"], "cleanup_policy": {"mode": "NONE"},
        "runner_type": "PYTEST", "automation_mapping": {"reuse": {}},
    })
    assert not response["result"].get("isError")
    built = body(response)
    assert built["spec"]["status"] == "EXECUTABLE_SPEC"
    assert built["spec"]["oracle_fingerprint"]
    query = body(call("truth_query", {"artifact_type": "executable_test_spec", "filters": {"tc_id": "TC-L3-MCP-1"}, "limit": 10}))
    assert query["total"] == 1
    assert query["items"][0]["spec_id"] == built["spec"]["spec_id"]


def test_coordinator_cannot_use_professional_executable_spec_surface(monkeypatch, tmp_path):
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(tmp_path / "state"))
    worker = body(call("worker_issue", {"role": "COORDINATOR", "phase": "CASE_FREEZE", "layer": None, "generation": 0, "session_id": "dsh://coord/A"}))
    lease = body(call("lease_issue", {"worker_id": worker["worker_id"], "scope_ref": "mission:M1", "allowed_artifact_types": ["mission_checkpoint"], "allowed_tools": []}))
    response = call("executable_spec_build", {
        "worker_id": worker["worker_id"], "lease_id": lease["lease_id"], "case": frozen_case(),
        "target_requirements": ["TARGET-QUALIFIED"], "test_data_refs": [], "oracle_refs": ["oracle://1"],
        "cleanup_policy": {"mode": "NONE"}, "runner_type": "PYTEST", "automation_mapping": {},
    })
    assert response["result"]["isError"] is True
    assert "FORBIDDEN" in response["result"]["content"][0]["text"]


class _McpApiHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        payload = {"code": "0000", "business": "OK"} if self.path == "/apply" else {"code": "4040", "business": "NOT_FOUND"}
        status = 200 if self.path == "/apply" else 404
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def test_real_l3_process_executes_end_to_end_through_mcp_and_r1(monkeypatch, tmp_path):
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(tmp_path / "state"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _McpApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = "http://127.0.0.1:%d" % server.server_address[1]
        helper = tmp_path / "api_client.py"
        helper.write_text("from urllib.request import urlopen\n", encoding="utf-8")
        route_file = tmp_path / "route.txt"
        route_file.write_text("/apply", encoding="utf-8")

        automation = body(call("worker_issue", {
            "role": "AUTOMATION_ENGINEER", "phase": "AUTOMATION", "layer": None,
            "generation": 0, "session_id": "dsh://automation/mcp-vertical",
        }))
        automation_lease = body(call("lease_issue", {
            "worker_id": automation["worker_id"], "scope_ref": "case:TC-L3-MCP-1@1",
            "allowed_artifact_types": ["executable_test_spec", "automation_mapping", "script_artifact", "script_validation", "evidence"],
            "allowed_tools": [],
        }))
        common = {"worker_id": automation["worker_id"], "lease_id": automation_lease["lease_id"]}
        spec_result = body(call("executable_spec_build", {
            **common, "case": frozen_case(), "target_requirements": ["TARGET-MCP-L3", "api-runtime:READY"],
            "test_data_refs": [], "oracle_refs": ["oracle://TC-L3-MCP-1@1"],
            "cleanup_policy": {"mode": "NONE"}, "runner_type": "PYTEST", "automation_mapping": {"reuse_required": True},
        }))
        spec = spec_result["spec"]
        resolution_result = body(call("automation_reuse_resolve", {
            **common, "spec": spec, "search_roots": [str(tmp_path)], "extra_keywords": ["api", "http"],
        }))
        assert any(item["category"] == "api_client" for item in resolution_result["resolution"]["assets"])

        script_source = (
            "import json\n"
            "import os\n"
            "from pathlib import Path\n"
            "from urllib.request import urlopen\n"
            "from rc6_runtime.runner_manifest import record_actual_result, record_tool_call\n\n"
            "def test_mcp_real_l3():\n"
            "    route = Path(os.environ['RC6_ROUTE_FILE']).read_text(encoding='utf-8').strip()\n"
            "    with urlopen(os.environ['RC6_BASE_URL'] + route, timeout=5) as response:\n"
            "        body = json.loads(response.read().decode('utf-8'))\n"
            "        status = int(response.status)\n"
            "    record_tool_call('api-runtime', 'http-call://mcp-l3', 'http-evidence://mcp-l3')\n"
            "    record_actual_result({'http_status': status, 'code': body.get('code'), 'route': route})\n"
            "    assert status == 200\n"
        )
        script_result = body(call("script_build", {
            **common, "spec": spec, "resolution": resolution_result["resolution"],
            "source_content": script_source, "file_name": "test_mcp_real_l3.py", "test_symbol": "test_mcp_real_l3",
            "builder_evidence_refs": ["builder://mcp-real-l3"], "revision": 1,
        }))
        script = script_result["script"]
        env = {
            "RC6_BASE_URL": base_url,
            "RC6_ROUTE_FILE": str(route_file),
            "PYTHONPATH": str(REPO_ROOT) + (os.pathsep + os.environ.get("PYTHONPATH", "") if os.environ.get("PYTHONPATH") else ""),
        }
        validation_result = body(call("script_validate", {
            **common, "spec": spec, "script": script, "cwd": str(tmp_path), "env": env,
        }))
        validation = validation_result["validation"]
        assert validation["status"] == "SCRIPT_READY"

        executor = body(call("worker_issue", {
            "role": "L3_EXECUTE", "phase": "EXECUTION", "layer": "L3",
            "generation": 0, "session_id": "dsh://l3/mcp-vertical",
        }))
        exec_lease = body(call("lease_issue", {
            "worker_id": executor["worker_id"], "scope_ref": "case:TC-L3-MCP-1@1",
            "allowed_artifact_types": ["execution_attempt", "assertion", "evidence", "coverage_observation"],
            "allowed_tools": ["api-runtime"],
        }))
        call("capability_discover", {"tool_id": "api-runtime", "location": "stdlib://urllib"})
        call("capability_mark_executable", {"tool_id": "api-runtime", "exec_ref": "python://urllib.request"})
        call("capability_register", {"tool_id": "api-runtime", "registration_ref": "runner-manifest://api-runtime"})
        call("capability_bind_worker", {"tool_id": "api-runtime", "worker_id": executor["worker_id"], "visible": True, "permitted": True})
        call("capability_record_probe", {"tool_id": "api-runtime", "success": True, "tool_call_ref": "probe://api-runtime", "evidence_ref": "probe-evidence://api-runtime"})
        call("capability_target_ready", {"tool_id": "api-runtime", "target_id": "TARGET-MCP-L3", "evidence_ref": "target-evidence://mcp-l3"})

        execution_result = body(call("runner_execute", {
            "worker_id": executor["worker_id"], "lease_id": exec_lease["lease_id"],
            "case": frozen_case(), "spec": spec, "script": script, "validation": validation,
            "prepared_attempt": {
                "status": "PREPARED", "attempt_id": "ATT-MCP-L3-1", "tc_id": "TC-L3-MCP-1", "case_version": 1,
                "target_id": "TARGET-MCP-L3", "precondition_evidence": ["precondition://mcp-target"],
                "initial_state_bindings": {}, "input_data_bindings": {}, "binding_evidence": ["binding://mcp-none"],
                "cleanup_policy": {"mode": "NONE"},
                "oracle_snapshot": {"type": "field_equals", "field": "code", "value": "0000"},
            },
            "cwd": str(tmp_path), "env": env,
        }))
        assert execution_result["execution"]["status"] == "PASS"
        assert execution_result["execution"]["integrity_passed"] is True
        assert execution_result["execution"]["actual_result"]["code"] == "0000"
        assert "http-call://mcp-l3" in execution_result["execution"]["tool_call_refs"]

        attempts = body(call("truth_query", {
            "artifact_type": "execution_attempt", "filters": {"attempt_id": "ATT-MCP-L3-1"}, "limit": 10,
        }))
        assertions = body(call("truth_query", {
            "artifact_type": "assertion", "filters": {"attempt_id": "ATT-MCP-L3-1"}, "limit": 10,
        }))
        evidence = body(call("truth_query", {
            "artifact_type": "evidence", "filters": {"attempt_id": "ATT-MCP-L3-1"}, "limit": 50,
        }))
        assert attempts["total"] == 1 and attempts["items"][0]["status"] == "PASS"
        assert assertions["total"] == 1 and assertions["items"][0]["passed"] is True
        assert evidence["total"] >= 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
