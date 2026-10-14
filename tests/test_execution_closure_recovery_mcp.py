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


def recovery_worker_and_lease(allowed=None):
    worker = body(call("worker_issue", {
        "role": "FAILURE_DIAGNOSTIC", "phase": "DIAGNOSIS", "layer": None,
        "generation": 0, "session_id": "dsh://diag/recovery-mcp",
    }))
    lease = body(call("lease_issue", {
        "worker_id": worker["worker_id"], "scope_ref": "attempt:ATT-REC-1",
        "allowed_artifact_types": allowed or [
            "failure_diagnosis", "recovery_decision", "recovery_action", "execution_convergence", "evidence", "defect"
        ],
        "allowed_tools": [],
    }))
    return worker, lease


def record_product_failure_attempt():
    worker = body(call("worker_issue", {
        "role": "L3_EXECUTE", "phase": "EXECUTION", "layer": "L3",
        "generation": 0, "session_id": "dsh://l3/product-attempt",
    }))
    lease = body(call("lease_issue", {
        "worker_id": worker["worker_id"], "scope_ref": "case:TC-L3-REC-1@1",
        "allowed_artifact_types": ["execution_attempt", "assertion", "evidence"], "allowed_tools": [],
    }))
    response = call("artifact_record", {
        "worker_id": worker["worker_id"], "lease_id": lease["lease_id"],
        "authorization_artifact_type": "execution_attempt",
        "payload": {
            "attempt_id": "ATT-REC-1", "release_id": RELEASE, "requirement_id": "STBB19-320",
            "sst_id": "STB915-7489", "tc_id": "TC-L3-REC-1", "case_version": 1,
            "target_id": TARGET, "layer": "L3", "status": "FAIL",
            "actual_result": {"http_status": 200, "code": "9999"},
            "tool_call_refs": ["http-call://product/ATT-REC-1"],
            "evidence_refs": ["evidence://execution/ATT-REC-1"],
        },
    })
    assert not response["result"].get("isError")


def product_context():
    return {
        "attempt_id": "ATT-REC-1", "tc_id": "TC-L3-REC-1", "case_version": 1,
        "target_id": TARGET, "layer": "L3", "execution_status": "FAIL",
        "preparation_verified": True, "real_action_executed": True, "assertion_failed": True,
        "execution_evidence_refs": ["evidence://execution/ATT-REC-1", "evidence://oracle/ATT-REC-1"],
        "case_oracle_verified": True, "executable_spec_verified": True, "script_validated": True,
        "data_verified": True, "auth_verified": True, "route_verified": True, "tool_verified": True,
        "environment_verified": True, "dependency_verified": True,
        "http_status": 200, "business_error_code": "9999", "route": "/apply",
        "assertion_identity": "assertion://ATT-REC-1",
    }


def product_diagnosis():
    return {
        "diagnosis_id": "DIAG-PROD-1", "attempt_id": "ATT-REC-1", "failure_class": "PRODUCT",
        "evidence_refs": ["evidence://execution/ATT-REC-1", "evidence://oracle/ATT-REC-1"],
        "cat_required": False, "cat_queried": False,
        "rationale": "all test-side ownership candidates excluded", "classifier_ref": "classifier://product/v1",
        "failure_signature": {
            "signature_id": "FSIG-PROD-1", "exception_type": None, "root_stack_frame": None,
            "http_status": 200, "business_error_code": "9999", "route": "/apply",
            "assertion_identity": "assertion://ATT-REC-1",
        },
        "root_cause_candidate": {
            "candidate_id": "RCA-PROD-1", "symbol": "CfgDataService.apply",
            "call_path": ["CfgDataController.apply", "CfgDataService.apply"],
            "git_change_refs": ["git-diff://cfg-data/product"],
            "requirement_refs": ["STBB19-320", "STB915-7489"],
            "evidence_refs": ["codegraph://CfgDataService.apply", "git-diff://cfg-data/product"],
            "confidence": 0.97,
        },
    }


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


def test_product_terminal_recovery_creates_r1_defect_candidate_without_adapter(monkeypatch, tmp_path):
    state = tmp_path / "state"
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(state))
    clear_recovery_adapters(state)
    record_product_failure_attempt()
    worker, lease = recovery_worker_and_lease()
    result = body(call("recovery_execute", {
        "worker_id": worker["worker_id"], "lease_id": lease["lease_id"], "release_id": RELEASE,
        "context": product_context(), "diagnosis": product_diagnosis(),
        "decision": {
            "diagnosis_id": "DIAG-PROD-1", "attempt_id": "ATT-REC-1", "action": "PRODUCT_DEFECT",
            "retry_allowed": False, "reprepare_allowed": False, "terminal": True,
            "next_attempt_id": None, "reason": "EVIDENCE_BACKED_PRODUCT_FAILURE_TERMINAL",
        },
        "history": history(), "budgets": {},
    }))
    assert result["recovery_action"]["terminal_status"] == "PRODUCT_DEFECT_CONFIRMED"
    assert result["recovery_action"]["next_attempt_id"] is None
    candidate = result["defect_candidate"]
    assert candidate["defect"]["status"] == "CANDIDATE"
    assert candidate["defect"]["attempt_id"] == "ATT-REC-1"
    assert candidate["defect"]["defect_candidate_ref"].startswith("defect-candidate://ATT-REC-1/FSIG-PROD-1")
    rows = body(call("truth_query", {"artifact_type": "defect", "filters": {"attempt_id": "ATT-REC-1"}, "limit": 10}))
    assert rows["total"] == 1
    assert rows["items"][0]["status"] == "CANDIDATE"
    assert len(result["attempt_history"]) == 1


def test_execution_convergence_requires_failure_diagnostic_authority(monkeypatch, tmp_path):
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(tmp_path / "state"))
    coordinator = body(call("worker_issue", {
        "role": "COORDINATOR", "phase": "EXECUTION_INTEGRITY", "layer": None,
        "generation": 0, "session_id": "dsh://coord/convergence",
    }))
    coordinator_lease = body(call("lease_issue", {
        "worker_id": coordinator["worker_id"], "scope_ref": "mission:M1",
        "allowed_artifact_types": ["mission_checkpoint"], "allowed_tools": [],
    }))
    denied = call("execution_convergence", {
        "worker_id": coordinator["worker_id"], "lease_id": coordinator_lease["lease_id"],
        "release_id": RELEASE, "attempt_id": "ATT-REC-1", "history": history(),
        "pass_observed": True, "evidence_refs": ["evidence://pass/ATT-REC-1"],
    })
    assert "FORBIDDEN" in error_text(denied)

    worker, lease = recovery_worker_and_lease(["execution_convergence"])
    allowed = body(call("execution_convergence", {
        "worker_id": worker["worker_id"], "lease_id": lease["lease_id"],
        "release_id": RELEASE, "attempt_id": "ATT-REC-1", "history": history(),
        "pass_observed": True, "evidence_refs": ["evidence://pass/ATT-REC-1"],
    }))
    assert allowed["artifact"]["status"] == "PASS"
