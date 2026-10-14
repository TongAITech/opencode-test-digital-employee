from __future__ import annotations

import json

from rc6_release.mcp_server import handle
from rc6_release.recovery_adapter_registry import clear_recovery_adapters, register_recovery_adapter
from rc6_runtime.recovery_adapters import RouteRecoveryAdapter


RELEASE = "BLOAN-PF1.2.0"
TARGET = "TARGET-MCP-RECOVERY"


def call(name, arguments):
    return handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})


def body(response):
    return json.loads(response["result"]["content"][0]["text"])


def error_text(response):
    assert response["result"]["isError"] is True
    return response["result"]["content"][0]["text"]


def context():
    return {
        "attempt_id": "ATT-REC-1", "tc_id": "TC-L3-REC-1", "case_version": 1,
        "target_id": TARGET, "layer": "L3", "execution_status": "FAIL",
        "preparation_verified": True, "real_action_executed": True, "assertion_failed": True,
        "execution_evidence_refs": ["evidence://execution/ATT-REC-1"],
        "route_verified": False, "http_status": 404, "business_error_code": "ROUTE_NOT_FOUND",
        "route": "/wrong", "assertion_identity": "assertion://ATT-REC-1",
    }


def diagnosis():
    return {
        "diagnosis_id": "DIAG-REC-1", "attempt_id": "ATT-REC-1", "failure_class": "ROUTE",
        "evidence_refs": ["evidence://execution/ATT-REC-1", "evidence://route/mismatch"],
        "cat_required": False, "cat_queried": False,
        "rationale": "authoritative route binding mismatch", "classifier_ref": "classifier://route/v1",
        "failure_signature": {
            "signature_id": "FSIG-REC-1", "exception_type": None, "root_stack_frame": None,
            "http_status": 404, "business_error_code": "ROUTE_NOT_FOUND", "route": "/wrong",
            "assertion_identity": "assertion://ATT-REC-1",
        },
        "root_cause_candidate": None,
    }


def decision():
    return {
        "diagnosis_id": "DIAG-REC-1", "attempt_id": "ATT-REC-1", "action": "RECONCILE_ROUTE_BINDING",
        "retry_allowed": True, "reprepare_allowed": False, "terminal": False,
        "next_attempt_id": "ATT-REC-2", "reason": "FAILURE_CLASS:ROUTE",
    }


def history():
    return [{
        "attempt_id": "ATT-REC-1", "parent_attempt_id": None, "tc_id": "TC-L3-REC-1",
        "case_version": 1, "target_id": TARGET, "layer": "L3", "status": "FAIL",
        "evidence_refs": ["evidence://execution/ATT-REC-1"], "recorded_at": 1,
        "failure_signature_id": "FSIG-REC-1",
    }]


def recovery_worker_and_lease():
    worker = body(call("worker_issue", {
        "role": "FAILURE_DIAGNOSTIC", "phase": "DIAGNOSIS", "layer": None,
        "generation": 0, "session_id": "dsh://diag/recovery-mcp",
    }))
    lease = body(call("lease_issue", {
        "worker_id": worker["worker_id"], "scope_ref": "attempt:ATT-REC-1",
        "allowed_artifact_types": ["failure_diagnosis", "recovery_decision", "recovery_action", "evidence", "defect"],
        "allowed_tools": [],
    }))
    return worker, lease


def test_mcp_recovery_fails_closed_when_verified_adapter_is_not_bound(monkeypatch, tmp_path):
    state = tmp_path / "state"
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(state))
    clear_recovery_adapters(state)
    worker, lease = recovery_worker_and_lease()
    response = call("recovery_execute", {
        "worker_id": worker["worker_id"], "lease_id": lease["lease_id"], "release_id": RELEASE,
        "context": context(), "diagnosis": diagnosis(), "decision": decision(), "history": history(),
        "budgets": {"max_route_repairs": 2},
    })
    assert "RECOVERY_ADAPTER_NOT_BOUND:RECONCILE_ROUTE_BINDING" in error_text(response)


def test_mcp_recovery_invokes_registered_real_route_adapter_and_records_new_attempt(monkeypatch, tmp_path):
    state = tmp_path / "state"
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(state))
    clear_recovery_adapters(state)
    route_file = tmp_path / "route.txt"
    route_file.write_text("/wrong", encoding="utf-8")

    def reconcile(_context, _diagnosis):
        route_file.write_text("/apply", encoding="utf-8")
        return {"binding_ref": "cfg-data/apply", "evidence_ref": "route-evidence://authoritative/apply"}

    register_recovery_adapter(state, RouteRecoveryAdapter(
        reconcile=reconcile,
        verify=lambda result: route_file.read_text(encoding="utf-8").strip() == "/apply",
    ))
    worker, lease = recovery_worker_and_lease()
    result = body(call("recovery_execute", {
        "worker_id": worker["worker_id"], "lease_id": lease["lease_id"], "release_id": RELEASE,
        "context": context(), "diagnosis": diagnosis(), "decision": decision(), "history": history(),
        "budgets": {"max_route_repairs": 2},
    }))
    assert route_file.read_text(encoding="utf-8").strip() == "/apply"
    assert result["recovery_action"]["status"] == "RECOVERY_EXECUTED"
    assert result["recovery_action"]["next_attempt_id"] == "ATT-REC-2"
    assert "route-binding://cfg-data/apply" in result["recovery_action"]["output_refs"]
    assert len(result["attempt_history"]) == 2
    assert result["attempt_history"][1]["parent_attempt_id"] == "ATT-REC-1"

    rows = body(call("truth_query", {
        "artifact_type": "recovery_action", "filters": {"release_id": RELEASE}, "limit": 10,
    }))
    assert rows["total"] == 1
    assert rows["items"][0]["next_attempt_id"] == "ATT-REC-2"
    clear_recovery_adapters(state)
