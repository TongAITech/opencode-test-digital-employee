from __future__ import annotations

import json
import sys
from pathlib import Path

import rc6_runtime.execution_overlay  # noqa: F401
from rc6_runtime.truth import TruthRuntime
from rc7_release import dsh
from rc7_release import mcp_server_field
from rc7_runtime.execution_recovery_conformance import persist_contract as persist_recovery_contract
from rc7_runtime.models import Mission, Task, TaskStatus
from rc7_runtime.truth_overlay import append_entity, install_rc7_truth_overlay


MISSION = "MISSION-MCP-CAT"
RELEASE = "REL-MCP-CAT"
TASK = "TASK-MCP-EXEC"
ATTEMPT = "ATTEMPT-MCP-CAT"
TARGET = "TARGET-MCP-CAT"


def _seed(tmp_path: Path, monkeypatch) -> TruthRuntime:
    monkeypatch.setenv("PFC_AITEST_HOME", str(tmp_path))
    monkeypatch.setenv("PFC_AITEST_STATE_DIR", str(tmp_path / "runtime-state"))
    path = tmp_path / "runtime-state" / "r1" / "event-stream.jsonl"
    install_rc7_truth_overlay()
    truth = TruthRuntime(path)
    append_entity(truth, Mission(mission_id=MISSION, release_id=RELEASE, goal="MCP CAT"), release_id=RELEASE)
    append_entity(
        truth,
        Task(
            task_id=TASK,
            mission_id=MISSION,
            node="EXECUTION",
            task_type="PRODUCE",
            objective="execute",
            state=TaskStatus.RUNNING,
            lease_owner="WORKER-EXEC",
        ),
        release_id=RELEASE,
    )
    persist_recovery_contract(truth, mission_id=MISSION, release_id=RELEASE, execution_task_id=TASK)
    truth.append_atomic(
        "EXECUTION_ATTEMPT_UPSERTED",
        {
            "attempt_id": ATTEMPT,
            "release_id": RELEASE,
            "requirement_id": "REQ-1",
            "tc_id": "TC-1",
            "case_version": 1,
            "target_id": TARGET,
            "layer": "L3",
            "status": "FAIL",
            "actual_result": {"status": 500},
            "tool_call_refs": ["tool://runner"],
            "evidence_refs": ["evidence://runner"],
        },
    )
    provider = tmp_path / "cat_provider.py"
    provider.write_text(
        """
import json, sys
json.load(sys.stdin)
json.dump({
 "success": True,
 "target_verified": True,
 "tool_call_ref": "cat-tool://mcp",
 "evidence_ref": "cat-evidence://mcp",
 "cat_evidence_ref": "cat-log://mcp",
 "correlation_ref": "cat-correlation://mcp",
 "signals": {"ERROR": 1}
}, sys.stdout)
""",
        encoding="utf-8",
    )
    config = tmp_path / "providers.json"
    config.write_text(
        json.dumps({"providers": {"BANK_CAT_QUERY": {"provider_id": "cat-mcp", "command": [sys.executable, str(provider)]}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PFC_RC7_BANK_SERVICE_PROVIDER_CONFIG", str(config))
    return truth


def _context(worker: str = "WORKER-DIAGNOSTIC") -> dict:
    return {"mission_id": MISSION, "task_id": TASK, "worker_id": worker}


def _scope() -> dict:
    return {
        "applications": ["cfg-center", "cfg-data"],
        "window_start": 100,
        "window_end": 200,
        "request_id": "REQ-MCP",
    }


def test_bank_mcp_exposes_runtime_attempt_cat_and_dsh_patch_uses_wrapper(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path, monkeypatch)
    listed = mcp_server_field.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert "attempt_cat_query" in names

    patch = dsh.write_patch(tmp_path / "rc7.patch.yml", tmp_path, sys.executable).read_text(encoding="utf-8")
    assert "rc7_release.mcp_server_field" in patch
    assert "rc7_release.mcp_server']" not in patch


def test_attempt_cat_query_runs_provider_and_agent_cat_result_is_forbidden(tmp_path: Path, monkeypatch) -> None:
    truth = _seed(tmp_path, monkeypatch)
    queried = mcp_server_field.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "attempt_cat_query",
                "arguments": {
                    "mission_context": _context(),
                    "attempt_id": ATTEMPT,
                    "target_id": TARGET,
                    "correlation": _scope(),
                },
            },
        }
    )
    assert queried["result"].get("isError") is not True
    payload = json.loads(queried["result"]["content"][0]["text"])
    assert payload["status"] == "PASS"
    assert payload["signals"]["ERROR"] == 1

    forbidden = mcp_server_field.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "failure_diagnose",
                "arguments": {
                    "mission_context": _context(),
                    "worker_id": "WORKER-DIAGNOSTIC",
                    "lease_id": "LEASE-DIAG",
                    "release_id": RELEASE,
                    "context": {
                        "attempt_id": ATTEMPT,
                        "tc_id": "TC-1",
                        "case_version": 1,
                        "target_id": TARGET,
                        "layer": "L3",
                        "runner_status": "FAIL",
                        "assertion_failed": True,
                        "actual_result": {"status": 500},
                        "execution_evidence_refs": ["evidence://runner"],
                        "runner_log_refs": ["log://runner"],
                        "correlation": _scope(),
                    },
                    "classification": {"failure_class": "PRODUCT", "rationale": "boom", "classifier_ref": "classifier://x"},
                    "cat_result": {"signals": {"FAKE": 1}},
                },
            },
        }
    )
    assert forbidden["result"]["isError"] is True
    assert "AGENT_SUPPLIED_CAT_RESULT_FORBIDDEN" in forbidden["result"]["content"][0]["text"]

    rows = [row for row in truth.query("rc7_evidence", mission_id=MISSION) if row.get("kind") == "ATTEMPT_CAT_QUERY"]
    assert len(rows) == 1
