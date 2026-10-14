import json

from rc6_release.mcp_server import handle


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
